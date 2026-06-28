/**
 * yt-clicks.js — 検証タブの「再生数・クリック数（投稿別）」一覧。
 *
 * 投稿ごとに：
 *   ・短縮URLのクリック数 … link-worker /api/stats（go5-short）から取得（共有シークレットで読み取り）。
 *   ・YouTube動画の再生数 … YouTube Data API v3（端末内のAPIキー）から取得。
 *
 * データ源は端末内の短縮URL履歴（short_hist__<acct>・bluesky.js が投稿のたびに記録）。
 * 各投稿に紐づくYouTube動画URLは verify_yt__<acct>（行ごとに入力・ウィザードが自動プリフィル）に保存。
 * 完全クライアントサイド。APIキーはこの端末内だけに保存（リポジトリには置かない）。
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  if (!$('ytClickList')) return;

  function acct() { try { return localStorage.getItem('current_account') || 'acc1'; } catch (e) { return 'acc1'; } }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function histKey() { return 'short_hist__' + acct(); }
  function ytMapKey() { return 'verify_yt__' + acct(); }
  function loadHist() { try { var a = JSON.parse(localStorage.getItem(histKey()) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
  function loadYtMap() { try { return JSON.parse(localStorage.getItem(ytMapKey()) || '{}') || {}; } catch (e) { return {}; } }
  function saveYtMap(m) { try { localStorage.setItem(ytMapKey(), JSON.stringify(m)); } catch (e) {} }
  function apiKey() { try { return (localStorage.getItem('yt_api_key') || '').trim(); } catch (e) { return ''; } }
  function itemKey(it) { return it.postUri ? ('u:' + it.postUri) : ('s:' + (it.shortUrl || '')); }
  function num(n) { try { return Number(n).toLocaleString(); } catch (e) { return String(n); } }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  function setStatus(m) { var e = $('ytClickStatus'); if (e) e.textContent = m || ''; }
  function ytIdOf(url) { return (url && window.IdGen && window.IdGen.youtubeId) ? (window.IdGen.youtubeId(url) || '') : ''; }

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
  // 複数の動画ID → viewCount マップ（videos.list は1回1ユニット・最大50件）。
  function fetchViews(ids) {
    var key = apiKey();
    var uniq = ids.filter(function (v, i, a) { return v && a.indexOf(v) === i; });
    if (!key || !uniq.length) return Promise.resolve({});
    var url = 'https://www.googleapis.com/youtube/v3/videos?part=statistics&id=' + uniq.slice(0, 50).join(',') + '&key=' + encodeURIComponent(key);
    return fetch(url).then(function (r) { return r.json(); }).then(function (j) {
      var out = {}; ((j && j.items) || []).forEach(function (it) { if (it && it.id && it.statistics) out[it.id] = parseInt(it.statistics.viewCount || '0', 10); });
      if (j && j.error) out.__error = (j.error.message || 'YouTube APIエラー');
      return out;
    }).catch(function () { return {}; });
  }

  var clicksCache = {}; // code -> clicks
  var viewsCache = {};  // videoId -> views
  var lastErr = '';

  function render() {
    var list = $('ytClickList');
    var items = loadHist();
    var ymap = loadYtMap();
    if (!items.length) { list.innerHTML = '<p class="hint">まだ投稿の記録がありません（投稿して短縮URLが出ると、ここに集まります）。表示中アカウント：' + esc(acct()) + '</p>'; return; }
    list.innerHTML = items.map(function (it) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var code = codeOf(it.shortUrl || '');
      var clicks = code && (code in clicksCache) ? clicksCache[code] : null;
      var views = vid && (vid in viewsCache) ? viewsCache[vid] : null;
      return '<div class="vrow">' +
        '<div class="vrow-h"><b>' + esc(fmtTs(it.ts)) + '</b> ' + esc(it.title || '(無題)') + '</div>' +
        '<div class="vmetrics">' +
        '<span title="YouTube再生数">▶ ' + (views != null ? num(views) : (vid ? '…' : '–')) + '</span>' +
        '<span title="短縮URLクリック数">🔗 ' + (clicks != null ? num(clicks) : (code ? '…' : '–')) + '</span>' +
        (it.shortUrl ? '<a class="vlink" href="' + esc(it.shortUrl) + '" target="_blank" rel="noopener">短縮URL↗</a>' : '') +
        (yt ? '<a class="vlink" href="' + esc(yt) + '" target="_blank" rel="noopener">動画↗</a>' : '') +
        '</div>' +
        '<label class="vyt">YouTube URL <input type="url" inputmode="url" placeholder="https://youtu.be/… を貼ると再生数を取得" data-k="' + esc(k) + '" value="' + esc(yt) + '"></label>' +
        '</div>';
    }).join('');
    list.querySelectorAll('input[data-k]').forEach(function (inp) {
      inp.addEventListener('change', function () {
        var m = loadYtMap(); var v = inp.value.trim();
        if (v) m[inp.getAttribute('data-k')] = v; else delete m[inp.getAttribute('data-k')];
        saveYtMap(m); refresh();
      });
    });
  }

  function refresh() {
    render(); // まずキャッシュ反映で即描画
    var items = loadHist(); var ymap = loadYtMap();
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); }).filter(Boolean);
    var vids = items.map(function (it) { var k = itemKey(it); return ytIdOf(ymap[k] || it.ytUrl || ''); }).filter(Boolean);
    if (!codes.length && !vids.length) { setStatus(apiKey() ? '' : '※YouTube再生数は⚙️詳細設定でAPIキーを設定し、各行にYouTube URLを入れると表示されます'); return; }
    setStatus('取得中…');
    var jobs = [];
    codes.forEach(function (code) { jobs.push(fetchClicks(code).then(function (c) { if (c != null) clicksCache[code] = c; })); });
    if (vids.length) jobs.push(fetchViews(vids).then(function (m) { lastErr = m.__error || ''; delete m.__error; Object.keys(m).forEach(function (id) { viewsCache[id] = m[id]; }); }));
    Promise.all(jobs).then(function () {
      setStatus(lastErr ? ('⚠️ ' + lastErr) : (!apiKey() && vids.length ? '※再生数の表示には⚙️詳細設定のAPIキーが必要です' : ''));
      render();
    });
  }

  var tab = $('tabVerify'); if (tab) tab.addEventListener('click', refresh);
  var rb = $('ytClickRefresh'); if (rb) rb.addEventListener('click', refresh);
  document.addEventListener('account-changed', function () { render(); });

  // 詳細設定タブの YouTube APIキー入力：端末内に保存・復元（秘密扱い）。
  var keyEl = $('ytApiKey');
  if (keyEl) {
    try { keyEl.value = localStorage.getItem('yt_api_key') || ''; } catch (e) {}
    keyEl.addEventListener('input', function () { try { localStorage.setItem('yt_api_key', keyEl.value.trim()); } catch (e) {} });
  }
})();
