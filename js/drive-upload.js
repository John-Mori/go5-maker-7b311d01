/**
 * drive-upload.js — 動画作成完了時に、生成動画＋元画像を Cloudflare Worker 経由で
 * Google Drive(マイドライブ/AFI5秒動画/[チャンネル]/[動画名]/)へ自動保存する。
 *
 * - チャンネルは window.getCurrentAccount()。(acc1=月詠み色恋劇場 / acc2=宵桜艶帖)
 *   不明なら保存せずエラー表示。(取り違え防止)
 * - 失敗しても動画作成自体は成功のまま。リトライ可能なエラーを出す。
 * - 共有シークレットは「閲覧可能でも問題ない前提」。実防御は Worker 側の Origin制限＋
 *   レート制限＋最小限の操作。(新規作成のみ)秘密の本体(OAuth)は Worker Secrets。
 *
 * 設定：Worker をデプロイしたら下の WORKER_URL と SHARED_SECRET を埋める
 *   。(または端末ごとに localStorage に drive_worker_url / drive_shared_secret を入れてもよい)
 */
(function () {
  "use strict";

  var CFG = {
    // ↓↓↓ デプロイ後にここを書き換える(SETUP.md 参照)↓↓↓
    WORKER_URL: "https://go5-drive-saver.trustsignalbot.workers.dev",
    SHARED_SECRET: "daremogamewoubawareteikukimihakanpekidekyukyokunoidol", // Worker側 SHARED_SECRET と同一(公開可＝ソフト鍵)
  };
  // 端末ごとの上書き(任意)：repoに秘密を置きたくない場合
  try {
    CFG.WORKER_URL = localStorage.getItem("drive_worker_url") || CFG.WORKER_URL;
    CFG.SHARED_SECRET = localStorage.getItem("drive_shared_secret") || CFG.SHARED_SECRET;
  } catch (e) {}

  function configured() {
    return CFG.WORKER_URL && CFG.SHARED_SECRET &&
      CFG.WORKER_URL.indexOf("PASTE_") !== 0 && CFG.SHARED_SECRET.indexOf("PASTE_") !== 0;
  }

  // ★タイムアウト付きfetch(iOS Safariの無応答fetch=永久保留を断つ)。ms経過でabortし、reject(拒否)で返す。
  //   呼び出し側は .catch でフォールバック(null/""/{ok:false})へ倒す=判定不能でも必ず前へ進む(failopen-guardの型)。
  //   ★これが無いと fetchPreview/fetchVideo/resolveFolderUrl/queueSave が1つでもハングした時、
  //     driveSaveDataset_ のPromise鎖が done() へ到達せず「再生成中…」のまま永久に固まる
  //     (Chami報告2026-08-18「再生成中から待たされる」の真因)。
  function fetchT_(url, opt, ms) {
    opt = opt || {};
    var ctl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    if (ctl) opt.signal = ctl.signal;
    var tid = 0;
    var timed = new Promise(function (_resolve, reject) {
      tid = setTimeout(function () { try { if (ctl) ctl.abort(); } catch (e) {} reject(new Error("timeout")); }, ms || 15000);
    });
    var run = fetch(url, opt).then(function (r) { clearTimeout(tid); return r; }, function (e) { clearTimeout(tid); throw e; });
    return Promise.race([run, timed]);
  }

  // ステータス表示用の小さな領域を結果エリア付近に用意(無ければ作る)
  function statusEl() {
    var el = document.getElementById("driveStatus");
    if (el) return el;
    el = document.createElement("div");
    el.id = "driveStatus";
    el.className = "status";
    var area = document.getElementById("resultArea") || document.querySelector("#pageMovie main") || document.body;
    area.appendChild(el);
    return el;
  }
  function setStatus(html) { statusEl().innerHTML = html; }

  function channelLabel(id) {
    return id === "acc1" ? "月詠み色恋劇場" : id === "acc2" ? "宵桜艶帖" : "";
  }

  var lastPayload = null; // 手動リトライ用(メモリのみ)
  // 直近アップロードの文脈：Bsky添付画像を「同じ動画フォルダ」へ後追い保存するために保持。
  var lastCtx = { videoId: "", title: "", channel: "", folderId: "", queuedImage: null };

  // 一時的な失敗(通信・アップロード失敗)は自動でリトライ。(2.5秒→6秒の2回)
  // 設定系エラー(認証・チャンネル不明・上限)はリトライしても無駄なので即エラー表示。
  var RETRYABLE = { network: 1, upload_failed: 1, folder_create_failed: 1, auth_failed: 1 };
  function send(payload, attempt) {
    attempt = attempt || 0;
    lastPayload = payload;
    setStatus("☁️ Driveへ保存中…(" + channelLabel(payload.channel) + ")" + (attempt ? "(再試行 " + attempt + "/2)" : ""));

    var fd = new FormData();
    fd.append("channel", payload.channel);
    fd.append("title", payload.title);
    // ★同題名は上書き(Chami依頼2026-08-13)。Worker側の二重ロック(env.ALLOW_OVERWRITE='1')が揃った時だけ発動し、
    //   窓内(作成30日以内)の同名フォルダを新規保存の"後"にゴミ箱送りする。日付はWorkerがDriveのcreatedTimeを正とする
    //   ので、ここからは送らない。追記(sendAppend)には付けない=既存フォルダをtrashしない。
    fd.append("overwrite", "1");
    if (payload.normalize) fd.append("normalize", "1"); // ★正常化(名前を正しく保存し直す)の明示intentだけ=Worker側で30日窓を外す
    fd.append("video", payload.videoFile, payload.videoFile.name);
    (payload.images || []).forEach(function (img) { if (img) fd.append("image", img, img.name); });

    fetch(CFG.WORKER_URL, {
      method: "POST",
      headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, // Content-Type はブラウザが自動付与(boundary込み)
      body: fd,
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok && res.j && res.j.ok) {
          var link = res.j.folderLink || "#";
          // 上書きの結果を文言に反映：旧フォルダをゴミ箱へ送れた/整理に失敗(重複が残るがデータは無事)。
          var owNote = res.j.overwritten ? '(旧フォルダをゴミ箱へ・30日間復元可)'
            : (res.j.warning === 'trash_failed' ? '(旧フォルダの整理に失敗・重複が残っていますがデータは無事)' : '');
          setStatus('✅ Driveに保存しました(' + channelLabel(payload.channel) + ')' + owNote + ' ' +
            '<a href="' + link + '" target="_blank" rel="noopener">フォルダを開く</a>');
          // ★背骨ID→フォルダIDを端末に控える(drive_up_<videoId>)。動画作成時に即保存した後、
          //   共通保存側はこれを見て「動画は保存済み」と判断し、足りない画像だけ追記する(二重保存しない)。
          if (payload.videoId && res.j.folderId) {
            try { localStorage.setItem("drive_up_" + payload.videoId, res.j.folderId); } catch (e3) {}
          }
          // フォルダIDを控える＝Bsky添付画像の後追い保存先。待ち画像があれば今すぐ送る。
          if (payload.videoId && payload.videoId === lastCtx.videoId) {
            lastCtx.folderId = res.j.folderId || "";
            if (lastCtx.queuedImage && lastCtx.folderId) { var q = lastCtx.queuedImage; lastCtx.queuedImage = null; sendAppend(q, 0); }
          }
        } else {
          var code = (res.j && res.j.error) || "network";
          if (RETRYABLE[code] && attempt < 2) setTimeout(function () { send(payload, attempt + 1); }, attempt === 0 ? 2500 : 6000);
          else showError(code);
        }
      })
      .catch(function () {
        if (attempt < 2) setTimeout(function () { send(payload, attempt + 1); }, attempt === 0 ? 2500 : 6000);
        else showError("network");
      });
  }

  // Bsky添付画像を「既存の動画フォルダ」へ追記保存。(folderId指定)こちらも自動リトライ。
  function sendAppend(img, attempt) {
    attempt = attempt || 0;
    if (!lastCtx.folderId) return;
    var fd = new FormData();
    fd.append("channel", lastCtx.channel);
    fd.append("title", lastCtx.title);
    fd.append("folderId", lastCtx.folderId);
    fd.append("image", img, img.name);
    fetch(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok && res.j && res.j.ok) setStatus('✅ Bsky添付画像もDriveの同フォルダへ保存しました。');
        else if (attempt < 2) setTimeout(function () { sendAppend(img, attempt + 1); }, 2500);
        else setStatus('⚠️ Bsky添付画像のDrive保存に失敗しました。(動画は保存済み)');
      })
      .catch(function () {
        if (attempt < 2) setTimeout(function () { sendAppend(img, attempt + 1); }, 2500);
        else setStatus('⚠️ Bsky添付画像のDrive保存に失敗しました。(動画は保存済み)');
      });
  }

  // Bluesky投稿成功時：Bluesky独自に添付した画像を同じ動画フォルダへ「動画名_Bsky投稿.拡張子」で保存。(bluesky.jsが発火)
  // ※独自画像を添付しなかった場合は動画の画像と同一なので発火しない＝重複保存しない。(ユーザー要望2026-07)
  document.addEventListener("bsky-image-posted", function (e) {
    if (!configured()) return;
    var d = (e && e.detail) || {};
    var f = d.file;
    if (!f) return;
    // videoId が分かるならフォルダ取り違え防止に照合。空同士でも動く。(従来通り)
    if (d.videoId && lastCtx.videoId && d.videoId !== lastCtx.videoId) return;
    var named = new File([f], lastCtx.title + "_Bsky投稿." + imgExt(f), { type: f.type || "image/jpeg" });
    if (lastCtx.folderId) sendAppend(named, 0);
    else lastCtx.queuedImage = named; // 動画アップロード完了(フォルダ確定)待ち → 完了時に自動送信
  });

  function showError(code) {
    var msg = {
      channel_unresolved: "チャンネルが判定できず保存していません。(取り違え防止)",
      parent_folder_not_found: "保存先フォルダIDが見つかりません。(Worker設定を確認)",
      bad_secret: "認証エラー。(共有シークレット不一致)",
      origin_not_allowed: "このサイトからの保存は許可されていません。(Origin設定)",
      rate_limited: "本日の保存上限に達しました。",
      auth_failed: "Google認証に失敗。(リフレッシュトークン等を確認)",
      upload_failed: "アップロードに失敗しました。",
      network: "通信に失敗しました。",
    }[code] || ("保存に失敗しました。(" + code + ")");
    var b = document.createElement("button");
    setStatus("⚠️ " + msg + " ");
    b.textContent = "↻ Driveに再保存";
    b.className = "ghost";
    b.style.marginLeft = "8px";
    b.onclick = function () { if (lastPayload) send(lastPayload); };
    statusEl().appendChild(b);
  }

  // ★Drive保存の起点は stock.js の「ドラフト台帳が動画実体付きで確定した瞬間」へ一本化。
  //   この video-created リスナーは、まだドラフトID(stk...)が確定していないためDriveへ書かず、
  //   Bsky後追い画像の宛先文脈だけを控える。stock.js の saveStock_.onCommitted が、動画/元画像/
  //   仕上がりプレビューを共通の driveSaveDataset_ へ渡す。投稿完了はDrive保存を起動しない。
  document.addEventListener("video-created", function (e) {
    var d = (e && e.detail) || {};
    if (!d.blob || d.test) return;
    var name = d.name || "video.mp4";
    var title = (d.title || "").trim() || name.replace(/\.[^.]+$/, "");
    var channel = (d.account === "acc1" || d.account === "acc2") ? d.account
      : ((typeof window.getCurrentAccount === "function") ? window.getCurrentAccount() : "");
    if (channel !== "acc1" && channel !== "acc2") return;
    // 宛先の題名/チャンネルだけ控える。folderId は投稿完了時に確定するのでここでは空のまま。
    lastCtx = { videoId: d.videoId || "", title: title, channel: channel, folderId: "", queuedImage: lastCtx.queuedImage };
  });

  // 共通Drive保存から呼ばれる。blob を受け取って Drive へアップロードする。
  //   srcImages=動画に使った元画像(stock.js がIDB/R2から読み出して渡す)。動画と同じフォルダへ一緒に保存する。
  function driveUpload_(blob, videoName, title, channel, videoId, srcImages, previewImage, opts) {
    opts = opts || {};
    if (!configured()) { showError("channel_unresolved"); return; }
    if (!blob) return;
    if (channel !== "acc1" && channel !== "acc2") { showError("channel_unresolved"); return; }
    // キューに溜まっていた Bsky 添付画像は引き継ぐ
    lastCtx = { videoId: videoId || "", title: title, channel: channel, folderId: "", queuedImage: lastCtx.queuedImage };
    var videoFile = new File([blob], videoName || (title.replace(/[\\/:"*?<>|]/g, '_') + '.mp4'), { type: blob.type || "video/mp4" });
    // 元画像は「動画名_元画像(_2,_3…).拡張子」で名付ける。File名が無い/被る事故を防ぐ。
    var safeTitle = String(title || "動画").replace(/[\\/:"*?<>|]/g, '_');
    var images = (srcImages || []).filter(Boolean).map(function (f, i) {
      var name = safeTitle + "_元画像" + (i ? "_" + (i + 1) : "") + "." + imgExt(f);
      return new File([f], name, { type: f.type || "image/jpeg" });
    });
    // ★仕上がりプレビューは「動画名_プレビュー.拡張子」で先頭に。(Chami依頼2026-07-30・従来通り同フォルダへ)
    if (previewImage) {
      images.unshift(new File([previewImage], safeTitle + "_プレビュー." + imgExt(previewImage), { type: previewImage.type || "image/jpeg" }));
    }
    send({ channel: channel, title: title, videoId: videoId || "", videoFile: videoFile, images: images, normalize: !!opts.normalize });
  }
  // 過去分プレビュー取り込み：Driveの[題名]フォルダから「題名_プレビュー.*」を取得して data URL を返す。
  //   見つからなければ null(Chami「ないものはなかったでOK」)。Worker側は read-only=非破壊。
  function fetchPreview_(channel, title) {
    if (!configured()) return Promise.resolve(null);
    if (channel !== "acc1" && channel !== "acc2") return Promise.resolve(null);
    if (!title) return Promise.resolve(null);
    var fd = new FormData();
    fd.append("action", "fetch_preview");
    fd.append("channel", channel);
    fd.append("title", title);
    return fetchT_(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd }, 15000)
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (j) { return (j && j.ok && j.found && j.dataUrl) ? j.dataUrl : null; })
      .catch(function () { return null; });
  }
  // 過去分プレビュー生成の最終手段：この端末に動画の控えが無い(別端末で作成)時、Driveの[題名]フォルダから
  //   動画本体を取り寄せて Blob で返す。無ければ null。Worker側は read-only=非破壊(既存物に触れない)。
  //   ★Chami指摘2026-08-14「別端末とか関係なく保存先のGoogleドライブの動画参照すればできる」への対応。
  function fetchVideo_(channel, title) {
    if (!configured()) return Promise.resolve(null);
    if (channel !== "acc1" && channel !== "acc2") return Promise.resolve(null);
    if (!title) return Promise.resolve(null);
    var fd = new FormData();
    fd.append("action", "fetch_video");
    fd.append("channel", channel);
    fd.append("title", title);
    // 動画本体のDL=数MBありうる=長め(45秒)。それでも返らなければabortしてnull(この端末では生成不可)。
    return fetchT_(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd }, 45000)
      .then(function (r) {
        var ct = (r.headers.get("Content-Type") || "").toLowerCase();
        if (r.ok && ct.indexOf("video/") === 0) return r.blob(); // 見つかった=動画バイト列
        return null;                                             // JSON(found:false)や失敗は null
      })
      .catch(function () { return null; });
  }
  // 作品フォルダに 動画/仕上がりプレビュー/元画像 がそれぞれ在るかを read-only で問い合わせる(非破壊)。
  //   データ再生成が「Driveに無いものだけ補う(既にあるものは上げ直さない)」判定に使う=プレビューの重複生成を止め、
  //   足りない元画像だけを補う(Chami報告2026-08-18)。返り= {saved,hasPreview,hasSrc} / 判定不能は null
  //   (呼び出し側は null を「不明」として重複防止側=追記しない へ倒す)。
  function folderState_(channel, title) {
    if (!configured() || (channel !== "acc1" && channel !== "acc2") || !title) return Promise.resolve(null);
    var fd = new FormData();
    fd.append("action", "folder_state");
    fd.append("channel", channel);
    fd.append("title", title);
    return fetchT_(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd }, 15000)
      .then(function (r) { return r.json().catch(function () { return null; }); })
      .then(function (j) { return (j && j.ok) ? { saved: !!j.saved, hasPreview: !!j.hasPreview, hasSrc: !!j.hasSrc } : null; })
      .catch(function () { return null; });
  }
  // 退避保存：動画本体が復元不能でも、せめて[チャンネル]/[題名]フォルダを作り、手元にあるプレビュー/元画像だけ
  //   名前を付けて保存する(Chami依頼2026-08-18「動画がないなら仕方ない。フォルダくらい作って、プレビュー画像や
  //   元画像はあるなら取得して名前変えて保存すればいい」)。imgs = [{blob, role:'preview'|'src'}]。
  //   Worker側(action=ensure_folder)が既存フォルダ再利用＋同役割の重複を上げない(冪等)。命名は投稿完了時と同じ
  //   "題名_プレビュー.拡張子"/"題名_元画像.拡張子"。返り= {ok,folderId,folderLink,created,added,skipped} / 失敗は{ok:false}。
  function ensureFolderSave_(channel, title, imgs, videoId) {
    if (!configured() || (channel !== "acc1" && channel !== "acc2") || !title) return Promise.resolve({ ok: false, error: "not_ready" });
    var safeTitle = String(title || "動画").replace(/[\\/:"*?<>|]/g, '_');
    var fd = new FormData();
    fd.append("action", "ensure_folder");
    fd.append("channel", channel);
    fd.append("title", title);
    (imgs || []).forEach(function (it) {
      if (!it || !it.blob) return;
      // ★プレビュー/元画像どちらのファイル名にするかは core/image-role.js(Go5ImageRole)の判定を使う
      //   (2026-08-23・単一権威化。imgs=[{blob, role:'preview'|'src'}] の role タグをここで解釈する)。
      //   core/image-role.jsが読めない異常時は安全側(プレビュー扱い=元画像として誤って上書きしない)。
      var role = window.Go5ImageRole ? window.Go5ImageRole.imageRole(it) : "preview";
      var name = (role === "source")
        ? (safeTitle + "_元画像." + imgExt(it.blob))
        : (safeTitle + "_プレビュー." + imgExt(it.blob));
      fd.append("image", new File([it.blob], name, { type: it.blob.type || "image/jpeg" }), name);
    });
    // フォルダ作成＋画像アップロードは秒がかかりうる=30秒。返らなければ {ok:false} へ倒す(failopen-guard)。
    return fetchT_(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd }, 30000)
      .then(function (r) { return r.json().catch(function () { return { ok: false }; }); })
      .then(function (j) {
        j = j || { ok: false };
        if (j.ok && j.folderId) rememberFolderId_(channel, title, videoId, j.folderId);
        return j;
      })
      .catch(function () { return { ok: false, error: "network" }; });
  }
  // 背骨ID→動画作成時に保存したDriveフォルダID(無ければ空)。投稿完了側が「もう保存済みか」を判定する。
  function folderIdFor_(videoId) {
    try { return videoId ? (localStorage.getItem("drive_up_" + videoId) || "") : ""; } catch (e) { return ""; }
  }
  // 既存の動画フォルダ(folderId)へ画像1枚だけ追記する。(投稿完了時の仕上がりプレビュー追記に使う)
  //   ★動画/元画像は作成時に保存済み=ここでは上げ直さない。プレビューだけ「動画名_プレビュー.拡張子」で足す。
  function appendImageToFolder_(channel, title, folderId, imgBlob, fileName) {
    if (!configured() || !folderId || !imgBlob) return;
    if (channel !== "acc1" && channel !== "acc2") return;
    var safeTitle = String(title || "動画").replace(/[\\/:"*?<>|]/g, '_');
    var name = fileName || (safeTitle + "_プレビュー." + imgExt(imgBlob));
    // ★File実体が既に別名(候補タブ由来の candidate_N.jpg 等)を持っていても、必ず意図した名前で上げ直す。
    //   旧: `instanceof File` の時は渡されたFileの名前をそのまま使っていた=candidate_3.jpg のような誤名が
    //   Driveへ入り、Workerの findSrcImageFile(name contains '元画像')に一致せず「元画像なし」判定になる→
    //   データ再生成のたびに candidate_N.jpg が新規に増殖した(Chami報告2026-08-22「いらんやつ作られてまっせ」)。
    //   常に name で包み直す=命名規則(題名_元画像/題名_プレビュー)を1箇所で強制。
    var f = new File([imgBlob], name, { type: imgBlob.type || "image/jpeg" });
    lastCtx.channel = channel; lastCtx.title = title; lastCtx.folderId = folderId;
    sendAppend(f, 0);
  }
  // ── ★サーバー側完走ジョブ(ドラフト確定直後に起動・途中で閉じても裏で完結)──
  //   ドラフト確定後に「重い動画アップロード」をこのページ内で走らせず、動画は既にR2に控えてある(ensureVideoMirror_)ので
  //   その在り処(videoKey)だけを軽いFormDataでWorkerへ渡す→Workerが即202を返し、あとはR2→Driveをサーバー側で完走。
  //   本体が軽い(数百バイト)ので keepalive:true が確実に効く=送信の途中でタブを閉じてもブラウザが送り切る。
  //   opts = { videoId(R2キー算出に使う下書きID), title, channel, previewKey?, srcKey?, overwrite? }
  function queueSave_(opts) {
    opts = opts || {};
    var channel = opts.channel, title = opts.title, videoId = opts.videoId;
    if (!configured()) return Promise.resolve({ ok: false, error: "not_configured" });
    if (channel !== "acc1" && channel !== "acc2") return Promise.resolve({ ok: false, error: "channel_unresolved" });
    if (!title || !videoId) return Promise.resolve({ ok: false, error: "missing_fields" });
    if (!(window.Go5Sync && Go5Sync.keyForName && Go5Sync.getConfig)) return Promise.resolve({ ok: false, error: "no_sync" });
    var r2Base = (Go5Sync.getConfig() || {}).url || "";
    if (!/^https?:\/\//.test(r2Base)) return Promise.resolve({ ok: false, error: "no_r2_base" });
    setStatus("☁️ Driveへ保存中…(" + channelLabel(channel) + ")");
    return Go5Sync.keyForName("go5vid:" + videoId).then(function (videoKey) {
      var fd = new FormData();
      fd.append("action", "save_job");
      fd.append("channel", channel);
      fd.append("title", title);
      fd.append("videoId", videoId);
      fd.append("r2Base", r2Base);
      fd.append("videoKey", videoKey);
      if (opts.previewKey) fd.append("previewKey", opts.previewKey);
      if (opts.srcKey) fd.append("srcKey", opts.srcKey); // 元画像(動画に使った写真)のR2在り処。投稿完了と同じ一式を揃える
      if (opts.overwrite) fd.append("overwrite", "1"); // 上書きはWorker側の env.ALLOW_OVERWRITE と二重ロック
      if (opts.normalize) fd.append("normalize", "1"); // ★正常化=手動の明示「名前を正しく保存し直す」だけ。Worker側で30日窓を外し古いフォルダも作り直し対象にする(自動保存には付かない)

      return fetchT_(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd, keepalive: true }, 20000)
        .then(function (r) {
          if (r.status === 202 || r.ok) { setStatus("☁️ Driveへ保存中(" + channelLabel(channel) + ")…確認でき次第、作成履歴カードに『保存済み(実物確認)』が付きます"); return { ok: true }; }
          return r.json().then(function (j) { return { ok: false, error: (j && j.error) || ("http_" + r.status) }; }).catch(function () { return { ok: false, error: "http_" + r.status }; });
        })
        .catch(function () { return { ok: false, error: "network" }; });
    }).catch(function () { return { ok: false, error: "keygen" }; });
  }
  // 完走確認(read-only)：[題名]フォルダに動画が在れば true。永続pendingを畳めるかの照会に使う。
  function checkSaved_(channel, title) {
    if (!configured() || (channel !== "acc1" && channel !== "acc2") || !title) return Promise.resolve(false);
    var fd = new FormData();
    fd.append("action", "check_saved");
    fd.append("channel", channel);
    fd.append("title", title);
    // ★15秒でabort(iOS Safariのfetchは無応答で永久保留になりうる=照会Promiseが未解決のまま
    //   verifyDriveLanded_/sweepの次段が黙って止まる穴を塞ぐ。判定不能は false=「まだ確認できず」へ倒す
    //   =read-onlyなので保存を壊さない・自動再確認が続く。failopen-guardの型)。
    var ctl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var tid = ctl ? setTimeout(function () { try { ctl.abort(); } catch (e) {} }, 15000) : 0;
    var opt = { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd };
    if (ctl) opt.signal = ctl.signal;
    return fetch(CFG.WORKER_URL, opt)
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (j) { if (tid) clearTimeout(tid); return !!(j && j.ok && j.saved); })
      .catch(function () { if (tid) clearTimeout(tid); return false; });
  }
  // ── ★保存先パスの設計を一箇所に集約(2026-08-16 Chami「将来アカウントが変わってもパスを一括で柔軟に変えられるよう設計」)──
  //   保存先の実体= マイドライブ/[DRIVE_ROOT]/[チャンネル名]/[題名]/。チャンネル別ルートフォルダIDの正本は
  //   Worker Secrets(env.FOLDER_ID_ACC1/ACC2)＝フロント(公開repo)にはIDを置かない。ここではその「パスの形」だけを
  //   宣言し、リンクの組み立てをこの1関数へ集約する。将来アカウント(Googleドライブ)が変わっても、
  //   ・検索リンク=ログイン中のDriveをそのまま検索するのでコード変更ゼロで追従
  //   ・直リンク=手元に控えた実フォルダID(drive_up_<videoId>)がある時だけ使う=別アカウントの古いIDは使わない
  //   ので、パスまわりを直したい時はこのブロック1箇所を見ればよい。
  var DRIVE_PATH = {
    root: "AFI5秒動画",                                   // マイドライブ直下の親フォルダ名(保存先の頂点)
    channels: { acc1: "月詠み色恋劇場", acc2: "宵桜艶帖" }, // チャンネル→フォルダ名(表示・照合用の控え)
  };
  function folderLink_(fid) { return "https://drive.google.com/drive/folders/" + encodeURIComponent(fid); }
  // 題名ベースの控えキー(videoIdが無い過去投稿でも実フォルダIDを覚えておける)。
  function folderCacheKey_(channel, title) { return "drive_folder_" + channel + "_" + String(title || "").trim(); }
  // WorkerがGoogle Drive上で実在確認または新規作成したIDだけを控える。
  // 題名キーと背骨キーを同時に揃え、旧投稿履歴でも後続処理が同じフォルダを再利用する。
  function rememberFolderId_(channel, title, videoId, folderId) {
    if (!folderId) return '';
    try {
      localStorage.setItem(folderCacheKey_(channel, title), folderId);
      if (videoId) localStorage.setItem("drive_up_" + videoId, folderId);
    } catch (e) {}
    return folderId;
  }
  // 端末に控えた実フォルダIDを返す(videoId優先→題名キャッシュ)。無ければ ""。
  function cachedFolderId_(channel, title, videoId) {
    try {
      var fid = videoId && localStorage.getItem("drive_up_" + videoId);
      if (fid) return fid;
      var fid2 = localStorage.getItem(folderCacheKey_(channel, title));
      if (fid2) return fid2;
    } catch (e) {}
    return "";
  }
  // この作品のGoogleドライブ保存先を開く「同期の」URLを組む(hrefの初期値用)。実フォルダIDの控えがあれば直リンク、
  //   無ければ題名でDrive検索。title 空 かつ 控えID無し のときは "" を返す(呼び出し側はリンクを出さない=切れリンクを作らない)。
  function driveFolderUrl_(channel, title, videoId) {
    var fid = cachedFolderId_(channel, title, videoId);
    if (fid) return folderLink_(fid);
    var t = String(title || "").trim();
    if (!t) return "";
    return "https://drive.google.com/drive/search?q=" + encodeURIComponent(t);
  }
  // ★クリック時に「その作品のフォルダそのもの」を解決して直リンクURLを返す(非同期・Chami依頼2026-08-16②
  //   「検索じゃなくこの作品のフォルダ内に移動して」)。①端末の控えがあれば即・直リンク ②無ければWorkerの
  //   read-onlyアクション folder_link で[チャンネル]/[題名]フォルダのIDを引き当て、控えて直リンク ③見つからなければ ""
  //   (呼び出し側は題名検索へフォールバック)。サーバー側完走ジョブ(queueSave)はfolderIdをクライアントへ返さないため、
  //   このオンデマンド解決が「作成時に控えていない作品」でも実フォルダへ入るための唯一の経路。
  function resolveFolderUrl_(channel, title, videoId) {
    var fid = cachedFolderId_(channel, title, videoId);
    if (fid) return Promise.resolve(folderLink_(fid));
    if (!configured() || (channel !== "acc1" && channel !== "acc2") || !title) return Promise.resolve("");
    var fd = new FormData();
    fd.append("action", "folder_link");
    fd.append("channel", channel);
    fd.append("title", title);
    return fetchT_(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd }, 15000)
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (j) {
        if (j && j.ok && j.found && j.folderId) {
          try {
            localStorage.setItem(folderCacheKey_(channel, title), j.folderId);
            if (videoId) localStorage.setItem("drive_up_" + videoId, j.folderId);
          } catch (e2) {}
          return j.link || folderLink_(j.folderId);
        }
        return "";
      })
      .catch(function () { return ""; });
  }

  window.Go5Drive = { upload: driveUpload_, fetchPreview: fetchPreview_, fetchVideo: fetchVideo_, folderIdFor: folderIdFor_, rememberFolder: rememberFolderId_, appendImage: appendImageToFolder_, ensureFolder: ensureFolderSave_, queueSave: queueSave_, checkSaved: checkSaved_, folderState: folderState_, folderUrl: driveFolderUrl_, resolveFolderUrl: resolveFolderUrl_, pathConfig: DRIVE_PATH };

  // ファイルの拡張子を推定。(MIME優先、無ければ元ファイル名から)
  function imgExt(file) {
    var t = (file.type || "").toLowerCase();
    if (t.indexOf("png") >= 0) return "png";
    if (t.indexOf("jpeg") >= 0 || t.indexOf("jpg") >= 0) return "jpg";
    if (t.indexOf("webp") >= 0) return "webp";
    if (t.indexOf("heic") >= 0) return "heic";
    if (t.indexOf("gif") >= 0) return "gif";
    var m = String(file.name || "").match(/\.([A-Za-z0-9]{1,5})$/);
    return m ? m[1].toLowerCase() : "jpg";
  }
})();
