/**
 * yt-clicks.js — 検証タブの「再生数・クリック数（投稿別）」一覧。
 *
 * 投稿ごとに：
 *   ・短縮URLのクリック数 … link-worker /api/stats（go5-short）から取得（共有シークレットで読み取り）。
 *   ・YouTube動画の再生数・投稿日時・タイトル … YouTube Data API v3（端末内のAPIキー）から取得。
 *
 * 行の見出し日時は「YouTubeに投稿した時刻（snippet.publishedAt）」を表示する（動画の作成時刻ではない）。
 * 並び順：YouTube投稿日時が新しいものほど上。YouTube URL未入力＝投稿日時不明のものは末尾へ。
 *
 * データ源：
 *   ・端末内の短縮URL履歴 short_hist__<acct>（bluesky.js が投稿のたびに記録）
 *   ・手動追加分 verify_manual__<acct>（このタブの「手動で追加」）
 *   ・各行のYouTube動画URL verify_yt__<acct>（行ごとに入力・ウィザードが自動プリフィル）
 * 完全クライアントサイド。APIキーはこの端末内だけに保存（リポジトリには置かない）。
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  if (!$('ytClickList')) return;

  function acct() { try { return localStorage.getItem('current_account') || 'acc1'; } catch (e) { return 'acc1'; } }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // 作品属性（複数可）。キャラ=実在キャラの二次創作 / JK / ギャル / 異世界。キャラ無し＝オリジナル(非表示)。
  var ATTR_DEFS = [
    { key: 'chara', label: 'キャラ' },
    { key: 'jk', label: 'JK' },
    { key: 'gyaru', label: 'ギャル' },
    { key: 'isekai', label: '異世界' }
  ];
  var COMMON_TAGS = ['#マンガ紹介', '#漫画', '#アニメ', '#anime'];
  function stripCommonTags(t) {
    var r = String(t || '');
    COMMON_TAGS.forEach(function (tag) { r = r.split(tag).join(''); });
    return r.replace(/\s+/g, ' ').trim();
  }
  function missingCommonTags(t) { return COMMON_TAGS.some(function (tag) { return String(t || '').indexOf(tag) < 0; }); }
  function histKey() { return 'short_hist__' + acct(); }
  function manualKey() { return 'verify_manual__' + acct(); }
  function ytMapKey() { return 'verify_yt__' + acct(); }
  function loadArr(k) { try { var a = JSON.parse(localStorage.getItem(k) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
  function saveArr(k, a) { try { localStorage.setItem(k, JSON.stringify(a)); } catch (e) {} }
  function loadHist() { return loadArr(histKey()); }
  function loadManual() { return loadArr(manualKey()); }
  function loadYtMap() { try { return JSON.parse(localStorage.getItem(ytMapKey()) || '{}') || {}; } catch (e) { return {}; } }
  function saveYtMap(m) { try { localStorage.setItem(ytMapKey(), JSON.stringify(m)); } catch (e) {} }
  function apiKey() { try { return (localStorage.getItem('yt_api_key') || '').trim(); } catch (e) { return ''; } }
  function itemKey(it) { if (it.manual) return it.id; return it.postUri ? ('u:' + it.postUri) : ('s:' + (it.shortUrl || '')); }
  function num(n) { try { return Number(n).toLocaleString(); } catch (e) { return String(n); } }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  // 祝日セット（内閣府データ window.__HOLIDAYS__）。土=青/日祝=赤 の判定に使う。
  var _holSet = null;
  function holSet() {
    if (_holSet) return _holSet;
    _holSet = {};
    try { var h = (window.__HOLIDAYS__ && window.__HOLIDAYS__.holidays) || []; for (var i = 0; i < h.length; i++) if (h[i] && h[i].date) _holSet[h[i].date] = 1; } catch (e) {}
    return _holSet;
  }
  var DOW = ['日', '月', '火', '水', '木', '金', '土'];
  // 「6/18 (土) 20:00」形式。曜日だけ色付け（土=青/日祝=赤）。戻り値はHTML（自前データのみ・エスケープ不要）。
  function fmtPostDate(ms) {
    try {
      var d = new Date(ms), p = function (n) { return (n < 10 ? '0' : '') + n; };
      var ymd = d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
      var dw = d.getDay(), hol = !!holSet()[ymd];
      var cls = (dw === 6) ? 'dow-sat' : ((dw === 0 || hol) ? 'dow-sun' : '');
      var dowHtml = cls ? '<span class="' + cls + '">(' + DOW[dw] + ')</span>' : '(' + DOW[dw] + ')';
      return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + dowHtml + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    } catch (e) { return ''; }
  }
  function setStatus(m, html) { var e = $('ytClickStatus'); if (!e) return; if (html) e.innerHTML = m || ''; else e.textContent = m || ''; }
  function ytIdOf(url) { return (url && window.IdGen && window.IdGen.youtubeId) ? (window.IdGen.youtubeId(url) || '') : ''; }

  // 表示する全アイテム（履歴＋手動追加）を結合。manualOnly=true の手動短縮URL履歴は除外。
  function allItems() { return loadHist().filter(function (it) { return !it.manualOnly; }).concat(loadManual()); }

  // 投稿時刻(ts)等から背骨ID(videoId)を生成。idgen があれば流用、無ければ同形式で自前生成。
  function genVideoId(ts) {
    var d = (ts && ts > 0) ? new Date(ts) : new Date();
    if (window.IdGen && window.IdGen.makeVideoId) { try { return window.IdGen.makeVideoId(acct(), d); } catch (e) {} }
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    var stamp = '' + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '-' + p(d.getHours()) + p(d.getMinutes());
    var r = ''; for (var i = 0; i < 4; i++) r += Math.floor(Math.random() * 36).toString(36);
    return acct() + '-' + stamp + '-' + r;
  }
  // この履歴を正とし、IDが未付与のアイテムへ背骨IDを付与・永続化（投稿履歴=スプレッドシートの行キー）。
  function ensureIds() {
    var hist = loadHist(), c1 = false;
    hist.forEach(function (it) { if (!it.videoId) { it.videoId = genVideoId(it.ts); c1 = true; } });
    if (c1) saveArr(histKey(), hist);
    var man = loadManual(), c2 = false;
    man.forEach(function (it) { if (!it.videoId) { it.videoId = genVideoId(it.ts); c2 = true; } });
    if (c2) saveArr(manualKey(), man);
  }

  // 短縮URLから go5-short のコードを抽出（自前ワーカーの払い出しURLのみ対象）。
  function codeOf(shortUrl) {
    var w = (window.Go5Short && window.Go5Short.WORKER_URL) || '';
    if (!w || !shortUrl) return '';
    var base = w.replace(/\/+$/, '');
    if (shortUrl.indexOf(base + '/') !== 0) return '';
    var rest = shortUrl.slice(base.length + 1).split(/[/?#]/)[0];
    return /^[0-9A-Za-z]+$/.test(rest) ? rest : '';
  }
  function fetchClicks(code) {
    var w = window.Go5Short; if (!w || !code) return Promise.resolve(null);
    var u = w.WORKER_URL.replace(/\/+$/, '') + '/api/stats?code=' + encodeURIComponent(code) + '&secret=' + encodeURIComponent(w.SHARED_SECRET);
    return fetch(u).then(function (r) { return r.json(); }).then(function (j) { return (j && j.ok && typeof j.clicks === 'number') ? j.clicks : null; }).catch(function () { return null; });
  }
  // 複数の動画ID → {views, publishedAt(ms), title}（videos.list は parts に関わらず1回1ユニット・最大50件）。
  function fetchVideos(ids) {
    var key = apiKey();
    var uniq = ids.filter(function (v, i, a) { return v && a.indexOf(v) === i; });
    if (!key || !uniq.length) return Promise.resolve({});
    var url = 'https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics&id=' + uniq.slice(0, 50).join(',') + '&key=' + encodeURIComponent(key);
    return fetch(url).then(function (r) { return r.json(); }).then(function (j) {
      var out = {};
      ((j && j.items) || []).forEach(function (it) {
        if (!it || !it.id) return;
        var rec = {};
        if (it.statistics) rec.views = parseInt(it.statistics.viewCount || '0', 10);
        if (it.snippet) { rec.title = it.snippet.title || ''; var t = Date.parse(it.snippet.publishedAt || ''); if (!isNaN(t)) rec.published = t; }
        out[it.id] = rec;
      });
      if (j && j.error) out.__error = (j.error.message || 'YouTube APIエラー');
      return out;
    }).catch(function () { return {}; });
  }

  var clicksCache = {};    // code -> clicks
  var viewsCache = {};     // videoId -> views
  var publishedCache = {}; // videoId -> publishedAt(ms)
  var titleCache = {};     // videoId -> YouTubeタイトル
  var lastErr = '';

  // ── YouTubeメタ（題名/投稿日時/視聴回数）を localStorage に永続化 ──────────────
  //   在メモリだけだとリロードのたびに再取得＝取得失敗時に題名が消えて不安定。
  //   永続化して起動時に即表示し、refresh で上書き更新する（題名/投稿日時は不変・視聴回数は最新化）。
  function ytMetaLoad() { try { return JSON.parse(localStorage.getItem('yt_meta_cache') || '{}') || {}; } catch (e) { return {}; } }
  function ytMetaSave(m) { try { localStorage.setItem('yt_meta_cache', JSON.stringify(m)); } catch (e) {} }
  (function () { // 起動時：永続キャッシュ→在メモリへ
    var m = ytMetaLoad();
    Object.keys(m).forEach(function (id) { var r = m[id] || {}; if (r.title) titleCache[id] = r.title; if (r.published != null) publishedCache[id] = r.published; if (r.views != null) viewsCache[id] = r.views; });
  })();
  function ytMetaPersist(fetched) { // fetched: id -> {views,published,title}
    var m = ytMetaLoad(), now = new Date().getTime();
    Object.keys(fetched).forEach(function (id) {
      var rec = fetched[id] || {}; if (id === '__error') return;
      m[id] = m[id] || {};
      if (rec.title) m[id].title = rec.title;
      if (rec.published != null) m[id].published = rec.published;
      if (rec.views != null) m[id].views = rec.views;
      m[id].fetchedAt = now;
    });
    ytMetaSave(m);
  }

  // 並び替え用：YouTube投稿日時(known)があればそれ、無ければ末尾グループへ。
  function sortItems(items, ymap) {
    var arr = items.map(function (it, i) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var hasUrl = !!vid;
      var pub = (vid && (vid in publishedCache)) ? publishedCache[vid] : null;
      var group = hasUrl ? 1 : 0;
      var t = (pub != null) ? pub : (it.ts || 0);
      return { it: it, i: i, group: group, t: t };
    });
    arr.sort(function (a, b) {
      if (a.group !== b.group) return a.group - b.group;
      if (b.t !== a.t) return b.t - a.t;
      return a.i - b.i;
    });
    return arr.map(function (x) { return x.it; });
  }

  // ── モーダル ──────────────────────────────────────────────────────────────
  var _saveCb = null;
  var _pendingShare = ''; // 生成した計測用リンクの共有URL(da.gd)。保存時に item.shareUrl へ付与
  var _pendingShort = ''; // 生成した計測用リンクのr2 URL。保存時に item.shortUrl へ付与（計測キー）
  var _curSrcUrl = '';    // 生成の元にする投稿URL（編集中アイテムのpostUrl等）

  function injectModal_() {
    if ($('veditOverlay')) return;
    var d = document.createElement('div');
    d.id = 'veditOverlay';
    d.className = 'vedit-overlay';
    d.hidden = true;
    d.innerHTML =
      '<div class="vedit-modal">' +
        '<p class="vedit-title" id="veditTitle">URL を編集</p>' +
        '<p class="vedit-error" id="veditError" hidden></p>' +
        '<label class="vedit-field">YouTube URL' +
          '<input id="veditYt" type="url" inputmode="url" autocomplete="off" placeholder="https://youtu.be/…（省略可）">' +
        '</label>' +
        '<label class="vedit-field">Bluesky 投稿URL（計測用の短縮URL）' +
          '<div class="vedit-bsky-row">' +
            '<input id="veditBsky" type="url" inputmode="url" autocomplete="off" placeholder="https://bsky.app/… または短縮URL（省略可）">' +
            '<button id="veditBskyCopy" type="button" class="vedit-copy">Copy</button>' +
          '</div>' +
        '</label>' +
        '<div id="veditGenResult" class="vedit-gen-result" hidden></div>' +
        '<label class="vedit-field">作品URL（DMM/FANZAの商品ページURL）' +
          '<input id="veditWork" type="url" inputmode="url" autocomplete="off" placeholder="https://www.dmm.co.jp/…（省略可）">' +
        '</label>' +
        '<div class="vedit-attrs">' +
          '<div class="vedit-attrs-title">カテゴリ（複数選択可・キャラ無し＝オリジナル）</div>' +
          ATTR_DEFS.map(function (a) {
            return '<label class="vedit-attr"><input id="veditAttr_' + a.key + '" type="checkbox"><span class="vatt vatt-' + a.key + '">' + a.label + '</span></label>';
          }).join('') +
        '</div>' +
        '<label class="vedit-field">作品状態（投稿当時の状態・後から変更可）' +
          '<select id="veditWorkState">' +
            '<option value="新作">新作</option>' +
            '<option value="準新作">準新作</option>' +
            '<option value="旧作">旧作</option>' +
          '</select>' +
        '</label>' +
        '<div class="vedit-actions">' +
          '<button id="veditGenShort" type="button" class="vedit-gen">短縮リンク<br>再生成</button>' +
          '<div class="vedit-actions-main">' +
            '<button id="veditCancel" type="button">キャンセル</button>' +
            '<button id="veditSave" type="button">保存</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(d);
    $('veditCancel').addEventListener('click', closeModal_);
    d.addEventListener('click', function (e) { if (e.target === d) closeModal_(); });
    // Bluesky投稿URLのコピー（clipboard API＋execCommandフォールバック）。
    $('veditBskyCopy').addEventListener('click', function () {
      var inp = $('veditBsky'); if (!inp) return;
      var v = (inp.value || '').trim();
      if (!v) { return; }
      var btn = this, orig = btn.textContent;
      function ok() { btn.textContent = '✓'; setTimeout(function () { btn.textContent = orig; }, 1200); }
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(v).then(ok, function () { copyFallback_(inp, ok); });
        } else { copyFallback_(inp, ok); }
      } catch (e) { copyFallback_(inp, ok); }
    });
    $('veditSave').addEventListener('click', function () {
      if (typeof _saveCb !== 'function') return;
      var cb = _saveCb;
      _saveCb = null;
      var attrs = {};
      ATTR_DEFS.forEach(function (a) { var el = $('veditAttr_' + a.key); attrs[a.key] = !!(el && el.checked); });
      var wsEl = $('veditWorkState');
      cb(
        ($('veditYt').value || '').trim(),
        ($('veditBsky').value || '').trim(),
        ($('veditWork').value || '').trim(),
        attrs,
        (wsEl && wsEl.value) || '旧作'
      );
      var o = $('veditOverlay');
      if (o && !o.hidden) _saveCb = cb;
    });
    // 計測用の短縮リンクを生成（過去のBluesky投稿URL→r2短縮(計測)＋da.gd短縮(表示)）
    $('veditGenShort').addEventListener('click', function () {
      var btn = this;
      var src = _curSrcUrl || ($('veditBsky').value || '').trim();
      if (!/^https?:\/\//.test(src)) { showModalErr_('先に「Bluesky投稿URL」を入れてください（https://bsky.app/… ）'); return; }
      if (typeof window.Go5MakeShort !== 'function') { showModalErr_('短縮機能が未読み込みです。🦋投稿タブを一度開いてから再度お試しください。'); return; }
      var errEl = $('veditError'); if (errEl) errEl.hidden = true;
      var orig = btn.textContent; btn.disabled = true; btn.textContent = '生成中…';
      window.Go5MakeShort(src).then(function (res) {
        var r2 = (res && res.shortUrl) || '', share = (res && res.shareUrl) || r2;
        if (!r2) { showModalErr_('短縮に失敗しました（r2ワーカーに接続できませんでした）。'); return; }
        $('veditBsky').value = share; // 欄には短い計測URL(da.gd)を表示
        _pendingShort = r2;          // 保存時に shortUrl=r2（クリック計測のキー）
        _pendingShare = share;       // 保存時に shareUrl=da.gd（表示・概要欄用）
        var gr = $('veditGenResult');
        if (gr) {
          gr.hidden = false;
          gr.innerHTML = '✅ 計測用リンクを生成しました。<b>この短縮URLをYouTube概要欄に貼り替えてください</b>：<br>' +
            '<code class="vgen-url">' + esc(share) + '</code> ' +
            '<button type="button" class="vgen-copy">コピー</button>' +
            '<div class="vgen-note">「保存」を押すと確定。以後このリンクのクリックが計測されます。</div>';
          var cp = gr.querySelector('.vgen-copy');
          if (cp) cp.addEventListener('click', function () {
            try { navigator.clipboard.writeText(share); cp.textContent = '✓ コピー'; } catch (e) {}
          });
        }
      }).catch(function () { showModalErr_('短縮に失敗しました。'); })
        .then(function () { btn.disabled = false; btn.textContent = orig; });
    });
  }

  function closeModal_() {
    var o = $('veditOverlay'); if (o) o.hidden = true;
    _saveCb = null;
  }

  function openModal_(title, ytVal, bskyVal, workVal, attrs, workState, onSave) {
    injectModal_();
    $('veditTitle').textContent = title;
    $('veditYt').value = ytVal || '';
    $('veditBsky').value = bskyVal || '';
    $('veditWork').value = workVal || '';
    attrs = attrs || {};
    ATTR_DEFS.forEach(function (a) { var el = $('veditAttr_' + a.key); if (el) el.checked = !!attrs[a.key]; });
    if ($('veditWorkState')) $('veditWorkState').value = workState || '旧作';
    _pendingShare = ''; _pendingShort = ''; // 生成状態をリセット
    var gr = $('veditGenResult'); if (gr) { gr.hidden = true; gr.innerHTML = ''; }
    var errEl = $('veditError'); if (errEl) { errEl.textContent = ''; errEl.hidden = true; }
    $('veditOverlay').hidden = false;
    setTimeout(function () { var el = $('veditYt'); if (el) el.focus(); }, 50);
    _saveCb = onSave;
  }

  function showModalErr_(msg) {
    var el = $('veditError'); if (!el) return;
    el.textContent = msg; el.hidden = false;
  }

  // clipboard API 不可の環境向けフォールバック（テキスト選択→execCommand('copy')）。
  function copyFallback_(inp, ok) {
    try {
      inp.focus(); inp.select();
      if (inp.setSelectionRange) inp.setSelectionRange(0, 99999);
      if (document.execCommand('copy') && ok) ok();
    } catch (e) {}
  }

  // Bluesky URLをアイテムに保存（go5-short → shortUrl、その他 → postUrl）。
  function saveBskyToItem_(item, bskyUrl) {
    var w = (window.Go5Short && window.Go5Short.WORKER_URL) ? window.Go5Short.WORKER_URL.replace(/\/+$/, '') : '';
    var isGo5 = w && bskyUrl && bskyUrl.indexOf(w) === 0;
    if (bskyUrl) {
      if (isGo5) { item.shortUrl = bskyUrl; delete item.postUrl; }
      else { item.postUrl = bskyUrl; }
    } else {
      // 空白のとき：手動アイテムは両方消す、履歴アイテムは postUrl だけ消す（shortUrl はクリック計測に必要）
      if (item.manual) delete item.shortUrl;
      delete item.postUrl;
    }
  }

  // アイテムへ属性フラグを反映（true は立て、false は削除）。
  function applyAttrs_(item, attrs) {
    ATTR_DEFS.forEach(function (a) { if (attrs && attrs[a.key]) item[a.key] = true; else delete item[a.key]; });
  }
  // 編集保存：YouTube URL（ytMap）と Bluesky URL・作品URL・カテゴリ属性・作品状態（アイテム）を一括更新。
  function saveEdit_(k, it, ytUrl, bskyUrl, workUrl, attrs, workState) {
    // YouTube URL
    var ymap = loadYtMap();
    if (ytUrl) ymap[k] = ytUrl; else delete ymap[k];
    saveYtMap(ymap);
    var saved = null;
    // Bluesky URL と 作品URL・カテゴリ・作品状態（アイテムを直接書き換え）
    if (it.manual) {
      var manual = loadManual();
      for (var i = 0; i < manual.length; i++) {
        if (itemKey(manual[i]) !== k) continue;
        saveBskyToItem_(manual[i], bskyUrl);
        if (workUrl) manual[i].workUrl = workUrl; else delete manual[i].workUrl;
        applyAttrs_(manual[i], attrs);
        manual[i].workState = workState || '旧作';
        if (_pendingShort) { manual[i].shortUrl = _pendingShort; delete manual[i].postUrl; } // 計測キー(r2)
        if (_pendingShare) manual[i].shareUrl = _pendingShare; // 表示用(da.gd)
        saved = manual[i];
        break;
      }
      saveArr(manualKey(), manual);
    } else {
      var hist = loadHist();
      for (var j = 0; j < hist.length; j++) {
        if (itemKey(hist[j]) !== k) continue;
        saveBskyToItem_(hist[j], bskyUrl);
        if (workUrl) hist[j].workUrl = workUrl; else delete hist[j].workUrl;
        applyAttrs_(hist[j], attrs);
        hist[j].workState = workState || '旧作';
        if (_pendingShort) { hist[j].shortUrl = _pendingShort; delete hist[j].postUrl; } // 計測キー(r2)
        if (_pendingShare) hist[j].shareUrl = _pendingShare; // 表示用(da.gd)
        saved = hist[j];
        break;
      }
      saveArr(histKey(), hist);
    }
    if (saved) pushItemToGas_(saved); // スプレッドシートのカテゴリ列等へ反映（GAS設定時のみ）
    refresh();
  }

  // 履歴アイテム1件をスプレッドシート（GAS）へ upsert 送信。post_id=背骨ID(videoId)で同一行を更新。
  // 投稿日時を上書きしないよう postUrl は送らない（既存行のカテゴリ列だけ更新する用途）。
  function pushItemToGas_(it) {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl || !it || !it.videoId) return;
    var payload = {
      op: 'upsert',
      channel: acct(),
      videoId: it.videoId,           // post_id（upsertキー）
      title: it.title || '',
      postUri: it.postUri || '',
      workUrl: it.workUrl || '',
      shortUrl: it.shortUrl || '',
      shareUrl: it.shareUrl || ''
    };
    ATTR_DEFS.forEach(function (a) { payload[a.key] = !!it[a.key]; }); // カテゴリ列：属性名を明記
    payload.workState = it.workState || '旧作'; // 作品状態列
    try { fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) }).catch(function () {}); } catch (e) {}
  }

  // ── render ──────────────────────────────────────────────────────────────
  function render() {
    var list = $('ytClickList');
    var rawItems = allItems();
    var ymap = loadYtMap();
    if (!rawItems.length) {
      list.innerHTML = '<p class="hint">まだ投稿の記録がありません（投稿して短縮URLが出ると、ここに集まります）。「➕ 手動で追加」からYouTube動画を直接登録もできます。表示中アカウント：' + esc(acct()) + '</p>';
      return;
    }
    var items = sortItems(rawItems, ymap);
    list.innerHTML = items.map(function (it) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var code = codeOf(it.shortUrl || '');
      var clicks = code && (code in clicksCache) ? clicksCache[code] : null;
      var views = vid && (vid in viewsCache) ? viewsCache[vid] : null;
      var pub = vid && (vid in publishedCache) ? publishedCache[vid] : null;
      var dateHtml = pub != null
        ? '<b>' + fmtPostDate(pub) + '</b>'
        : (vid ? '<b class="vdate-pending">…</b>' : '<b class="vdate-unknown">投稿日時不明</b>');
      var rawTitle = (vid && titleCache[vid]) || it.title || (it.manual ? '(手動追加)' : '(無題)');
      var dispTitle = esc(stripCommonTags(rawTitle));
      var tagWarn = !it.manual && vid && (vid in titleCache) && missingCommonTags(rawTitle);
      var titleHtml = tagWarn
        ? '<span style="color:#dc465a;font-weight:700;">' + dispTitle + ' #タグ忘れ</span>'
        : dispTitle;
      var bskyHref = it.shareUrl || it.shortUrl || it.postUrl || ''; // 表示リンクは共有(da.gd)優先。計測は下のcode(=r2)で行う
      // 属性バッジ（作品名の下に改行して表示。作品状態は価格行の左に別途表示）
      var tagsHtml = ATTR_DEFS.map(function (a) { return it[a.key] ? '<span class="vtag vtag-' + a.key + '">' + a.label + '</span>' : ''; }).join('');
      return '<div class="vrow">' +
        (it.workUrl ? '<img class="vrow-thumb" data-fanza-thumb-url="' + esc(it.workUrl) + '" alt="作品サムネ（タップで詳細）" title="タップで作品詳細" style="display:none;">' : '') +
        '<div class="vrow-h">' + dateHtml + ' ' + titleHtml + '</div>' +
        (it.workUrl ? '<div class="fanza-name-row" data-fanza-url="' + esc(it.workUrl) + '" style="display:none;"></div>' : '') +
        (it.workUrl ?
          '<div class="fanza-snap-row"><span class="fp-state fp-state-snap">' + esc(it.workState || '旧作') + '</span> ' +
            '<span class="fanza-snap-price" data-fanza-snap-url="' + esc(it.workUrl) + '">' + (it.fanzaSnap ? fmtSnapPriceHtml(it.fanzaSnap) : '') + '</span>' +
          '</div>'
        : '') +
        '<div class="fanza-price-row">' +
          '<span class="fp-state-slot"' + (it.workUrl ? ' data-fanza-state-url="' + esc(it.workUrl) + '"' : '') + '>' + stateBadgeHtml_(it.workState) + '</span>' +
          (it.workUrl ? '<span class="fanza-price" data-fanza-price-url="' + esc(it.workUrl) + '" style="display:none;"></span>' : '') +
        '</div>' +
        (tagsHtml ? '<div class="vrow-tags">' + tagsHtml + '</div>' : '') +
        '<div class="vmetrics">' +
          '<span title="YouTube再生数">▶ ' + (views != null ? num(views) : (vid ? '…' : '–')) + '</span>' +
          '<span title="Bsky投稿クリック数">🔗 ' + (clicks != null ? num(clicks) : (code ? '…' : '–')) + '</span>' +
          '<button class="vedit-btn" type="button" data-k="' + esc(k) + '">🛠️編集</button>' +
          (bskyHref ? '<a class="vlink vlink-bsky" href="' + esc(bskyHref) + '" target="_blank" rel="noopener">Bsky投稿↗</a>' : '') +
          (yt ? '<a class="vlink vlink-yt" href="' + esc(yt) + '" target="_blank" rel="noopener">YouTube↗</a>' : '') +
          (it.workUrl ? '<a class="vlink vlink-work" href="' + esc(it.workUrl) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
        '</div>' +
        '<div class="vrow-foot">' +
          '<span class="vrow-foot-gap"></span>' +
          '<button class="vdel" type="button" data-k="' + esc(k) + '" title="この記録を消去">🗑</button>' +
        '</div>' +
        '</div>';
    }).join('');
    fillFanzaNames();

    // YouTube URL 直接入力
    list.querySelectorAll('input[data-k]').forEach(function (inp) {
      inp.addEventListener('change', function () {
        var m = loadYtMap(); var v = inp.value.trim();
        if (v) m[inp.getAttribute('data-k')] = v; else delete m[inp.getAttribute('data-k')];
        saveYtMap(m); refresh();
      });
    });

    // 削除
    list.querySelectorAll('.vdel').forEach(function (b) {
      b.addEventListener('click', function () { deleteItem(b.getAttribute('data-k')); });
    });

    // サムネ → 作品詳細モーダル
    list.querySelectorAll('.vrow-thumb').forEach(function (im) {
      im.addEventListener('click', function () { openFanzaModal_(im.getAttribute('data-fanza-thumb-url')); });
    });

    // 編集モーダル
    list.querySelectorAll('.vedit-btn').forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.getAttribute('data-k');
        var rawItems = allItems(), ymap = loadYtMap();
        var it = null;
        for (var i = 0; i < rawItems.length; i++) { if (itemKey(rawItems[i]) === k) { it = rawItems[i]; break; } }
        if (!it) return;
        var ytCur = ymap[k] || it.ytUrl || '';
        var bskyCur = it.shareUrl || it.shortUrl || it.postUrl || ''; // 短い計測URL(da.gd)を優先表示
        var workCur = it.workUrl || '';
        var attrCur = {}; ATTR_DEFS.forEach(function (a) { attrCur[a.key] = !!it[a.key]; });
        _curSrcUrl = it.postUrl || it.shortUrl || bskyCur || ''; // 生成の元＝この投稿の元URL
        openModal_('URL を編集', ytCur, bskyCur, workCur, attrCur, it.workState || '旧作', function (ytUrl, bskyUrl, workUrl, attrs, workState) {
          closeModal_();
          saveEdit_(k, it, ytUrl, bskyUrl, workUrl, attrs, workState);
        });
      });
    });
  }

  // 1件削除（確認ダイアログ）。手動追加分は verify_manual から、投稿履歴は short_hist から除去。
  function deleteItem(k) {
    var rawItems = allItems(), ymap = loadYtMap();
    var target = null;
    for (var i = 0; i < rawItems.length; i++) { if (itemKey(rawItems[i]) === k) { target = rawItems[i]; break; } }
    if (!target) return;
    var vid = ytIdOf(ymap[k] || target.ytUrl || '');
    var title = (vid && titleCache[vid]) || target.title || (target.manual ? '(手動追加)' : '(無題)');
    if (!window.confirm('「' + title + '」を本当に消去しますか？\n（この記録を一覧から削除します。取り消せません）')) return;
    if (target.manual) {
      saveArr(manualKey(), loadManual().filter(function (x) { return itemKey(x) !== k; }));
    } else {
      saveArr(histKey(), loadHist().filter(function (x) { return itemKey(x) !== k; }));
    }
    if (ymap[k] != null) { delete ymap[k]; saveYtMap(ymap); }
    refresh();
  }

  // YouTube動画を手動で追加（モーダルで YouTube URL + Bluesky URL + 作品URL を一括入力）。
  function addManual() {
    // 作品URLをアフィリンクタブの②から自動取得（なければ bsky_work_url を使用）
    var autoWorkUrl = '';
    try {
      var afEl = document.getElementById('affiUrls');
      var afRaw = afEl ? afEl.value : (localStorage.getItem('field_affiUrls') || '');
      autoWorkUrl = afRaw.trim().split('\n').map(function (l) { return l.trim(); }).filter(Boolean)[0] || '';
      if (!autoWorkUrl) {
        var acctId = (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1');
        autoWorkUrl = localStorage.getItem('bsky_work_url__' + acctId) || '';
      }
    } catch (e) {}
    _curSrcUrl = ''; // 新規追加：生成元はveditBskyの入力値を使う
    openModal_('YouTube動画を追加', '', '', autoWorkUrl, {}, '旧作', function (ytUrl, bskyUrl, workUrl, attrs, workState) {
      if (!ytUrl) { showModalErr_('YouTube URLを入力してください。'); return; }
      var vid = ytIdOf(ytUrl);
      if (!vid) {
        showModalErr_('YouTubeのURLを認識できませんでした。\nhttps://youtu.be/… か https://www.youtube.com/watch?v=… 形式を貼ってください。');
        return;
      }
      closeModal_();
      var id = 'm:' + new Date().getTime();
      var entry = { manual: true, id: id, ts: 0 };
      saveBskyToItem_(entry, bskyUrl);
      if (workUrl) entry.workUrl = workUrl;
      applyAttrs_(entry, attrs);
      if (workState && workState !== '旧作') entry.workState = workState; else entry.workState = '旧作';
      if (_pendingShort) { entry.shortUrl = _pendingShort; delete entry.postUrl; } // 計測キー(r2)
      if (_pendingShare) entry.shareUrl = _pendingShare; // 表示用(da.gd)
      saveArr(manualKey(), loadManual().concat([entry]));
      var m = loadYtMap(); m[id] = ytUrl; saveYtMap(m);
      refresh();
    });
  }

  // クリック数(開封数)・YouTube視聴回数/投稿日時/題名をAPIから取得しキャッシュへ。Promiseを返す。
  function fetchData_(items, ymap) {
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); }).filter(Boolean);
    var vids = items.map(function (it) { var k = itemKey(it); return ytIdOf(ymap[k] || it.ytUrl || ''); }).filter(Boolean);
    if (!codes.length && !vids.length) return Promise.resolve(false);
    var jobs = [];
    codes.forEach(function (code) { jobs.push(fetchClicks(code).then(function (c) { if (c != null) clicksCache[code] = c; })); });
    if (vids.length) jobs.push(fetchVideos(vids).then(function (m) {
      lastErr = m.__error || ''; delete m.__error;
      Object.keys(m).forEach(function (id) {
        var rec = m[id] || {};
        if (rec.views != null) viewsCache[id] = rec.views;
        if (rec.published != null) publishedCache[id] = rec.published;
        if (rec.title) titleCache[id] = rec.title;
      });
      ytMetaPersist(m); // 永続化（リロードで消えない）
    }));
    return Promise.all(jobs).then(function () { return true; });
  }

  // announce=true（手動更新ボタン）のときは、完了時に成功/失敗を明確に表示する。
  function refresh(announce) {
    ensureIds(); // IDが無いアイテムへ背骨IDを付与（履歴=スプレッドシートの正キー）
    render();
    var items = allItems(); var ymap = loadYtMap();
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); }).filter(Boolean);
    var vids = items.map(function (it) { var k = itemKey(it); return ytIdOf(ymap[k] || it.ytUrl || ''); }).filter(Boolean);
    if (!codes.length && !vids.length) {
      if (announce) setStatus('更新対象がありません（各行にYouTube URLを入れる／⚙️詳細設定でAPIキー設定が必要です）');
      else setStatus(apiKey() ? '' : '※YouTube再生数・投稿日時は⚙️詳細設定でAPIキーを設定し、各行にYouTube URLを入れると表示されます');
      return Promise.resolve(false);
    }
    setStatus('🔄 更新中…（再生数・クリック数）');
    return fetchData_(items, ymap).then(function () {
      if (lastErr) setStatus('⚠️ 更新に失敗しました：' + lastErr);
      else if (announce) setStatus('✅ 更新しました（再生数・クリック数' + (vids.length ? '・' + vids.length + '本' : '') + '）');
      else setStatus(!apiKey() && vids.length ? '※再生数・投稿日時の表示には⚙️詳細設定のAPIキーが必要です' : '');
      render();
      return true;
    }).catch(function () { setStatus('⚠️ 更新に失敗しました（通信エラー）'); return false; });
  }

  // この投稿履歴を正として、全アイテムを記録シート(GAS)へ一括 upsert 同期する。
  // ID・投稿日時(ts)・キャラ属性も送り、シート側で post_id 一致行を更新＋日付降順ソート。
  function syncSheet() {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl) { setStatus('⚠️ 記録用GASのURLが未設定です（⚙️詳細設定で設定してください）'); return; }
    ensureIds();
    var btn = $('ytSyncSheet'); if (btn) btn.disabled = true;
    setStatus('最新の再生数・クリック数を取得中…');
    // まずYouTube題名・視聴回数・開封数を最新取得してから送る（取れたぶんだけ反映）。
    fetchData_(allItems(), loadYtMap()).then(function () { sendSync_(gasUrl, btn); });
  }
  function sendSync_(gasUrl, btn) {
    var ymap = loadYtMap();
    var items = allItems().map(function (it) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var code = codeOf(it.shortUrl || '');
      // 投稿日時：実投稿時刻(ts)を最優先。無ければYouTube公開日時を使う（→朝ばかり/今日になる問題を解消）。
      var pubMs = (vid && publishedCache[vid] != null) ? publishedCache[vid] : null;
      var postedMs = (it.ts && it.ts > 0) ? it.ts : pubMs;
      var rec = {
        videoId: it.videoId || '',
        title: it.title || '',                                          // 題名(コメント)＝アプリの④コメント
        ytTitle: (vid && titleCache[vid]) || '',                        // YouTube動画の実題名（取得済みのみ）
        views: (vid && viewsCache[vid] != null) ? viewsCache[vid] : '', // YouTube視聴回数（取得済みのみ）
        clicks: (code && clicksCache[code] != null) ? clicksCache[code] : '', // 短縮URLクリック数（取得済みのみ）
        postUri: it.postUri || '',
        postUrl: it.postUrl || '',
        shortUrl: it.shortUrl || '',
        shareUrl: it.shareUrl || '',
        workUrl: it.workUrl || '',
        youtubeUrl: yt,
        postedAt: postedMs ? new Date(postedMs).toISOString() : ''
      };
      ATTR_DEFS.forEach(function (a) { rec[a.key] = !!it[a.key]; }); // カテゴリ属性
      rec.workState = it.workState || '旧作'; // 作品状態
      return rec;
    }).filter(function (r) { return r.videoId; });
    if (!items.length) { setStatus('同期する履歴がありません'); if (btn) btn.disabled = false; return; }
    setStatus('スプレッドシートへ同期中… (' + items.length + '件)');
    fetch(gasUrl, { method: 'POST', body: JSON.stringify({ op: 'sync_history', channel: acct(), items: items }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.ok) setStatus('✅ スプレッドシートへ同期しました（' + (j.synced != null ? j.synced : items.length) + '件）');
        else setStatus('⚠️ 同期に失敗しました' + (j && j.error ? '：' + j.error : ''));
      })
      .catch(function () {
        // GASのCORS応答は読めないことがあるが、送信自体は届いている（記録は実行される）。
        setStatus('📤 同期リクエストを送信しました（' + items.length + '件）。数秒後にスプレッドシートをご確認ください。');
      })
      .then(function () { if (btn) btn.disabled = false; });
  }

  // この投稿履歴に無い post_id の行を、記録シート(GAS)から消去する（このアカウントのタブのみ）。
  function pruneSheet() {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl) { setStatus('⚠️ 記録用GASのURLが未設定です（⚙️詳細設定で設定してください）'); return; }
    ensureIds();
    var keepIds = allItems().map(function (it) { return it.videoId; }).filter(Boolean);
    if (!keepIds.length) { setStatus('掃除の基準になる履歴がありません（先に同期してください）'); return; }
    if (!window.confirm('この投稿履歴に無い行を、スプレッドシートの「' + acct() + '」タブから消去します。\n（記録シートをこの履歴に合わせます。よろしいですか？）')) return;
    var btn = $('ytPruneSheet'); if (btn) btn.disabled = true;
    setStatus('履歴に無い行を掃除中…');
    fetch(gasUrl, { method: 'POST', body: JSON.stringify({ op: 'prune_history', channel: acct(), keepIds: keepIds }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.ok) setStatus('🧹 掃除しました（' + (j.cleared != null ? j.cleared : '?') + '行を消去）');
        else setStatus('⚠️ 掃除に失敗しました' + (j && j.error ? '：' + j.error : ''));
      })
      .catch(function () { setStatus('🧹 掃除リクエストを送信しました。数秒後にスプレッドシートをご確認ください。'); })
      .then(function () { if (btn) btn.disabled = false; });
  }

  // 過去投稿に計測用の短縮リンク(r2+da.gd)を生成する。silent=true で自動実行（確認・完了ダイアログ無し）。
  //   対象＝shortUrlがr2でない or shareUrl無しの履歴。各投稿URL→(必要ならworkerで解決)→r2短縮→da.gd短縮。
  //   1件ごとに保存＝途中で閉じても進んだぶんは残る（冪等：既にr2済みは対象外）。
  var _bulkBusy = false;
  function runBulkGen(silent) {
    if (_bulkBusy) return;
    var go5 = window.Go5Short || {};
    var workerUrl = (go5.WORKER_URL || '').replace(/\/+$/, '');
    var secret = go5.SHARED_SECRET || '';
    if (typeof window.Go5MakeShort !== 'function' || !workerUrl) { if (!silent) setStatus('⚠️ 短縮機能が未読み込みです。🦋投稿タブを一度開いてから再度お試しください。'); return; }
    var handle = ''; try { handle = localStorage.getItem('bsky_handle__' + acct()) || ''; } catch (e) {}
    ensureIds();
    function isR2(u) { return !!u && u.indexOf(workerUrl + '/') === 0; }
    var hist = loadHist(), manual = loadManual(), targets = [];
    hist.forEach(function (it) { if (!isR2(it.shortUrl) || !it.shareUrl) targets.push(it); });
    manual.forEach(function (it) { if (!isR2(it.shortUrl) || !it.shareUrl) targets.push(it); });
    if (!targets.length) { if (!silent) setStatus('未生成の項目はありません（すべて計測リンク済み）'); return; }
    _bulkBusy = true;
    var btn = $('ytBulkGen'); if (btn) btn.disabled = true;
    var i = 0, done = 0, fail = 0;
    function resolveTarget(it) {
      if (it.postUri && handle) { var rk = String(it.postUri).split('/').pop(); return Promise.resolve('https://bsky.app/profile/' + handle + '/post/' + rk); }
      var src = it.postUrl || '';
      if (/^https?:\/\/[^/]*bsky\.app\//.test(src)) return Promise.resolve(src);      // 既にbsky.app
      if (!/^https?:\/\//.test(src)) return Promise.resolve('');
      return fetch(workerUrl + '/api/resolve?url=' + encodeURIComponent(src) + '&secret=' + encodeURIComponent(secret))
        .then(function (r) { return r.json(); })
        .then(function (j) { return (j && j.ok && /bsky\.app/.test(j.final || '')) ? j.final : ''; })
        .catch(function () { return ''; });
    }
    function step() {
      if (i >= targets.length) {
        saveArr(histKey(), hist); saveArr(manualKey(), manual);
        _bulkBusy = false; if (btn) btn.disabled = false;
        setStatus('✅ 計測リンク生成 完了：成功 ' + done + ' / 失敗 ' + fail + '。各行の「Bsky投稿↗」が計測用の短縮URLです（長押しでコピー→YouTube概要欄に貼り替え）。');
        render();
        return;
      }
      var it = targets[i++];
      setStatus('計測リンクを生成中… (' + i + '/' + targets.length + ')');
      resolveTarget(it).then(function (target) {
        if (!target) { fail++; return null; }
        return window.Go5MakeShort(target).then(function (res) {
          if (res && res.shortUrl) {
            it.shortUrl = res.shortUrl; it.shareUrl = res.shareUrl || res.shortUrl; done++;
            saveArr(histKey(), hist); saveArr(manualKey(), manual); // 逐次保存（途中終了に強い）
          } else fail++;
        });
      }).catch(function () { fail++; }).then(function () { setTimeout(step, 800); });
    }
    step();
  }
  // 投稿履歴を開いたら、未生成の項目があれば自動で計測リンクを生成する（ボタン任せにしない）。
  function maybeAutoGen() { if (!_bulkBusy) runBulkGen(true); }

  // 投稿本文からの当時割引/新作の復元を「1回だけ」自動実行（フラグ管理・ボタン不要で確実に）。
  function maybeRestorePromo_() {
    var FLAG = 'bsky_promo_restored_v1';
    try { if (localStorage.getItem(FLAG)) return; } catch (e) {}
    // 価格(定価)キャッシュが載ってから走らせたいので少し待つ。完了時のみフラグを立てる（対象0件では立てない）。
    setTimeout(function () {
      restorePctFromBsky_(function () { try { localStorage.setItem(FLAG, '1'); } catch (e) {} });
    }, 3500);
  }

  // Bluesky本文から「新作」「◯%オフ」を検出（半角/全角%・オフ/OFF/割引・半額に対応）。
  function parseBskyPromo_(text) {
    var t = String(text || '').replace(/[０-９]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); });
    var isNew = /新作/.test(t);
    var pct = null;
    if (/半額/.test(t)) pct = 50;
    var m = t.match(/(\d{1,3})\s*[%％]\s*(?:オフ|off|OFF|割引)/i) || t.match(/(?:オフ|off|OFF)\s*(\d{1,3})\s*[%％]/i);
    if (m) { var n = parseInt(m[1], 10); if (n > 0 && n < 100) pct = n; }
    return { isNew: isNew, pct: pct };
  }
  // 【1回限り】両chの投稿本文をBluesky公開APIで取得し、明記された当時の割引率/新作を当時スナップへ反映。
  // onDone は実際に処理を走らせたときだけ完了後に呼ぶ（対象0件のときは呼ばない＝フラグを立てず後で再試行可能に）。
  var _restoreBusy = false;
  function restorePctFromBsky_(onDone) {
    if (_restoreBusy) return;
    var keys = ['short_hist__acc1', 'verify_manual__acc1', 'short_hist__acc2', 'verify_manual__acc2'];
    var store = {}, jobs = [];
    keys.forEach(function (k) {
      var arr; try { arr = JSON.parse(localStorage.getItem(k) || '[]') || []; } catch (e) { arr = []; }
      store[k] = arr;
      arr.forEach(function (it, idx) { if (it && it.postUri) jobs.push({ key: k, idx: idx, uri: String(it.postUri) }); });
    });
    if (!jobs.length) return;
    _restoreBusy = true;
    var fzCache = fanzaNameCacheLoad();
    var updated = 0, skipped = 0, i = 0, BATCH = 25;
    function listPriceOf(it) {
      if (it.fanzaSnap && it.fanzaSnap.listPrice != null) return it.fanzaSnap.listPrice;
      var c = it.workUrl ? fzCache[it.workUrl] : null;
      if (c && c.priceInfo && c.priceInfo.listPrice != null) return c.priceInfo.listPrice;
      return null;
    }
    function applyToItem(it, promo) {
      var did = false;
      if (promo.isNew && it.workState !== '新作') { it.workState = '新作'; did = true; }
      if (promo.pct != null) {
        var lp = listPriceOf(it), snap = it.fanzaSnap || {};
        snap.discountPct = promo.pct;
        if (lp != null) { snap.listPrice = lp; snap.price = Math.round(lp * (1 - promo.pct / 100)); }
        snap.fromBsky = true; snap.at = snap.at || new Date().toISOString();
        it.fanzaSnap = snap; did = true;
      }
      return did;
    }
    function step() {
      if (i >= jobs.length) {
        keys.forEach(function (k) { try { localStorage.setItem(k, JSON.stringify(store[k])); } catch (e) {} });
        _restoreBusy = false;
        if (updated) setStatus('✅ 投稿文から当時の割引/新作を反映：' + updated + '件（記載なし ' + skipped + '件・両ch）。');
        render();
        if (typeof onDone === 'function') onDone();
        return;
      }
      var slice = jobs.slice(i, i + BATCH);
      var q = slice.map(function (j) { return 'uris=' + encodeURIComponent(j.uri); }).join('&');
      setStatus('Blueskyの投稿本文を確認中…（' + Math.min(i, jobs.length) + '/' + jobs.length + '）');
      fetch('https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts?' + q)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var byUri = {};
          ((data && data.posts) || []).forEach(function (p) { byUri[p.uri] = (p.record && p.record.text) || ''; });
          slice.forEach(function (j) {
            var text = byUri[j.uri];
            if (text == null) { skipped++; return; }
            var promo = parseBskyPromo_(text);
            if (!promo.isNew && promo.pct == null) { skipped++; return; }
            if (applyToItem(store[j.key][j.idx], promo)) updated++; else skipped++;
          });
        })
        .catch(function () {})
        .then(function () { i += BATCH; setTimeout(step, 300); });
    }
    step();
  }

  var tab = $('tabVerify'); if (tab) tab.addEventListener('click', function () { refresh(); setTimeout(maybeAutoGen, 400); maybeRestorePromo_(); });
  var rb = $('ytClickRefresh'); if (rb) rb.addEventListener('click', function () { purgeNegativeFanzaCache(); refresh(true); });
  var fd = $('ytFetchDmm'); if (fd) fd.addEventListener('click', refetchFanza_);
  var ab = $('ytAddManual'); if (ab) ab.addEventListener('click', addManual);
  var bg = $('ytBulkGen'); if (bg) bg.addEventListener('click', function () { runBulkGen(false); });
  var sb = $('ytSyncSheet'); if (sb) sb.addEventListener('click', syncSheet);
  var pb = $('ytPruneSheet'); if (pb) pb.addEventListener('click', pruneSheet);
  document.addEventListener('account-changed', function () { render(); });
  // 読み込み時点で既に投稿履歴タブを開いている場合も自動生成＋当時割引の復元（各1回）。
  setTimeout(function () { var pv = $('pageVerify'); if (pv && !pv.hidden) { maybeAutoGen(); maybeRestorePromo_(); } }, 2500);

  // 詳細設定タブの YouTube APIキー入力：端末内に保存・復元（秘密扱い）。
  var keyEl = $('ytApiKey');
  if (keyEl) {
    try { keyEl.value = localStorage.getItem('yt_api_key') || ''; } catch (e) {}
    keyEl.addEventListener('input', function () { try { localStorage.setItem('yt_api_key', keyEl.value.trim()); } catch (e) {} });
  }

  // ── FANZA 商品名 キャッシュ＆DOM埋め込み ────────────────────────────────────
  // FANZA同人ページは未ログインだとログイン/年齢確認ページが返り、その og:title が
  // 「ログイン - FANZA」等になる。これを商品名として表示しないための判定。
  function isBadFanzaTitle(t) {
    var s = String(t || '').trim();
    if (!s) return true;
    if (s.indexOf('ログイン') >= 0) return true;
    if (s.toLowerCase().indexOf('login') >= 0) return true;
    if (s.indexOf('年齢確認') >= 0) return true;
    if (s.indexOf('エラー') >= 0) return true;
    if (s === 'FANZA' || s === 'DMM') return true;
    return false;
  }
  function fanzaNameCacheLoad() {
    try { return JSON.parse(localStorage.getItem('fanza_title_cache') || '{}'); } catch (e) { return {}; }
  }
  function fanzaNameCacheSave(c) {
    try { localStorage.setItem('fanza_title_cache', JSON.stringify(c)); } catch (e) {}
  }
  // 既存キャッシュから不正タイトル（ログイン/エラーページ等）を一掃する。変更があれば保存。
  function purgeBadFanzaCache() {
    var c = fanzaNameCacheLoad();
    var changed = false;
    Object.keys(c).forEach(function (url) {
      if (!c[url] || isBadFanzaTitle(c[url].title)) { delete c[url]; changed = true; }
    });
    if (changed) fanzaNameCacheSave(c);
  }
  // 「未取得(空)」のネガティブキャッシュを消す＝手動更新で失敗分を即・強制再取得できるようにする。
  function purgeNegativeFanzaCache() {
    var c = fanzaNameCacheLoad();
    var changed = false;
    Object.keys(c).forEach(function (url) {
      if (c[url] && !c[url].title) { delete c[url]; changed = true; }
    });
    if (changed) fanzaNameCacheSave(c);
  }
  // data-fanza-url が一致する現在の DOM 要素を全て更新（DOM 再描画後も正しく反映される）
  function setFanzaEls(fanzaUrl, title) {
    var ok = title && !isBadFanzaTitle(title);
    document.querySelectorAll('[data-fanza-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-url') !== fanzaUrl) return;
      if (ok) { el.textContent = title; el.style.display = ''; }
      else { el.textContent = ''; el.style.display = 'none'; }
    });
  }
  // 発売日(YYYY-MM-DD…)→現在の作品状態。新作=30日以内 / 準新作=90日以内 / それ以降=旧作。取得不可は''。
  function deriveWorkState_(dateStr) {
    if (!dateStr) return '';
    var t = Date.parse(String(dateStr).replace(' ', 'T'));
    if (isNaN(t)) return '';
    var days = (new Date().getTime() - t) / 86400000;
    if (days <= 30) return '新作';
    if (days <= 90) return '準新作';
    return '旧作';
  }
  // 作品状態バッジのHTML（新作=緑 / 準新作=青緑 / 旧作=セピア）。空/未指定は旧作扱い。
  function stateBadgeHtml_(ws) {
    var s = ws || '旧作';
    var cls = s === '新作' ? 'fp-state-new' : (s === '準新作' ? 'fp-state-semi' : 'fp-state-old');
    return '<span class="fp-state ' + cls + '">' + esc(s) + '</span>';
  }
  function yen_(n) { return '¥' + Number(n).toLocaleString('ja-JP'); }
  // 現在価格のHTML。セール時は「現在定価/セール価格/○%off」、セール無しは「現在定価」を通常色で。
  function fmtFanzaPriceHtml(p) {
    if (!p || p.price == null) return '';
    if (p.listPrice != null && p.discountPct > 0 && p.listPrice > p.price) {
      return '現在定価:<span class="fp-list">' + yen_(p.listPrice) + '</span>' +
             ' <span class="fp-sale-lbl">セール価格:</span><span class="fp-sale">' + yen_(p.price) + '</span>' +
             ' <span class="fp-off">' + p.discountPct + '%off</span>';
    }
    return '現在定価:<span class="fp-cur">' + yen_(p.price) + '</span>';
  }
  // 投稿時（当時）価格のHTML。全体を作品名と同じ淡色で表示。%offは現在と同様に枠で囲む。
  function fmtSnapPriceHtml(p) {
    if (!p || p.price == null) return '';
    if (p.listPrice != null && p.discountPct > 0 && p.listPrice > p.price) {
      return '定価:' + yen_(p.listPrice) + ' セール価格:' + yen_(p.price) + ' <span class="fp-snap-off">' + p.discountPct + '%off</span>';
    }
    return '定価:' + yen_(p.price);
  }
  // data-fanza-snap-url が一致する当時価格の要素へ反映。
  function setFanzaSnapEls(fanzaUrl, html) {
    document.querySelectorAll('[data-fanza-snap-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-snap-url') !== fanzaUrl) return;
      el.innerHTML = html || '';
    });
  }
  // 投稿履歴/手動アイテムのうち、この作品URLで当時スナップ未保存のものに現在価格を当時として固定保存。
  function backfillSnap_(workUrl, pinfo) {
    if (!workUrl || !pinfo || pinfo.price == null) return;
    var snap = { price: pinfo.price, listPrice: pinfo.listPrice, discountPct: pinfo.discountPct || 0, at: new Date().toISOString(), backfilled: true };
    function apply(arr, key) {
      var did = false;
      arr.forEach(function (it) { if (it.workUrl === workUrl && !it.fanzaSnap) { it.fanzaSnap = snap; did = true; } });
      if (did) saveArr(key, arr);
      return did;
    }
    var d1 = apply(loadHist(), histKey());
    var d2 = apply(loadManual(), manualKey());
    if (d1 || d2) setFanzaSnapEls(workUrl, fmtSnapPriceHtml(snap));
  }
  // data-fanza-thumb-url が一致するサムネ<img>へ画像を設定して表示。
  function setFanzaThumbEls(fanzaUrl, src) {
    if (!src) return;
    document.querySelectorAll('img[data-fanza-thumb-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-thumb-url') !== fanzaUrl) return;
      if (el.getAttribute('src') !== src) el.setAttribute('src', src);
      el.style.display = '';
    });
  }

  // 作品詳細モーダル（サムネクリックで開く）。キャッシュから作品名/画像/ジャンル/発売日/サービスを表示。
  function openFanzaModal_(fanzaUrl) {
    var cache = fanzaNameCacheLoad();
    var c = cache[fanzaUrl];
    if (!c) return;
    var media = c.media || {}, pinfo = c.priceInfo || {};
    var title = c.title || '(無題)';
    var big = media.thumb || media.thumbSmall || '';
    var samples = media.samples || [];
    var genres = media.genres || [];
    var date = pinfo.releaseDate || '';
    var svc = [media.service, media.floor].filter(Boolean).join(' / ');

    var ov = $('fzOverlay');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'fzOverlay';
      ov.className = 'fz-overlay';
      ov.hidden = true;
      ov.innerHTML = '<div class="fz-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) closeFanzaModal_(); });
      ov.querySelector('.fz-close').addEventListener('click', closeFanzaModal_);
    }
    // 画像ギャラリー：作品画像（先頭）＋サンプル画像。クリックでズームビューア（スワイプ切替）。
    _fzGallery = [];
    if (big) _fzGallery.push(big);
    samples.forEach(function (s) { _fzGallery.push(s); });
    var sBase = big ? 1 : 0;
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      '<div class="fz-title">' + esc(title) + '</div>' +
      (big ? '<div class="fz-hero"><img class="fz-zoomable" data-zoom="0" src="' + esc(big) + '" alt="タップで拡大"></div>' : '') +
      (samples.length ? '<div class="fz-samples">' + samples.map(function (s, si) { return '<img class="fz-zoomable" data-zoom="' + (sBase + si) + '" src="' + esc(s) + '" alt="" loading="lazy">'; }).join('') + '</div>' : '') +
      (genres.length ? '<div class="fz-sec"><span class="fz-lbl">ジャンル</span><div class="fz-genres">' + genres.map(function (g) { return '<span class="fz-genre">' + esc(g) + '</span>'; }).join('') + '</div></div>' : '') +
      '<div class="fz-sec fz-meta-row">' +
        '<div class="fz-meta"><span class="fz-lbl">発売日</span>' + esc(date ? String(date).slice(0, 10) : '—') + '</div>' +
        '<div class="fz-meta"><span class="fz-lbl">サービス/フロア</span>' + esc(svc || '—') + '</div>' +
      '</div>' +
      '<div class="fz-foot"><a class="fz-open" href="' + esc(fanzaUrl) + '" target="_blank" rel="noopener">作品ページを開く ↗</a></div>';
    body.querySelectorAll('.fz-zoomable').forEach(function (im) {
      im.addEventListener('click', function () { openZoom_(_fzGallery, parseInt(im.getAttribute('data-zoom'), 10) || 0); });
    });
    ov.hidden = false;
  }
  function closeFanzaModal_() { var ov = $('fzOverlay'); if (ov) ov.hidden = true; }

  // 画像ズームビューア（作品画像＋サンプルを1つのギャラリーとして、左右スワイプで切替。矢印ボタンなし）。
  var _fzGallery = [], _zoomImgs = [], _zoomIdx = 0;
  function openZoom_(images, idx) {
    if (!images || !images.length) return;
    var z = $('fzZoom');
    if (!z) {
      z = document.createElement('div');
      z.id = 'fzZoom'; z.className = 'fz-zoom'; z.hidden = true;
      z.innerHTML = '<button class="fz-zoom-close" type="button" aria-label="閉じる">✕</button><img class="fz-zoom-img" alt=""><div class="fz-zoom-count"></div>';
      document.body.appendChild(z);
      z.addEventListener('click', function (e) { if (e.target === z) closeZoom_(); });
      z.querySelector('.fz-zoom-close').addEventListener('click', closeZoom_);
      var sx = null, sy = null;
      z.addEventListener('touchstart', function (e) { var t = e.changedTouches[0]; sx = t.clientX; sy = t.clientY; }, { passive: true });
      z.addEventListener('touchend', function (e) {
        if (sx == null) return; var t = e.changedTouches[0], dx = t.clientX - sx, dy = t.clientY - sy;
        if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) zoomGo_(dx < 0 ? 1 : -1);
        sx = sy = null;
      }, { passive: true });
      var px = null;
      z.addEventListener('pointerdown', function (e) { if (e.pointerType === 'touch') return; px = e.clientX; });
      z.addEventListener('pointerup', function (e) { if (e.pointerType === 'touch' || px == null) return; var dx = e.clientX - px; if (Math.abs(dx) > 40) zoomGo_(dx < 0 ? 1 : -1); px = null; });
      document.addEventListener('keydown', function (e) {
        var zz = $('fzZoom'); if (!zz || zz.hidden) return;
        if (e.key === 'ArrowRight') zoomGo_(1); else if (e.key === 'ArrowLeft') zoomGo_(-1); else if (e.key === 'Escape') closeZoom_();
      });
    }
    _zoomImgs = images.slice(); _zoomIdx = idx || 0;
    renderZoom_();
    z.hidden = false;
  }
  function renderZoom_() {
    var z = $('fzZoom'); if (!z) return;
    var im = z.querySelector('.fz-zoom-img'), cnt = z.querySelector('.fz-zoom-count');
    if (im) im.src = _zoomImgs[_zoomIdx] || '';
    if (cnt) cnt.textContent = _zoomImgs.length > 1 ? (_zoomIdx + 1) + ' / ' + _zoomImgs.length + '（左右スワイプ）' : '';
  }
  function zoomGo_(dir) {
    if (_zoomImgs.length < 2) return;
    _zoomIdx = (_zoomIdx + dir + _zoomImgs.length) % _zoomImgs.length;
    renderZoom_();
  }
  function closeZoom_() { var z = $('fzZoom'); if (z) z.hidden = true; }

  // data-fanza-price-url が一致するDOM要素へ価格を反映＋発売日から現在の作品状態バッジを更新。
  function setFanzaPriceEls(fanzaUrl, priceInfo) {
    var html = fmtFanzaPriceHtml(priceInfo);
    document.querySelectorAll('[data-fanza-price-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-price-url') !== fanzaUrl) return;
      if (html) { el.innerHTML = html; el.style.display = ''; }
      else { el.innerHTML = ''; el.style.display = 'none'; }
    });
    // 発売日→現在の作品状態（APIで取得できたときだけ上書き。取れなければ手動値のまま）。
    var apiState = priceInfo && deriveWorkState_(priceInfo.releaseDate);
    if (apiState) {
      document.querySelectorAll('[data-fanza-state-url]').forEach(function (el) {
        if (el.getAttribute('data-fanza-state-url') !== fanzaUrl) return;
        el.innerHTML = stateBadgeHtml_(apiState);
      });
    }
  }

  var _fanzaBusy = false; // 二重起動防止（順次取得中の再入を防ぐ）
  // manual=true（DMM作品情報取得ボタン）のときは進捗と完了/失敗をステータスへ表示する。
  function fillFanzaNames(manual) {
    var targets = document.querySelectorAll('[data-fanza-url]');
    if (!targets.length) { if (manual) setStatus('作品URLのある投稿がありません。'); return; }
    if (typeof window.FanzaCore === 'undefined' || typeof window.buildAffiliateLink === 'undefined') { if (manual) setStatus('⚠️ FANZAモジュール未読込。少し待って再度お試しください。'); return; }
    var workerUrl = '';
    var sharedSecret = '';
    try { workerUrl = localStorage.getItem('fanza_worker_url') || ''; } catch (e) {}
    try { sharedSecret = localStorage.getItem('fanza_shared_secret') || ''; } catch (e) {}
    if (!workerUrl) { if (manual) setStatus('⚠️ FANZAワーカーURLが未設定です（⚙️詳細設定で設定してください）。'); return; }
    purgeBadFanzaCache(); // 旧版で混入したログイン/エラータイトルを先に掃除
    var cache = fanzaNameCacheLoad();
    var now = new Date().getTime();
    var DAY = 86400000, NEG = 30 * 60000; // 題名キャッシュ=1日 / 「未取得(空)」キャッシュ=30分(瞬断からの復帰を速く)
    var jobs = [], seen = {};
    // 失敗表示用：作品URL→投稿(YouTube)の題名。どの投稿の取得が失敗したか明示するのに使う。
    var titleByUrl = {};
    try { allItems().forEach(function (it) { if (it.workUrl && !titleByUrl[it.workUrl]) titleByUrl[it.workUrl] = it.title || ''; }); } catch (e) {}
    targets.forEach(function (nameEl) {
      var url = nameEl.getAttribute('data-fanza-url');
      if (!url) return;
      var cached = cache[url];
      if (cached) {
        // 有効な題名キャッシュ（旧スキーマ=価格/発売日/画像未保存なら再取得して埋める）
        if (cached.title && !isBadFanzaTitle(cached.title) && (now - (cached.fetchedAt || 0)) < DAY && cached.priceInfo && ('releaseDate' in cached.priceInfo) && cached.media) {
          nameEl.textContent = cached.title; nameEl.style.display = '';
          setFanzaPriceEls(url, cached.priceInfo); backfillSnap_(url, cached.priceInfo);
          setFanzaThumbEls(url, cached.media.thumbSmall || cached.media.thumb); return;
        }
        if (!cached.title && (now - (cached.fetchedAt || 0)) < NEG) return; // 直近「未取得」→再取得しない（連打防止）
      }
      var res = window.buildAffiliateLink(url, '');
      if (!res || !res.ok || !res.cid) return;
      if (seen[url]) return; seen[url] = true;
      jobs.push({ url: url, cid: res.cid, el: nameEl, title: titleByUrl[url] || '' });
      nameEl.textContent = '…'; nameEl.style.display = '';
    });
    if (_fanzaBusy) { if (manual) setStatus('作品情報を取得中です。少しお待ちください…'); return; }
    if (!jobs.length) { if (manual) setStatus('✅ 作品情報は取得済みです（再取得の必要はありません）。'); return; }
    // ★DMM APIのレート制限回避：一斉に叩かず 1件ずつ間隔をあけて順次取得する。
    // ★不安定対策：1件につき最大3回リトライ（瞬断/一時的な失敗を吸収）。それでもダメなら30分だけ空キャッシュ。
    _fanzaBusy = true;
    var GAP = 1000, i = 0, done = 0, fail = 0, total = jobs.length, fails = [];
    if (manual) setStatus('🎬 DMMから作品情報を取得中…（0/' + total + '）');
    function fetchWithRetry(job, tries) {
      return window.FanzaCore.fetchFanzaInfo(job.cid, workerUrl, sharedSecret).then(function (info) {
        if (info && info.title && !isBadFanzaTitle(info.title)) return info; // 成功
        // 恒久的失敗（作品が見つからない等）はリトライしない＝無駄な待ち時間を作らない。一時的失敗のみ再試行。
        var canRetry = info && info.__error ? !!info.retryable : true;
        if (tries > 0 && canRetry) return new Promise(function (r) { setTimeout(r, 1300); }).then(function () { return fetchWithRetry(job, tries - 1); });
        return info || null;
      }).catch(function () {
        if (tries > 0) return new Promise(function (r) { setTimeout(r, 1300); }).then(function () { return fetchWithRetry(job, tries - 1); });
        return null;
      });
    }
    function step() {
      if (i >= jobs.length) {
        _fanzaBusy = false;
        if (manual) {
          if (!fails.length) setStatus('✅ DMM作品情報を取得しました（成功 ' + done + ' 件）。');
          else {
            var lines = fails.map(function (f) { return '・「' + esc(f.title || '(無題)') + '」<br>　└ ' + esc(f.reason); }).join('<br>');
            setStatus('DMM作品情報：成功 ' + done + ' / <b>失敗 ' + fail + '</b><br><b>取得に失敗した投稿と原因：</b><br>' + lines, true);
          }
        }
        return;
      }
      var job = jobs[i++];
      if (manual) setStatus('🎬 DMMから作品情報を取得中…（' + i + '/' + total + '）');
      fetchWithRetry(job, 2).then(function (info) {
        var c = fanzaNameCacheLoad();
        if (info && info.title && !isBadFanzaTitle(info.title)) {
          var pinfo = { price: info.price, listPrice: info.listPrice, discountPct: info.discountPct || 0, releaseDate: info.releaseDate || '' };
          var media = { thumb: info.thumb || '', thumbSmall: info.thumbSmall || info.thumb || '', samples: info.samples || [], genres: info.genres || [], service: info.service || '', floor: info.floor || '' };
          c[job.url] = { title: info.title, priceInfo: pinfo, media: media, fetchedAt: new Date().getTime() };
          fanzaNameCacheSave(c); setFanzaEls(job.url, info.title); setFanzaPriceEls(job.url, pinfo); backfillSnap_(job.url, pinfo);
          setFanzaThumbEls(job.url, media.thumbSmall); done++;
        } else {
          c[job.url] = { title: '', priceInfo: null, media: null, fetchedAt: new Date().getTime() }; // 未取得は30分だけキャッシュ（再ハンマー防止＆早期復帰）
          fanzaNameCacheSave(c); setFanzaEls(job.url, ''); setFanzaPriceEls(job.url, null); fail++;
          if (manual) fails.push({ title: job.title, reason: (info && info.__error && info.reason) ? info.reason : '作品が見つかりません' });
        }
      }).catch(function () { setFanzaEls(job.url, ''); fail++; if (manual) fails.push({ title: job.title, reason: '通信エラー' }); })
        .then(function () { setTimeout(step, GAP); }); // 次を間隔をあけて実行
    }
    step();
  }

  // 「DMM 作品情報を取得」ボタン：表示中アイテムのFANZAキャッシュを消して、DMM APIから強制再取得。
  function refetchFanza_() {
    if (_fanzaBusy) { setStatus('作品情報を取得中です。少しお待ちください…'); return; }
    var urls = {};
    document.querySelectorAll('[data-fanza-url]').forEach(function (el) { var u = el.getAttribute('data-fanza-url'); if (u) urls[u] = 1; });
    var c = fanzaNameCacheLoad(), changed = false;
    Object.keys(urls).forEach(function (u) { if (c[u]) { delete c[u]; changed = true; } }); // キャッシュ削除＝強制再取得
    if (changed) fanzaNameCacheSave(c);
    fillFanzaNames(true);   // 進捗・完了を表示しつつ取得（キャッシュ削除済みなので全件取り直す）
  }

  // ── ランキングタブ（両アカウント合算・再生数順）──────────────────────────────
  function renderRank() {
    var el = $('pageRank');
    if (!el) return;

    // 両アカウントからアイテムとYouTube URLを収集
    var combined = [];
    ['acc1', 'acc2'].forEach(function (a) {
      var ymap;
      try { ymap = JSON.parse(localStorage.getItem('verify_yt__' + a) || '{}') || {}; } catch (e) { ymap = {}; }
      var items = loadArr('short_hist__' + a).concat(loadArr('verify_manual__' + a));
      items.forEach(function (it) {
        var k = itemKey(it);
        var yt = ymap[k] || it.ytUrl || '';
        var vid = ytIdOf(yt);
        if (!vid) return;
        combined.push({ it: it, vid: vid, yt: yt, acct: a });
      });
    });

    // vid で重複排除（同じ動画が両アカウントに存在する場合、先に出た方のみ）
    var seen = {};
    var uniq = combined.filter(function (x) {
      if (seen[x.vid]) return false;
      seen[x.vid] = true;
      return true;
    });

    if (!uniq.length) {
      el.innerHTML = '<p class="hint">YouTube URLが設定された動画がありません。<br>🧪 検証タブで各行にYouTube URLを入力すると表示されます。</p>';
      return;
    }

    var ACCT_NAME = { acc1: '月詠み', acc2: '宵桜' };
    function fmtTsFull(ts) {
      if (!ts) return '';
      try {
        var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; };
        return d.getFullYear() + '/' + p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
      } catch (e) { return ''; }
    }

    function doRender() {
      var rows = uniq.map(function (x) {
        var it = x.it;
        return {
          vid: x.vid,
          yt: x.yt,
          acct: x.acct,
          title: titleCache[x.vid] || it.title || (it.manual ? '(手動追加)' : '(無題)'),
          views: (x.vid in viewsCache) ? viewsCache[x.vid] : null,
          ts: it.ts || (publishedCache[x.vid] || 0),
          bskyHref: it.shortUrl || it.postUrl || '',
          workUrl: it.workUrl || '',
          workState: it.workState || '旧作'
        };
      });
      rows.sort(function (a, b) {
        if (a.views === null && b.views === null) return 0;
        if (a.views === null) return 1;
        if (b.views === null) return -1;
        return b.views - a.views;
      });
      el.innerHTML = '<div class="rank-list">' +
        rows.map(function (r, i) {
          var rank = i + 1;
          var topCls = rank <= 3 ? ' rank-top' + rank : '';
          var dispTitle = esc(stripCommonTags(r.title));
          var dateStr = fmtTsFull(r.ts);
          var acctLabel = ACCT_NAME[r.acct] || r.acct;
          return '<div class="rank-row' + topCls + '">' +
            '<span class="rank-num">' + rank + '</span>' +
            '<div class="rank-info">' +
              (dateStr ? '<div class="rank-date">' + esc(dateStr) + '</div>' : '') +
              '<div class="rank-title-row">' +
                '<span class="rank-acct rank-acct-' + esc(r.acct) + '">' + esc(acctLabel) + '</span>' +
                '<div class="rank-title">' +
                  (r.yt ? '<a class="rank-title-link" href="' + esc(r.yt) + '" target="_blank" rel="noopener">' + dispTitle + ' ↗</a>' : dispTitle) +
                '</div>' +
              '</div>' +
              (r.workUrl ? '<div class="fanza-name-row" data-fanza-url="' + esc(r.workUrl) + '" style="display:none;"></div>' : '') +
              '<div class="fanza-price-row">' +
                '<span class="fp-state-slot"' + (r.workUrl ? ' data-fanza-state-url="' + esc(r.workUrl) + '"' : '') + '>' + stateBadgeHtml_(r.workState) + '</span>' +
                (r.workUrl ? '<span class="fanza-price" data-fanza-price-url="' + esc(r.workUrl) + '" style="display:none;"></span>' : '') +
              '</div>' +
              '<div class="rank-metrics">' +
                '<span>▶ ' + (r.views != null ? num(r.views) : (apiKey() ? '…' : '–')) + '</span>' +
                (r.bskyHref ? '<a class="vlink" href="' + esc(r.bskyHref) + '" target="_blank" rel="noopener">Bsky↗</a>' : '') +
                (r.workUrl ? '<a class="vlink vlink-work" href="' + esc(r.workUrl) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
              '</div>' +
            '</div>' +
          '</div>';
        }).join('') +
      '</div>';
      fillFanzaNames();
    }

    // キャッシュにない vid だけ API フェッチ（最大 50 件ずつ）
    var missing = uniq.map(function (x) { return x.vid; }).filter(function (v) { return !(v in viewsCache); });
    if (missing.length) {
      el.innerHTML = '<p style="color:var(--sub);font-size:13px;padding:8px 14px;">再生数を取得中…</p>';
      // 50件ずつバッチに分割して並列フェッチ
      var batches = [];
      for (var i = 0; i < missing.length; i += 50) { batches.push(missing.slice(i, i + 50)); }
      Promise.all(batches.map(function (b) { return fetchVideos(b); })).then(function (results) {
        results.forEach(function (m) {
          var err = m.__error || ''; delete m.__error;
          if (err && !lastErr) lastErr = err;
          Object.keys(m).forEach(function (id) {
            var rec = m[id] || {};
            if (rec.views != null) viewsCache[id] = rec.views;
            if (rec.published != null) publishedCache[id] = rec.published;
            if (rec.title) titleCache[id] = rec.title;
          });
          ytMetaPersist(m); // 永続化（リロードで消えない）
        });
        doRender();
      });
    } else {
      doRender();
    }
  }
  try { window.YtRank = { renderRank: renderRank }; } catch (e) {}
})();
