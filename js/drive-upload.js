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
          //   投稿完了側はこれを見て「動画は保存済み」と判断し、仕上がりプレビューだけ追記する(二重保存しない)。
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

  // ★Drive保存は「ドラフトの投稿完了」でまとめて行う(2026-08-13 Chami「保存タイミングは投稿モードから
  //   投稿完了を押した時に全て保存するタイミングにして」)。作成の瞬間には保存しない=ここでは lastCtx を
  //   控えるだけ(Bsky後追い画像の宛先題名/チャンネルの保険)で Drive へは書かない。
  //   《なぜ作成時保存を外して安全か》以前(2026-08-11)作成時に上げていた理由は「iOSが投稿完了までに
  //   IDBの動画blobを捨てると投稿完了時にblobが取れずDriveに動画が残らない」ため。だが現在は作成直後に
  //   ensureVideoMirror_ が動画blobを R2 へ控え、投稿完了側の resolveVideoBlob_ が手元IDBに無ければ R2 から
  //   取り寄せる(stock.js)。=投稿完了の時点でも動画blobは確実に手に入る=作成時保存に頼らなくてよい。
  //   投稿完了(stock.js driveSaveForCompleted_)が動画+元画像+仕上がりプレビューを1度に upload する。
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

  // ドラフトタブの「投稿完了」から呼ばれる。blob を受け取って Drive へアップロードする。
  //   srcImages=動画に使った元画像(stock.js が投稿完了時にIDBから読み出して渡す)。動画と同じフォルダへ一緒に保存する。
  function driveUpload_(blob, videoName, title, channel, videoId, srcImages, previewImage) {
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
    send({ channel: channel, title: title, videoId: videoId || "", videoFile: videoFile, images: images });
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
    return fetch(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd })
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
    return fetch(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd })
      .then(function (r) {
        var ct = (r.headers.get("Content-Type") || "").toLowerCase();
        if (r.ok && ct.indexOf("video/") === 0) return r.blob(); // 見つかった=動画バイト列
        return null;                                             // JSON(found:false)や失敗は null
      })
      .catch(function () { return null; });
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
    var f = (imgBlob instanceof File) ? imgBlob : new File([imgBlob], name, { type: imgBlob.type || "image/jpeg" });
    lastCtx.channel = channel; lastCtx.title = title; lastCtx.folderId = folderId;
    sendAppend(f, 0);
  }
  // ── ★サーバー側完走ジョブ(2026-08-16 Chami「途中で閉じても裏で完結」)──
  //   投稿完了で「重い動画アップロード」をこのページ内で走らせず、動画は既にR2に控えてある(ensureVideoMirror_)ので
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
      return fetch(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd, keepalive: true })
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
    return fetch(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (j) { return !!(j && j.ok && j.saved); })
      .catch(function () { return false; });
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
    return fetch(CFG.WORKER_URL, { method: "POST", headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, body: fd })
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

  window.Go5Drive = { upload: driveUpload_, fetchPreview: fetchPreview_, fetchVideo: fetchVideo_, folderIdFor: folderIdFor_, appendImage: appendImageToFolder_, queueSave: queueSave_, checkSaved: checkSaved_, folderUrl: driveFolderUrl_, resolveFolderUrl: resolveFolderUrl_, pathConfig: DRIVE_PATH };

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
