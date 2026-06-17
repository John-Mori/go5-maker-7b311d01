/**
 * bluesky.js
 * Bluesky 自動投稿＋記録のUI配線。
 * - 設定の永続化（ハンドル・アプリパスワード・固定文・提携文・作品URL・記録用GAS URL・ON/OFF）
 * - 動画完成イベント（app.js が発火する 'video-created'）を受け、確認ダイアログ→投稿
 * - 添付画像は「挿入した元写真そのもの」（#photo）を JPEG 圧縮（Bluesky の 1MB 制限対応）
 * - 本文のリンクは「🔗アフィリンク」タブの af_id を流用した【生のアフィリンク（無改変）】
 * - 投稿後、共有URL・タイトル・アフィリンクを GAS Web App へ送信
 *   （GAS 側で投稿URLを Bitly 短縮しスプレッドシートへ記録、クリック数は GAS が定期集計）
 *
 * 秘匿情報（アプリパスワード・af_id・シークレット）は console に出さない。
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var els = {
    enable: $('bskyEnable'),
    settings: $('bskySettings'),
    handle: $('bskyHandle'),
    appPw: $('bskyAppPw'),
    words: $('bskyWords'),
    disclosure: $('bskyDisclosure'),
    workUrl: $('bskyWorkUrl'),
    gasUrl: $('bskyGasUrl'),
    gasSecret: $('bskyGasSecret'),
    status: $('bskyStatus')
  };
  // UIが無い（未配置の）場合は何もしない＝多重読み込みや旧HTMLでも安全。
  if (!els.enable) return;

  // ---- 設定の永続化（localStorage） ----
  var KEYS = {
    enable: 'bsky_enable',
    handle: 'bsky_handle',
    appPw: 'bsky_app_pw',       // アプリパスワード（端末内のみ・revoke 可能）
    words: 'bsky_words',
    disclosure: 'bsky_disclosure',
    workUrl: 'bsky_work_url',
    gasUrl: 'bsky_gas_url',
    gasSecret: 'bsky_gas_secret'
  };
  var FIELDS = [
    [els.handle, KEYS.handle], [els.appPw, KEYS.appPw], [els.words, KEYS.words],
    [els.disclosure, KEYS.disclosure], [els.workUrl, KEYS.workUrl],
    [els.gasUrl, KEYS.gasUrl], [els.gasSecret, KEYS.gasSecret]
  ];
  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function save(key, val) { try { localStorage.setItem(key, val); } catch (e) {} }

  (function restore() {
    els.enable.checked = (load(KEYS.enable) === '1');
    FIELDS.forEach(function (pair) {
      if (!pair[0]) return;
      var v = load(pair[1]);
      if (v != null) pair[0].value = v;
    });
    syncSettingsVisibility();
  })();

  function syncSettingsVisibility() {
    if (els.settings) els.settings.hidden = !els.enable.checked;
  }

  els.enable.addEventListener('change', function () {
    save(KEYS.enable, els.enable.checked ? '1' : '0');
    syncSettingsVisibility();
  });
  FIELDS.forEach(function (pair) {
    if (!pair[0]) return;
    pair[0].addEventListener('input', function () { save(pair[1], pair[0].value); });
  });

  function setStatus(msg) { if (els.status) els.status.textContent = msg || ''; }

  // ---- 投稿に入れるリンク（作品URL＋af_id → 生のアフィリンク。無改変＝af_id保持） ----
  function resolveLink() {
    var url = (els.workUrl.value || '').trim();
    if (!url) return '';
    var afId = '';
    try { afId = localStorage.getItem('fanza_af_id') || ''; } catch (e) {}
    if (typeof buildAffiliateLink === 'function') {
      var r = buildAffiliateLink(url, afId);
      if (r && r.ok) return r.link;   // cid あり → アフィリンク
    }
    return url;                        // cid 無し等 → 元URLをそのまま
  }

  // ---- Canvas → JPEG（Bluesky の blob 上限 ≈ 976KB に収める） ----
  var MAX_BYTES = 950000;
  function toBlob(canvas, type, quality) {
    return new Promise(function (resolve) { canvas.toBlob(resolve, type, quality); });
  }
  function compressCanvas(canvas) {
    var quality = 0.9;
    function tryQuality() {
      return toBlob(canvas, 'image/jpeg', quality).then(function (b) {
        if (b && b.size <= MAX_BYTES) return b;
        quality -= 0.12;
        if (quality >= 0.3) return tryQuality();
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
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error('画像の読み込みに失敗しました')); };
      img.src = src;
    });
  }
  function getPostImageBlob() {
    var input = $('photo');
    var file = input && input.files && input.files[0];
    if (!file) return compressCanvas($('cv'));   // 念のためのフォールバック（合成プレビュー）
    var url = URL.createObjectURL(file);
    return loadImage(url).then(function (img) {
      // 元写真の比率を保ったまま、長辺を抑えてから JPEG 圧縮
      var maxSide = 2048;
      var scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      var c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(img.width * scale));
      c.height = Math.max(1, Math.round(img.height * scale));
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      return compressCanvas(c);
    });
  }

  // ---- GAS Web App へ記録送信（投稿URL→Bitly短縮＆スプレッドシート追記は GAS 側） ----
  // Content-Type を付けない＝simple request（プリフライト回避）。GAS は e.postData.contents を読む。
  function recordToSheet(record) {
    var gasUrl = (els.gasUrl.value || '').trim();
    if (!gasUrl) return Promise.resolve(null);   // 未設定ならスキップ
    var payload = {
      secret: (els.gasSecret.value || '').trim(),
      title: record.title || '',
      postUrl: record.postUrl || '',
      affiliateUrl: record.affiliate || ''
    };
    return fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) })
      .then(function (res) { return res.json(); })
      .catch(function () { return null; });   // CORS等で本文が読めなくても、記録自体は届いている
  }

  // ---- 動画完成 → 確認 → 投稿 → 記録 ----
  function handleVideoCreated(ev) {
    if (!els.enable.checked) return;

    var handle = (els.handle.value || '').trim();
    var appPw = (els.appPw.value || '').trim();
    if (!handle || !appPw) {
      setStatus('Bluesky のハンドルとアプリパスワードを入力してください（投稿はスキップしました）。');
      return;
    }
    if (!window.BlueskyCore) { setStatus('投稿モジュールが読み込まれていません。'); return; }

    var link = resolveLink();
    var built = window.BlueskyCore.buildBlueskyPost({
      words: els.words.value, disclosure: els.disclosure.value, link: link
    });

    var ok = window.confirm('Bluesky に以下を投稿します。よろしいですか？\n\n――――――\n' + built.text + '\n――――――\n（挿入した元写真を1枚添付します）');
    if (!ok) { setStatus('投稿をキャンセルしました。'); return; }

    var alt = (ev && ev.detail && ev.detail.title) ? String(ev.detail.title) : '';
    var gasSet = !!(els.gasUrl.value || '').trim();
    setStatus('Bluesky に投稿中…');

    getPostImageBlob().then(function (imageBlob) {
      return window.BlueskyCore.blueskyPostWithImage({
        identifier: handle, appPassword: appPw,
        words: els.words.value, disclosure: els.disclosure.value, link: link,
        imageBlob: imageBlob, alt: alt
      });
    }).then(function (res) {
      els._lastPost = { title: alt, postUrl: res.postUrl, affiliate: link };
      setStatus('✅ Bluesky に投稿しました（@' + (res.handle || handle) + '）' + (gasSet ? '。記録中…' : ''));
      return recordToSheet(els._lastPost);
    }).then(function (rec) {
      if (rec && rec.ok && rec.shortUrl) {
        setStatus('✅ 投稿＆記録完了。投稿の短縮URL：' + rec.shortUrl);
      } else if (gasSet) {
        setStatus('✅ 投稿しました。記録を送信しました（スプレッドシートをご確認ください）。');
      }
    }).catch(function (e) {
      setStatus('⚠️ 投稿に失敗しました：' + (e && e.message ? e.message : e));
    });
  }

  document.addEventListener('video-created', handleVideoCreated);
})();
