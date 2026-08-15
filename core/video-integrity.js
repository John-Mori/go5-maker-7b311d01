// core/video-integrity.js — 動画Blobを「存在する」ではなく「使える」で判定する単一権威。
//
// 背景:
//   MediaRecorder が空Blobを返す、IndexedDB が書込成功を返しても読み戻せない、という
//   iOS Safari の間欠故障を、従来はどちらも「保存成功」と扱っていた。その結果、動画本体が
//   無いのにドラフトのメタ情報だけが残り、黒いサムネとDL不能カードが作られていた。
//
// 方針:
//   * 軽い同期判定 isUsableBlob は、生成・IDB読戻し・R2取得・DLの全境界で共用する。
//   * 生成直後だけ probePlayable で実際にブラウザがデコードできることまで確認する。
//   * Nodeテストからも同じ isUsableBlob を require できる純粋モジュールにする。
(function (root) {
  'use strict';

  // 5秒・1080x1920・8Mbps指定の正規出力はこの値を大幅に上回る。
  // ヘッダだけ/空に近い破損Blobを通さず、低ビットレート実装は誤拒否しない保守的な下限。
  var MIN_VIDEO_BYTES = 16 * 1024;

  function isUsableBlob(blob) {
    if (!blob || typeof blob.size !== 'number' || blob.size < MIN_VIDEO_BYTES) return false;
    var type = String(blob.type || '').toLowerCase().split(';')[0].trim();
    // R2からの旧データは type が空または octet-stream の場合があるため許容する。
    if (type && type.indexOf('video/') !== 0 && type !== 'application/octet-stream') return false;
    return typeof blob.arrayBuffer === 'function' || typeof root.FileReader === 'function';
  }

  function probePlayable(blob, opts) {
    opts = opts || {};
    if (!isUsableBlob(blob)) return Promise.resolve(false);
    // Node等DOMの無い場所では軽量判定まで。ブラウザ本番では必ず下のデコード確認を通る。
    if (!root.document || !root.URL || typeof root.URL.createObjectURL !== 'function') return Promise.resolve(true);

    return new Promise(function (resolve) {
      var url = null;
      var video = null;
      var timer = null;
      var done = false;
      function finish(ok) {
        if (done) return;
        done = true;
        if (timer) clearTimeout(timer);
        if (video) {
          video.onloadedmetadata = video.onloadeddata = video.oncanplay = null;
          video.onerror = video.onabort = null;
          try { video.removeAttribute('src'); video.load(); } catch (e) {}
        }
        if (url) { try { root.URL.revokeObjectURL(url); } catch (e2) {} }
        resolve(!!ok);
      }
      function decoded() {
        if (video && video.videoWidth > 0 && video.videoHeight > 0) finish(true);
      }
      try {
        url = root.URL.createObjectURL(blob);
        video = root.document.createElement('video');
        video.preload = 'metadata';
        video.muted = true;
        video.playsInline = true;
        video.onloadedmetadata = decoded;
        video.onloadeddata = decoded;
        video.oncanplay = decoded;
        video.onerror = function () { finish(false); };
        video.onabort = function () { finish(false); };
        timer = setTimeout(function () { finish(false); }, opts.timeoutMs || 10000);
        video.src = url;
        video.load();
      } catch (e3) {
        finish(false);
      }
    });
  }

  var api = {
    MIN_VIDEO_BYTES: MIN_VIDEO_BYTES,
    isUsableBlob: isUsableBlob,
    probePlayable: probePlayable
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.Go5VideoIntegrity = api;
})(typeof window !== 'undefined' ? window : this);