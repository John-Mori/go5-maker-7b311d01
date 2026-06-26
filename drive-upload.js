/**
 * drive-upload.js — 動画作成完了時に、生成動画＋元画像を Cloudflare Worker 経由で
 * Google Drive（マイドライブ/AFI5秒動画/[チャンネル]/[動画名]/）へ自動保存する。
 *
 * - チャンネルは window.getCurrentAccount()（acc1=月詠み色恋劇場 / acc2=宵桜艶帖）。
 *   不明なら保存せずエラー表示（取り違え防止）。
 * - 失敗しても動画作成自体は成功のまま。リトライ可能なエラーを出す。
 * - 共有シークレットは「閲覧可能でも問題ない前提」。実防御は Worker 側の Origin制限＋
 *   レート制限＋最小限の操作（新規作成のみ）。秘密の本体（OAuth）は Worker Secrets。
 *
 * 設定：Worker をデプロイしたら下の WORKER_URL と SHARED_SECRET を埋める
 *   （または端末ごとに localStorage に drive_worker_url / drive_shared_secret を入れてもよい）。
 */
(function () {
  "use strict";

  var CFG = {
    // ↓↓↓ デプロイ後にここを書き換える（SETUP.md 参照）↓↓↓
    WORKER_URL: "https://go5-drive-saver.trustsignalbot.workers.dev",
    SHARED_SECRET: "daremogamewoubawareteikukimihakanpekidekyukyokunoidol", // Worker側 SHARED_SECRET と同一（公開可＝ソフト鍵）
  };
  // 端末ごとの上書き（任意）：repoに秘密を置きたくない場合
  try {
    CFG.WORKER_URL = localStorage.getItem("drive_worker_url") || CFG.WORKER_URL;
    CFG.SHARED_SECRET = localStorage.getItem("drive_shared_secret") || CFG.SHARED_SECRET;
  } catch (e) {}

  function configured() {
    return CFG.WORKER_URL && CFG.SHARED_SECRET &&
      CFG.WORKER_URL.indexOf("PASTE_") !== 0 && CFG.SHARED_SECRET.indexOf("PASTE_") !== 0;
  }

  // ステータス表示用の小さな領域を結果エリア付近に用意（無ければ作る）
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

  var lastPayload = null; // リトライ用（メモリのみ）

  function send(payload) {
    lastPayload = payload;
    setStatus("☁️ Driveへ保存中…（" + channelLabel(payload.channel) + "）");

    var fd = new FormData();
    fd.append("channel", payload.channel);
    fd.append("title", payload.title);
    fd.append("video", payload.videoFile, payload.videoFile.name);
    (payload.images || []).forEach(function (img) { if (img) fd.append("image", img, img.name); });

    fetch(CFG.WORKER_URL, {
      method: "POST",
      headers: { "X-Shared-Secret": CFG.SHARED_SECRET }, // Content-Type はブラウザが自動付与（boundary込み）
      body: fd,
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok && res.j && res.j.ok) {
          var link = res.j.folderLink || "#";
          setStatus('✅ Driveに保存しました（' + channelLabel(payload.channel) + '） ' +
            '<a href="' + link + '" target="_blank" rel="noopener">フォルダを開く</a>');
        } else {
          var code = (res.j && res.j.error) || ("http_" + (res.j ? "" : "error"));
          showError(code);
        }
      })
      .catch(function () { showError("network"); });
  }

  function showError(code) {
    var msg = {
      channel_unresolved: "チャンネルが判定できず保存していません（取り違え防止）。",
      parent_folder_not_found: "保存先フォルダIDが見つかりません（Worker設定を確認）。",
      bad_secret: "認証エラー（共有シークレット不一致）。",
      origin_not_allowed: "このサイトからの保存は許可されていません（Origin設定）。",
      rate_limited: "本日の保存上限に達しました。",
      auth_failed: "Google認証に失敗（リフレッシュトークン等を確認）。",
      upload_failed: "アップロードに失敗しました。",
      network: "通信に失敗しました。",
    }[code] || ("保存に失敗しました（" + code + "）。");
    var b = document.createElement("button");
    setStatus("⚠️ " + msg + " ");
    b.textContent = "↻ Driveに再保存";
    b.className = "ghost";
    b.style.marginLeft = "8px";
    b.onclick = function () { if (lastPayload) send(lastPayload); };
    statusEl().appendChild(b);
  }

  document.addEventListener("video-created", function (e) {
    if (!configured()) return; // 未設定時は無害にスキップ（既存フローは一切壊さない）
    var d = (e && e.detail) || {};
    var blob = d.blob;
    if (!blob) return; // 動画Blobが取れなければ何もしない
    var name = d.name || "video.mp4";
    var title = (d.title || "").trim() || name.replace(/\.[^.]+$/, "");
    // フォルダ/ファイル名は動画名（タイトル）そのまま。同名は Worker 側で _2,_3… に自動回避。
    // ※安定動画IDは記録シートの post_id に使うのみ（Drive名には付けない）。

    var channel = (typeof window.getCurrentAccount === "function") ? window.getCurrentAccount() : "";
    if (channel !== "acc1" && channel !== "acc2") { showError("channel_unresolved"); return; }

    var videoFile = new File([blob], name, { type: blob.type || "video/mp4" });

    // 元写真（あれば）。形式はそのまま＝再エンコードせず原本を保持し、名前だけ「タイトル.元拡張子」に。
    var origImage = null;
    var photo = document.getElementById("photo");
    var pf = (photo && photo.files && photo.files[0]) ? photo.files[0] : null;
    if (pf) origImage = new File([pf], title + "." + imgExt(pf), { type: pf.type || "image/jpeg" });

    function finish(previewImage) {
      // プレビューを先頭に＝旧Worker（先頭1枚のみ保存）でも仕上がりプレビューは残る。新Workerは両方保存。
      send({ channel: channel, title: title, videoFile: videoFile, images: [previewImage, origImage].filter(Boolean) });
    }

    // 仕上がりプレビュー（合成済み Canvas #cv＝1080×1920）を PNG「タイトル_プレビュー.png」で保存（文字が鮮明）。
    var cv = document.getElementById("cv");
    if (cv && typeof cv.toBlob === "function") {
      try {
        cv.toBlob(function (pngBlob) {
          finish(pngBlob ? new File([pngBlob], title + "_プレビュー.png", { type: "image/png" }) : null);
        }, "image/png");
      } catch (err) { finish(null); }
    } else {
      finish(null);
    }
  });

  // ファイルの拡張子を推定（MIME優先、無ければ元ファイル名から）。
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
