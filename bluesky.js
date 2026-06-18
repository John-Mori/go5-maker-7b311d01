/**
 * bluesky.js — Bluesky 投稿のUI配線（統合版・v18）
 *   本文＝固定文のみ（編集可）。アフィリンクは「作品URL」から投稿時に自動付与、画像も自動添付。
 *   プレビューは実アカウントのアイコンを取得して表示。投稿される見た目そのもの。
 *   投稿手段：①動画作成後の自動投稿（編集できる確認）②今すぐ投稿（単独）③予約投稿。
 *   秘匿情報（アプリパスワード・シークレット）は console に出さない。
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  var els = {
    enable: $('bskyEnable'), text: $('bskyText'), count: $('postCount'), workUrl: $('bskyWorkUrl'),
    handle: $('bskyHandle'), appPw: $('bskyAppPw'), gasUrl: $('bskyGasUrl'), gasStatus: $('gasStatus'),
    bskyStatus: $('bskyStatus'), postStatus: $('postStatus'), postNow: $('postNowBtn'),
    schedAt: $('postSchedAt'), reserveBtn: $('postReserveBtn'), unattended: $('bskyUnattended'),
    postImg: $('postImg'), postImgName: $('postImgName'), postImgClear: $('postImgClear'),
    pvName: $('pvName'), pvHandle: $('pvHandle'), pvBody: $('pvBody'),
    pvImgWrap: $('pvImgWrap'), pvImg: $('pvImg'), pvImgNote: $('pvImgNote'),
    pvAvatar: $('pvAvatar'), pvAvFallback: $('pvAvFallback'),
    pcModal: $('postConfirmModal'), pcText: $('pcText'), pcNote: $('pcNote'), pcOk: $('pcOk'), pcCancel: $('pcCancel')
  };
  if (!els.text) return;

  var selectedPostFile = null, lastImgUrl = null;

  // ---- 永続化 ----
  var KEYS = {
    enable: 'bsky_enable', text: 'bsky_text', workUrl: 'bsky_work_url',
    handle: 'bsky_handle', appPw: 'bsky_app_pw', gasUrl: 'bsky_gas_url'
  };
  var FIELDS = [
    [els.text, KEYS.text], [els.workUrl, KEYS.workUrl], [els.handle, KEYS.handle],
    [els.appPw, KEYS.appPw], [els.gasUrl, KEYS.gasUrl]
  ];
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  (function restore() {
    if (els.enable) els.enable.checked = (load(KEYS.enable) === '1');
    FIELDS.forEach(function (p) { if (!p[0]) return; var v = load(p[1]); if (v != null) p[0].value = v; });
    // 移行：旧本文に紛れ込んだ説明の括弧書き（自動付与の注記）を一度だけ除去
    if (els.text && els.text.value) {
      var cleaned = els.text.value.split('\n').filter(function (line) {
        return !/^\s*[（(].*(自動で追加|自動で添付|自動添付|自動で付).*[)）]\s*$/.test(line);
      }).join('\n').replace(/\n{3,}/g, '\n\n').replace(/^\n+|\n+$/g, '');
      if (cleaned !== els.text.value) { els.text.value = cleaned; save(KEYS.text, cleaned); }
    }
  })();
  if (els.enable) els.enable.addEventListener('change', function () { save(KEYS.enable, els.enable.checked ? '1' : '0'); });
  if (els.unattended) { els.unattended.checked = (load('bsky_unattended') === '1'); els.unattended.addEventListener('change', function () { save('bsky_unattended', els.unattended.checked ? '1' : '0'); }); }
  FIELDS.forEach(function (p) {
    if (!p[0]) return;
    p[0].addEventListener('input', function () { save(p[1], p[0].value); renderPreview(); updateGasStatus(); });
  });

  function setBskyStatus(m) { if (els.bskyStatus) els.bskyStatus.textContent = m || ''; }
  function setPostStatus(m, html) { if (!els.postStatus) return; if (html) els.postStatus.innerHTML = m; else els.postStatus.textContent = m || ''; }
  function creds() { return { handle: (els.handle.value || '').trim(), appPw: (els.appPw.value || '').trim() }; }
  function firstUrl(t) { var m = String(t).match(/https?:\/\/[^\s]+/); return m ? m[0] : ''; }
  function escapeHtml(s) { return String(s).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }
  function highlightLinks(h) { return h.replace(/(https?:\/\/[^\s]+)/g, '<span class="lnk">$1</span>'); }
  function countGraphemes(s) {
    try { if (typeof Intl !== 'undefined' && Intl.Segmenter) { var seg = new Intl.Segmenter('ja', { granularity: 'grapheme' }); var n = 0, it = seg.segment(s)[Symbol.iterator](); while (!it.next().done) n++; return n; } } catch (e) {}
    return Array.from(s).length;
  }
  function photoFile() { var p = $('photo'); return p && p.files && p.files[0]; }

  // ---- アフィリンク自動付与・本文合成 ----
  function resolveAffLink() {
    var url = (els.workUrl.value || '').trim(); if (!url) return '';
    var afId = ''; try { afId = localStorage.getItem('fanza_af_id') || ''; } catch (e) {}
    if (typeof buildAffiliateLink === 'function') { var r = buildAffiliateLink(url, afId); if (r && r.ok) return r.link; }
    return url;
  }
  function composePostText() {
    var caption = (els.text.value || '').replace(/[ \t\r\n]+$/, '');
    var link = resolveAffLink();
    return link ? (caption + '\n\n' + link) : caption;
  }

  // ---- アバター（実アカウントのアイコンを公開APIで取得） ----
  var avatarFor = null, avatarUrl = null;
  function setAvatar(url) {
    if (!els.pvAvatar || !els.pvAvFallback) return;
    if (url) { els.pvAvatar.src = url; els.pvAvatar.hidden = false; els.pvAvFallback.style.display = 'none'; }
    else { els.pvAvatar.hidden = true; els.pvAvatar.removeAttribute('src'); els.pvAvFallback.style.display = ''; }
  }
  function ensureAvatar(handle) {
    if (!handle) { setAvatar(null); return; }
    if (avatarFor === handle) { setAvatar(avatarUrl); return; }
    avatarFor = handle;
    var ck = 'bsky_avatar_' + handle;
    try { var c = localStorage.getItem(ck); if (c) { avatarUrl = c; setAvatar(c); } } catch (e) {}
    fetch('https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=' + encodeURIComponent(handle))
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j && j.avatar) { avatarUrl = j.avatar; try { localStorage.setItem(ck, j.avatar); } catch (e) {} setAvatar(j.avatar); } })
      .catch(function () {});
  }

  // ---- プレビュー画像（単独=選択画像／無ければ動画の元写真／無ければ自動添付の注記） ----
  function showPreviewImage(file) {
    if (lastImgUrl) { try { URL.revokeObjectURL(lastImgUrl); } catch (e) {} }
    lastImgUrl = URL.createObjectURL(file);
    els.pvImg.src = lastImgUrl; els.pvImgWrap.style.display = 'block';
    if (els.pvImgNote) els.pvImgNote.style.display = 'none';
  }
  function hidePreviewImage() {
    els.pvImgWrap.style.display = 'none'; els.pvImg.removeAttribute('src');
    if (els.pvImgNote) els.pvImgNote.style.display = 'block';
  }

  // ---- プレビュー描画（＝投稿される見た目） ----
  function renderPreview() {
    var caption = els.text.value;
    var link = resolveAffLink();
    var html = caption ? highlightLinks(escapeHtml(caption)) : '<span class="ph">（本文）</span>';
    html += link ? ('\n\n<span class="lnk">' + escapeHtml(link) + '</span>')
                 : '\n\n<span class="ph">（投稿時にアフィリンクを自動で追加します）</span>';
    if (els.pvBody) els.pvBody.innerHTML = html;

    if (els.count) { var n = countGraphemes(composePostText()); els.count.textContent = n + ' / 300'; els.count.classList.toggle('over', n > 300); }

    var h = (els.handle.value || '').trim().replace(/^@/, '');
    if (els.pvHandle) els.pvHandle.textContent = h ? ('@' + h) : '@（ハンドル未設定）';
    if (els.pvName) els.pvName.textContent = h ? h.split('.')[0] : 'あなた';
    ensureAvatar(h);

    var f = selectedPostFile || photoFile();
    if (f) showPreviewImage(f); else hidePreviewImage();
  }

  // 動画作成タブの写真選択にも追従（自動投稿の画像プレビュー反映）
  (function () { var p = $('photo'); if (p) p.addEventListener('change', function () { renderPreview(); }); })();

  // ---- 単独投稿の画像選択 ----
  if (els.postImg) {
    els.postImg.addEventListener('change', function () {
      var f = els.postImg.files[0]; if (!f) return;
      selectedPostFile = f;
      if (els.postImgName) els.postImgName.textContent = f.name;
      if (els.postImgClear) els.postImgClear.style.display = '';
      renderPreview();
    });
  }
  if (els.postImgClear) {
    els.postImgClear.addEventListener('click', function () {
      selectedPostFile = null; if (els.postImg) els.postImg.value = '';
      if (els.postImgName) els.postImgName.textContent = '未選択';
      els.postImgClear.style.display = 'none'; renderPreview();
    });
  }

  // ---- 画像圧縮（Bluesky blob 上限 ≈ 976KB） ----
  var MAX_BYTES = 950000;
  function toBlob(c, q) { return new Promise(function (r) { c.toBlob(r, 'image/jpeg', q); }); }
  function compressCanvas(canvas) {
    var quality = 0.9;
    function tryQ() { return toBlob(canvas, quality).then(function (b) { if (b && b.size <= MAX_BYTES) return b; quality -= 0.12; if (quality >= 0.3) return tryQ(); return down(0.85); }); }
    function down(sc) { var c2 = document.createElement('canvas'); c2.width = Math.max(1, Math.round(canvas.width * sc)); c2.height = Math.max(1, Math.round(canvas.height * sc)); c2.getContext('2d').drawImage(canvas, 0, 0, c2.width, c2.height); return toBlob(c2, 0.8).then(function (b) { if (b && b.size <= MAX_BYTES) return b; if (sc > 0.35) return down(sc - 0.15); return b; }); }
    return tryQ();
  }
  function loadImage(src) { return new Promise(function (res, rej) { var i = new Image(); i.onload = function () { res(i); }; i.onerror = function () { rej(new Error('画像の読み込みに失敗')); }; i.src = src; }); }
  function compressFile(file) {
    var url = URL.createObjectURL(file);
    return loadImage(url).then(function (img) {
      var maxSide = 2048, scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      var c = document.createElement('canvas'); c.width = Math.max(1, Math.round(img.width * scale)); c.height = Math.max(1, Math.round(img.height * scale));
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      return compressCanvas(c);
    });
  }

  // ---- GAS 記録（共有シークレットは廃止） ----
  function recordToSheet(record) {
    var gasUrl = (els.gasUrl.value || '').trim(); if (!gasUrl) return Promise.resolve(null);
    var payload = { title: record.title || '', postUrl: record.postUrl || '', affiliateUrl: record.affiliate || '' };
    return fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) }).then(function (r) { return r.json(); }).catch(function () { return null; });
  }
  function updateGasStatus() {
    if (!els.gasStatus) return;
    var on = !!(els.gasUrl.value || '').trim();
    els.gasStatus.textContent = on ? '記録：ON（すべての投稿をこのGASに記録します）' : '記録：OFF（URL未設定。記録・検証するには設定してください）';
    els.gasStatus.className = 'gas-status ' + (on ? 'on' : 'off');
  }

  // 投稿成功通知（integration.js が書き戻し＋下のリスナが必ず記録）
  function notifyPosted(res, text, alt) {
    try { document.dispatchEvent(new CustomEvent('bluesky-posted', { detail: { post_uri: res.uri || '', post_url: res.postUrl || '', affiliate: firstUrl(text), posted_at: new Date().toISOString(), title: alt || (String(text).split('\n')[0] || '') } })); } catch (e) {}
  }
  // すべての投稿を一元的に記録（即時・自動・予約のどれでも必ず記録される）
  document.addEventListener('bluesky-posted', function (e) {
    var d = (e && e.detail) || {};
    recordToSheet({ title: d.title || '', postUrl: d.post_url, affiliate: d.affiliate });
  });

  // ---- 編集できる確認モーダル（方法①自動投稿） ----
  function confirmEditable(text, note) {
    return new Promise(function (resolve) {
      if (!els.pcModal) { resolve(window.confirm(text) ? text : null); return; }
      els.pcText.value = text;
      if (els.pcNote) els.pcNote.textContent = note || '';
      els.pcModal.hidden = false;
      function cleanup() { els.pcModal.hidden = true; els.pcOk.removeEventListener('click', ok); els.pcCancel.removeEventListener('click', cancel); }
      function ok() { var v = els.pcText.value; cleanup(); resolve(v); }
      function cancel() { cleanup(); resolve(null); }
      els.pcOk.addEventListener('click', ok); els.pcCancel.addEventListener('click', cancel);
    });
  }

  // ---- 方法②：今すぐ投稿（単独） ----
  if (els.postNow) {
    els.postNow.addEventListener('click', function () {
      if (!els.text.value.trim()) { setPostStatus('本文を入力してください。'); return; }
      var text = composePostText();
      if (countGraphemes(text) > 300) { setPostStatus('300文字を超えています。短くしてください。'); return; }
      var c = creds(); if (!c.handle || !c.appPw) { setPostStatus('⚙設定でハンドルとアプリパスワードを入れてください。'); return; }
      if (!window.BlueskyCore) { setPostStatus('投稿モジュール未読込。'); return; }
      if (!window.confirm('プレビュー通りに Bluesky へ投稿します。よろしいですか？')) return;
      els.postNow.disabled = true; setPostStatus('投稿中…');
      var alt = (text.split('\n')[0] || ''), f = selectedPostFile || photoFile();
      (f ? compressFile(f) : Promise.resolve(null))
        .then(function (blob) { return window.BlueskyCore.blueskyPostRaw({ identifier: c.handle, appPassword: c.appPw, text: text, imageBlob: blob, alt: alt }); })
        .then(function (res) { setPostStatus('✅ 投稿しました → <a href="' + res.postUrl + '" target="_blank" rel="noopener">投稿を開く</a>', true); notifyPosted(res, text, alt); })
        .catch(function (e) { setPostStatus('⚠️ 投稿に失敗：' + (e && e.message ? e.message : e)); })
        .then(function () { els.postNow.disabled = false; });
    });
  }

  // ---- 無人予約（Phase5）：GASへ送信し、時間トリガーが投稿（タブを閉じてもOK） ----
  function reserveUnattended(text, blob, ms, slotId) {
    var gasUrl = (els.gasUrl.value || '').trim();
    if (!gasUrl) { setPostStatus('無人予約には⚙の「記録用URL（GAS）」設定が必要です。'); return; }
    var payload = { type: 'reserve', scheduled_at: new Date(ms).toISOString(), text: text, slot_id: slotId || '' };
    function send() {
      setPostStatus('☁️ 無人予約を送信中…');
      fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j && j.ok) setPostStatus('☁️ 無人予約しました：' + new Date(ms).toLocaleString('ja-JP') + '（タブを閉じてもOK）');
          else setPostStatus('予約に失敗：' + ((j && j.error) || '不明'));
        })
        .catch(function () { setPostStatus('予約送信に失敗（GAS URL・通信をご確認ください）。'); });
    }
    if (blob) { var fr = new FileReader(); fr.onload = function () { payload.image = fr.result; send(); }; fr.onerror = function () { send(); }; fr.readAsDataURL(blob); }
    else send();
  }

  // ---- 方法③：予約投稿（無人＝GAS／開いている間＝端末タイマー） ----
  if (els.reserveBtn) {
    els.reserveBtn.addEventListener('click', function () {
      if (!els.text.value.trim()) { setPostStatus('本文を入力してください。'); return; }
      var v = els.schedAt && els.schedAt.value, ms = v ? new Date(v).getTime() : NaN;
      if (isNaN(ms)) { setPostStatus('予約時刻を指定してください。'); return; }
      if (ms <= Date.now()) { setPostStatus('未来の時刻を指定してください。'); return; }
      var text = composePostText(), alt = (text.split('\n')[0] || '');
      var slotId = window.__activeSlot__ ? window.__activeSlot__.id : null, f = selectedPostFile || photoFile();
      var unattended = els.unattended && els.unattended.checked;
      setPostStatus('予約を準備中…');
      if (unattended) {
        (f ? compressFile(f) : Promise.resolve(null)).then(function (blob) { reserveUnattended(text, blob, ms, slotId); });
        return;
      }
      var c = creds();
      if (!c.handle || !c.appPw) { setPostStatus('⚙設定でハンドルとアプリパスワードを入れてください（無人予約ならGAS設定）。'); return; }
      if (!window.Scheduler) { setPostStatus('スケジューラ未読込。'); return; }
      (f ? compressFile(f) : Promise.resolve(null)).then(function (blob) {
        window.Scheduler.reserve({ slotId: slotId, text: text, imageBlob: blob, scheduledAtMs: ms, alt: alt, handle: c.handle, appPw: c.appPw });
        setPostStatus('⏰ 予約しました：' + new Date(ms).toLocaleString('ja-JP') + '（このタブを開いている間に自動投稿）');
      });
    });
  }

  // ---- 方法①：動画作成後の自動投稿（編集できる確認） ----
  function handleVideoCreated(ev) {
    if (!els.enable || !els.enable.checked) return;
    var c = creds();
    if (!c.handle || !c.appPw) { setBskyStatus('「🦋 投稿」タブの⚙でハンドルとアプリパスワードを入れると自動投稿します（今回はスキップ）。'); return; }
    if (!window.BlueskyCore) { setBskyStatus('投稿モジュール未読込。'); return; }
    var composed = composePostText();
    if (!composed.trim()) { setBskyStatus('投稿本文が空です（「🦋 投稿」タブで入力）。'); return; }
    var alt = (ev && ev.detail && ev.detail.title) ? String(ev.detail.title) : (composed.split('\n')[0] || '');
    confirmEditable(composed, 'この動画の元写真を1枚自動で添付します').then(function (edited) {
      if (edited == null) { setBskyStatus('自動投稿をキャンセルしました。'); return; }
      if (!edited.trim()) { setBskyStatus('本文が空のため中止しました。'); return; }
      var gasSet = !!(els.gasUrl.value || '').trim();
      setBskyStatus('Bluesky に投稿中…');
      var photo = photoFile();
      var prep = photo ? compressFile(photo) : (function () { var cv = $('cv'); return cv ? compressCanvas(cv) : Promise.resolve(null); })();
      prep.then(function (blob) { return window.BlueskyCore.blueskyPostRaw({ identifier: c.handle, appPassword: c.appPw, text: edited, imageBlob: blob, alt: alt }); })
        .then(function (res) { setBskyStatus('✅ Bluesky に投稿しました（@' + (res.handle || c.handle) + '）' + (gasSet ? '・記録しました' : '')); notifyPosted(res, edited, alt); })
        .catch(function (e) { setBskyStatus('⚠️ 投稿に失敗しました：' + (e && e.message ? e.message : e)); });
    });
  }
  document.addEventListener('video-created', handleVideoCreated);

  renderPreview();
  updateGasStatus();
})();
