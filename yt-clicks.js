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
  function setStatus(m) { var e = $('ytClickStatus'); if (e) e.textContent = m || ''; }
  function ytIdOf(url) { return (url && window.IdGen && window.IdGen.youtubeId) ? (window.IdGen.youtubeId(url) || '') : ''; }

  // 表示する全アイテム（履歴＋手動追加）を結合。
  function allItems() { return loadHist().concat(loadManual()); }

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

  // 並び替え用：YouTube投稿日時(known)があればそれ、無ければ末尾グループへ。
  function sortItems(items, ymap) {
    var arr = items.map(function (it, i) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var hasUrl = !!vid;
      var pub = (vid && (vid in publishedCache)) ? publishedCache[vid] : null;
      // group0=YouTube URLあり（新しい順）／group1=URL無し＝投稿日時不明（末尾）
      var group = hasUrl ? 0 : 1;
      // 既知のYouTube投稿日時を最優先。未取得（URLはある）の間は元ts、URL無しも元tsで暫定整列。
      var t = (pub != null) ? pub : (it.ts || 0);
      return { it: it, i: i, group: group, t: t };
    });
    arr.sort(function (a, b) {
      if (a.group !== b.group) return a.group - b.group;
      if (b.t !== a.t) return b.t - a.t;       // 日時の新しい順
      return a.i - b.i;                         // 同値は元の順序で安定化
    });
    return arr.map(function (x) { return x.it; });
  }

  function render() {
    var list = $('ytClickList');
    var rawItems = allItems();
    var ymap = loadYtMap();
    if (!rawItems.length) { list.innerHTML = '<p class="hint">まだ投稿の記録がありません（投稿して短縮URLが出ると、ここに集まります）。「➕ 手動で追加」からYouTube動画を直接登録もできます。表示中アカウント：' + esc(acct()) + '</p>'; return; }
    var items = sortItems(rawItems, ymap);
    list.innerHTML = items.map(function (it) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var code = codeOf(it.shortUrl || '');
      var clicks = code && (code in clicksCache) ? clicksCache[code] : null;
      var views = vid && (vid in viewsCache) ? viewsCache[vid] : null;
      var pub = vid && (vid in publishedCache) ? publishedCache[vid] : null;
      // 見出し日時＝YouTube投稿時刻。未取得はプレースホルダ表示。
      var dateHtml = pub != null
        ? '<b>' + esc(fmtTs(pub)) + '</b>'
        : (vid ? '<b class="vdate-pending">…</b>' : '<b class="vdate-unknown">投稿日時不明</b>');
      var title = (vid && titleCache[vid]) || it.title || (it.manual ? '(手動追加)' : '(無題)');
      return '<div class="vrow">' +
        '<div class="vrow-h">' + dateHtml + ' ' + esc(title) +
        (it.videoId ? ' <span class="vtag vtag-id">' + esc(it.videoId) + '</span>' : '') +
        (it.manual ? ' <span class="vtag">手動</span>' : '') +
        '</div>' +
        '<div class="vmetrics">' +
        '<span title="YouTube再生数">▶ ' + (views != null ? num(views) : (vid ? '…' : '–')) + '</span>' +
        '<span title="Bsky投稿クリック数">🔗 ' + (clicks != null ? num(clicks) : (code ? '…' : '–')) + '</span>' +
        (it.shortUrl ? '<a class="vlink" href="' + esc(it.shortUrl) + '" target="_blank" rel="noopener">Bsky投稿↗</a>' : '') +
        (yt ? '<a class="vlink" href="' + esc(yt) + '" target="_blank" rel="noopener">YouTube↗</a>' : '') +
        '</div>' +
        '<div class="vrow-foot">' +
        '<label class="vyt">YouTube URL <input type="url" inputmode="url" placeholder="https://youtu.be/… を貼ると再生数・投稿日時を取得" data-k="' + esc(k) + '" value="' + esc(yt) + '"></label>' +
        '<button class="vdel" type="button" data-k="' + esc(k) + '" title="この記録を消去">🗑</button>' +
        '</div>' +
        '</div>';
    }).join('');
    list.querySelectorAll('input[data-k]').forEach(function (inp) {
      inp.addEventListener('change', function () {
        var m = loadYtMap(); var v = inp.value.trim();
        if (v) m[inp.getAttribute('data-k')] = v; else delete m[inp.getAttribute('data-k')];
        saveYtMap(m); refresh();
      });
    });
    list.querySelectorAll('.vdel').forEach(function (b) {
      b.addEventListener('click', function () { deleteItem(b.getAttribute('data-k')); });
    });
  }

  // 1件削除（念のため確認ダイアログ）。手動追加分は verify_manual から、投稿履歴は short_hist から除去。
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
    // 紐づくYouTube URLマッピングも掃除。
    if (ymap[k] != null) { delete ymap[k]; saveYtMap(ymap); }
    refresh();
  }

  // YouTube動画を手動で追加（URLを貼るだけ。タイトル・再生数・投稿日時はAPIで取得）。
  function addManual() {
    var url = window.prompt('追加するYouTube動画のURLを貼り付けてください\n（例：https://youtu.be/XXXXXXXXXXX）');
    if (url == null) return;
    url = url.trim(); if (!url) return;
    var vid = ytIdOf(url);
    if (!vid) { window.alert('YouTubeのURLを認識できませんでした。\nhttps://youtu.be/… か https://www.youtube.com/watch?v=… 形式を貼ってください。'); return; }
    var id = 'm:' + new Date().getTime();
    var manual = loadManual();
    manual.push({ manual: true, id: id, ts: 0 });
    saveArr(manualKey(), manual);
    var m = loadYtMap(); m[id] = url; saveYtMap(m);
    refresh();
  }

  function refresh() {
    render(); // まずキャッシュ反映で即描画
    var items = allItems(); var ymap = loadYtMap();
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); }).filter(Boolean);
    var vids = items.map(function (it) { var k = itemKey(it); return ytIdOf(ymap[k] || it.ytUrl || ''); }).filter(Boolean);
    if (!codes.length && !vids.length) { setStatus(apiKey() ? '' : '※YouTube再生数・投稿日時は⚙️詳細設定でAPIキーを設定し、各行にYouTube URLを入れると表示されます'); return; }
    setStatus('取得中…');
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
    }));
    Promise.all(jobs).then(function () {
      setStatus(lastErr ? ('⚠️ ' + lastErr) : (!apiKey() && vids.length ? '※再生数・投稿日時の表示には⚙️詳細設定のAPIキーが必要です' : ''));
      render(); // 投稿日時が取れたので並び替えも反映
    });
  }

  var tab = $('tabVerify'); if (tab) tab.addEventListener('click', refresh);
  var rb = $('ytClickRefresh'); if (rb) rb.addEventListener('click', refresh);
  var ab = $('ytAddManual'); if (ab) ab.addEventListener('click', addManual);
  document.addEventListener('account-changed', function () { render(); });

  // 詳細設定タブの YouTube APIキー入力：端末内に保存・復元（秘密扱い）。
  var keyEl = $('ytApiKey');
  if (keyEl) {
    try { keyEl.value = localStorage.getItem('yt_api_key') || ''; } catch (e) {}
    keyEl.addEventListener('input', function () { try { localStorage.setItem('yt_api_key', keyEl.value.trim()); } catch (e) {} });
  }
})();
