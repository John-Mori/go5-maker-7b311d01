/**
 * bluesky.js — Bluesky 投稿のUI配線（統合版・v19）
 *   本文＝固定文のみ（編集可）。アフィリンクは「作品URL」から投稿時に自動付与、画像も自動添付。
 *   プレビューは実アカウントのアイコンを取得して表示。投稿される見た目そのもの。
 *   投稿手段：①動画作成後の自動投稿（編集できる確認）②今すぐ投稿（単独）③予約投稿。
 *   秘匿情報（アプリパスワード・シークレット）は console に出さない。
 *   v19: アカウント別（acc1/acc2）に設定を分離。gasUrl のみ共通。
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
    pcModal: $('postConfirmModal'), pcText: $('pcText'), pcNote: $('pcNote'), pcOk: $('pcOk'), pcCancel: $('pcCancel'),
    shortUrlOut: $('shortUrlOut'), shortUrlCopy: $('shortUrlCopy'), ytDesc: $('ytDesc'), ytInsert: $('ytInsert'), ytCopy: $('ytCopy'),
    ytTitle: $('ytTitle'), ytTitleCopy: $('ytTitleCopy'), ytTags: $('ytTags'),
    discountSel: $('discountSel'), discountSel2: $('discountSel2'), discountSelPc: $('discountSelPc'),
    histList: $('histList'), histRefresh: $('histRefresh'),
    manualUrl: $('manualUrl'), manualTitle: $('manualTitle'), manualShortBtn: $('manualShortBtn'),
    manualResult: $('manualResult'), manualOut: $('manualOut'), manualCopy: $('manualCopy')
  };
  if (!els.text) return;

  var selectedPostFile = null, lastImgUrl = null;

  // ---- 汎用永続化 ----
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  // ---- アカウント別永続化ヘルパ ----
  function acctId() { return (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'); }
  function pk(base) { return base + '__' + acctId(); }
  function loadA(base) { try { return localStorage.getItem(pk(base)); } catch (e) { return null; } }
  function saveA(base, v) { try { localStorage.setItem(pk(base), v); } catch (e) {} }

  // ---- DOM初期値の保持（空アカウント時のデフォルト） ----
  var DEF = {
    text: (els.text ? els.text.value : ''),
    ytDesc: (els.ytDesc ? els.ytDesc.value : ''),
    ytTags: (els.ytTags ? els.ytTags.value : ''),
    workUrl: '', handle: '', appPw: ''
  };
  // アカウント別の本文テンプレ既定（保存が空のときに使う）。〇 は割引％のプレースホルダ。
  var DEF_TEXT = {
    acc1: 'おすすめ漫画見つけた💕\n\n↓詳細はこちらから🎀 #PR #漫画',
    acc2: '続きが気になっちゃう一冊、みつけた📚\nしかも今なら〇%オフ💕\n\n↓続きはこちらから🌙 #PR #漫画'
  };
  function defText() { return DEF_TEXT[acctId()] || DEF_TEXT.acc1; }

  // アカウント別の YouTube説明欄テンプレ既定（保存が空のときに使う）。1行目の短縮URLプレースホルダは投稿後に自動で実URLへ置換。
  var DEF_YTDESC = {
    acc1: '↑ URLを長押し&リンクを開く ↑\nこちらからアクセスしてね💕\n\n\n\n\n【感想📖】',
    acc2: '(短縮URLが入ります)\n\n⬆️URLを長押し&リンクを開く\n続きはこちらからどうぞ💫\n\n\n\n\n📚ひとこと📚'
  };
  function defYtDesc() { return DEF_YTDESC[acctId()] || DEF_YTDESC.acc1; }

  // ---- 一度だけ移行（既存の共有値を現在のアカウント名前空間へコピー） ----
  (function migrateOnce() {
    if (load('acct_split_migrated') === '1') return;
    var a = acctId();
    ['bsky_enable', 'bsky_text', 'bsky_work_url', 'bsky_handle', 'bsky_app_pw', 'bsky_unattended', 'yt_desc', 'yt_tags'].forEach(function (base) {
      var legacy = load(base);
      if (legacy != null && load(base + '__' + a) == null) { try { localStorage.setItem(base + '__' + a, legacy); } catch (e) {} }
    });
    save('acct_split_migrated', '1');
  })();

  // ---- gasUrl（共有）の復元 ----
  if (els.gasUrl) { var gv = load('bsky_gas_url'); if (gv != null) els.gasUrl.value = gv; }

  // ---- 現在アカウントの設定を画面に反映 ----
  function applyAccount() {
    // enable / unattended
    if (els.enable) els.enable.checked = (loadA('bsky_enable') === '1');
    if (els.unattended) els.unattended.checked = (loadA('bsky_unattended') === '1');

    // テキスト系（null なら DEF を使用）
    var tv = loadA('bsky_text'); if (els.text) els.text.value = (tv != null && tv !== '') ? tv : defText();
    if (els.discountSel) els.discountSel.value = '';
    if (els.discountSel2) els.discountSel2.value = '';
    if (els.histList) loadHistory();
    var wv = loadA('bsky_work_url'); if (els.workUrl) els.workUrl.value = (wv != null ? wv : DEF.workUrl);
    var hv = loadA('bsky_handle'); if (els.handle) els.handle.value = (hv != null ? hv : DEF.handle);
    var pv = loadA('bsky_app_pw'); if (els.appPw) els.appPw.value = (pv != null ? pv : DEF.appPw);
    var dv = loadA('yt_desc'); if (els.ytDesc) els.ytDesc.value = (dv != null ? dv : defYtDesc());
    var tgv = loadA('yt_tags'); if (els.ytTags) els.ytTags.value = (tgv != null ? tgv : DEF.ytTags);

    // 本文の括弧書き自動クリーンアップ（移行直後の旧注記を除去）
    if (els.text && els.text.value) {
      var cleaned = els.text.value.split('\n').filter(function (line) {
        return !/^\s*[（(].*(自動で追加|自動で添付|自動添付|自動で付).*[)）]\s*$/.test(line);
      }).join('\n').replace(/\n{3,}/g, '\n\n').replace(/^\n+|\n+$/g, '');
      if (cleaned !== els.text.value) { els.text.value = cleaned; saveA('bsky_text', cleaned); }
    }

    // アバター再取得（ハンドル変更に追従）
    var hHandle = (els.handle ? (els.handle.value || '').trim().replace(/^@/, '') : '');
    avatarFor = null; // キャッシュを無効化して再取得を強制
    ensureAvatar(hHandle);

    // 依存UIを更新
    renderPreview();
    updateGasStatus();
    buildTitle();
  }

  // ---- gasUrl の保存配線（共有） ----
  if (els.gasUrl) {
    els.gasUrl.addEventListener('input', function () {
      save('bsky_gas_url', els.gasUrl.value);
      renderPreview();
      updateGasStatus();
    });
  }

  // ---- アカウント別フィールドの保存配線 ----
  if (els.enable) els.enable.addEventListener('change', function () { saveA('bsky_enable', els.enable.checked ? '1' : '0'); });
  if (els.unattended) els.unattended.addEventListener('change', function () { saveA('bsky_unattended', els.unattended.checked ? '1' : '0'); });
  if (els.text) els.text.addEventListener('input', function () { saveA('bsky_text', els.text.value); renderPreview(); updateGasStatus(); });
  if (els.workUrl) els.workUrl.addEventListener('input', function () { saveA('bsky_work_url', els.workUrl.value); renderPreview(); updateGasStatus(); });
  if (els.handle) els.handle.addEventListener('input', function () { saveA('bsky_handle', els.handle.value); renderPreview(); updateGasStatus(); });
  if (els.appPw) els.appPw.addEventListener('input', function () { saveA('bsky_app_pw', els.appPw.value); renderPreview(); updateGasStatus(); });
  if (els.ytDesc) els.ytDesc.addEventListener('input', function () { saveA('yt_desc', els.ytDesc.value); });
  if (els.ytTags) els.ytTags.addEventListener('input', function () { saveA('yt_tags', els.ytTags.value); buildTitle(); });

  // ---- 割引％ドロップダウン（アカウント別の割引文テンプレ） ----
  // acc1：本文1行目の直下に「N%オフのおトク作品！」を挿入／なしで削除。
  // acc2：本文テンプレに含まれる「しかも今なら〇%オフ💕」の数字を差し替え／なしで〇に戻す。
  var DISC = {
    acc1: { build: function (n) { return n + '%オフのおトク作品！'; }, placeholder: '〇%オフのおトク作品！', mark: /オフのおトク作品/, persistent: false },
    acc2: { build: function (n) { return 'しかも今なら' + n + '%オフ💕'; }, placeholder: 'しかも今なら〇%オフ💕', mark: /しかも今なら[^\n]*オフ/, persistent: false }
  };
  // 割引文の挿入/差し替え/削除を行う純粋関数（対象テキストを受け取り新テキストを返す）。
  function discApply(text, val) {
    var cfg = DISC[acctId()] || DISC.acc1;
    var lines = String(text == null ? '' : text).split('\n');
    var idx = -1;
    for (var i = 0; i < lines.length; i++) { if (cfg.mark.test(lines[i])) { idx = i; break; } }
    if (val === '') {
      if (cfg.persistent) { if (idx >= 0) lines[idx] = cfg.placeholder; else lines.splice(Math.min(1, lines.length), 0, cfg.placeholder); }
      else if (idx >= 0) lines.splice(idx, 1);
    } else {
      var nl = cfg.build(val === 'custom' ? '' : val);  // custom は数字なし（ユーザーが入力）
      if (idx >= 0) lines[idx] = nl; else lines.splice(Math.min(1, lines.length), 0, nl);
    }
    return lines.join('\n');
  }
  function setDiscountLine(val) {
    if (!els.text) return;
    els.text.value = discApply(els.text.value, val);
    saveA('bsky_text', els.text.value); renderPreview(); updateGasStatus();
  }
  // 割引文：投稿タブ／動画作成タブ どちらのドロップダウンからでも共通の本文へ反映し、両方の表示を同期。
  function applyDiscount(val) {
    setDiscountLine(val);
    if (els.discountSel) els.discountSel.value = val;
    if (els.discountSel2) els.discountSel2.value = val;
  }
  if (els.discountSel) els.discountSel.addEventListener('change', function () { applyDiscount(els.discountSel.value); });
  if (els.discountSel2) els.discountSel2.addEventListener('change', function () { applyDiscount(els.discountSel2.value); });
  // 投稿確認モーダル内：この投稿のテキスト(pcText)にだけ割引文を反映（保存はしない）。
  if (els.discountSelPc) els.discountSelPc.addEventListener('change', function () {
    if (els.pcText) els.pcText.value = discApply(els.pcText.value, els.discountSelPc.value);
  });

  // ---- アカウント切替で再読込 ----
  document.addEventListener('account-changed', function () { applyAccount(); });

  // ---- テンプレ更新の一回限り移行（2026Q2）：旧テンプレ保存値を新テンプレへ。独自文（旧マーカー無し）は保持。----
  (function migrateTemplates2026q2() {
    if (load('feat_2026q2_migrated') === '1') return;
    try {  // ② acc2本文：↓全部はこちらから → ↓続きはこちらから
      var t2 = load('bsky_text__acc2');
      if (t2 && t2.indexOf('↓全部はこちらから') >= 0) save('bsky_text__acc2', t2.replace('↓全部はこちらから', '↓続きはこちらから'));
    } catch (e) {}
    ['acc1', 'acc2'].forEach(function (a) {  // ③ YouTube説明欄：旧共有テンプレ（感想/アクセス文を含む）を新テンプレへ
      try {
        var key = 'yt_desc__' + a, v = load(key);
        if (v == null || v.indexOf('【感想') >= 0 || v.indexOf('こちらからアクセスしてね') >= 0) save(key, DEF_YTDESC[a]);
      } catch (e) {}
    });
    save('feat_2026q2_migrated', '1');
  })();

  // ---- YouTube説明欄テンプレ更新の一回移行（v3）：旧/前テンプレ保存値を最新テンプレへ。独自文は保持。----
  (function migrateYtDescV3() {
    if (load('ytdesc_tpl_v3') === '1') return;
    var sig = { acc1: 'こちらからアクセスしてね', acc2: '続きはこちらからどうぞ' };
    ['acc1', 'acc2'].forEach(function (a) {
      try {
        var key = 'yt_desc__' + a, v = load(key);
        if (v == null || v.indexOf(sig[a]) >= 0 || v.indexOf('【感想') >= 0 || v.indexOf('ひとこと') >= 0) save(key, DEF_YTDESC[a]);
      } catch (e) {}
    });
    save('ytdesc_tpl_v3', '1');
  })();

  // ---- 初期化（移行→applyAccount の順） ----
  applyAccount();

  function setBskyStatus(m) { if (els.bskyStatus) els.bskyStatus.textContent = m || ''; }
  function setPostStatus(m, html) { if (!els.postStatus) return; if (html) els.postStatus.innerHTML = m; else els.postStatus.textContent = m || ''; }
  function creds() { return { handle: (els.handle.value || '').trim(), appPw: (els.appPw.value || '').trim() }; }
  function firstUrl(t) { var m = String(t).match(/https?:\/\/[^\s]+/); return m ? m[0] : ''; }
  function escapeHtml(s) { return String(s).replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }
  function highlightLinks(h) {
    h = h.replace(/(https?:\/\/[^\s]+)/g, '<span class="lnk">$1</span>');     // URL
    h = h.replace(/(^|\s)(#[^\s#<]+)/g, '$1<span class="lnk">$2</span>');     // ハッシュタグ
    return h;
  }
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
  var avatarFor = null, avatarUrl = null, displayNameVal = null;
  function setAvatar(url) {
    if (!els.pvAvatar || !els.pvAvFallback) return;
    if (url) { els.pvAvatar.src = url; els.pvAvatar.hidden = false; els.pvAvFallback.style.display = 'none'; }
    else { els.pvAvatar.hidden = true; els.pvAvatar.removeAttribute('src'); els.pvAvFallback.style.display = ''; }
  }
  // ハンドル上の表示名＝Blueskyの displayName（取得できなければハンドル先頭／未設定なら「あなた」）
  function setPvName() {
    if (!els.pvName) return;
    var h = (els.handle.value || '').trim().replace(/^@/, '');
    els.pvName.textContent = displayNameVal || (h ? h.split('.')[0] : 'あなた');
  }
  function ensureAvatar(handle) {
    if (!handle) { setAvatar(null); displayNameVal = null; setPvName(); return; }
    if (avatarFor === handle) { setAvatar(avatarUrl); setPvName(); return; }
    avatarFor = handle; displayNameVal = null;
    var ck = 'bsky_avatar_' + handle, dk = 'bsky_dn_' + handle;
    try { var c = localStorage.getItem(ck); if (c) { avatarUrl = c; setAvatar(c); } } catch (e) {}
    try { var dn = localStorage.getItem(dk); if (dn) { displayNameVal = dn; } } catch (e) {}
    setPvName();
    fetch('https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=' + encodeURIComponent(handle))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (avatarFor !== handle) return; // ハンドルが変わっていたら古い結果は無視
        if (j && j.avatar) { avatarUrl = j.avatar; try { localStorage.setItem(ck, j.avatar); } catch (e) {} setAvatar(j.avatar); }
        if (j && j.displayName) { displayNameVal = j.displayName; try { localStorage.setItem(dk, j.displayName); } catch (e) {} }
        setPvName();
      })
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
    ensureAvatar(h); // 表示名(displayName)とアバターを設定（pvName はここで反映）

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

  // ---- 短縮URL表示・コピー助関数 ----
  var prevShortUrl = '', lastShortUrl = '';
  var PLACEHOLDER_URL = '（投稿するとここに短縮URLが入ります）';
  function fallbackCopy(text, ok) {
    var ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.focus(); ta.select();
    try { document.execCommand('copy'); ok && ok(); } catch (e) {} document.body.removeChild(ta);
  }
  function copyText(text, btn) {
    function ok() { if (!btn) return; if (!btn.dataset.label) btn.dataset.label = btn.textContent; btn.textContent = '✓ コピーしました'; setTimeout(function () { btn.textContent = btn.dataset.label; }, 1500); }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(ok).catch(function () { fallbackCopy(text, ok); });
    else fallbackCopy(text, ok);
  }
  function putUrlTop(url) {
    if (!url || !els.ytDesc) return;
    var lines = els.ytDesc.value.split('\n'); if (!lines.length) lines = [''];
    var f = (lines[0] || '').trim();
    // 1行目が「短縮URLプレースホルダ」or 前回URL or URL なら置換。それ以外（例：↑案内文）は上に差し込む。
    if (f === PLACEHOLDER_URL || f === prevShortUrl || /^https?:\/\//.test(f) || /短縮URL/.test(f)) lines[0] = url;
    else lines.unshift(url);
    els.ytDesc.value = lines.join('\n'); saveA('yt_desc', els.ytDesc.value);
  }
  function setShareOutputs(shortUrl, fallbackUrl) {
    var url = shortUrl || fallbackUrl || '';
    if (els.shortUrlOut) els.shortUrlOut.textContent = url || '（短縮URLを取得できませんでした）';
    if (url) { putUrlTop(url); prevShortUrl = url; lastShortUrl = url; }
  }

  // ---- GAS 記録（共有シークレットは廃止） ----
  function recordToSheet(record) {
    var gasUrl = (els.gasUrl.value || '').trim(); if (!gasUrl) return Promise.resolve(null);
    var payload = {
      channel: (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'),
      title: record.title || '', postUrl: record.postUrl || '', affiliateUrl: record.affiliate || '',
      workUrl: ((els.workUrl && els.workUrl.value) || '').trim(),
      hashtags: record.hashtags || '', postUri: record.postUri || ''
    };
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
    var tags = (String(text).match(/#[^\s#]+/g) || []).join(' ');
    try { document.dispatchEvent(new CustomEvent('bluesky-posted', { detail: { post_uri: res.uri || '', post_url: res.postUrl || '', affiliate: firstUrl(text), hashtags: tags, posted_at: new Date().toISOString(), title: alt || (String(text).split('\n')[0] || '') } })); } catch (e) {}
  }
  // すべての投稿を一元的に記録（即時・自動・予約のどれでも必ず記録される）
  document.addEventListener('bluesky-posted', function (e) {
    var d = (e && e.detail) || {};
    recordToSheet({ title: d.title || '', postUrl: d.post_url, affiliate: d.affiliate, hashtags: d.hashtags, postUri: d.post_uri }); // 分析シートへ記録（結果は使わない）
    shortenAndShow(d.post_url, d.post_uri, d.title);  // 短縮URLはブラウザ側で生成（GAS/Bitly非依存）
  });

  // ブラウザだけで短縮（CORS対応・トークン不要）。失敗時は空文字。
  //   一次：da.gd（結果が x.gd 並みに短い「da.gd/xxxxx」。Access-Control-Allow-Origin:* で全ブラウザ確実）
  //   二次：TinyURL（da.gd が落ちている時の保険。CORSは Origin 反射のため不安定なことがある）
  function shortenVia(api, longUrl) {
    return fetch(api + encodeURIComponent(longUrl))
      .then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (t) { t = String(t || '').trim(); return /^https?:\/\//.test(t) ? t : ''; })
      .catch(function () { return ''; });
  }
  function shortenUrl(longUrl) {
    if (!longUrl) return Promise.resolve('');
    return shortenVia('https://da.gd/s?url=', longUrl).then(function (s) {
      return s || shortenVia('https://tinyurl.com/api-create.php?url=', longUrl);
    });
  }
  function shortenAndShow(longUrl, postUri, title) {
    if (!longUrl) return;
    if (els.shortUrlOut) els.shortUrlOut.textContent = '短縮URLを作成中…';
    shortenUrl(longUrl).then(function (short) {
      var url = short || longUrl;                      // 失敗時は長いURLで代替（リンクは有効）
      setShareOutputs(url, longUrl);
      histAdd({ title: title, shortUrl: url, postUrl: longUrl, postUri: postUri });
    });
  }

  // JSONP（CORS回避）でGASから値を取得。<script>はCORS対象外なのでPOST応答が読めない環境でも確実。
  function jsonpGet(url, cb) {
    var s = document.createElement('script');
    jsonpGet._n = (jsonpGet._n || 0) + 1;
    var name = '__gascb' + jsonpGet._n + '_' + (new Date().getTime());
    var done = false;
    window[name] = function (data) { done = true; try { cb(data); } finally { try { delete window[name]; } catch (e) {} if (s.parentNode) s.parentNode.removeChild(s); } };
    s.onerror = function () { if (done) return; try { delete window[name]; } catch (e) {} if (s.parentNode) s.parentNode.removeChild(s); cb(null); };
    s.src = url + (url.indexOf('?') >= 0 ? '&' : '?') + 'callback=' + name;
    document.head.appendChild(s);
  }

  // ---- 過去の短縮URL履歴（端末内・アカウント別。GAS非依存で確実）----
  function histKey() { return 'short_hist__' + acctId(); }
  function histLoad() { try { return JSON.parse(localStorage.getItem(histKey()) || '[]'); } catch (e) { return []; } }
  function histSaveArr(a) { try { localStorage.setItem(histKey(), JSON.stringify(a.slice(0, 200))); } catch (e) {} }
  function histAdd(rec) {
    if (!rec || !rec.shortUrl) return; // 短縮URLが取れた投稿だけ記録
    var a = histLoad().filter(function (x) { return rec.postUri ? x.postUri !== rec.postUri : x.shortUrl !== rec.shortUrl; }); // 同一投稿の重複を排除
    a.unshift({ ts: new Date().getTime(), title: rec.title || '', shortUrl: rec.shortUrl, postUrl: rec.postUrl || '', postUri: rec.postUri || '' });
    histSaveArr(a);
    if (els.histList) renderHistory(a);
  }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  function loadHistory() { if (els.histList) renderHistory(histLoad()); }
  function renderHistory(items) {
    if (!els.histList) return;
    if (!items.length) { els.histList.innerHTML = '<p class="hint">このアカウントの履歴はまだありません（投稿して短縮URLが出ると、ここに自動で貯まります）。</p>'; return; }
    els.histList.innerHTML = items.map(function (it) {
      var short = it.shortUrl || '';
      return '<div class="hist-row">' +
        '<div class="hist-meta">' + escapeHtml(fmtTs(it.ts)) + '　' + escapeHtml(it.title || '(無題)') + '</div>' +
        '<div class="hist-act">' +
        '<code class="hist-url">' + escapeHtml(short) + '</code>' +
        '<button class="copy-btn hist-copy" type="button" data-url="' + escapeHtml(short) + '">コピー</button>' +
        '<button class="ghost hist-ins" type="button" data-url="' + escapeHtml(short) + '">概要欄へ</button>' +
        (it.postUrl ? '<a class="ghost" href="' + escapeHtml(it.postUrl) + '" target="_blank" rel="noopener">投稿↗</a>' : '') +
        '<button class="ghost hist-del" type="button" data-uri="' + escapeHtml(it.postUri || '') + '" data-short="' + escapeHtml(short) + '" data-title="' + escapeHtml(it.title || '') + '">🗑 削除</button>' +
        '</div></div>';
    }).join('');
    els.histList.querySelectorAll('.hist-copy').forEach(function (b) { b.addEventListener('click', function () { copyText(b.getAttribute('data-url'), b); }); });
    els.histList.querySelectorAll('.hist-ins').forEach(function (b) { b.addEventListener('click', function () { setShareOutputs(b.getAttribute('data-url'), ''); b.textContent = '✓ 入れました'; setTimeout(function () { b.textContent = '概要欄へ'; }, 1500); }); });
    els.histList.querySelectorAll('.hist-del').forEach(function (b) { b.addEventListener('click', function () { deleteHistory(b.getAttribute('data-uri'), b.getAttribute('data-short'), b.getAttribute('data-title')); }); });
  }
  function deleteHistory(postUri, short, title) {
    if (!window.confirm('「' + (title || 'この投稿') + '」を履歴から削除しますか？\n（取り消せません）')) return;
    var a = histLoad().filter(function (x) { return postUri ? x.postUri !== postUri : x.shortUrl !== short; });
    histSaveArr(a); renderHistory(a);
  }
  if (els.histRefresh) els.histRefresh.addEventListener('click', loadHistory);
  var ytTabBtn_ = document.getElementById('tabYT');
  if (ytTabBtn_) ytTabBtn_.addEventListener('click', loadHistory);

  // ---- 手動短縮（アプリ外で単独投稿した分のURLを貼って短縮＋履歴追加）----
  if (els.manualShortBtn) els.manualShortBtn.addEventListener('click', function () {
    var url = (els.manualUrl && els.manualUrl.value || '').trim();
    if (!/^https?:\/\//.test(url)) {
      if (els.manualOut) els.manualOut.textContent = 'URLは http:// か https:// で始めてください';
      if (els.manualResult) els.manualResult.hidden = false;
      return;
    }
    var btn = els.manualShortBtn, orig = btn.textContent;
    btn.disabled = true; btn.textContent = '短縮中…';
    shortenUrl(url).then(function (short) {
      var s = short || url;  // 失敗時は元URLで代替
      if (els.manualOut) els.manualOut.textContent = s;
      if (els.manualResult) els.manualResult.hidden = false;
      histAdd({ title: (els.manualTitle && els.manualTitle.value || '').trim() || '(手動追加)', shortUrl: s, postUrl: url, postUri: '' });
      btn.textContent = '✓ 履歴に追加しました'; setTimeout(function () { btn.textContent = orig; btn.disabled = false; }, 1600);
      if (els.manualUrl) els.manualUrl.value = '';
      if (els.manualTitle) els.manualTitle.value = '';
    });
  });
  if (els.manualCopy) els.manualCopy.addEventListener('click', function () { copyText(els.manualOut.textContent, els.manualCopy); });

  // ---- 編集できる確認モーダル（方法①自動投稿） ----
  function confirmEditable(text, note) {
    return new Promise(function (resolve) {
      if (!els.pcModal) { resolve(window.confirm(text) ? text : null); return; }
      els.pcText.value = text;
      if (els.discountSelPc) els.discountSelPc.value = '';
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
    var payload = { type: 'reserve', channel: (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'), scheduled_at: new Date(ms).toISOString(), text: text, slot_id: slotId || '' };
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

  if (els.shortUrlCopy) els.shortUrlCopy.addEventListener('click', function () { if (lastShortUrl) copyText(lastShortUrl, els.shortUrlCopy); });
  if (els.ytCopy) els.ytCopy.addEventListener('click', function () { if (els.ytDesc) copyText(els.ytDesc.value, els.ytCopy); });
  if (els.ytInsert) els.ytInsert.addEventListener('click', function () { if (lastShortUrl) putUrlTop(lastShortUrl); });

  var lastTitle = '';
  var topEl = document.getElementById('top');
  function buildTitle() {
    if (!els.ytTitle) return;
    var comment = (topEl && topEl.value ? topEl.value.trim() : '');
    var tags = (els.ytTags && els.ytTags.value ? els.ytTags.value.trim() : '');
    var title = comment + (comment && tags ? ' ' : '') + tags;
    lastTitle = title;
    els.ytTitle.textContent = title || '（「動画作成」タブのコメントを入れると題名が出ます）';
  }
  if (topEl) topEl.addEventListener('input', buildTitle);
  var tabPostBtn = document.getElementById('tabPost'); if (tabPostBtn) tabPostBtn.addEventListener('click', buildTitle);
  if (els.ytTitleCopy) els.ytTitleCopy.addEventListener('click', function () { if (lastTitle) copyText(lastTitle, els.ytTitleCopy); });
  buildTitle();
})();
