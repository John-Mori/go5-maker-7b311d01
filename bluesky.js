/**
 * bluesky.js
 * Bluesky 投稿のUI配線（統合版）。2つの投稿手段を1ページで提供：
 *   方法①：動画作成後に自動投稿（#bskyEnable トグル）→ 本文(#bskyText)＋動画の元写真(#photo)
 *   方法②：単独で今すぐ投稿（#postNowBtn・🦋投稿タブ）→ 本文(#bskyText)＋任意画像(#postImg)
 * 本文・アカウント設定（ハンドル/アプリパスワード/記録設定）は両手段で共通。
 * 投稿タブには Bluesky 風のライブプレビュー（このまま投稿される見た目）を表示。
 *
 * 秘匿情報（アプリパスワード・シークレット）は console に出さない。
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var els = {
    enable: $('bskyEnable'),
    text: $('bskyText'),
    count: $('postCount'),
    handle: $('bskyHandle'),
    appPw: $('bskyAppPw'),
    gasUrl: $('bskyGasUrl'),
    gasSecret: $('bskyGasSecret'),
    bskyStatus: $('bskyStatus'),     // 自動投稿（方法①）の状態（動画作成タブ）
    postStatus: $('postStatus'),     // 単独投稿（方法②）の状態（投稿タブ）
    postNow: $('postNowBtn'),
    postImg: $('postImg'), postImgName: $('postImgName'), postImgClear: $('postImgClear'),
    pvName: $('pvName'), pvHandle: $('pvHandle'), pvBody: $('pvBody'),
    pvImgWrap: $('pvImgWrap'), pvImg: $('pvImg')
  };
  if (!els.text) return;   // 投稿UIが無ければ何もしない（安全）

  var selectedPostFile = null;   // 単独投稿の添付画像

  // ---- 設定の永続化（localStorage） ----
  var KEYS = {
    enable: 'bsky_enable', text: 'bsky_text', handle: 'bsky_handle',
    appPw: 'bsky_app_pw', gasUrl: 'bsky_gas_url', gasSecret: 'bsky_gas_secret'
  };
  var FIELDS = [
    [els.text, KEYS.text], [els.handle, KEYS.handle], [els.appPw, KEYS.appPw],
    [els.gasUrl, KEYS.gasUrl], [els.gasSecret, KEYS.gasSecret]
  ];
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  (function restore() {
    if (els.enable) els.enable.checked = (load(KEYS.enable) === '1');
    FIELDS.forEach(function (p) { if (!p[0]) return; var v = load(p[1]); if (v != null) p[0].value = v; });
  })();

  if (els.enable) els.enable.addEventListener('change', function () { save(KEYS.enable, els.enable.checked ? '1' : '0'); });
  FIELDS.forEach(function (p) {
    if (!p[0]) return;
    p[0].addEventListener('input', function () { save(p[1], p[0].value); if (p[0] === els.text || p[0] === els.handle) renderPreview(); });
  });

  // 投稿成功を通知（integration.js がスロットへ書き戻す）
  function notifyPosted(res, text) {
    try {
      document.dispatchEvent(new CustomEvent('bluesky-posted', { detail: {
        post_uri: res.uri || '', post_url: res.postUrl || '',
        affiliate: firstUrl(text), posted_at: new Date().toISOString()
      } }));
    } catch (e) {}
  }
  function setBskyStatus(m) { if (els.bskyStatus) els.bskyStatus.textContent = m || ''; }
  function setPostStatus(m, html) {
    if (!els.postStatus) return;
    if (html) els.postStatus.innerHTML = m; else els.postStatus.textContent = m || '';
  }
  function firstUrl(text) { var m = String(text).match(/https?:\/\/[^\s]+/); return m ? m[0] : ''; }

  // ---- ライブプレビュー（＝投稿される見た目） ----
  function escapeHtml(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function highlightLinks(html) { return html.replace(/(https?:\/\/[^\s]+)/g, '<span class="lnk">$1</span>'); }
  function countGraphemes(s) {
    try { if (typeof Intl !== 'undefined' && Intl.Segmenter) { var seg = new Intl.Segmenter('ja', { granularity: 'grapheme' }); var n = 0; var it = seg.segment(s)[Symbol.iterator](); while (!it.next().done) n++; return n; } } catch (e) {}
    return Array.from(s).length;
  }
  function renderPreview() {
    var text = els.text.value;
    if (els.pvBody) els.pvBody.innerHTML = text ? highlightLinks(escapeHtml(text)) : '<span class="ph">（ここに本文が表示されます）</span>';
    if (els.count) {
      var n = countGraphemes(text);
      els.count.textContent = n + ' / 300';
      els.count.classList.toggle('over', n > 300);
    }
    var h = (els.handle.value || '').trim().replace(/^@/, '');
    if (els.pvHandle) els.pvHandle.textContent = h ? ('@' + h) : '@（ハンドル未設定）';
    if (els.pvName) els.pvName.textContent = h ? h.split('.')[0] : 'あなた';
  }

  // ---- 単独投稿の画像選択 ----
  if (els.postImg) {
    els.postImg.addEventListener('change', function () {
      var f = els.postImg.files[0]; if (!f) return;
      selectedPostFile = f;
      if (els.postImgName) els.postImgName.textContent = f.name;
      if (els.postImgClear) els.postImgClear.style.display = '';
      var url = URL.createObjectURL(f);
      if (els.pvImg) els.pvImg.src = url;
      if (els.pvImgWrap) els.pvImgWrap.style.display = 'block';
    });
  }
  if (els.postImgClear) {
    els.postImgClear.addEventListener('click', function () {
      selectedPostFile = null; if (els.postImg) els.postImg.value = '';
      if (els.postImgName) els.postImgName.textContent = '未選択';
      els.postImgClear.style.display = 'none';
      if (els.pvImgWrap) els.pvImgWrap.style.display = 'none';
      if (els.pvImg) els.pvImg.removeAttribute('src');
    });
  }

  // ---- Canvas/画像 → JPEG（Bluesky の blob 上限 ≈ 976KB に収める） ----
  var MAX_BYTES = 950000;
  function toBlob(canvas, q) { return new Promise(function (r) { canvas.toBlob(r, 'image/jpeg', q); }); }
  function compressCanvas(canvas) {
    var quality = 0.9;
    function tryQuality() {
      return toBlob(canvas, quality).then(function (b) {
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
      return toBlob(c2, 0.8).then(function (b) {
        if (b && b.size <= MAX_BYTES) return b;
        if (scale > 0.35) return downscale(scale - 0.15);
        return b;
      });
    }
    return tryQuality();
  }
  function loadImage(src) {
    return new Promise(function (res, rej) {
      var img = new Image();
      img.onload = function () { res(img); };
      img.onerror = function () { rej(new Error('画像の読み込みに失敗しました')); };
      img.src = src;
    });
  }
  function compressFile(file) {
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
    var payload = { secret: (els.gasSecret.value || '').trim(), title: record.title || '', postUrl: record.postUrl || '', affiliateUrl: record.affiliate || '' };
    return fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) })
      .then(function (res) { return res.json(); })
      .catch(function () { return null; });
  }

  // 共通：認証チェック
  function creds() {
    return { handle: (els.handle.value || '').trim(), appPw: (els.appPw.value || '').trim() };
  }

  // ---- 方法②：単独で今すぐ投稿（ボタン） ----
  if (els.postNow) {
    els.postNow.addEventListener('click', function () {
      var text = (els.text.value || '');
      if (!text.trim()) { setPostStatus('本文を入力してください。'); return; }
      if (countGraphemes(text) > 300) { setPostStatus('300文字を超えています。短くしてください。'); return; }
      var c = creds();
      if (!c.handle || !c.appPw) { setPostStatus('⚙設定でハンドルとアプリパスワードを入れてください。'); return; }
      if (!window.BlueskyCore) { setPostStatus('投稿モジュール未読込。'); return; }
      if (!window.confirm('プレビュー通りに Bluesky へ投稿します。よろしいですか？')) return;

      els.postNow.disabled = true; setPostStatus('投稿中…');
      var prep = selectedPostFile ? compressFile(selectedPostFile) : Promise.resolve(null);
      var alt = (text.split('\n')[0] || '');
      prep.then(function (blob) {
        return window.BlueskyCore.blueskyPostRaw({ identifier: c.handle, appPassword: c.appPw, text: text, imageBlob: blob, alt: alt });
      }).then(function (res) {
        setPostStatus('✅ 投稿しました → <a href="' + res.postUrl + '" target="_blank" rel="noopener">投稿を開く</a>', true);
        notifyPosted(res, text);
        return recordToSheet({ title: alt, postUrl: res.postUrl, affiliate: firstUrl(text) });
      }).catch(function (e) {
        setPostStatus('⚠️ 投稿に失敗：' + (e && e.message ? e.message : e));
      }).then(function () { els.postNow.disabled = false; });
    });
  }

  // ---- 方法①：動画作成後の自動投稿（イベント購読） ----
  function handleVideoCreated(ev) {
    if (!els.enable || !els.enable.checked) return;
    var text = (els.text.value || '');
    if (!text.trim()) { setBskyStatus('投稿本文が空です（「🦋 投稿」タブで入力／今回はスキップ）。'); return; }
    var c = creds();
    if (!c.handle || !c.appPw) { setBskyStatus('「🦋 投稿」タブの⚙でハンドルとアプリパスワードを入れると自動投稿します（今回はスキップ）。'); return; }
    if (!window.BlueskyCore) { setBskyStatus('投稿モジュール未読込。'); return; }
    if (!window.confirm('Bluesky に以下を投稿します。よろしいですか？\n\n――――――\n' + text + '\n――――――\n（この動画の元写真を1枚添付します）')) {
      setBskyStatus('自動投稿をキャンセルしました。'); return;
    }
    var alt = (ev && ev.detail && ev.detail.title) ? String(ev.detail.title) : (text.split('\n')[0] || '');
    var gasSet = !!(els.gasUrl.value || '').trim();
    setBskyStatus('Bluesky に投稿中…');

    // 動画の元写真（#photo）を添付。無ければ合成プレビュー(#cv)で代替。
    var photo = $('photo'), file = photo && photo.files && photo.files[0];
    var prep = file ? compressFile(file) : (function () { var cv = $('cv'); return cv ? compressCanvas(cv) : Promise.resolve(null); })();
    prep.then(function (blob) {
      return window.BlueskyCore.blueskyPostRaw({ identifier: c.handle, appPassword: c.appPw, text: text, imageBlob: blob, alt: alt });
    }).then(function (res) {
      setBskyStatus('✅ Bluesky に投稿しました（@' + (res.handle || c.handle) + '）' + (gasSet ? '。記録中…' : ''));
      notifyPosted(res, text);
      return recordToSheet({ title: alt, postUrl: res.postUrl, affiliate: firstUrl(text) });
    }).then(function (rec) {
      if (rec && rec.ok && rec.shortUrl) setBskyStatus('✅ 投稿＆記録完了。投稿の短縮URL：' + rec.shortUrl);
      else if (gasSet) setBskyStatus('✅ 投稿しました。記録を送信しました（スプレッドシートをご確認ください）。');
    }).catch(function (e) {
      setBskyStatus('⚠️ 投稿に失敗しました：' + (e && e.message ? e.message : e));
    });
  }
  document.addEventListener('video-created', handleVideoCreated);

  renderPreview();
})();
