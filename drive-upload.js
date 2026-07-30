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
          setStatus('✅ Driveに保存しました(' + channelLabel(payload.channel) + ') ' +
            '<a href="' + link + '" target="_blank" rel="noopener">フォルダを開く</a>');
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

  // Drive保存は「投稿完了」まで延期。video-created では Bsky添付画像の後追い用に文脈のみ記録する。
  document.addEventListener("video-created", function (e) {
    var d = (e && e.detail) || {};
    if (!d.blob || d.test) return;
    var name = d.name || "video.mp4";
    var title = (d.title || "").trim() || name.replace(/\.[^.]+$/, "");
    var channel = (typeof window.getCurrentAccount === "function") ? window.getCurrentAccount() : "";
    if (channel !== "acc1" && channel !== "acc2") return;
    lastCtx = { videoId: d.videoId || "", title: title, channel: channel, folderId: "", queuedImage: null };
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
  window.Go5Drive = { upload: driveUpload_ };

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
