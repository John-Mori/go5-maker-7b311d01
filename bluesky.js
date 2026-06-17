/**
 * bluesky.js
 * Bluesky 自動投稿＋記録のUI配線（1テキストボックス版）。
 * - 本文は「1つの自由テキスト欄(bskyText)」で完結。改行もそのまま投稿。
 * - 本文中のアフィリンク（生リンク・無改変）は自動でクリック可能リンク化（facet）。
 * - 添付画像は「挿入した元写真そのもの」（#photo）を JPEG 圧縮（1MB制限対応）。
 * - 投稿アカウント/記録設定は折りたたみ（任意）。アプリパスワード未入力なら投稿はスキップ。
 * - 投稿後、共有URL・タイトル・本文中の先頭URLを GAS Web App へ送信（任意）。
 *
 * 秘匿情報（アプリパスワード・シークレット）は console に出さない。
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var els = {
    enable: $('bskyEnable'),
    settings: $('bskySettings'),
    text: $('bskyText'),
    handle: $('bskyHandle'),
    appPw: $('bskyAppPw'),
    gasUrl: $('bskyGasUrl'),
    gasSecret: $('bskyGasSecret'),
    status: $('bskyStatus')
  };
  if (!els.enable) return;   // UIが無ければ何もしない（安全）

  // ---- 設定の永続化（localStorage） ----
  var KEYS = {
    enable: 'bsky_enable',
    text: 'bsky_text',
    handle: 'bsky_handle',
    appPw: 'bsky_app_pw',
    gasUrl: 'bsky_gas_url',
    gasSecret: 'bsky_gas_secret'
  };
  var FIELDS = [
    [els.text, KEYS.text], [els.handle, KEYS.handle], [els.appPw, KEYS.appPw],
    [els.gasUrl, KEYS.gasUrl], [els.gasSecret, KEYS.gasSecret]
  ];
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  (function restore() {
    els.enable.checked = (load(KEYS.enable) === '1');
    FIELDS.forEach(function (p) { if (!p[0]) return; var v = load(p[1]); if (v != null) p[0].value = v; });
    syncSettingsVisibility();
  })();

  function syncSettingsVisibility() { if (els.settings) els.settings.hidden = !els.enable.checked; }
  els.enable.addEventListener('change', function () { save(KEYS.enable, els.enable.checked ? '1' : '0'); syncSettingsVisibility(); });
  FIELDS.forEach(function (p) { if (!p[0]) return; p[0].addEventListener('input', function () { save(p[1], p[0].value); }); });

  function setStatus(msg) { if (els.status) els.status.textContent = msg || ''; }
  function firstUrl(text) { var m = String(text).match(/https?:\/\/[^\s]+/); return m ? m[0] : ''; }

  // ---- Canvas → JPEG（Bluesky の blob 上限 ≈ 976KB に収める） ----
  var MAX_BYTES = 950000;
  function toBlob(canvas, type, quality) { return new Promise(function (r) { canvas.toBlob(r, type, quality); }); }
  function compressCanvas(canvas) {
    var quality = 0.9;
    function tryQuality() {
      return toBlob(canvas, 'image/jpeg', quality).then(function (b) {
        if (b && b.size <= MAX_BYTES) return b;
        quality -= 0.12; if (quality >= 0.3) return tryQuality();
        return downscale(0.85);
      });
    }
    function downscale(scale) {
      var c2 = document.createElement('canvas');
      c2.width = Math.max(1, Math.round(canvas.width * scale));
      c2.height = Math.max(1, Math.round(canvas.height * scale));
      c2.getContext('2d').drawImage(canvas, 0, 0, c2.width, c2.height);
      return toBlob(c2, 'image/jpeg', 0.8).then(function (b) {
        if (b && b.size <= MAX_BYTES) return b;
        if (scale > 0.35) return downscale(scale - 0.15);
        return b;
      });
    }
    return tryQuality();
  }

  // ---- 添付画像＝「挿入した元写真そのもの」を取得して圧縮 ----
  function loadImage(src) {
    return new Promise(function (res, rej) {
      var img = new Image();
      img.onload = function () { res(img); };
      img.onerror = function () { rej(new Error('画像の読み込みに失敗しました')); };
      img.src = src;
    });
  }
  function getPostImageBlob() {
    var input = $('photo');
    var file = input && input.files && input.files[0];
    if (!file) return compressCanvas($('cv'));   // フォールバック（合成プレビュー）
    var url = URL.createObjectURL(file);
    return loadImage(url).then(function (img) {
      var maxSide = 2048, scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      var c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(img.width * scale));
      c.height = Math.max(1, Math.round(img.height * scale));
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      return compressCanvas(c);
    });
  }

  // ---- GAS Web App へ記録送信（任意） ----
  function recordToSheet(record) {
    var gasUrl = (els.gasUrl.value || '').trim();
    if (!gasUrl) return Promise.resolve(null);
    var payload = {
      secret: (els.gasSecret.value || '').trim(),
      title: record.title || '', postUrl: record.postUrl || '', affiliateUrl: record.affiliate || ''
    };
    return fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) })
      .then(function (res) { return res.json(); })
      .catch(function () { return null; });
  }

  // ---- 動画完成 → 確認 → 投稿（本文そのまま） → 記録 ----
  function handleVideoCreated(ev) {
    if (!els.enable.checked) return;

    var text = (els.text.value || '');
    if (!text.trim()) { setStatus('投稿本文が空です（投稿はスキップしました）。'); return; }

    var handle = (els.handle.value || '').trim();
    var appPw = (els.appPw.value || '').trim();
    if (!handle || !appPw) { setStatus('⚙設定でハンドルとアプリパスワードを入れると投稿します（今回はスキップ）。'); return; }
    if (!window.BlueskyCore) { setStatus('投稿モジュールが読み込まれていません。'); return; }

    if (!window.confirm('Bluesky に以下を投稿します。よろしいですか？\n\n――――――\n' + text + '\n――――――\n（挿入した元写真を1枚添付します）')) {
      setStatus('投稿をキャンセルしました。'); return;
    }

    var alt = (ev && ev.detail && ev.detail.title) ? String(ev.detail.title) : '';
    var gasSet = !!(els.gasUrl.value || '').trim();
    setStatus('Bluesky に投稿中…');

    getPostImageBlob().then(function (imageBlob) {
      return window.BlueskyCore.blueskyPostRaw({ identifier: handle, appPassword: appPw, text: text, imageBlob: imageBlob, alt: alt });
    }).then(function (res) {
      els._lastPost = { title: alt, postUrl: res.postUrl, affiliate: firstUrl(text) };
      setStatus('✅ Bluesky に投稿しました（@' + (res.handle || handle) + '）' + (gasSet ? '。記録中…' : ''));
      return recordToSheet(els._lastPost);
    }).then(function (rec) {
      if (rec && rec.ok && rec.shortUrl) setStatus('✅ 投稿＆記録完了。投稿の短縮URL：' + rec.shortUrl);
      else if (gasSet) setStatus('✅ 投稿しました。記録を送信しました（スプレッドシートをご確認ください）。');
    }).catch(function (e) {
      setStatus('⚠️ 投稿に失敗しました：' + (e && e.message ? e.message : e));
    });
  }

  document.addEventListener('video-created', handleVideoCreated);
})();
