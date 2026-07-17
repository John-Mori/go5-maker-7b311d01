/**
 * yt-clicks.js — 検証タブの「再生数・クリック数(投稿別)」一覧。
 *
 * 投稿ごとに：
 *   ・短縮URLのクリック数 … link-worker /api/stats(go5-short)から取得。(共有シークレットで読み取り)
 *   ・YouTube動画の再生数・投稿日時・タイトル … YouTube Data API v3(端末内のAPIキー)から取得。
 *
 * 行の見出し日時は「YouTubeに投稿した時刻(snippet.publishedAt)」を表示する。(動画の作成時刻ではない)
 * 並び順：YouTube投稿日時が新しいものほど上。YouTube URL未入力＝投稿日時不明のものは末尾へ。
 *
 * データ源：
 *   ・端末内の短縮URL履歴 short_hist__<acct>(bluesky.js が投稿のたびに記録)
 *   ・手動追加分 verify_manual__<acct>(このタブの「手動で追加」)
 *   ・各行のYouTube動画URL verify_yt__<acct>(行ごとに入力・ウィザードが自動プリフィル)
 * 完全クライアントサイド。APIキーはこの端末内だけに保存。(リポジトリには置かない)
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  if (!$('ytClickList')) return;

  function acct() { try { return localStorage.getItem('current_account') || 'acc1'; } catch (e) { return 'acc1'; } }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // 作品属性。(複数可)キャラ=実在キャラの二次創作 / JK / ギャル / 異世界。キャラ無し＝オリジナル。(非表示)
  var ATTR_DEFS = [
    { key: 'chara', label: 'キャラ' },
    { key: 'jk', label: 'JK' },
    { key: 'gyaru', label: 'ギャル' },
    { key: 'isekai', label: '異世界' },
    { key: 'harem', label: 'ハーレム' },
    { key: 'ai', label: 'AI' },
    { key: 'ol', label: 'OL' },
    { key: 'soshu', label: '総集編' }
  ];
  // 題名表示のタグ省略(2026-07-13・Chami指定): タグ構成は今後も変わるため固定リスト方式を廃止し、
  //   「最初の#以降を丸ごと省略」に統一。#が一個も無い題名だけ「タグ忘れあり」を表示する。
  function stripCommonTags(t) {
    var r = String(t || '');
    var i = r.indexOf('#');
    if (i < 0) return r.trim();
    return (r.slice(0, i).trim() || r.trim()); // #開始の題名は全消えを避けて原文のまま
  }
  function missingCommonTags(t) { return String(t || '').indexOf('#') < 0; }
  function histKey() { return 'short_hist__' + acct(); }
  function manualKey() { return 'verify_manual__' + acct(); }
  function ytMapKey() { return 'verify_yt__' + acct(); }
  function loadArr(k) { try { var a = JSON.parse(localStorage.getItem(k) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }

  // ── 履歴消失の自動証拠採取(INC 宵桜③・Chami承認2026-07-17) ────────────────
  // 背景: 「宵桜(acc2)の投稿履歴だけが消える」が唯一の未解決INC。静的解析では犯人を断定できず、
  //   これまで「次に消えた時にChamiがF12で採取する」という人間頼みの受け身だった。再現が稀な上、
  //   Chamiが先に復旧してしまうと証拠も消える=永遠に捕まらない構造だった。
  // 設計: short_hist__/verify_manual__ への書き込みは saveArr/saveArrFor_ の2つが唯一の出口。
  //   ここで「件数が減る瞬間」だけを捕らえれば、犯人が誰であっても(サニタイザ/復元/未知の第三者)
  //   必ず記録に残る。呼び出し元は new Error().stack から取る=事前に容疑者を決め打ちしない。
  // 制約: 常時ONだが、減少時以外は何もしない(通常運用のコストはゼロ)。証拠は直近3件のみ保持。
  var LOSS_KEY = 'hist_loss_evidence';
  function recordLoss_(key, before, after) {
    try {
      var log = [];
      try { log = JSON.parse(localStorage.getItem(LOSS_KEY) || '[]') || []; } catch (e) {}
      var stack = '';
      try { stack = String((new Error()).stack || '').split('\n').slice(2, 7).join(' | ').replace(/https?:\/\/[^)]*\//g, ''); } catch (e) {}
      log.unshift({
        at: new Date().toISOString(),
        key: key,                      // どのキーが減ったか(short_hist__acc2 等)
        before: before.length,
        after: after.length,
        lostIds: before.filter(function (b) {                       // 消えた実体のid(先頭5件)
          return !after.some(function (a) { return a && b && (a.videoId || a.id) === (b.videoId || b.id); });
        }).slice(0, 5).map(function (x) { return (x && (x.videoId || x.id || x.shortUrl)) || '?'; }),
        acct: (function () { try { return acct(); } catch (e) { return '?'; } })(),
        by: stack                      // ★犯人=呼び出し元のスタック
      });
      localStorage.setItem(LOSS_KEY, JSON.stringify(log.slice(0, 3)));
      try { console.warn('[go5 hist] 履歴が減少したので証拠を記録した', key, before.length + '→' + after.length); } catch (e) {}
    } catch (e) {}
  }
  // 監視対象=消失が報告されているキーだけ(他キーの正常な削除に反応しない)
  function watched_(k) { return /^(short_hist__|verify_manual__)/.test(String(k)); }
  function saveArr(k, a) {
    try {
      if (watched_(k)) {
        var before = loadArr(k);
        if (before.length && Array.isArray(a) && a.length < before.length) recordLoss_(k, before, a);
      }
    } catch (e) {}
    try { localStorage.setItem(k, JSON.stringify(a)); } catch (e) {}
  }
  function loadHist() { return loadArr(histKey()); }
  function loadManual() { return loadArr(manualKey()); }
  function loadYtMap() { try { return JSON.parse(localStorage.getItem(ytMapKey()) || '{}') || {}; } catch (e) { return {}; } }
  function saveYtMap(m) { try { localStorage.setItem(ytMapKey(), JSON.stringify(m)); } catch (e) {} }
  function apiKey() { try { return (localStorage.getItem('yt_api_key') || '').trim(); } catch (e) { return ''; } }
  function itemKey(it) { if (it.manual) return it.id; return it.postUri ? ('u:' + it.postUri) : ('s:' + (it.shortUrl || '')); }
  function num(n) { try { return Number(n).toLocaleString(); } catch (e) { return String(n); } }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  // 祝日セット。(内閣府データ window.__HOLIDAYS__)土=青/日祝=赤 の判定に使う。
  var _holSet = null;
  function holSet() {
    if (_holSet) return _holSet;
    _holSet = {};
    try { var h = (window.__HOLIDAYS__ && window.__HOLIDAYS__.holidays) || []; for (var i = 0; i < h.length; i++) if (h[i] && h[i].date) _holSet[h[i].date] = 1; } catch (e) {}
    return _holSet;
  }
  var DOW = ['日', '月', '火', '水', '木', '金', '土'];
  // 「6/18 (土) 20:00」形式。曜日だけ色付け。(土=青/日祝=赤)戻り値はHTML。(自前データのみ・エスケープ不要)
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
  // DMM作品情報の処理メッセージ専用ゾーン。(クリック数/再生数の更新メッセージと別枠で消し合わない・常に先頭にFANZAのFアイコン)
  var FICON = '<img class="emico fico" src="assets/icons/ic-fanza.png" alt="F"> ';
  function setDmmStatus(m) { var e = $('ytDmmStatus'); if (!e) return; e.innerHTML = m ? (FICON + m) : ''; }
  function ytIdOf(url) { return (url && window.IdGen && window.IdGen.youtubeId) ? (window.IdGen.youtubeId(url) || '') : ''; }

  // 表示する全アイテム(履歴＋手動追加)を結合。manualOnly=true の手動短縮URL履歴は除外。
  function allItems() { return loadHist().filter(function (it) { return !it.manualOnly; }).concat(loadManual()); }

  // ── PC(広い画面)向け：投稿履歴カードの列数(ユーザー選択・スマホは無効)。候補タブと同方式。 ──
  var K_HISTCOLS = 'hist_pc_cols';
  var HCOLS_MIN = 1, HCOLS_MAX = 4, HCOLS_DEF = 1;
  function histCols_() { var n; try { n = parseInt(localStorage.getItem(K_HISTCOLS) || String(HCOLS_DEF), 10); } catch (e) { n = HCOLS_DEF; } return (n >= HCOLS_MIN && n <= HCOLS_MAX) ? n : HCOLS_DEF; }
  function applyHistCols_(n) { try { document.documentElement.style.setProperty('--hist-cols', String(n)); } catch (e) {} }
  function histColsCtlHtml_() {
    var cur = histCols_(), opts = '';
    for (var n = HCOLS_MIN; n <= HCOLS_MAX; n++) opts += '<option value="' + n + '"' + (n === cur ? ' selected' : '') + '>' + n + '列</option>';
    return '<span class="hist-cols-ctl"><label class="hint">表示列数</label><select id="histColsSel">' + opts + '</select></span>';
  }
  try { applyHistCols_(histCols_()); } catch (e) {}

  // 投稿時刻(ts)等から背骨ID(videoId)を生成。idgen があれば流用、無ければ同形式で自前生成。
  function genVideoId(ts) {
    var d = (ts && ts > 0) ? new Date(ts) : new Date();
    if (window.IdGen && window.IdGen.makeVideoId) { try { return window.IdGen.makeVideoId(acct(), d); } catch (e) {} }
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    var stamp = '' + d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '-' + p(d.getHours()) + p(d.getMinutes());
    var r = ''; for (var i = 0; i < 4; i++) r += Math.floor(Math.random() * 36).toString(36);
    return acct() + '-' + stamp + '-' + r;
  }
  // この履歴を正とし、IDが未付与のアイテムへ背骨IDを付与・永続化。(投稿履歴=スプレッドシートの行キー)
  function ensureIds() {
    var hist = loadHist(), c1 = false;
    hist.forEach(function (it) { if (!it.videoId) { it.videoId = genVideoId(it.ts); c1 = true; } });
    if (c1) saveArr(histKey(), hist);
    var man = loadManual(), c2 = false;
    man.forEach(function (it) { if (!it.videoId) { it.videoId = genVideoId(it.ts); c2 = true; } });
    if (c2) saveArr(manualKey(), man);
  }

  // 短縮URLから go5-short のコードを抽出。(自前ワーカーの払い出しURLのみ対象)
  function codeOf(shortUrl) {
    var w = (window.Go5Short && window.Go5Short.WORKER_URL) || '';
    if (!w || !shortUrl) return '';
    var base = w.replace(/\/+$/, '');
    if (shortUrl.indexOf(base + '/') !== 0) return '';
    var rest = shortUrl.slice(base.length + 1).split(/[/?#]/)[0];
    return /^[0-9A-Za-z]+$/.test(rest) ? rest : '';
  }
  // セール会場リンク(導線3・共通コード)のクリック統計。(2026-07-14 Chami依頼: 累計/今日/昨日/週を投稿履歴に表示)
  var SALE_CODES = ['JrziR']; // campaign=gain(utm)の歴史的コード(フォールバック)。af_id差/再生成でコードが変わり得るため下で実リンクからも導出。
  // 実際に生成されたセール会場短縮リンク(bsky_discount_list_link_r2)から現行コードを導出し、ハードコードと合算(重複除去)。
  //   ＝af_id変更や再短縮でコードが変わっても累計が0のまま張り付かない(Chami報告2026-07-15「累計0」対策)。歴史的JrziRも残し過去分を失わない。
  function saleCodes_() {
    var codes = SALE_CODES.slice();
    try { var c = codeOf(localStorage.getItem('bsky_discount_list_link_r2') || ''); if (c && codes.indexOf(c) < 0) codes.push(c); } catch (e) {}
    return codes;
  }
  function renderSaleStats_() {
    var el = document.getElementById('saleStats'); if (!el) return;
    var codes = saleCodes_();
    function paint() {
      var cum = null; codes.forEach(function (c) { if (c in clicksCache) cum = (cum || 0) + clicksCache[c]; });
      var d = (typeof deltaCache === 'object' && deltaCache) ? deltaCache.SALE : null;
      function f(x) { return (x == null ? '–' : num(x)); }
      el.textContent = '🏮 セール会場 累計' + f(cum) + '・今日' + f(d && d.tc) + '・昨日' + f(d && d.yc) + '・週' + f(d && d.wc);
    }
    // 既に一括取得済みならリクエスト0で描画。未取得のときだけ /api/list を1本(TTL内は再利用)。
    //   ＝render()のたびに /api/stats を叩いていた旧実装の無駄を除去(Cloudflare無料枠対策2026-07-16)
    if (codes.some(function (c) { return c in clicksCache; })) { paint(); return; }
    fetchAllClicks_().then(paint);
  }
  function fetchClicks(code) {
    var w = window.Go5Short; if (!w || !code) return Promise.resolve(null);
    var u = w.WORKER_URL.replace(/\/+$/, '') + '/api/stats?code=' + encodeURIComponent(code) + '&secret=' + encodeURIComponent(w.SHARED_SECRET);
    return fetch(u).then(function (r) { return r.json(); }).then(function (j) { return (j && j.ok && typeof j.clicks === 'number') ? j.clicks : null; }).catch(function () { return null; });
  }
  // ── クリック数は /api/list で「全コードを1リクエスト」で取得する ──
  //   旧実装は codes.forEach で /api/stats をコード毎に1本叩いていたため、投稿N件×2導線(導線1/2)で
  //   1回のrefreshにつき最大2N本のWorkerリクエストが飛び、Cloudflare無料枠(10万/日)を焼いていた。
  //   (Chami報告2026-07-16 上限超過メール)refresh()はタブ表示/アカウント切替/編集/削除など多数から
  //   呼ばれるため、1アクション=数百リクエストになっていたのが主因。→ 1本＋TTL再利用に置換。
  var _clicksAt = 0, _clicksP = null, CLICKS_TTL_MS = 60000;
  function fetchAllClicks_(force) {
    var w = window.Go5Short;
    if (!w || !w.WORKER_URL || !w.SHARED_SECRET) return Promise.resolve(false);
    var now = new Date().getTime();
    if (!force && _clicksP && (now - _clicksAt) < CLICKS_TTL_MS) return _clicksP; // 直近取得を再利用(連打・多発を抑制)
    _clicksAt = now;
    var u = w.WORKER_URL.replace(/\/+$/, '') + '/api/list?secret=' + encodeURIComponent(w.SHARED_SECRET);
    _clicksP = fetch(u).then(function (r) { return r.json(); }).then(function (j) {
      if (!j || !j.ok || !j.links) return false;
      j.links.forEach(function (l) { if (l && l.code) clicksCache[l.code] = l.clicks || 0; });
      return true;
    }).catch(function () { return false; });
    return _clicksP;
  }
  // 複数の動画ID → {views, publishedAt(ms), title}。(videos.list は parts に関わらず1回1ユニット・最大50件)
  function fetchVideos(ids) {
    var key = apiKey();
    var uniq = ids.filter(function (v, i, a) { return v && a.indexOf(v) === i; });
    if (!key || !uniq.length) return Promise.resolve({});
    var url = 'https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,status&id=' + uniq.slice(0, 50).join(',') + '&key=' + encodeURIComponent(key);
    return fetch(url).then(function (r) { return r.json(); }).then(function (j) {
      var out = {};
      ((j && j.items) || []).forEach(function (it) {
        if (!it || !it.id) return;
        var rec = {};
        if (it.statistics) rec.views = parseInt(it.statistics.viewCount || '0', 10);
        if (it.snippet) { rec.title = it.snippet.title || ''; rec.channelId = it.snippet.channelId || ''; var t = Date.parse(it.snippet.publishedAt || ''); if (!isNaN(t)) rec.published = t; } // channelId＝アカウント判定の鍵
        if (it.status) {
          rec.privacy = it.status.privacyStatus || '';
          var pa = Date.parse(it.status.publishAt || ''); if (!isNaN(pa)) rec.publishAt = pa; // 予約公開時刻(オーナー認証時のみ返る)
        }
        out[it.id] = rec;
      });
      // 照会したID一覧。(応答に含まれないID＝非公開/予約公開の判定に使う)
      out.__queried = uniq.slice(0, 50);
      if (j && j.error) out.__error = (j.error.message || 'YouTube APIエラー');
      return out;
    }).catch(function () { return { __error: '通信エラー(YouTubeに接続できませんでした)' }; }); // D2: 失敗を{}で握りつぶさない＝「成功表示なのに取れない」を防ぐ
  }

  // ── 今日/昨日/直近1週間の再生・クリック増加(GASが毎時サーバー側で記録した差分)──
  // localStorageに前回値を保持し、開いた瞬間に即表示→GAS取得で最新化。
  var deltaCache = (function () { try { return JSON.parse(localStorage.getItem('delta_cache') || '{}') || {}; } catch (e) { return {}; } })(); // vid -> {tv,yv,wv,tc,yc,wc}
  var peakCache = (function () { try { return JSON.parse(localStorage.getItem('peak_cache') || '{}') || {}; } catch (e) { return {}; } })(); // vid -> {vRate,vWin,cRate,cWin}
  var _deltaFetched = false;
  function gasUrl_() { try { return (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) { return ''; } }
  // JSONP。(GASのGETをCORS回避で読む。キャッシュバスターcb付き)
  //   失敗時は null ではなく {__jsonpFail:true, reason} を渡す(呼び出し側は !res||!res.ok の
  //   既存チェックで従来どおり「失敗」と判定できる＝後方互換。reason で原因を区別できる：
  //   'blocked'＝<script>読込が即エラー(広告ブロッカー/セキュリティソフト/DNSフィルタで
  //   script.google.com 等が遮断されている可能性が高い＝数百ms〜数秒で発生)、
  //   'timeout'＝20秒待っても応答無し。(通信不安定/GAS側の遅延)
  function jsonp_(base, params, cb) {
    if (!base) { cb(null); return; }
    var name = '__go5d_' + new Date().getTime() + '_' + Math.floor(Math.random() * 1e6);
    var s = document.createElement('script'), done = false, t0 = Date.now();
    function clean() { try { delete window[name]; } catch (e) { window[name] = undefined; } if (s.parentNode) s.parentNode.removeChild(s); }
    var timer = setTimeout(function () { if (done) return; done = true; clean(); cb({ __jsonpFail: true, reason: 'timeout', ms: Date.now() - t0 }); }, 20000);
    window[name] = function (d) { if (done) return; done = true; clearTimeout(timer); clean(); cb(d); };
    var q = Object.keys(params).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); }).join('&');
    s.src = base + (base.indexOf('?') >= 0 ? '&' : '?') + q + '&cb=' + new Date().getTime() + '&callback=' + name;
    s.onerror = function () { if (done) return; done = true; clearTimeout(timer); clean(); cb({ __jsonpFail: true, reason: 'blocked', ms: Date.now() - t0 }); };
    document.body.appendChild(s);
  }
  // Chami仕様(2026-07-12): 「–」が許されるのは【今日投稿した動画の"昨日"】だけ。
  //   それ以外で値が出せない時は ⚠(記録欠損=追跡開始前の期間/取得失敗) を明示して区別する。
  function postedTodayOf_(tsMs) {
    if (!tsMs) return false;
    var d = new Date(Number(tsMs)), n = new Date();
    return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
  }
  function fmtDelta_(d, tsMs, hasWork) {
    if (!d) return '';
    var CI = '<img class="emico" src="assets/icons/ic-link.png" alt="">';         // 導線1(Bsky投稿クリック)
    var WI = '<img class="emico emico-cursor" src="assets/icons/ic-cursor-pink.png" alt="">'; // 導線2(作品クリック)
    var todayPosted = postedTodayOf_(tsMs);
    function cell(v, allowDash) {
      if (v != null) return num(v);
      return allowDash ? '–' : '<span title="記録欠損: 追跡開始前の期間か、その回の取得失敗。(YT APIクォータ等)以後の期間は正常に記録されます">⚠</span>';
    }
    // 作品短縮URLがある投稿だけ導線2(ピンク矢印)の増分を併記する。(Chami依頼2026-07-14)
    function seg(lbl, v, c, wc, allowDash) {
      return '<span class="dl-seg"><b>' + lbl + '</b> ▶' + cell(v, allowDash) + ' ' + CI + cell(c, allowDash)
        + (hasWork ? ' ' + WI + cell(wc, allowDash) : '') + '</span>';
    }
    // 昨日だけ「今日投稿なら–許容」。今日/週はフォールバック済みでnullが出るのは欠損時のみ=⚠。
    return seg('今日', d.tv, d.tc, d.twc, false) + seg('昨日', d.yv, d.yc, d.ywc, todayPosted) + seg('週', d.wv, d.wc, d.wwc, false);
  }
  function applyDeltas_() {
    try { renderSaleStats_(); } catch (e) {} // セール会場統計もデルタ到着時に更新

    document.querySelectorAll('[data-delta-vid]').forEach(function (el) {
      var vid = el.getAttribute('data-delta-vid');
      el.innerHTML = fmtDelta_(vid && deltaCache[vid], el.getAttribute('data-delta-ts'), el.getAttribute('data-delta-haswork') === '1') || el.innerHTML;
    });
  }
  function fetchDeltas_(force, cb) {
    if (_deltaFetched && !force) { applyDeltas_(); if (cb) cb(); return; }
    var url = gasUrl_(); if (!url) { applyDeltas_(); if (cb) cb(); return; }
    jsonp_(url, { action: 'deltas' }, function (res) {
      if (res && res.ok && res.deltas) {
        deltaCache = res.deltas; _deltaFetched = true;
        try { localStorage.setItem('delta_cache', JSON.stringify(deltaCache)); } catch (e) {}
        if (res.peaks) { peakCache = res.peaks; try { localStorage.setItem('peak_cache', JSON.stringify(peakCache)); } catch (e) {} }
      }
      applyDeltas_();
      try { repairMissing_(); } catch (e) {} // 「記録待ち」「クリック⚠」を実データ基点で自己修復
      if (cb) cb();
    });
  }
  // サーバーのデルタを見て、シートに計測URLが取りこぼされた投稿を後追い反映して治す。(Chami報告2026-07-14)
  //   ①「記録待ち」= deltaCache[vid] 不在 = サーバーがこのvidを知らない = YouTube動画URLがシート未反映。
  //   ②「クリック⚠」= tc===null = 短縮URLがシート未反映でクリックがスナップされていない。
  //   楽観的な同期台帳が「送信済み」と誤マークして再送しない取りこぼしを、実データ基点で確実に治す。
  var _repairDone = {};
  function repairMissing_() {
    var url = gasUrl_(); if (!url) return;
    var ymap = loadYtMap();
    var pushed = 0;
    allItems().forEach(function (it) {
      if (pushed >= 20) return;
      if (!it.videoId) return;
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      if (!vid || _repairDone[vid]) return;
      var d = deltaCache[vid];
      var needYt = !d;                                              // ①記録待ち: vidがサーバーに無い
      var needShort = !!(d && d.tc === null && codeOf(it.shortUrl || '')); // ②クリック⚠: 短縮URL未反映
      var needWork = !!(d && d.twc === null && codeOf(it.workShortUrl || '')); // ③作品クリック⚠: 作品短縮URL未反映
      if (!needYt && !needShort && !needWork) return;
      _repairDone[vid] = true;
      // pushItemToGas_ は it.ytUrl を送る=YT URLがymap側だけの時に備えて補完してから送る。
      var toSend = it.ytUrl ? it : (function () { var c = {}; for (var p in it) c[p] = it[p]; c.ytUrl = yt; return c; })();
      pushItemToGas_(toSend);                                       // YT URL+短縮URL+作品短縮URLをまとめて反映
      pushed++;
    });
    if (pushed > 0) {
      pokeSnapshotNow_();                          // 反映後に即スナップ→vid/クリックが記録され表示に変わる
      setTimeout(function () { try { fetchDeltas_(true); } catch (e) {} }, 9000);
    }
  }

  // クリック数キャッシュは localStorage に永続化(リロード直後や取得失敗時に「…」のままに
  // ならず、前回値を即表示→取得成功で最新化。再生数等の yt_meta_cache と同方針)。
  var clicksCache = (function () { try { return JSON.parse(localStorage.getItem('clicks_cache') || '{}') || {}; } catch (e) { return {}; } })(); // code -> clicks
  function clicksPersist_() { try { localStorage.setItem('clicks_cache', JSON.stringify(clicksCache)); } catch (e) {} }
  var viewsCache = {};     // videoId -> views
  var publishedCache = {}; // videoId -> publishedAt(ms)
  var titleCache = {};     // videoId -> YouTubeタイトル
  var lastErr = '';

  // ── YouTubeメタ(題名/投稿日時/視聴回数)を localStorage に永続化 ──────────────
  //   在メモリだけだとリロードのたびに再取得＝取得失敗時に題名が消えて不安定。
  //   永続化して起動時に即表示し、refresh で上書き更新する。(題名/投稿日時は不変・視聴回数は最新化)
  function ytMetaLoad() { try { return JSON.parse(localStorage.getItem('yt_meta_cache') || '{}') || {}; } catch (e) { return {}; } }
  function ytMetaSave(m) { try { localStorage.setItem('yt_meta_cache', JSON.stringify(m)); } catch (e) {} }
  (function () { // 起動時：永続キャッシュ→在メモリへ
    var m = ytMetaLoad();
    Object.keys(m).forEach(function (id) { var r = m[id] || {}; if (r.title) titleCache[id] = r.title; if (r.published != null) publishedCache[id] = r.published; if (r.views != null) viewsCache[id] = r.views; });
  })();
  // 既存キャッシュのゴミ掃除。(過去バージョンで __queried 等のメタキーが混入した分を1回で除去)
  (function () {
    try {
      var m = ytMetaLoad(), dirty = false;
      Object.keys(m).forEach(function (id) { if (id.indexOf('__') === 0) { delete m[id]; dirty = true; } });
      if (dirty) ytMetaSave(m);
    } catch (e) {}
  })();
  function ytMetaPersist(fetched) { // fetched: id -> {views,published,title}
    var m = ytMetaLoad(), now = new Date().getTime();
    Object.keys(fetched).forEach(function (id) {
      var rec = fetched[id] || {}; if (id === '__error' || id.indexOf('__') === 0) return; // __系メタキーは保存しない
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
  var _pendingShare = ''; // 生成した計測用リンクの共有URL。(da.gd)保存時に item.shareUrl へ付与
  var _pendingShort = ''; // 生成した計測用リンクのr2 URL。保存時に item.shortUrl へ付与(計測キー)
  var _pendingWorkShort = ''; // 作品クリック(導線2)の生成r2 URL。保存時に item.workShortUrl へ付与
  var _pendingWorkShare = ''; // 作品クリック(導線2)の生成表示URL。保存時に item.workShareUrl へ付与
  var _curSrcUrl = '';    // 生成の元にする投稿URL(編集中アイテムのpostUrl等)

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
          '<div class="vedit-bsky-row">' +
            '<input id="veditYt" type="url" inputmode="url" autocomplete="off" placeholder="https://youtu.be/…(省略可)">' +
            '<button id="veditYtPaste" type="button" class="vedit-copy">貼り付け</button>' +
          '</div>' +
        '</label>' +
        '<label class="vedit-field">Bluesky 投稿URL(計測用の短縮URL)' +
          '<div class="vedit-bsky-row">' +
            '<input id="veditBsky" type="url" inputmode="url" autocomplete="off" placeholder="https://bsky.app/… または短縮URL(省略可)">' +
            '<button id="veditBskyCopy" type="button" class="vedit-copy">Copy</button>' +
          '</div>' +
        '</label>' +
        '<div id="veditGenResult" class="vedit-gen-result" hidden></div>' +
        '<label class="vedit-field">作品URL(DMM/FANZAの商品ページURL)' +
          '<div class="vedit-bsky-row">' +
            '<input id="veditWork" type="url" inputmode="url" autocomplete="off" placeholder="https://www.dmm.co.jp/…(省略可)">' +
            '<button id="veditWorkCopy" type="button" class="vedit-copy">コピー</button>' +
          '</div>' +
        '</label>' +
        '<label class="vedit-field">作品クリック計測用の短縮URL(投稿→FANZA・導線2)' +
          '<div class="vedit-bsky-row">' +
            '<input id="veditWorkShort" type="url" inputmode="url" autocomplete="off" placeholder="投稿すると自動で入ります・空なら「自動生成」で作成">' +
            '<button id="veditWorkShortGen" type="button" class="vedit-copy">自動生成</button>' +
          '</div>' +
          '<span class="vedit-hint" style="font-size:11px;color:var(--sub);">この短縮URLのクリックが作品クリック数(ピンクの矢印)として集計されます。空だと表示されません。</span>' +
        '</label>' +
        '<div class="vedit-attrs">' +
          '<div class="vedit-attrs-title">カテゴリ(複数選択可・キャラ無し＝オリジナル)</div>' +
          ATTR_DEFS.map(function (a) {
            return '<label class="vedit-attr"><input id="veditAttr_' + a.key + '" type="checkbox"><span class="vatt vatt-' + a.key + '">' + a.label + '</span></label>';
          }).join('') +
        '</div>' +
        '<label class="vedit-field">作品状態(投稿当時の状態・後から変更可)' +
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
    // Bluesky投稿URLのコピー。(clipboard API＋execCommandフォールバック)
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
    // 作品URLのコピー。(Blueskyのコピーと同じ挙動)
    $('veditWorkCopy').addEventListener('click', function () {
      var inp = $('veditWork'); if (!inp) return;
      var v = (inp.value || '').trim(); if (!v) return;
      var btn = this, orig = btn.textContent;
      function ok() { btn.textContent = '✓'; setTimeout(function () { btn.textContent = orig; }, 1200); }
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(v).then(ok, function () { copyFallback_(inp, ok); });
        } else { copyFallback_(inp, ok); }
      } catch (e) { copyFallback_(inp, ok); }
    });
    // YouTube URLの貼り付け。(クリップボードの文字列を入れる)
    $('veditYtPaste').addEventListener('click', function () {
      var inp = $('veditYt'); if (!inp) return;
      if (navigator.clipboard && navigator.clipboard.readText) {
        navigator.clipboard.readText().then(function (t) { inp.value = (t || '').trim(); inp.focus(); })
          .catch(function () { inp.focus(); alert('クリップボードを読み取れませんでした。入力欄を長押しして貼り付けてください。'); });
      } else { inp.focus(); alert('この環境ではボタン貼り付けに未対応です。入力欄を長押しして貼り付けてください。'); }
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
        (wsEl && wsEl.value) || '旧作',
        ($('veditWorkShort').value || '').trim()
      );
      var o = $('veditOverlay');
      if (o && !o.hidden) _saveCb = cb;
    });
    // 計測用の短縮リンクを生成(過去のBluesky投稿URL→r2短縮(計測)＋da.gd短縮(表示))
    $('veditGenShort').addEventListener('click', function () {
      var btn = this;
      var src = _curSrcUrl || ($('veditBsky').value || '').trim();
      if (!/^https?:\/\//.test(src)) { showModalErr_('先に「Bluesky投稿URL」を入れてください(https://bsky.app/… )'); return; }
      if (typeof window.Go5MakeShort !== 'function') { showModalErr_('短縮機能が未読み込みです。🦋投稿タブを一度開いてから再度お試しください。'); return; }
      var errEl = $('veditError'); if (errEl) errEl.hidden = true;
      var orig = btn.textContent; btn.disabled = true; btn.textContent = '生成中…';
      window.Go5MakeShort(src).then(function (res) {
        var r2 = (res && res.shortUrl) || '', share = (res && res.shareUrl) || r2;
        if (!r2) { showModalErr_('短縮に失敗しました。(r2ワーカーに接続できませんでした)'); return; }
        $('veditBsky').value = share; // 欄には短い計測URL(da.gd)を表示
        _pendingShort = r2;          // 保存時に shortUrl=r2(クリック計測のキー)
        _pendingShare = share;       // 保存時に shareUrl=da.gd(表示・概要欄用)
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
    // 作品クリック計測URL(導線2)の自動生成: 作品URL→アフィリンク→r2短縮。投稿時と同じ計測キーを作る。
    $('veditWorkShortGen').addEventListener('click', function () {
      var btn = this;
      var wurl = ($('veditWork').value || '').trim();
      if (!/^https?:\/\//.test(wurl)) { showModalErr_('先に「作品URL(DMM/FANZAの商品ページURL)」を入れてください'); return; }
      if (typeof window.buildAffiliateLink !== 'function' || typeof window.Go5MakeShort !== 'function') { showModalErr_('短縮機能が未読み込みです。🦋投稿タブを一度開いてから再度お試しください。'); return; }
      var afId = ''; try { afId = localStorage.getItem('fanza_af_id') || ''; } catch (e) {}
      var aff = window.buildAffiliateLink(wurl, afId);
      if (!aff || !aff.ok || !aff.link) { showModalErr_('作品URLからアフィリンクを作れませんでした(URLを確認してください)'); return; }
      var errEl = $('veditError'); if (errEl) errEl.hidden = true;
      var orig = btn.textContent; btn.disabled = true; btn.textContent = '生成中…';
      window.Go5MakeShort(aff.link).then(function (res) {
        var r2 = (res && res.shortUrl) || '', share = (res && res.shareUrl) || r2;
        if (!r2) { showModalErr_('短縮に失敗しました。(r2ワーカーに接続できませんでした)'); return; }
        $('veditWorkShort').value = share; // 欄には短い表示URLを表示
        _pendingWorkShort = r2;            // 保存時 workShortUrl=r2(作品クリック計測キー)
        _pendingWorkShare = share;         // 保存時 workShareUrl=表示URL
      }).catch(function () { showModalErr_('短縮に失敗しました。'); })
        .then(function () { btn.disabled = false; btn.textContent = orig; });
    });
  }

  function closeModal_() {
    var o = $('veditOverlay'); if (o) o.hidden = true;
    _saveCb = null;
  }

  function openModal_(title, ytVal, bskyVal, workVal, attrs, workState, onSave, workShortVal) {
    injectModal_();
    $('veditTitle').textContent = title;
    $('veditYt').value = ytVal || '';
    $('veditBsky').value = bskyVal || '';
    $('veditWork').value = workVal || '';
    if ($('veditWorkShort')) $('veditWorkShort').value = workShortVal || '';
    attrs = attrs || {};
    ATTR_DEFS.forEach(function (a) { var el = $('veditAttr_' + a.key); if (el) el.checked = !!attrs[a.key]; });
    if ($('veditWorkState')) $('veditWorkState').value = workState || '旧作';
    _pendingShare = ''; _pendingShort = ''; _pendingWorkShare = ''; _pendingWorkShort = ''; // 生成状態をリセット
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

  // clipboard API 不可の環境向けフォールバック(テキスト選択→execCommand('copy'))。
  function copyFallback_(inp, ok) {
    try {
      inp.focus(); inp.select();
      if (inp.setSelectionRange) inp.setSelectionRange(0, 99999);
      if (document.execCommand('copy') && ok) ok();
    } catch (e) {}
  }

  // Bluesky URLをアイテムに保存。(go5-short → shortUrl、その他 → postUrl)
  // 表示(bskyCur/bskyHref)は shareUrl→shortUrl→postUrl の優先順で読むため、優先度の低い
  // postUrl だけを書き換えても、既存の shareUrl/shortUrl に隠れて訂正が画面へ反映されない
  // 。(INC: 訂正して保存しても直らない)現在表示中＝優先度最上位の項目を直接書き換える。
  function saveBskyToItem_(item, bskyUrl) {
    var w = (window.Go5Short && window.Go5Short.WORKER_URL) ? window.Go5Short.WORKER_URL.replace(/\/+$/, '') : '';
    var isGo5 = w && bskyUrl && bskyUrl.indexOf(w) === 0;
    if (bskyUrl) {
      if (isGo5) { item.shortUrl = bskyUrl; delete item.postUrl; delete item.shareUrl; }
      // ★r2でない入力は計測キー(shortUrl)を絶対に上書きしない。(INC調査2026-07-12: 「–」化の原因の一つ)
      //   shareUrlが空でも先にそちらへ入れ、shortUrlはr2のまま守る。
      else if (item.shareUrl || item.shortUrl) item.shareUrl = bskyUrl;
      else item.postUrl = bskyUrl;
    } else {
      // 空白のとき：手動アイテムは両方消す、履歴アイテムは postUrl だけ消す(shortUrl はクリック計測に必要)
      if (item.manual) delete item.shortUrl;
      delete item.postUrl;
    }
  }

  // アイテムへ属性フラグを反映。(true は立て、false は削除)
  function applyAttrs_(item, attrs) {
    ATTR_DEFS.forEach(function (a) { if (attrs && attrs[a.key]) item[a.key] = true; else delete item[a.key]; });
  }
  // YT URLを紐付けた直後にGASへ即時スナップショットを要求。(fire-and-forget)
  //   視聴履歴はURL記載後からしか蓄積されないため、紐付け当日中にベースラインを作る=「今日/昨日」が翌日から出る。(④対策2026-07-12)
  var _snapPokeAt = 0;
  function pokeSnapshotNow_() {
    try {
      var gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim();
      if (!gasUrl || Date.now() - _snapPokeAt < 60000) return; // 1分デバウンス
      _snapPokeAt = Date.now();
      jsonp_(gasUrl, { action: 'snapshot_now' }, function () {});
    } catch (e) {}
  }

  // 編集保存：YouTube URL(ytMap)と Bluesky URL・作品URL・カテゴリ属性・作品状態(アイテム)を一括更新。
  // 作品クリック計測URL(導線2)を item へ反映。自動生成(_pendingWorkShort)>手入力>クリアの優先。
  function applyWorkShort_(item, typedVal) {
    if (_pendingWorkShort) { item.workShortUrl = _pendingWorkShort; item.workShareUrl = _pendingWorkShare || _pendingWorkShort; }
    else if (typedVal) { item.workShortUrl = typedVal; item.workShareUrl = typedVal; }
    else { delete item.workShortUrl; delete item.workShareUrl; }
  }
  function saveEdit_(k, it, ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal) {
    // YouTube URL
    var ymap = loadYtMap();
    if (ytUrl) ymap[k] = ytUrl; else delete ymap[k];
    saveYtMap(ymap);
    var saved = null;
    // Bluesky URL と 作品URL・カテゴリ・作品状態(アイテムを直接書き換え)
    if (it.manual) {
      var manual = loadManual();
      for (var i = 0; i < manual.length; i++) {
        if (itemKey(manual[i]) !== k) continue;
        if (ytUrl) manual[i].ytUrl = ytUrl; else delete manual[i].ytUrl; // P2: 本体にも保存＝キーが変わっても迷子にならない
        saveBskyToItem_(manual[i], bskyUrl);
        if (workUrl) manual[i].workUrl = workUrl; else delete manual[i].workUrl;
        applyAttrs_(manual[i], attrs);
        manual[i].workState = workState || '旧作';
        if (_pendingShort) { manual[i].shortUrl = _pendingShort; delete manual[i].postUrl; } // 計測キー(r2)
        if (_pendingShare) manual[i].shareUrl = _pendingShare; // 表示用(da.gd)
        applyWorkShort_(manual[i], workShortVal); // 作品クリック計測URL(導線2)
        saved = manual[i];
        break;
      }
      saveArr(manualKey(), manual);
    } else {
      var hist = loadHist();
      for (var j = 0; j < hist.length; j++) {
        if (itemKey(hist[j]) !== k) continue;
        if (ytUrl) hist[j].ytUrl = ytUrl; else delete hist[j].ytUrl; // P2: 本体にも保存＝キーが変わっても迷子にならない
        saveBskyToItem_(hist[j], bskyUrl);
        if (workUrl) hist[j].workUrl = workUrl; else delete hist[j].workUrl;
        applyAttrs_(hist[j], attrs);
        hist[j].workState = workState || '旧作';
        if (_pendingShort) { hist[j].shortUrl = _pendingShort; delete hist[j].postUrl; } // 計測キー(r2)
        if (_pendingShare) hist[j].shareUrl = _pendingShare; // 表示用(da.gd)
        applyWorkShort_(hist[j], workShortVal); // 作品クリック計測URL(導線2)
        saved = hist[j];
        break;
      }
      saveArr(histKey(), hist);
    }
    if (saved) pushItemToGas_(saved); // スプレッドシートのカテゴリ列等へ反映(GAS設定時のみ)
    if (ytUrl) pokeSnapshotNow_();   // YT URLを紐付けた日は即スナップ=日別記録のベースラインを当日中に作る(④)
    // 非r2リンクを入れた保存でも自動で計測キーを確定させる(冪等短縮=同URLなら既存コード+累積クリックを引き継ぐ)
    if (saved) autoMeasureItem_(saved, function () { saveArr(saved.manual ? manualKey() : histKey(), saved.manual ? manual : hist); });
    // 作品クリック計測URL(導線2)も、手入力がr2でなければ自動で計測キー(r2)へ確定させる。
    //   これをしないと codeOf() がコードを取れず、ピンクの矢印(作品クリック数)が表示されない。(Chami報告2026-07-14)
    if (saved) autoMeasureWorkShort_(saved, function () { saveArr(saved.manual ? manualKey() : histKey(), saved.manual ? manual : hist); });
    refresh();
  }
  // 作品クリック計測URL(導線2)の自動確定。手入力が r2 でない(作品ページURL/アフィリンク/da.gd等)場合、
  //   アフィリンク化→r2短縮して workShortUrl を計測可能なキーに整える。既に r2 なら何もしない(冪等)。
  function autoMeasureWorkShort_(it, persist) {
    try {
      var go5 = window.Go5Short || {}; var w = (go5.WORKER_URL || '').replace(/\/+$/, '');
      function isR2(u) { return !!u && u.indexOf(w + '/') === 0; }
      var cur = (it && it.workShortUrl) || '';
      if (!it || !w || typeof window.Go5MakeShort !== 'function') return;
      if (!/^https?:\/\//.test(cur) || isR2(cur)) return; // 値なし/既にr2＝そのまま
      var toShorten = cur;
      // FANZA/DMMの作品ページURL(al.fanza等のアフィリンクではない)なら、先にアフィリンク化する。
      if (window.buildAffiliateLink && /(^|\.)dmm\.co\.jp|(^|\.)dlsite|fanza/.test(cur) && !/al\.(fanza|dmm)/.test(cur)) {
        var afId = ''; try { afId = localStorage.getItem('fanza_af_id') || ''; } catch (e) {}
        var aff = window.buildAffiliateLink(cur, afId);
        if (aff && aff.ok && aff.link) toShorten = aff.link;
      }
      window.Go5MakeShort(toShorten).then(function (res) {
        if (!(res && res.shortUrl && isR2(res.shortUrl))) return;
        it.workShortUrl = res.shortUrl; it.workShareUrl = res.shareUrl || res.shortUrl;
        if (typeof persist === 'function') persist();
        refresh(); // 作品クリック(ピンク矢印)がこの再描画で出るようになる
      });
    } catch (e) {}
  }

  // 履歴アイテム1件をスプレッドシート(GAS)へ upsert 送信。post_id=背骨ID(videoId)で同一行を更新。
  // 投稿日時を上書きしないよう postUrl は送らない。(既存行のカテゴリ列だけ更新する用途)
  // T5: シートへ送るchannelは背骨ID(videoId)接頭辞を優先。(現UIではなく作品の所属)
  //   混入アイテムを現アカウントのタブへ薄行として転写する『感染プリンタ』を止める。
  function chOfVid_(videoId, fallback) { var m = String(videoId || '').match(/^(acc[12])-/); return m ? m[1] : (fallback || acct()); }
  function chForItem_(it) { return chOfVid_(it && it.videoId, acct()); }
  function pushItemToGas_(it) {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl || !it || !it.videoId) return;
    var payload = {
      op: 'upsert',
      channel: chForItem_(it),       // 接頭辞優先で誤タブ書き込みを防ぐ
      videoId: it.videoId,           // post_id(upsertキー)
      title: it.title || '',
      postUri: it.postUri || '',
      workUrl: it.workUrl || '',
      shortUrl: it.shortUrl || '',
      shareUrl: it.shareUrl || '',
      youtube_url: it.ytUrl || '',   // ★YouTube動画URL列へ反映=サーバーがvidを認識→日別記録(デルタ)開始。
                                     //   これが空だとシートにvidが無く、スナップされず「記録待ち」が永久固定になる(根治)
      work_short_url: it.workShortUrl || '' // 導線2(作品クリック)の計測URL=作品クリック数の日次スナップ元(GAS 14C)
    };
    ATTR_DEFS.forEach(function (a) { payload[a.key] = !!it[a.key]; }); // カテゴリ列：属性名を明記
    payload.workState = it.workState || '旧作'; // 作品状態列
    try { fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) }).catch(function () {}); } catch (e) {}
  }

  // 自己修復: 端末が持つ計測URL(YouTube動画URL・短縮URL=r2)がシートへ未反映だと、サーバーが
  //   vid/クリックを認識できず「記録待ち」や日別クリックの⚠が固定化する。それをシートへ後追いupsertで治す。
  //   videoId毎に「YT URL＋短縮URL」の署名が変わった時だけ送る(localStorage台帳・冪等)。
  function reconcileYtToSheet_() {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl) return;
    var ledger = {};
    try { ledger = JSON.parse(localStorage.getItem('yt_sheet_synced') || '{}') || {}; } catch (e) { ledger = {}; }
    var ymap = loadYtMap();
    var pushed = 0;
    allItems().forEach(function (it) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var short = it.shortUrl || '';
      if ((!yt && !short) || !it.videoId) return;
      var sig = yt + '' + short;            // YT URL＋短縮URLの複合署名=どちらが欠けていても治す
      if (ledger[it.videoId] === sig) return;      // 同一署名は送信済み=再送しない
      if (pushed >= 12) return;                    // 1回のreconcileで送る上限=大量アイテム時のGAS負荷を抑える
      var toSend = it.ytUrl ? it : (function () { var c = {}; for (var p in it) c[p] = it[p]; c.ytUrl = yt; return c; })();
      pushItemToGas_(toSend);
      ledger[it.videoId] = sig;
      pushed++;
    });
    if (pushed > 0) {
      try { localStorage.setItem('yt_sheet_synced', JSON.stringify(ledger)); } catch (e) {}
      pokeSnapshotNow_(); // シート反映後に即スナップ=次の巡回を待たず当日中にベースラインを作る
      // スナップが載る頃合いでデルタを再取得＝リロードせず同一セッションで「記録待ち」「クリック⚠」を解消する。
      setTimeout(function () { try { fetchDeltas_(true); } catch (e) {} }, 8000);
    }
  }

  // ── render ──────────────────────────────────────────────────────────────
  function render() {
    var list = $('ytClickList');
    var rawItems = allItems();
    var ymap = loadYtMap();
    if (!rawItems.length) {
      list.innerHTML = '<p class="hint">まだ投稿の記録がありません。(投稿して短縮URLが出ると、ここに集まります)「➕ 手動で追加」からYouTube動画を直接登録もできます。表示中アカウント：' + esc(acct()) + '</p>';
      return;
    }
    var items = sortItems(rawItems, ymap);
    // YouTube公開前(非公開/予約公開)の動画一覧 → vidで引けるマップに(「投稿予定」バッジ表示用)
    var schedMap = {};
    try { loadYtSched_(acct()).forEach(function (y) { if (y && y.vid) schedMap[y.vid] = y; }); } catch (e) {}
    // 被リビルド作品の非表示トグル。(最新の投稿カードにボタンを設置。ONで被リビルド済みを一覧から除外)
    var hideRemadeKey = 'verify_hide_remade__' + acct();
    var hideRemade = false; try { hideRemade = localStorage.getItem(hideRemadeKey) === '1'; } catch (e) {}
    var visibleItems = hideRemade ? items.filter(function (it) { return !it.remade; }) : items;
    // 非表示トグルは行の枠外(リスト最上部の独立バー)に置く＝先頭カードに重ならない。
    var hideBarHtml = '<div class="vhide-remade-bar">' +
      '<span id="saleStats" class="sale-stats" title="セール会場リンク(🏮大幅割引セール中の同人祭ページ)のクリック数。累計はr2計測・今日/昨日/週は日次スナップショット">🏮 セール会場 …</span>' +
      histColsCtlHtml_() + // 列数セレクタ(PCのみCSSで表示)
      '<button id="hideRemadeBtn" type="button" class="vhide-remade-btn" title="被リビルド作品を一覧から隠す/戻す">' + (hideRemade ? '👁 被リビルドを表示' : '被リビルドを非表示') + '</button></div>';
    list.innerHTML = hideBarHtml + visibleItems.map(function (it, idx) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var code = codeOf(it.shortUrl || '');
      var clicks = code && (code in clicksCache) ? clicksCache[code] : null;
      // 導線2(投稿→FANZA): 本文中の作品リンクの計測コード(bluesky.jsが投稿時に置換・記録)
      var wcode = codeOf(it.workShortUrl || '');
      var wclicks = wcode && (wcode in clicksCache) ? clicksCache[wcode] : null;
      // リビルド結合＝この投稿のクリック＋リビルド前の動画のクリック(rebuildBaseClicks)を総合値に。(別短縮URLのため加算)
      // リビルド版はカッコ内(rebuildBaseClicks)も足した総合計を表示。自分のクリックが0/未取得でも被リビルド分は必ず加算する(例：0+5=5(5))。
      var clicksTotal = (it.rebuildMerged && it.rebuildBaseClicks != null) ? ((clicks != null ? clicks : 0) + it.rebuildBaseClicks) : clicks;
      // 作品の動画で使った画像。(＋Bluesky添付画像)作品cid経由で候補タブの保存画像を引く。
      var rImgCid = it.workUrl ? workCidOf_(it.workUrl) : '';
      var rImgArr = (rImgCid && window.Go5Cand && window.Go5Cand.refImgs) ? (window.Go5Cand.refImgs(rImgCid) || []) : [];
      var refThumb = rImgArr[0] || (rImgCid && window.Go5Cand && window.Go5Cand.bskyImg ? window.Go5Cand.bskyImg(rImgCid) : '') || '';
      // 🛠️編集で後付け添付した投稿画像。(履歴アイテム単位)1枚目をカードに表示し、タップで全枚数をズーム。
      var pKey = it.videoId || k;
      var postImgArr = (window.Go5Cand && window.Go5Cand.postImgs) ? (window.Go5Cand.postImgs(pKey) || []) : [];
      var postThumb = postImgArr[0] || '';
      var views = vid && (vid in viewsCache) ? viewsCache[vid] : null;
      var pub = vid && (vid in publishedCache) ? publishedCache[vid] : null;
      var sched = (pub == null) && vid && schedMap[vid]; // 公開済みが観測されたら予約表示はしない
      // YouTube動画が紐付いていない投稿(Bluesky単体投稿等)は、YouTube公開日時が原理的に存在しない。
      //   sendSync_()と同じ考え方(実投稿時刻(ts)を正とする)でit.tsにフォールバックする＝
      //   「投稿日時不明」のまま放置しない。(シート復元直後のvid無し投稿で顕在化)
      var dateHtml = sched
        ? ((sched.publishAt ? '<b>' + fmtPostDate(sched.publishAt) + '</b> ' : '') + '<span class="vtag vtag-scheduled">投稿予定</span>')
        : (pub != null
          ? '<b>' + fmtPostDate(pub) + '</b>'
          : (vid ? '<b class="vdate-pending">…</b>'
            : (it.ts ? '<b class="vdate-tsonly">' + fmtPostDate(it.ts) + '</b>' : '<b class="vdate-unknown">投稿日時不明</b>')));
      var rawTitle = (vid && titleCache[vid]) || it.title || (it.manual ? '(手動追加)' : '(無題)');
      var dispTitle = esc(stripCommonTags(rawTitle));
      var tagWarn = !it.manual && vid && (vid in titleCache) && missingCommonTags(rawTitle);
      var titleHtml = tagWarn
        ? '<span style="color:#dc465a;font-weight:700;">' + dispTitle + ' ⚠タグ忘れあり</span>'
        : dispTitle;
      var bskyHref = it.shareUrl || it.shortUrl || it.postUrl || ''; // 表示リンクは共有(da.gd)優先。計測は下のcode(=r2)で行う
      // 属性バッジ(作品名の下に改行して表示。作品状態は価格行の左に別途表示)
      var tagsHtml = ATTR_DEFS.map(function (a) { return it[a.key] ? '<span class="vtag vtag-' + a.key + '">' + a.label + '</span>' : ''; }).join('');
      // 作り直し系バッジ：rebuild=この動画自体がリビルド版 / remade=この投稿は被リビルド(=リビルド版に取って代わられた)
      if (it.rebuild) tagsHtml += '<span class="vtag vtag-rebuild">🔁リビルド版</span>';
      if (it.remade) tagsHtml += '<span class="vtag vtag-remade">🔁被リビルド</span>';
      return '<div class="vrow' + (it.remade ? ' vrow-remade' : '') + '">' +
        '<div class="vrow-body">' +
        // 1行目＝日付＋サークル名(作者名)、2行目＝動画の題名(改行して統一)
        '<div class="vrow-h">' + dateHtml + (it.workUrl ? '<span class="vrow-author" data-fanza-author-url="' + esc(it.workUrl) + '"></span>' : '') + '</div>' +
        '<div class="vrow-title">' + titleHtml + '</div>' +
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
          '<span title="Bsky投稿クリック数(YT→投稿・導線1)' + (it.rebuildBaseClicks != null ? '(総合値。カッコ内＝リビルド前の動画までのクリック数)' : '') + '"><img class="emico" src="assets/icons/ic-link.png" alt="クリック"> ' + (clicksTotal != null ? num(clicksTotal) : (code ? '…' : '–')) +
            (it.rebuildBaseClicks != null ? ' <span class="vclicks-base">(' + num(it.rebuildBaseClicks) + ')</span>' : '') + '</span>' +
          (wcode ? '<span title="作品リンククリック数(投稿→FANZA・導線2)"><img class="emico emico-cursor" src="assets/icons/ic-cursor-pink.png" alt="作品クリック"> ' + (wclicks != null ? num(wclicks) : '…') + '</span>' : '') +
          '<span class="vrow-links">' + // 🛠️編集/Bsky↗/YouTube↗/作品↗ を1グループに＝編集もBskyと同じ段に表示・作品↗だけ改行される事故を防ぐ
            '<button class="vedit-btn" type="button" data-k="' + esc(k) + '">🛠️編集</button>' +
            (bskyHref ? '<a class="vlink vlink-bsky" href="' + esc(bskyHref) + '" target="_blank" rel="noopener">Bsky↗</a>' : '') +
            (yt ? '<a class="vlink vlink-yt" href="' + esc(yt) + '" target="_blank" rel="noopener">YouTube↗</a>' : '') +
            (it.workUrl ? '<a class="vlink vlink-work" href="' + esc(it.workUrl) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
          '</span>' +
        '</div>' +
        '</div>' + // .vrow-body
        ((it.workUrl || refThumb || postThumb) ? '<div class="vrow-thumbcol">' +
          (it.workUrl ? '<img class="vrow-thumb" data-fanza-thumb-url="' + esc(it.workUrl) + '" alt="作品サムネ(タップで詳細)" title="タップで作品詳細" loading="lazy" style="display:none;">' : '') +
          (refThumb ? '<img class="vrow-refimg" data-refcid="' + esc(rImgCid) + '" src="' + esc(refThumb) + '" alt="動画で使った画像(タップで拡大)" title="タップで拡大。Bluesky投稿画像と違えば左右フリックで両方表示" loading="lazy">' : '') +
          (postThumb ? '<img class="vrow-postimg" data-postkey="' + esc(pKey) + '" src="' + esc(postThumb) + '" alt="投稿画像(タップで拡大)" title="🛠️編集で添付した投稿画像。タップで拡大・左右で全枚数" loading="lazy">' : '') +
        '</div>' : '') +
        // footは本文列(vrow-body)の外＝カード全幅の独立行。これで🗑がカードの一番右(画像の真下)まで届く
        '<div class="vrow-foot">' +
          '<span class="vrow-delta"' + (vid ? ' data-delta-vid="' + esc(vid) + '" data-delta-ts="' + (it.ts || 0) + '"' + (wcode ? ' data-delta-haswork="1"' : '') : '') + ' title="日別の増分。(30分毎のサーバー記録から)⚠=記録欠損。(追跡開始前/取得失敗)–は今日投稿の昨日のみ">' + (vid ? (fmtDelta_(deltaCache[vid], it.ts, !!wcode) || '<span style="opacity:.55;" title="30分毎のサーバースナップ後に数値が出ます">⏳記録待ち(最大30分)</span>') : '<span style="opacity:.55;">今日 ▶– 🖱–　(YT未連携=日別記録なし)</span>') + '</span>' +
          '<div class="vrow-actcol">' +
            (!it.remade && it.videoId ? '<button class="vrebuild-from" type="button" data-rbvid="' + esc(it.videoId) + '" title="この投稿をリビルド元にして動画作成タブへ(同一作品ならBluesky投稿を引き継ぎ)">🔁 リビルド作成</button>' : '') +
            '<button class="vremake' + (it.remade ? ' on' : '') + '" type="button" data-k="' + esc(k) + '" title="この投稿に被リビルドの印を付ける(削除ではなく記録として残す)">' + (it.remade ? '↩ 被リビルド取消' : '🔁 被リビルドへ') + '</button>' +
          '</div>' +
          '<button class="vdel" type="button" data-k="' + esc(k) + '" title="この記録を消去">🗑</button>' +
        '</div>' +
        '</div>';
    }).join('');
    applyManualInfoNow_(); // 手動入力の作品情報は描画直後に即表示(フェッチ待ちで遅れない)
    fillFanzaNames();
    try { renderSaleStats_(); } catch (e) {} // セール会場統計(再描画のたびに最新表示)
    try { applyHistCols_(histCols_()); } catch (e) {} // 列数を反映(PCのみCSSで効く)
    (function () { var hcs = $('histColsSel'); if (hcs) hcs.addEventListener('change', function () { var n = parseInt(this.value, 10) || HCOLS_DEF; try { localStorage.setItem(K_HISTCOLS, String(n)); } catch (e) {} applyHistCols_(n); }); })();

    // YouTube URL 直接入力
    list.querySelectorAll('input[data-k]').forEach(function (inp) {
      inp.addEventListener('change', function () {
        var k = inp.getAttribute('data-k');
        var m = loadYtMap(); var v = inp.value.trim();
        if (v) m[k] = v; else delete m[k];
        saveYtMap(m);
        // P2: アイテム本体(ytUrl)にも保存。短縮URL再生成等でキーが変わっても迷子にならない恒久形。
        [[histKey(), loadHist()], [manualKey(), loadManual()]].forEach(function (p) {
          var dirty = false;
          p[1].forEach(function (it) { if (itemKey(it) === k) { if (v) it.ytUrl = v; else delete it.ytUrl; dirty = true; } });
          if (dirty) saveArr(p[0], p[1]);
        });
        refresh();
      });
    });

    // 削除
    list.querySelectorAll('.vdel').forEach(function (b) {
      b.addEventListener('click', function () {
        var row = b.parentNode; while (row && !(row.classList && row.classList.contains('vrow'))) row = row.parentNode; // "vrow-foot"等の部分一致を避け、正確に .vrow を探す
        if (row) row.classList.add('vrow-deleting'); // 削除範囲(この行)を枠線で明示
        var k = b.getAttribute('data-k');
        setTimeout(function () { deleteItem(k, row); }, 60); // 枠線を描画してから確認ダイアログ
      });
    });

    // 作り直し(削除の代わりに「被リビルド」の印を付ける／取り消す)
    list.querySelectorAll('.vremake').forEach(function (b) {
      b.addEventListener('click', function () { toggleRemade(b.getAttribute('data-k')); });
    });

    // 🔁リビルドで作る：この投稿をリビルド元にして動画作成タブへ(bluesky.jsのGo5Rebuildが対象選択＋作品データ反映まで実施)
    list.querySelectorAll('.vrebuild-from').forEach(function (b) {
      b.addEventListener('click', function () {
        if (window.Go5Rebuild && window.Go5Rebuild.startFromHistory) window.Go5Rebuild.startFromHistory(b.getAttribute('data-rbvid'));
      });
    });

    // 被リビルド作品の非表示トグル(最新の投稿カードのみに設置)
    var hideBtn = $('hideRemadeBtn');
    if (hideBtn) hideBtn.addEventListener('click', function () {
      try { localStorage.setItem(hideRemadeKey, hideRemade ? '0' : '1'); } catch (e) {}
      refresh();
    });

    // サムネ → 作品詳細モーダル
    list.querySelectorAll('.vrow-thumb').forEach(function (im) {
      im.addEventListener('click', function () { openFanzaModal_(im.getAttribute('data-fanza-thumb-url')); });
    });

    // 動画で使った画像 → 拡大ズーム。Bluesky投稿画像が動画画像と異なれば左右フリックで両方見られるよう並べる。
    //   モーダル各ページの上に用途見出しを表示: 動画生成用/Bluesky投稿用。同一画像なら1ページで「動画生成/Bluesky投稿」。
    list.querySelectorAll('.vrow-refimg').forEach(function (im) {
      im.addEventListener('click', function () {
        var cid = im.getAttribute('data-refcid');
        var imgs = (cid && window.Go5Cand && window.Go5Cand.refImgs) ? (window.Go5Cand.refImgs(cid) || []).slice() : [];
        var b = (cid && window.Go5Cand && window.Go5Cand.bskyImg) ? window.Go5Cand.bskyImg(cid) : '';
        var caps = imgs.map(function () { return '動画生成で使用した画像'; });
        if (b) {
          var bi = imgs.indexOf(b);
          if (bi >= 0) caps[bi] = '動画生成/Bluesky投稿';             // 同一画像＝1ページに統合表記
          else { imgs.push(b); caps.push('Bluesky投稿用画像'); }      // 異なる＝末尾ページに追加
        }
        if (!imgs.length && im.getAttribute('src')) { imgs = [im.getAttribute('src')]; caps = ['動画生成で使用した画像']; }
        if (imgs.length && window.Go5Cand && window.Go5Cand.zoomImages) window.Go5Cand.zoomImages(imgs, 0, { captions: caps });
      });
    });

    // 🛠️編集で添付した投稿画像 → 拡大ズーム。(左右で全枚数・下に「現在 / 総ページ数」)
    list.querySelectorAll('.vrow-postimg').forEach(function (im) {
      im.addEventListener('click', function () {
        var key = im.getAttribute('data-postkey');
        var imgs = (key && window.Go5Cand && window.Go5Cand.postImgs) ? (window.Go5Cand.postImgs(key) || []).slice() : [];
        if (!imgs.length && im.getAttribute('src')) imgs = [im.getAttribute('src')];
        if (imgs.length && window.Go5Cand && window.Go5Cand.zoomImages) window.Go5Cand.zoomImages(imgs, 0);
      });
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
        var workShortCur = it.workShareUrl || it.workShortUrl || ''; // 作品クリック計測URL(導線2)の現値
        var attrCur = {}; ATTR_DEFS.forEach(function (a) { attrCur[a.key] = !!it[a.key]; });
        _curSrcUrl = it.postUrl || it.shortUrl || bskyCur || ''; // 生成の元＝この投稿の元URL
        openModal_('URL を編集', ytCur, bskyCur, workCur, attrCur, it.workState || '旧作', function (ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal) {
          closeModal_();
          saveEdit_(k, it, ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal);
        }, workShortCur);
        addMoveButtonsToModal_(k, it); // 「→ 別アカウントへ移動」を差し込む
        addRebuildMergeButtonToModal_(k, it); // 「🔁 リビルド結合」を保存の上に差し込む
        addPostImagesToModal_(k, it); // 「投稿画像を添付(複数可)」を差し込む
      });
    });
  }

  // ── 🔁リビルド結合：この投稿を、別の投稿(＝リビルド前の動画)のリビルド版として結合する ──
  // 選んだ側が「被リビルド」(ランキング除外)になり、この投稿がランキングに残る。この投稿のクリックは
  // 「この投稿＋リビルド前」の総合値表示になり、括弧内にリビルド前分(結合時点のクリック数)を出す。
  function addRebuildMergeButtonToModal_(k, it) {
    var actions = $('veditOverlay') && $('veditOverlay').querySelector('.vedit-actions');
    if (!actions) return;
    var old = actions.parentNode.querySelector('#veditRebuildMergeRow');
    if (old) old.parentNode.removeChild(old);
    var row = document.createElement('div');
    row.id = 'veditRebuildMergeRow';
    row.style.cssText = 'margin:8px 0 0;';
    var cur = (it.rebuildOf && it.rebuildMerged) ? ('(現在：' + esc(rebuildTargetTitle_(it.rebuildOf) || '結合済み') + ')') : '';
    row.innerHTML = '<button id="veditRebuildMerge" type="button" class="vedit-gen">🔁 リビルド結合' + (cur ? '<span class="vgen-note" style="display:block;">' + cur + '</span>' : '') + '</button>';
    actions.parentNode.insertBefore(row, actions); // 保存を含む actions の直前＝「保存の上」
    row.querySelector('#veditRebuildMerge').addEventListener('click', function () { openRebuildMergePicker_(k, it); });
  }
  function rebuildTargetTitle_(videoId) {
    var all = allItems();
    for (var i = 0; i < all.length; i++) { if (all[i].videoId === videoId) return all[i].title || '(無題)'; }
    return '';
  }
  // 履歴アイテムの作品cid。(候補タブと同じ normalize+buildAffiliateLink)
  function workCidOf_(u) {
    try {
      if (!u || !window.buildAffiliateLink) return '';
      var n = window.normalizeWorkUrl ? window.normalizeWorkUrl(u) : u;
      var r = n ? window.buildAffiliateLink(n, '') : null;
      return (r && r.ok) ? r.cid : '';
    } catch (e) { return ''; }
  }
  var _rebuildPickerOv = null;
  function openRebuildMergePicker_(thisKey, thisItem) {
    var ov = _rebuildPickerOv;
    if (!ov) {
      ov = document.createElement('div'); ov.className = 'fz-overlay'; ov.hidden = true; ov.style.zIndex = '10001';
      ov.innerHTML = '<div class="fz-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) ov.hidden = true; });
      ov.querySelector('.fz-close').addEventListener('click', function () { ov.hidden = true; });
      _rebuildPickerOv = ov;
    }
    var myCid = workCidOf_(thisItem.workUrl);
    // 現アカウントの全投稿を新しい順に。自分自身と、既に被リビルド済みは対象外。
    var all = allItems().filter(function (x) { return itemKey(x) !== thisKey && x.videoId; })
      .sort(function (a, b) { return (b.ts || 0) - (a.ts || 0); });
    var matched = myCid ? all.filter(function (x) { return workCidOf_(x.workUrl) === myCid; }) : [];
    function rowHtml(x) {
      var d = x.ts ? new Date(x.ts) : null, ds = d ? ((d.getMonth() + 1) + '/' + d.getDate() + ' ') : '';
      var mark = x.remade ? ' <span style="color:#b08968;">🔁被リビルド</span>' : '';
      return '<button type="button" class="rbm-item" data-rbvid="' + esc(x.videoId) + '">' + esc(ds + (x.title || '(無題)')) + mark + '</button>';
    }
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      '<div class="fz-title" style="background:#fffef9;color:#111;padding:8px 12px;border-radius:8px;margin:2px 34px 10px 0;">🔁 リビルド結合する動画を選ぶ</div>' +
      '<div class="hint" style="color:#c8cdd4;">選んだ動画が「被リビルド」になり(ランキングから外れます)、この投稿がリビルド版として残ります。クリック数は合算されます。</div>' +
      '<div class="rbm-sec-label">作品URLが一致する投稿</div>' +
      (matched.length ? '<div class="rbm-list">' + matched.map(rowHtml).join('') + '</div>'
        : '<div class="hint" style="padding:4px 0;">一致する投稿はありません' + (myCid ? '' : '(この投稿に作品URLが無いため照合できません)') + '。下の一覧から選べます。</div>') +
      '<div class="rbm-sec-label">すべての投稿(新しい順)</div>' +
      (all.length ? '<div class="rbm-list">' + all.map(rowHtml).join('') + '</div>' : '<div class="hint">他に投稿がありません。</div>');
    ov.hidden = false;
    body.querySelectorAll('.rbm-item').forEach(function (b) {
      b.addEventListener('click', function () {
        var vid = b.getAttribute('data-rbvid');
        var target = null; all.forEach(function (x) { if (x.videoId === vid) target = x; });
        if (!target) return;
        if (!window.confirm('「' + (target.title || '(無題)') + '」をリビルド前の動画として結合します。\nこの投稿がリビルド版になり、選んだ動画はランキングから外れます。よろしいですか？')) return;
        mergeRebuild_(thisKey, thisItem, target);
        ov.hidden = true; closeModal_();
      });
    });
  }
  // リビルド結合の適用：この投稿=リビルド版(rebuild/rebuildOf/結合スナップショット)、選んだ動画=被リビルド。
  function mergeRebuild_(thisKey, thisItem, target) {
    var baseClicks = null;
    try { var tcode = codeOf(target.shortUrl || ''); if (tcode && (tcode in clicksCache)) baseClicks = clicksCache[tcode]; } catch (e) {}
    function applyIn(arrKey, arr) {
      var changed = false;
      arr.forEach(function (x) {
        if (itemKey(x) === thisKey) { x.rebuild = true; x.rebuildOf = target.videoId || ''; x.rebuildMerged = true; if (baseClicks != null) x.rebuildBaseClicks = baseClicks; changed = true; }
        if (x.videoId && target.videoId && x.videoId === target.videoId) { x.remade = true; changed = true; }
      });
      if (changed) saveArr(arrKey, arr);
    }
    applyIn(manualKey(), loadManual());
    applyIn(histKey(), loadHist());
    try { pushRemadeToGas_(target.videoId || '', true); } catch (e) {} // 記録シートにも被リビルドを反映
    refresh();
  }

  // 1件削除。(確認ダイアログ)手動追加分は verify_manual から、投稿履歴は short_hist から除去。
  function deleteItem(k, row) {
    function clearMark() { if (row && row.classList) row.classList.remove('vrow-deleting'); }
    var rawItems = allItems(), ymap = loadYtMap();
    var target = null;
    for (var i = 0; i < rawItems.length; i++) { if (itemKey(rawItems[i]) === k) { target = rawItems[i]; break; } }
    if (!target) { clearMark(); return; }
    var vid = ytIdOf(ymap[k] || target.ytUrl || '');
    var title = (vid && titleCache[vid]) || target.title || (target.manual ? '(手動追加)' : '(無題)');
    if (!window.confirm('「' + title + '」を本当に消去しますか？\n(この記録を一覧から削除します。取り消せません)')) { clearMark(); return; }
    if (target.manual) {
      saveArr(manualKey(), loadManual().filter(function (x) { return itemKey(x) !== k; }));
    } else {
      saveArr(histKey(), loadHist().filter(function (x) { return itemKey(x) !== k; }));
    }
    if (ymap[k] != null) { delete ymap[k]; saveYtMap(ymap); }
    refresh();
  }

  // 作り直し印のトグル。(削除はしない)ONで「この動画を消して作り直した」印を付け、記録シートにも反映。
  function toggleRemade(k) {
    var arrKey, arr;
    // 対象が手動追加(verify_manual)か投稿履歴(short_hist)かを判定して、その配列内のフラグを反転。
    var manual = loadManual(), hist = loadHist();
    var inManual = manual.some(function (x) { return itemKey(x) === k; });
    if (inManual) { arrKey = manualKey(); arr = manual; } else { arrKey = histKey(); arr = hist; }
    var target = null, next = false;
    arr.forEach(function (x) { if (itemKey(x) === k) { x.remade = !x.remade; target = x; next = !!x.remade; } });
    if (!target) return;
    saveArr(arrKey, arr);
    // 記録シート(GAS)にも反映：videoId 行の「作り直し」列を 作り直し済/解除 に。テストIDと未設定は送らない。
    pushRemadeToGas_(target.videoId || '', next);
    refresh();
  }
  // channel省略時は現在UIのアカウント。(既存の呼び出し=ボタン操作は常にUIと同じアカウントを見ているため安全)
  function pushRemadeToGas_(videoId, remade, channel) {
    if (!videoId) return;
    var isTest = (window.IdGen && window.IdGen.isTestId) ? window.IdGen.isTestId(videoId) : /^test-/.test(videoId);
    if (isTest) return;
    var gasUrl = ''; try { gasUrl = localStorage.getItem('bsky_gas_url') || ''; } catch (e) {}
    if (!gasUrl) return;
    // T5: 明示channel＞背骨ID接頭辞＞現UI。remade単独payloadが誤タブに薄行を作る事故を防ぐ。
    var ch = channel || chOfVid_(videoId, (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'));
    try {
      fetch(gasUrl, { method: 'POST', body: JSON.stringify({ op: 'upsert', channel: ch, videoId: videoId, remade: !!remade }) }).catch(function () {});
    } catch (e) {}
  }

  // ── 🔁リビルド連携：動画作成タブの「どの作品をリビルドするか」ピッカー・被リビルド自動反映 ──
  //   window.Go5History として外部(bluesky.js/index.html)から使う。
  //   listForRebuildPicker: 現在アカウントの投稿履歴を新しい順で返す。(既に被リビルド済みは対象から除外)
  function listForRebuildPicker_() {
    ensureIds(); // 履歴を正としてID未付与のアイテムへ背骨IDを付与＝ピッカーに全件を確実に出す(履歴一覧との不一致を防ぐ)
    var ymap = loadYtMap();
    return allItems()
      .filter(function (it) { return it.videoId && !it.remade; })
      .map(function (it) {
        // 題名は投稿履歴一覧と同じ解決順。(YouTubeタイトルがあれば優先→なければ記録タイトル)#タグは除去。
        var k = itemKey(it);
        var vid = ytIdOf(ymap[k] || it.ytUrl || '');
        var title = (vid && titleCache[vid]) || it.title || (it.manual ? '(手動追加)' : '(無題)');
        return { videoId: it.videoId, title: stripCommonTags(title), ts: it.ts || 0, workUrl: it.workUrl || '', workState: it.workState || '' };
      })
      .sort(function (a, b) { return (b.ts || 0) - (a.ts || 0); });
  }
  // videoIdを指定して「被リビルド」フラグ(remade)をONにする。account省略時は現在UIのアカウント。
  //   新しい動画作成時の自動リンク付け(bluesky.js)から呼ばれるため、投稿先アカウントを明示できるようにしている。
  function markRebuilt_(videoId, account) {
    if (!videoId) return;
    var a = account || acct();
    var bases = ['short_hist', 'verify_manual'];
    for (var i = 0; i < bases.length; i++) {
      var arr = loadArrFor_(bases[i], a);
      var found = false;
      arr.forEach(function (x) { if (x.videoId === videoId) { x.remade = true; found = true; } });
      if (found) {
        saveArrFor_(bases[i], a, arr);
        pushRemadeToGas_(videoId, true, a);
        if (a === acct()) refresh();
        return;
      }
    }
  }
  try { window.Go5History = { listForRebuildPicker: listForRebuildPicker_, markRebuilt: markRebuilt_ }; } catch (e) {}

  // ── アイテムのアカウント間移動(誤って別アカウントに入った履歴/手動追加を正しい側へ)──
  function acctName_(a) { return a === 'acc2' ? '宵桜艶帖' : '月詠み色恋劇場'; }
  function loadArrFor_(base, a) { try { var x = JSON.parse(localStorage.getItem(base + '__' + a) || '[]'); return Array.isArray(x) ? x : []; } catch (e) { return []; } }
  function saveArrFor_(base, a, arr) {
    // saveArr と並ぶ もう一方の書き込み出口。ここを塞がないとサニタイザ等の移動系がすり抜ける。
    var k = base + '__' + a;
    try {
      if (watched_(k)) {
        var before = loadArrFor_(base, a), after = (arr || []).slice(0, 200);
        if (before.length && after.length < before.length) recordLoss_(k, before, after);
      }
    } catch (e) {}
    try { localStorage.setItem(k, JSON.stringify(arr.slice(0, 200))); } catch (e) {}
  }
  function loadYtMapFor_(a) { try { return JSON.parse(localStorage.getItem('verify_yt__' + a) || '{}') || {}; } catch (e) { return {}; } }
  function saveYtMapFor_(a, m) { try { localStorage.setItem('verify_yt__' + a, JSON.stringify(m)); } catch (e) {} }
  // 1件をアカウント間で移動。(ローカルの base 配列＋verify_yt＋シート行)表示更新はしない。
  function moveOne_(base, it, from, to) {
    if (from === to || !it) return;
    var k = itemKey(it);
    var srcArr = loadArrFor_(base, from), moved = null;
    srcArr = srcArr.filter(function (x) { if (itemKey(x) === k) { moved = x; return false; } return true; });
    if (!moved) moved = it;
    saveArrFor_(base, from, srcArr);
    var dstArr = loadArrFor_(base, to).filter(function (x) { return itemKey(x) !== k; });
    dstArr.unshift(moved); saveArrFor_(base, to, dstArr);
    var fm = loadYtMapFor_(from), yUrl = fm[k];
    if (yUrl) { delete fm[k]; saveYtMapFor_(from, fm); var tm = loadYtMapFor_(to); tm[k] = yUrl; saveYtMapFor_(to, tm); }
    var gas = gasUrl_();
    if (gas && (moved.videoId || moved.postUri || moved.shortUrl)) {
      var mvpay = { from: from, to: to, videoId: moved.videoId || '', postUri: moved.postUri || '', short: moved.shortUrl || '' };
      // T2: 応答を検証し、失敗(通信断/GASエラー/ok:false)は再送キューへ積む＝ローカルとシートの無通知乖離を防ぐ。
      fetch(gas, { method: 'POST', body: JSON.stringify({ op: 'move_row', videoId: mvpay.videoId, postUri: mvpay.postUri, short: mvpay.short, from: from, to: to }) })
        .then(function (r) { return r.json(); })
        .then(function (j) { if (!j || !j.ok) throw new Error((j && j.error) || 'move_row_failed'); })
        .catch(function () { queueSheetMove_(mvpay); });
    }
  }
  // T2: シート行移動の失敗を貯めて次回更新時に自動再送。(ローカルだけ動いてシートが取り残される事故の恒久対策)
  function queueSheetMove_(mv) {
    try { var q = JSON.parse(localStorage.getItem('sheet_move_pending') || '[]') || []; q.push(mv); localStorage.setItem('sheet_move_pending', JSON.stringify(q)); } catch (e) {}
  }
  function flushSheetMovePending_() {
    var gas = gasUrl_(); if (!gas) return;
    var q; try { q = JSON.parse(localStorage.getItem('sheet_move_pending') || '[]') || []; } catch (e) { q = []; }
    if (!q.length) return;
    var mv = q[0]; // 1回のrefreshで1件ずつ(軽量・順序保存)
    fetch(gas, { method: 'POST', body: JSON.stringify({ op: 'move_row', videoId: mv.videoId, postUri: mv.postUri, short: mv.short, from: mv.from, to: mv.to }) })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j && j.ok) { var qq; try { qq = JSON.parse(localStorage.getItem('sheet_move_pending') || '[]') || []; } catch (e) { qq = []; } qq.shift(); try { localStorage.setItem('sheet_move_pending', JSON.stringify(qq)); } catch (e) {} } })
      .catch(function () {});
  }
  function moveItemAccount_(k, it, to) {
    var from = acct(); if (from === to) return;
    // T2: 本人投稿の誤移動ブロック。DID台帳が健全で「この投稿は現アカウント本人のもの」と確定できるなら強警告。
    var R = window.Go5AccountRepair;
    if (R && R.classifyByPost && R.ledgerFresh && R.ledgerFresh() && R.classifyByPost(it) === from) {
      if (!window.confirm('⚠️ この投稿は「' + acctName_(from) + '」本人のアカウント(投稿者DID)で投稿されています。\nそれでも ' + acctName_(to) + ' へ移動しますか？(通常は不要です)')) return;
    }
    moveOne_(it.manual ? 'verify_manual' : 'short_hist', it, from, to);
    setStatus('✅ 「' + (it.title || k) + '」を ' + acctName_(to) + ' へ移動しました。' + (gasUrl_() ? '' : '(シートは⚙記録用URL設定時に反映)'));
    render();
  }

  // ── YouTube channelId 取得(fetchVideos を流用・yt_meta_cache にキャッシュ)──
  function fetchChannelIds_(vids, cb) {
    var meta = ytMetaLoad(), need = [], out = {};
    (vids || []).forEach(function (v) { if (!v) return; if (meta[v] && meta[v].channelId) out[v] = meta[v].channelId; else need.push(v); });
    need = need.filter(function (v, i, a) { return a.indexOf(v) === i; });
    if (!need.length) { cb(out); return; }
    var chunks = []; for (var i = 0; i < need.length; i += 50) chunks.push(need.slice(i, i + 50));
    var pend = chunks.length;
    chunks.forEach(function (ch) {
      fetchVideos(ch).then(function (m) {
        var mm = ytMetaLoad();
        ch.forEach(function (v) { var r = m[v]; if (r && r.channelId) { out[v] = r.channelId; mm[v] = mm[v] || {}; mm[v].channelId = r.channelId; if (r.title) mm[v].title = r.title; } });
        ytMetaSave(mm);
        if (--pend === 0) cb(out);
      }).catch(function () { if (--pend === 0) cb(out); });
    });
  }

  // ── アカウント分類の「検出」(DID/ハンドル→YouTubeチャンネル→videoId接頭辞)──
  //   ★移動はしない。移動候補リストを返すだけ。(適用は applyMoves_ でユーザー確認後)
  //   安全ゲート: ①DID台帳をverifyLedgerで毎回検証(force解決・両DID相異・失敗時中止)
  //              ②channel地図は「片方のアカウントの票しか無いチャンネル」だけ採用(排他)
  var _smartRepairBusy = false;
  function detectAccountMoves_(cb) {
    if (_smartRepairBusy) { cb({ ok: false, reason: 'busy' }); return; }
    _smartRepairBusy = true;
    var R = window.Go5AccountRepair;
    if (!R || typeof R.verifyLedger !== 'function') { _smartRepairBusy = false; cb({ ok: false, reason: '修復モジュール未読込(🦋投稿タブを一度開いてください)' }); return; }
    R.verifyLedger(function (led) {
      if (!led.ok) { _smartRepairBusy = false; cb({ ok: false, reason: led.reason, ledger: led }); return; }
      var classifyByPost = R.classifyByPost;
      var buckets = [];
      ['acc1', 'acc2'].forEach(function (a) {
        loadArrFor_('short_hist', a).forEach(function (it) { buckets.push({ a: a, base: 'short_hist', it: it }); });
        loadArrFor_('verify_manual', a).forEach(function (it) { buckets.push({ a: a, base: 'verify_manual', it: it }); });
      });
      var ymapBy = { acc1: loadYtMapFor_('acc1'), acc2: loadYtMapFor_('acc2') };
      function vidOf(b) { return ytIdOf(ymapBy[b.a][itemKey(b.it)] || b.it.ytUrl || ''); }
      fetchChannelIds_(buckets.map(vidOf).filter(Boolean), function (vidChan) {
        // channel→account 地図(排他票のみ。両アカウントの票が入ったチャンネルは判定に使わない)
        var tally = {};
        buckets.forEach(function (b) {
          var byPost = classifyByPost(b.it); var vid = vidOf(b); var ch = vid ? vidChan[vid] : '';
          if (byPost && ch) { (tally[ch] || (tally[ch] = { acc1: 0, acc2: 0 }))[byPost]++; }
        });
        var chanToAcct = {};
        Object.keys(tally).forEach(function (ch) {
          var t = tally[ch];
          if (t.acc1 > 0 && t.acc2 === 0) chanToAcct[ch] = 'acc1';
          else if (t.acc2 > 0 && t.acc1 === 0) chanToAcct[ch] = 'acc2';
          // 両方の票があるチャンネルは曖昧＝不採用(誤った多数決で全量誤移動しない)
        });
        var moves = [], unknown = 0;
        buckets.forEach(function (b) {
          var target = classifyByPost(b.it), by = target ? 'post' : '';
          if (!target) { var vid = vidOf(b); var ch = vid ? vidChan[vid] : ''; if (ch && chanToAcct[ch]) { target = chanToAcct[ch]; by = 'channel'; } }
          if (!target) { var m = String(b.it.videoId || '').match(/^(acc[12])-/); if (m) { target = m[1]; by = 'videoId'; } }
          if (!target) { unknown++; return; }
          if (target !== b.a) moves.push({ base: b.base, it: b.it, from: b.a, to: target, by: by });
        });
        _smartRepairBusy = false;
        cb({ ok: true, moves: moves, unknown: unknown, total: buckets.length, ledger: led });
      });
    });
  }
  // 検出結果を適用。(移動ログを保存し「元に戻す」を可能にする)高信頼(post/channel)のみ。
  function applyMoves_(moves) {
    var log = [];
    moves.forEach(function (mv) {
      if (mv.by !== 'post' && mv.by !== 'channel') return; // videoId接頭辞のみは弱シグナル＝適用しない
      moveOne_(mv.base, mv.it, mv.from, mv.to);
      log.push({ base: mv.base, item: mv.it, from: mv.from, to: mv.to, by: mv.by, at: new Date().getTime() });
    });
    if (log.length) { try { localStorage.setItem('acct_move_log_last', JSON.stringify(log)); } catch (e) {} }
    return log.length;
  }
  // 直前の一括移動を元に戻す。(ログから逆適用。シート行も move_row で戻る)
  function undoLastMoves_() {
    var log = []; try { log = JSON.parse(localStorage.getItem('acct_move_log_last') || '[]') || []; } catch (e) {}
    if (!log.length) { setStatus('元に戻せる移動履歴がありません。'); return; }
    log.reverse().forEach(function (mv) { moveOne_(mv.base, mv.item, mv.to, mv.from); });
    try { localStorage.removeItem('acct_move_log_last'); } catch (e) {}
    setStatus('↩️ ' + log.length + '件の移動を元に戻しました。');
    render();
  }
  // 確認ダイアログ用の移動一覧テキスト。(最大12件表示)
  function movesSummary_(moves, led) {
    var lines = moves.slice(0, 12).map(function (mv) {
      return '・「' + String(mv.it.title || itemKey(mv.it)).slice(0, 24) + '」 ' + acctName_(mv.from) + ' → ' + acctName_(mv.to) + '(' + (mv.by === 'post' ? 'Bluesky投稿者' : 'YouTubeチャンネル') + '判定)';
    });
    if (moves.length > 12) lines.push('…ほか ' + (moves.length - 12) + '件');
    var idLine = '判定基準: 月詠み=@' + led.h1 + (led.dn1 ? '(' + led.dn1 + ')' : '') + ' / 宵桜=@' + led.h2 + (led.dn2 ? '(' + led.dn2 + ')' : '');
    return idLine + '\n\n' + lines.join('\n');
  }
  // ── シート(記録)から、現在アカウントの投稿履歴をローカルへ復元(非破壊)──
  //   記録シートを正本として、①別アカウントへ誤って入ったアイテムを現アカウントへ戻す
  //   ②ローカルに無い投稿はシートから薄いアイテムとして復活。既存ローカルは尊重。(消さない)
  // シートの作品cid → 作品URL を再構成。(同人=d_… / ブックス=数字ID)復元時に作品URLを取り戻す。
  function workUrlFromCid_(cid) {
    cid = String(cid || '').trim(); if (!cid) return '';
    if (/^d_/.test(cid)) return 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/';
    if (/^\d+$/.test(cid)) return 'https://book.dmm.com/product/' + cid + '/';
    return ''; // それ以外(動画等)はドメイン推定が難しいので空(手動編集で補完可)
  }
  function restoreHistoryFromSheet_(cb) {
    var gas = gasUrl_(); if (!gas) { if (cb) cb({ ok: false, reason: '記録用GAS(⚙記録用URL)が未設定です' }); return; }
    var to = acct();
    jsonp_(gas, { action: 'history', channel: to, limit: 300 }, function (res) {
      if (!res || !res.ok || !Array.isArray(res.items)) {
        var why = 'シートの投稿履歴を取得できませんでした';
        if (res && res.__jsonpFail && res.reason === 'blocked') why += '(' + res.ms + 'ms で読込失敗＝広告ブロッカー/セキュリティソフト/DNSフィルタが script.google.com への通信を遮断している可能性が高いです。拡張機能を無効化するかシークレットウィンドウで試してください)';
        else if (res && res.__jsonpFail && res.reason === 'timeout') why += '(20秒応答なし＝通信不安定、またはGAS側が混雑している可能性)';
        else if (res && res.error) why += '(GAS: ' + res.error + ')';
        if (cb) cb({ ok: false, reason: why });
        return;
      }
      var arrs = {};
      function arrOf(base, a) { var kk = base + '__' + a; if (!arrs[kk]) arrs[kk] = loadArrFor_(base, a); return arrs[kk]; }
      // 1アイテムを表す全キー。(postUri/短縮URL/videoId/題名+YT)安定キーが無い行も題名+YTで重複判定。
      function keysFor(o, yt) {
        var ks = [];
        if (o.postUri) ks.push('u:' + o.postUri);
        if (o.shortUrl) ks.push('s:' + o.shortUrl);
        if (o.videoId) ks.push('v:' + o.videoId);
        var y = yt || o.ytUrl || '';
        if ((o.title || y)) ks.push('t:' + (o.title || '') + '|' + y);
        return ks;
      }
      // ローカル全体を索引。(両アカウント×short_hist/verify_manual)各アイテムの全キーを登録。
      var idx = {};
      ['acc1', 'acc2'].forEach(function (a) {
        ['short_hist', 'verify_manual'].forEach(function (base) {
          var ym = loadYtMapFor_(a);
          arrOf(base, a).forEach(function (it) { var kk = itemKey(it); var loc = { a: a, base: base, key: kk }; keysFor(it, ym[kk]).forEach(function (kx) { if (!idx[kx]) idx[kx] = loc; }); });
        });
      });
      var added = 0, movedBack = 0, skipped = 0;
      var ytTo = loadYtMapFor_(to);
      res.items.forEach(function (si) {
        var sheetKeys = keysFor(si, si.youtubeUrl);
        if (!sheetKeys.length) { skipped++; return; } // 識別子が全く無い空行はスキップ
        // P4: 背骨IDの接頭辞が現アカウントと矛盾する行は取り込まない。
        //   シート側の誤タブ行(例: 宵桜タブに紛れた acc1-… の行)を復元経由でローカルへ「再感染」させない。
        var pm = String(si.videoId || '').match(/^(acc[12])-/);
        if (pm && pm[1] !== to) { skipped++; return; }
        var loc = null, matchedKey = ''; for (var i = 0; i < sheetKeys.length && !loc; i++) { if (idx[sheetKeys[i]]) { loc = idx[sheetKeys[i]]; matchedKey = sheetKeys[i]; } }
        if (loc) {
          if (loc.a !== to) { // 誤って別アカウントに入っている→現アカウントへ戻す(ローカルのみ・シートは触らない)
            // T3: 弱キー(t:題名|YT)一致での横断移動は禁止。(別作品/両垢同題名の誤吸引＝再感染を防ぐ。取り込まず据え置き)
            if (matchedKey.charAt(0) === 't') { skipped++; return; }
            var srcArr = arrOf(loc.base, loc.a), mv = null;
            var na = srcArr.filter(function (x) { if (itemKey(x) === loc.key) { mv = x; return false; } return true; });
            // T3: ローカル品の所属(投稿者DID／背骨ID接頭辞)が現アカウントと矛盾するなら移動しない。(naは未保存＝副作用なし)
            if (mv) { var ow = ownerOf_(mv); if (ow && ow !== to) { skipped++; return; } }
            arrs[loc.base + '__' + loc.a] = na; saveArrFor_(loc.base, loc.a, na);
            var dstBase = (mv && mv.manual) ? 'verify_manual' : 'short_hist';
            var dstArr = arrOf(dstBase, to).filter(function (x) { return itemKey(x) !== loc.key; });
            dstArr.unshift(mv || {}); arrs[dstBase + '__' + to] = dstArr; saveArrFor_(dstBase, to, dstArr);
            var fm = loadYtMapFor_(loc.a); if (fm[loc.key]) { ytTo[loc.key] = fm[loc.key]; delete fm[loc.key]; saveYtMapFor_(loc.a, fm); }
            loc.a = to; loc.base = dstBase; // 索引も現在地へ更新(同一runでの二重処理防止)
            movedBack++;
          }
          // 既に to にある：何もしない
        } else { // ローカルに無い→シートから薄い履歴アイテムを復活
          // ts＝postedAt優先。空なら背骨ID(videoId=acc-YYYYMMDD-HHMM-)から作成日時を復元＝投稿日が0のまま
          //   復元される「月詠み✔なのに投稿日が出ない」再発を防止。(次回のシート記録にも正しいpostedAtが乗る)
          var _svid = si.videoId || '';
          var _sts = (si.postedAt ? (Date.parse(si.postedAt) || 0) : 0) || (window.IdGen && window.IdGen.tsOfId ? window.IdGen.tsOfId(_svid) : 0);
          var item = { account: to, title: si.title || '', shortUrl: si.shortUrl || '', shareUrl: si.shareUrl || si.shortUrl || '', postUrl: si.postUrl || '', postUri: si.postUri || '', videoId: _svid, ts: _sts };
          var wu = si.workUrl || workUrlFromCid_(si.cid); if (wu) item.workUrl = wu; // 作品URLをcidから復元(サムネ・価格・作品状態が戻る)
          if (si.cid) item.cid = String(si.cid); // 作品cidも串刺しで保持(候補タブの「投稿済み」判定を確実にする)
          if (si.workState) item.workState = si.workState;
          var dstArr2 = arrOf('short_hist', to); dstArr2.unshift(item); arrs['short_hist__' + to] = dstArr2; saveArrFor_('short_hist', to, dstArr2);
          var k = itemKey(item); if (si.youtubeUrl) ytTo[k] = si.youtubeUrl;
          // 追加分も索引へ(同一run内の重複シート行を二重追加しない)
          var newLoc = { a: to, base: 'short_hist', key: k }; keysFor(item, si.youtubeUrl).forEach(function (kx) { if (!idx[kx]) idx[kx] = newLoc; });
          added++;
        }
      });
      saveYtMapFor_(to, ytTo);
      if (cb) cb({ ok: true, added: added, movedBack: movedBack, skipped: skipped, total: res.items.length });
    });
  }

  // 編集モーダルへ「→ 別アカウントへ移動」ボタンを差し込む。
  function addMoveButtonsToModal_(k, it) {
    var ov = document.getElementById('veditOverlay'); if (!ov) return;
    var modal = ov.querySelector('.vedit-modal'); if (!modal) return;
    var old = modal.querySelector('.vedit-move'); if (old) old.parentNode.removeChild(old);
    var to = acct() === 'acc1' ? 'acc2' : 'acc1';
    var div = document.createElement('div'); div.className = 'vedit-move';
    div.style.cssText = 'margin:8px 0 2px;padding-top:10px;border-top:1px solid var(--line);';
    div.innerHTML = '<div class="hint" style="margin-bottom:6px;">この投稿が<b>' + acctName_(acct()) + '以外</b>のものなら、正しいアカウントの投稿履歴へ移せます。</div>' +
      '<button type="button" class="ghost vedit-move-btn" style="width:auto;">→ ' + acctName_(to) + ' へ移動</button>';
    var actions = modal.querySelector('.vedit-actions');
    if (actions) modal.insertBefore(div, actions); else modal.appendChild(div);
    div.querySelector('.vedit-move-btn').addEventListener('click', function () {
      if (!window.confirm('「' + (it.title || k) + '」を ' + acctName_(to) + ' の投稿履歴へ移動します。\n(この端末とスプレッドシートの両方を移します)よろしいですか？')) return;
      closeModal_();
      moveItemAccount_(k, it, to);
    });
  }

  // 編集モーダルへ「投稿画像を添付(複数可)」セクションを差し込む。1枚目が投稿履歴カードに表示され、
  //   タップで作品画像と同様に拡大。(左右で全枚数・下に「現在 / 総ページ数」)保存はwrite-through。(追加/削除で即反映)
  function addPostImagesToModal_(k, it) {
    var ov = document.getElementById('veditOverlay'); if (!ov) return;
    var modal = ov.querySelector('.vedit-modal'); if (!modal) return;
    var old = modal.querySelector('.vedit-postimg'); if (old) old.parentNode.removeChild(old);
    var api = window.Go5Cand || {};
    if (!api.postImgs || !api.postImgSave) return; // 画像ストア未対応環境では出さない
    var pKey = it.videoId || k;
    var cid = it.workUrl ? workCidOf_(it.workUrl) : '';
    // 用途(保存先)。ref(動画で使った画像)/bsky(Bluesky添付)は作品cidが要る＝workUrlがある時だけ選べる。
    var USES = [{ v: 'post', label: '投稿画像', multi: true }];
    if (cid) { USES.push({ v: 'ref', label: '動画で使った画像', multi: true }); USES.push({ v: 'bsky', label: 'Bluesky投稿画像', multi: false }); }
    var use = 'post';
    function useDef_() { for (var i = 0; i < USES.length; i++) { if (USES[i].v === use) return USES[i]; } return USES[0]; }
    function load_() {
      if (use === 'ref') return (api.refImgs ? api.refImgs(cid) : []).slice();
      if (use === 'bsky') { var b = api.bskyImg ? api.bskyImg(cid) : ''; return b ? [b] : []; }
      return (api.postImgs(pKey) || []).slice();
    }
    function store_(arr) {
      if (use === 'ref') return api.refImgsSet ? api.refImgsSet(cid, arr) : false;
      if (use === 'bsky') return api.bskyImgSet ? api.bskyImgSet(cid, arr[0] || '') : false;
      return api.postImgSave(pKey, arr);
    }
    var imgs = load_(); // 作業コピー
    var wrap = document.createElement('div'); wrap.className = 'vedit-field vedit-postimg';
    var opts = USES.map(function (u) { return '<option value="' + u.v + '">' + u.label + '</option>'; }).join('');
    wrap.innerHTML =
      '<div class="vedit-postimg-lbl">画像を添付 <span style="font-weight:400;color:var(--sub);font-size:11px;">(用途を選び、コピー中の画像を貼り付け or ファイルから追加。1枚目が投稿履歴に表示)</span></div>' +
      '<div class="vedit-bsky-row" style="margin-bottom:6px;">' +
        '<select id="veditImgUse" style="flex:1;min-width:0;">' + opts + '</select>' +
        '<button id="veditImgPaste" type="button" class="vedit-copy">📋 貼り付け</button>' +
        '<label class="vedit-copy" style="cursor:pointer;margin:0;">＋ 選ぶ<input type="file" accept="image/*" multiple hidden></label>' +
      '</div>' +
      '<div class="vedit-postimg-grid"></div>' +
      '<div class="vedit-postimg-msg hint" style="min-height:0;margin:2px 0 0;"></div>';
    var actions = modal.querySelector('.vedit-actions');
    if (actions) modal.insertBefore(wrap, actions); else modal.appendChild(wrap);
    var grid = wrap.querySelector('.vedit-postimg-grid');
    var fileInp = wrap.querySelector('input[type=file]');
    var useSel = wrap.querySelector('#veditImgUse');
    var msg = wrap.querySelector('.vedit-postimg-msg');
    function persist() { store_(imgs); try { render(); } catch (e) {} } // 即保存＋カード再描画(画像変更なのでrender=クリック再取得を伴わない)
    function draw() {
      grid.innerHTML = '';
      if (!imgs.length) { grid.innerHTML = '<div class="hint" style="padding:6px 2px;">まだありません。「📋 貼り付け」か「＋ 選ぶ」で追加してください。</div>'; return; }
      imgs.forEach(function (src, i) {
        var cell = document.createElement('div'); cell.className = 'vedit-postimg-cell';
        cell.innerHTML = '<img src="' + esc(src) + '" alt="画像' + (i + 1) + '" loading="lazy">' +
          (i === 0 ? '<span class="vedit-postimg-first">1枚目</span>' : '') +
          '<button type="button" class="vedit-postimg-del" title="この画像を削除">✕</button>';
        grid.appendChild(cell);
        cell.querySelector('img').addEventListener('click', function () { if (api.zoomImages) api.zoomImages(imgs, i); });
        cell.querySelector('.vedit-postimg-del').addEventListener('click', function () { imgs.splice(i, 1); persist(); draw(); });
      });
    }
    function addUrls_(urls) {
      urls = (urls || []).filter(Boolean); if (!urls.length) return;
      if (useDef_().multi) { urls.forEach(function (u) { imgs.push(u); }); }
      else { imgs = [urls[urls.length - 1]]; } // 単発用途(Bluesky)は最後の1枚に差し替え
      persist(); draw();
    }
    useSel.addEventListener('change', function () { use = this.value; imgs = load_(); msg.textContent = ''; draw(); });
    wrap.querySelector('#veditImgPaste').addEventListener('click', function () {
      if (!api.pasteImage) { msg.textContent = 'この環境では貼り付けに未対応です(「＋ 選ぶ」をお使いください)'; return; }
      msg.textContent = '貼り付け中…';
      api.pasteImage(function (durl, err) {
        if (durl) { msg.textContent = ''; addUrls_([durl]); }
        else { msg.textContent = err || '画像を貼り付けできませんでした'; setTimeout(function () { if (msg) msg.textContent = ''; }, 2400); }
      });
    });
    fileInp.addEventListener('change', function () {
      var files = Array.prototype.slice.call(fileInp.files || []);
      if (!files.length) return;
      Promise.all(files.map(function (f) {
        return new Promise(function (res) {
          var r = new FileReader();
          r.onload = function () { res(String(r.result || '')); };
          r.onerror = function () { res(''); };
          r.readAsDataURL(f);
        });
      })).then(function (urls) { fileInp.value = ''; addUrls_(urls); }); // 同じ画像を続けて選べるようクリア
    });
    draw();
  }

  // YouTube動画を手動で追加。(モーダルで YouTube URL + Bluesky URL + 作品URL を一括入力)
  function addManual() {
    // 作品URLをアフィリンクタブの②から自動取得(なければ bsky_work_url を使用)
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
    openModal_('YouTube動画を追加', '', '', autoWorkUrl, {}, '旧作', function (ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal) {
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
      applyWorkShort_(entry, workShortVal); // 作品クリック計測URL(導線2)
      saveArr(manualKey(), loadManual().concat([entry]));
      var m = loadYtMap(); m[id] = ytUrl; saveYtMap(m);
      pokeSnapshotNow_(); // 手動追加でもYT URL紐付け当日に日別記録のベースラインを作る(④)
      refresh();
    });
  }

  // クリック数(開封数)・YouTube視聴回数/投稿日時/題名をAPIから取得しキャッシュへ。Promiseを返す。
  function fetchData_(items, ymap, force) { // force=true(手動🔄更新)のときだけTTLを無視して取り直す
    // 導線1(shortUrl=YT→投稿)と導線2(workShortUrl=投稿→FANZA)の両計測コードをまとめて照会
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); })
      .concat(items.map(function (it) { return codeOf(it.workShortUrl || ''); }))
      .filter(Boolean).filter(function (v, i, a) { return a.indexOf(v) === i; });
    var vids = items.map(function (it) { var k = itemKey(it); return ytIdOf(ymap[k] || it.ytUrl || ''); }).filter(Boolean);
    var uniqVids = vids.filter(function (v, i, a) { return a.indexOf(v) === i; }); // 重複動画IDは1回だけ照会
    if (!codes.length && !uniqVids.length) return Promise.resolve(false);
    var jobs = [];
    // クリック数は全コードまとめて1リクエスト(/api/list)。旧: コード毎に /api/stats=N本(無料枠を焼く原因)
    if (codes.length) jobs.push(fetchAllClicks_(!!force));
    // D1: YouTube照会は videos.list の上限(50件/回)に合わせて50件ずつ分割。件数が増えても全行を取得する
    //   。(旧実装は先頭50件で silent 打ち切り＝古い投稿/末尾の手動追加から更新が止まっていた)
    //   予約公開判定は「照会したのに応答に無い」を用いるため、queried は全バッチ合算してから一度だけ判定する。
    var merged = {}, allQueried = [], firstErr = '';
    for (var bi = 0; bi < uniqVids.length; bi += 50) {
      (function (batch) {
        jobs.push(fetchVideos(batch).catch(function () { return { __error: 'YouTube APIに接続できませんでした(通信エラー)' }; }).then(function (m) {
          if (m.__error && !firstErr) firstErr = m.__error;
          if (m.__queried) allQueried = allQueried.concat(m.__queried);
          Object.keys(m).forEach(function (id) {
            if (id.indexOf('__') === 0) return; // __error/__queried 等のメタキーは除外
            var rec = m[id] || {};
            if (rec.views != null) viewsCache[id] = rec.views;
            if (rec.published != null) publishedCache[id] = rec.published;
            if (rec.title) titleCache[id] = rec.title;
            merged[id] = rec;
          });
        }));
      })(uniqVids.slice(bi, bi + 50));
    }
    return Promise.all(jobs).then(function () {
      if (uniqVids.length) {
        lastErr = firstErr;
        ytMetaPersist(merged); // 永続化(リロードで消えない)
        updateYtScheduled_(items, ymap, merged, allQueried); // 公開前(非公開/予約公開)の作品を予約タブ用に抽出
      }
      clicksPersist_();
      try { captureSnaps_(); } catch (e) {}
      return true;
    });
  }

  // ── 公開前(非公開/予約公開)のYouTube作品を抽出し、予約タブ用に保存する ──
  //   APIキーでは予約公開中の動画は videos.list に返らない。よって「照会したのに応答に無い」
  //   かつ「一度も公開として観測していない(publishedCache に無い)」＝公開前 と判定する。
  function ytSchedKey_(acc) { return 'yt_scheduled__' + acc; }
  function loadYtSched_(acc) { try { return JSON.parse(localStorage.getItem(ytSchedKey_(acc)) || '[]') || []; } catch (e) { return []; } }
  function updateYtScheduled_(items, ymap, m, queried) {
    if (!apiKey() || lastErr) return; // キー無し/APIエラー時は誤検知するので更新しない
    var acc = (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1');
    var qset = {}; (queried || []).forEach(function (id) { qset[id] = true; });
    var seen = {}; var out = [];
    items.forEach(function (it) {
      var k = itemKey(it); var url = ymap[k] || it.ytUrl || ''; var vid = ytIdOf(url);
      if (!vid || !qset[vid] || seen[vid]) return; // 照会していないID(>50件時)は判定対象外＝誤検知防止
      var rec = m[vid];
      var returned = !!rec;
      var futureMs = (rec && rec.publishAt && rec.publishAt > Date.now()) ? rec.publishAt
                   : (rec && rec.published && rec.published > Date.now()) ? rec.published : null;
      // 公開前＝(応答に無い かつ 過去に公開として観測していない) もしくは (公開予定時刻が未来)
      var pre = (!returned && !(vid in publishedCache)) || !!futureMs;
      if (!pre) return;
      seen[vid] = true;
      out.push({ vid: vid, ytUrl: url, account: acc, title: (titleCache[vid] || it.title || '(無題)'), publishAt: futureMs, ts: it.ts || 0 });
    });
    try { localStorage.setItem(ytSchedKey_(acc), JSON.stringify(out)); } catch (e) {}
    if (window.Scheduler && window.Scheduler._renderTab) { try { window.Scheduler._renderTab(); } catch (e) {} }
  }
  // 予約タブ(scheduler.js)から参照：両アカウントの公開前YouTube作品をまとめて返す。
  try { window.YtSchedule = { list: function () { return loadYtSched_('acc1').concat(loadYtSched_('acc2')); } }; } catch (e) {}

  // announce=true(手動更新ボタン)のときは、完了時に成功/失敗を明確に表示する。
  function refresh(announce) {
    // 前段(所有権サニタイズ等)のどれかが例外を投げても、保存済みデータが一覧に反映されない
    // (＝保存はできるが表示されない)事態を防ぐため、render() 到達を最優先で保証する。
    var fixed = false;
    try { fixed = sanitizeOwnership_(); } catch (e) {} // ★誤アカウント混入を正へ帰還(ensureIdsより前＝偽の接頭辞を刻む前に所属確定)
    try { flushSheetMovePending_(); } catch (e) {} // 前回失敗したシート行移動を自動再送(T2)
    try { ensureIds(); } catch (e) {} // IDが無いアイテムへ背骨IDを付与(履歴=スプレッドシートの正キー)
    try { reconnectStrandedYt_(); } catch (e) {} // 取り残されたYT URLマップを正しいアカウントへ自己再接続(冪等)
    try { reconcileYtToSheet_(); } catch (e) {} // 端末のYT URLをシートへ後追い反映=「記録待ち」永久固定の自己修復(冪等・台帳ガード)
    render();
    // DID台帳がまだ未解決なら、解決後にもう一度サニタイズ。(postUriアイテムのDID確定分＝混入投稿を自動帰還)冪等。
    (function () {
      var R = window.Go5AccountRepair;
      if (R && R.ensureDids && !(R.ledgerFresh && R.ledgerFresh())) {
        R.ensureDids(function () { var more = sanitizeOwnership_(); if (more) { render(); notifySanitized_(more); } });
      }
    })();
    var note = sanitizeNoteHtml_(fixed); // 更新完了メッセージに付記(サニタイズ通知が上書きで消えない)
    var items = allItems(); var ymap = loadYtMap();
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); }).concat(items.map(function (it) { return codeOf(it.workShortUrl || ''); })).filter(Boolean);
    var vids = items.map(function (it) { var k = itemKey(it); return ytIdOf(ymap[k] || it.ytUrl || ''); }).filter(Boolean);
    if (!codes.length && !vids.length) {
      if (announce) setStatus('更新対象がありません(各行にYouTube URLを入れる／⚙️詳細設定でAPIキー設定が必要です)' + note, !!note);
      else setStatus((apiKey() ? '' : '※YouTube再生数・投稿日時は⚙️詳細設定でAPIキーを設定し、各行にYouTube URLを入れると表示されます') + note, !!note);
      if (fixed) wireSanUndo_();
      return Promise.resolve(false);
    }
    setStatus('🔄 更新中…(再生数・クリック数)');
    return fetchData_(items, ymap, !!announce).then(function () { // 手動更新(announce)のみ強制再取得
      if (lastErr) setStatus('⚠️ 更新に失敗しました：' + lastErr + note, !!note);
      else if (announce) setStatus('✅ 更新しました(再生数・クリック数' + (vids.length ? '・' + vids.length + '本' : '') + ')' + note, !!note);
      else setStatus((!apiKey() && vids.length ? '※再生数・投稿日時の表示には⚙️詳細設定のAPIキーが必要です' : '') + note, !!note);
      render();
      if (fixed) wireSanUndo_();
      return true;
    }).catch(function () { setStatus('⚠️ 更新に失敗しました(通信エラー)', false); return false; });
  }

  // この投稿履歴を正として、全アイテムを記録シート(GAS)へ一括 upsert 同期する。
  // ID・投稿日時(ts)・キャラ属性も送り、シート側で post_id 一致行を更新＋日付降順ソート。
  function syncSheet() {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl) { setStatus('⚠️ 記録用GASのURLが未設定です(⚙️詳細設定で設定してください)'); return; }
    ensureIds();
    var btn = $('ytSyncSheet'); if (btn) btn.disabled = true;
    setStatus('最新の再生数・クリック数を取得中…');
    // まずYouTube題名・視聴回数・開封数を最新取得してから送る。(取れたぶんだけ反映)
    fetchData_(allItems(), loadYtMap()).then(function () { sendSync_(gasUrl, btn); });
  }
  function sendSync_(gasUrl, btn) {
    var ymap = loadYtMap();
    var items = allItems().map(function (it) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      var code = codeOf(it.shortUrl || '');
      // 投稿日時：実投稿時刻(ts)を最優先。無ければYouTube公開日時を使う。(→朝ばかり/今日になる問題を解消)
      var pubMs = (vid && publishedCache[vid] != null) ? publishedCache[vid] : null;
      var postedMs = (it.ts && it.ts > 0) ? it.ts : pubMs;
      var rec = {
        videoId: it.videoId || '',
        title: it.title || '',                                          // 題名(コメント)＝アプリの④コメント
        ytTitle: (vid && titleCache[vid]) || '',                        // YouTube動画の実題名(取得済みのみ)
        views: (vid && viewsCache[vid] != null) ? viewsCache[vid] : '', // YouTube視聴回数(取得済みのみ)
        clicks: (code && clicksCache[code] != null) ? clicksCache[code] : '', // 短縮URLクリック数(取得済みのみ)
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
      if (it.goal) rec.goal = it.goal;          // 狙い(成約/集客)
      if (it.cmtType) rec.cmtType = it.cmtType; // コメント型(①〜⑧)
      return rec;
    }).filter(function (r) { return r.videoId; });
    // T5: 接頭辞が現アカウントと矛盾するアイテム(混入品)は現タブへ同期しない＝シートを汚さない。
    var total0 = items.length;
    items = items.filter(function (r) { var m = String(r.videoId).match(/^(acc[12])-/); return !m || m[1] === acct(); });
    var excluded = total0 - items.length;
    if (!items.length) { setStatus('同期する履歴がありません' + (excluded ? '(別アカウント所属の' + excluded + '件は除外)' : '')); if (btn) btn.disabled = false; return; }
    setStatus('スプレッドシートへ同期中… (' + items.length + '件' + (excluded ? '・別アカウント所属の' + excluded + '件は除外' : '') + ')');
    fetch(gasUrl, { method: 'POST', body: JSON.stringify({ op: 'sync_history', channel: acct(), items: items }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.ok) setStatus('✅ スプレッドシートへ同期しました(' + (j.synced != null ? j.synced : items.length) + '件)');
        else setStatus('⚠️ 同期に失敗しました' + (j && j.error ? '：' + j.error : ''));
      })
      .catch(function () {
        // GASのCORS応答は読めないことがあるが、送信自体は届いている。(記録は実行される)
        setStatus('📤 同期リクエストを送信しました。(' + items.length + '件)数秒後にスプレッドシートをご確認ください。');
      })
      .then(function () { if (btn) btn.disabled = false; });
  }

  // この投稿履歴に無い post_id の行を、記録シート(GAS)から消去する。(このアカウントのタブのみ)
  function pruneSheet() {
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl) { setStatus('⚠️ 記録用GASのURLが未設定です(⚙️詳細設定で設定してください)'); return; }
    ensureIds();
    var keepIds = allItems().map(function (it) { return it.videoId; }).filter(Boolean);
    if (!keepIds.length) { setStatus('掃除の基準になる履歴がありません(先に同期してください)'); return; }
    if (!window.confirm('この投稿履歴に無い行を、スプレッドシートの「' + acct() + '」タブから消去します。\n(記録シートをこの履歴に合わせます。よろしいですか？)')) return;
    var btn = $('ytPruneSheet'); if (btn) btn.disabled = true;
    setStatus('履歴に無い行を掃除中…');
    fetch(gasUrl, { method: 'POST', body: JSON.stringify({ op: 'prune_history', channel: acct(), keepIds: keepIds }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.ok) setStatus('🧹 掃除しました(' + (j.cleared != null ? j.cleared : '?') + '行を消去)');
        else setStatus('⚠️ 掃除に失敗しました' + (j && j.error ? '：' + j.error : ''));
      })
      .catch(function () { setStatus('🧹 掃除リクエストを送信しました。数秒後にスプレッドシートをご確認ください。'); })
      .then(function () { if (btn) btn.disabled = false; });
  }

  // 過去投稿に計測用の短縮リンク(r2+da.gd)を生成する。silent=true で自動実行。(確認・完了ダイアログ無し)
  //   対象＝shortUrlがr2でない or shareUrl無しの履歴。各投稿URL→(必要ならworkerで解決)→r2短縮→da.gd短縮。
  //   1件ごとに保存＝途中で閉じても進んだぶんは残る。(冪等：既にr2済みは対象外)
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
    if (!targets.length) { if (!silent) setStatus('未生成の項目はありません(すべて計測リンク済み)'); return; }
    _bulkBusy = true;
    var btn = $('ytBulkGen'); if (btn) btn.disabled = true;
    var i = 0, done = 0, fail = 0;
    function resolveTarget(it) {
      if (it.postUri && handle) { var rk = String(it.postUri).split('/').pop(); return Promise.resolve('https://bsky.app/profile/' + handle + '/post/' + rk); }
      // ★postUrlはシート復元品では常に空。(historyItems_が返さない)旧行の自己修復のため
      //   shareUrl(da.gd等)や非r2のshortUrlも/api/resolveで最終URLへ解決して再生成の元にする。(2026-07-12)
      var src = it.postUrl || '';
      if (!/^https?:\/\//.test(src)) {
        var cand = it.shareUrl || it.shortUrl || '';
        if (/^https?:\/\//.test(cand) && !(workerUrl && cand.indexOf(workerUrl + '/') === 0)) src = cand; // r2自身は解決しても意味がない(自分に戻る)
      }
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
        setStatus('✅ 計測リンク生成 完了：成功 ' + done + ' / 失敗 ' + fail + '。各行の「Bsky↗」が計測用の短縮URLです。(長押しでコピー→YouTube概要欄に貼り替え)');
        refresh(); // 新しく発行したコードのクリック数も取得(renderだけだと「…」のままになる)
        return;
      }
      var it = targets[i++];
      setStatus('計測リンクを生成中… (' + i + '/' + targets.length + ')');
      resolveTarget(it).then(function (target) {
        if (!target) { fail++; return null; }
        return window.Go5MakeShort(target).then(function (res) {
          if (res && res.shortUrl) {
            it.shortUrl = res.shortUrl; it.shareUrl = res.shareUrl || res.shortUrl; done++;
            saveArr(histKey(), hist); saveArr(manualKey(), manual); // 逐次保存(途中終了に強い)
            pushItemToGas_(it); // シートの短縮URL列も更新→snapshotStatsがクリックを拾い日別🖱が出る(2026-07-12)
          } else fail++;
        });
      }).catch(function () { fail++; }).then(function () { setTimeout(step, 800); });
    }
    step();
  }
  // 投稿履歴を開いたら、未生成の項目があれば自動で計測リンクを生成する。(ボタン任せにしない)
  function maybeAutoGen() { if (!_bulkBusy) runBulkGen(true); }
  // 投稿履歴タブを開いた時にも自動再生成を発火(従来は初期ロード時のみ=タブ遷移で開くと未修復のままだった・2026-07-12)
  (function () { var tb = $('tabVerify'); if (tb) tb.addEventListener('click', function () { setTimeout(function () { maybeAutoGen(); try { fetchDeltas_(); } catch (e) {} }, 1200); }); })();

  // 編集保存の直後に単一アイテムを自動計測化(2026-07-12・根本対策):
  //   入れたリンクがda.gd/生URL等(非r2)でも、最終URL(bsky.app)へ解決→Go5MakeShort(冪等=同URLは同コード)で
  //   計測キーを確定し、シートの短縮URL/共有URL列にも反映する。以後クリック数と日別🖱が表示される。
  function autoMeasureItem_(it, persist) {
    try {
      var go5 = window.Go5Short || {}; var w = (go5.WORKER_URL || '').replace(/\/+$/, ''); var sec = go5.SHARED_SECRET || '';
      function isR2(u) { return !!u && u.indexOf(w + '/') === 0; }
      if (!it || !w || typeof window.Go5MakeShort !== 'function' || isR2(it.shortUrl)) return;
      var handle = ''; try { handle = localStorage.getItem('bsky_handle__' + acct()) || ''; } catch (e) {}
      var srcP;
      if (it.postUri && handle) srcP = Promise.resolve('https://bsky.app/profile/' + handle + '/post/' + String(it.postUri).split('/').pop());
      else {
        var cand = [it.postUrl, it.shareUrl, it.shortUrl].filter(function (u) { return /^https?:\/\//.test(u || '') && !isR2(u); })[0] || '';
        if (!cand) return;
        srcP = /bsky\.app\//.test(cand) ? Promise.resolve(cand)
          : fetch(w + '/api/resolve?url=' + encodeURIComponent(cand) + '&secret=' + encodeURIComponent(sec))
              .then(function (r) { return r.json(); })
              .then(function (j) { return (j && j.ok && /bsky\.app/.test(j.final || '')) ? j.final : ''; })
              .catch(function () { return ''; });
      }
      srcP.then(function (target) {
        if (!target) return;
        return window.Go5MakeShort(target).then(function (res) {
          if (!(res && res.shortUrl && isR2(res.shortUrl))) return;
          it.shortUrl = res.shortUrl; it.shareUrl = res.shareUrl || res.shortUrl;
          if (typeof persist === 'function') persist();
          pushItemToGas_(it); // シートへ反映→snapshotStatsがこのコードのクリックを拾い日別🖱も出始める
          refresh();
        });
      });
    } catch (e) {}
  }

  // ── YouTube URL をシート(記録)から復元 ─────────────────────────────────────
  //   YouTube URLは端末内の verify_yt__<acct> にのみ表示元がある。iOSのストレージ消去等で
  //   これが消えると履歴からYT URLが消える。ただし sync_history でシートの「YouTube動画URL」列に
  //   常にバックアップされているため、そこから読み戻してローカルへ補完する。(手動編集は上書きしない)
  var _ytRestored = {}, _ytRestoreBusy = false;
  var _sheetYtCandidates = []; // 直近のシート照会で得たYT URL(P1: 題名照合の候補に加える)
  function restoreYtFromSheet_(onDone) {
    if (_ytRestoreBusy) { if (onDone) onDone(0); return; }
    var gasUrl = gasUrl_();
    if (!gasUrl) { if (onDone) onDone(0); return; }
    _ytRestoreBusy = true;
    jsonp_(gasUrl, { action: 'history', channel: acct(), limit: 300 }, function (res) {
      _ytRestoreBusy = false;
      if (!res || !res.ok || !Array.isArray(res.items)) { if (onDone) onDone(0); return; }
      _sheetYtCandidates = res.items.map(function (x) { return String((x && x.youtubeUrl) || '').trim(); }).filter(Boolean); // P1候補
      var m = loadYtMap(), restored = 0;
      // 背骨ID(videoId)で現アイテムを引けるように。短縮URL再生成などで postUri/shortUrl 由来の
      // キーがずれても、videoId は不変＝シート行と現アイテムを確実に対応づけられる。
      var hist = loadHist(), man = loadManual();
      var byVid = {};
      hist.concat(man).forEach(function (x) { if (x.videoId && !byVid[x.videoId]) byVid[x.videoId] = x; });
      var histDirty = false, manDirty = false;
      res.items.forEach(function (it) {
        // この行のYT URL候補: ①シートの youtubeUrl ②無ければ端末に残る「迷子のYT URL」
        //   (旧識別子キーで verify_yt に残った分)をシート行の旧識別子から回収する。
        var yt = String((it && it.youtubeUrl) || '').trim();
        var strayKey = ''; // 回収に使った迷子キー(回収成功時に掃除して件数を減らす)
        if (!yt) {
          if (it.postUri && m['u:' + it.postUri]) { yt = m['u:' + it.postUri]; strayKey = 'u:' + it.postUri; }
          else if (it.shortUrl && m['s:' + it.shortUrl]) { yt = m['s:' + it.shortUrl]; strayKey = 's:' + it.shortUrl; }
        }
        if (!yt) return;
        // ローカル項目のキー付けは postUri 優先だが、シート行は postUri か短縮URLの
        // どちらかしか無いことがある。取り違えを防ぐため両方のキーに補完する。(上書きはしない)
        var did = false;
        if (it.postUri) { var ku = 'u:' + it.postUri; if (!m[ku]) { m[ku] = yt; did = true; } }
        if (it.shortUrl) { var ks = 's:' + it.shortUrl; if (!m[ks]) { m[ks] = yt; did = true; } }
        // ★背骨IDで現アイテムへ直結：アイテム自身の ytUrl に書き戻す。(ymap[k] || it.ytUrl の第2経路)
        //   これで今後キーがずれても表示が消えない。既にYT URLが引ける行には書かない。(手動編集を尊重)
        var loc = it.videoId ? byVid[it.videoId] : null;
        if (loc) {
          var curKey = itemKey(loc);
          var curHas = !!ytIdOf(m[curKey] || loc.ytUrl || '');
          if (!curHas) {
            loc.ytUrl = yt; if (loc.manual) manDirty = true; else histDirty = true; did = true;
            // 迷子キーから回収できた場合は掃除(現行キーと同一なら生きているので消さない)
            if (strayKey && strayKey !== curKey && m[strayKey]) delete m[strayKey];
          }
          // ★計測コード(r2短縮URL)もシートから端末へ書き戻す(2026-07-13)：
          //   サーバー側backfillで直した行が端末に届かず「累計🖱が–のまま」になる問題の根治。
          //   端末側が空/非r2で、シート側がr2の時だけ採用。(手動編集や既存r2は上書きしない)
          var sheetShort = String(it.shortUrl || '');
          if (/workers\.dev\//.test(sheetShort) && !/workers\.dev\//.test(String(loc.shortUrl || ''))) {
            loc.shortUrl = sheetShort;
            if (loc.manual) manDirty = true; else histDirty = true; did = true;
          }
        }
        if (did) restored++;
      });
      if (histDirty) saveArr(histKey(), hist);
      if (manDirty) saveArr(manualKey(), man);
      if (restored) { saveYtMap(m); if (typeof render === 'function') render(); }
      if (onDone) onDone(restored);
    });
  }
  // 履歴を開いたとき各アカウント1回だけ自動復元。(端末のYT URLが消えていても静かに戻る)
  function maybeRestoreYt_() {
    var a = acct(); if (_ytRestored[a]) return; _ytRestored[a] = true;
    setTimeout(function () {
      restoreYtFromSheet_(function (n) { if (n > 0) setStatus('☁️ シートからYouTube URLを ' + n + '件 復元しました。'); });
    }, 1200);
  }
  // ── YT URLマップの取り残しを再接続(自己修復)──────────────────────────────
  //   DID矯正等でアイテムだけ別アカウントへ移り、YT URLマップ(verify_yt)が元アカウントに
  //   取り残されると、移動先で再生数/投稿日時/題名が出なくなる。(宵桜艶帖だけ欠落する主因の一つ)
  //   あるアカウントのマップにあるキーの item が実際には別アカウントに居るなら、その別アカウントへ移す。
  //   安全: 「itemが自分側に無く・相手側にあり・相手側マップが未設定」のときだけ移す。(誤上書きしない)冪等。
  function reconnectStrandedYt_() {
    try {
      var accs = ['acc1', 'acc2'];
      var keysByAcc = {}, mapByAcc = {};
      accs.forEach(function (a) {
        var set = {};
        loadArrFor_('short_hist', a).concat(loadArrFor_('verify_manual', a)).forEach(function (it) { set[itemKey(it)] = true; });
        keysByAcc[a] = set; mapByAcc[a] = loadYtMapFor_(a);
      });
      var changed = { acc1: false, acc2: false }, moved = 0;
      accs.forEach(function (a) {
        var other = a === 'acc1' ? 'acc2' : 'acc1';
        Object.keys(mapByAcc[a]).forEach(function (k) {
          if (!keysByAcc[a][k] && keysByAcc[other][k] && mapByAcc[other][k] == null) {
            mapByAcc[other][k] = mapByAcc[a][k]; delete mapByAcc[a][k];
            changed[a] = true; changed[other] = true; moved++;
          }
        });
      });
      if (changed.acc1) saveYtMapFor_('acc1', mapByAcc.acc1);
      if (changed.acc2) saveYtMapFor_('acc2', mapByAcc.acc2);
      return moved;
    } catch (e) { return 0; }
  }
  // ── T1: 所有権サニタイザ(誤アカウントに混入した投稿を、正しいアカウントへ自動帰還)──────
  //   所属判定 ownerOf_: (a) postUriあり かつ DID台帳がこのセッションで解決済み(権威) なら投稿者DIDで確定。
  //     postUriがあるのに台帳未解決なら“動かさない”。(次のrefreshで台帳解決後に判定＝正当な手動移動を誤って戻さない)
  //     どちらのDIDでもない場合も動かさない。 (b) postUri無し＝DID判定不能なら背骨ID接頭辞。(acc1-/acc2-)
  //   移動は「削除でなく別ストアへ移送＋到着先で強キー重複統合＋verify_yt随伴移送」。冪等・ローカルのみ。(シートは🩺/手動の役割)
  function ownerOf_(it) {
    if (!it) return '';
    if (it._ownerPin === 'acc1' || it._ownerPin === 'acc2') return it._ownerPin; // ユーザーが↩️で固定した所属を最優先(自動判定より人の指示が上)
    var R = window.Go5AccountRepair;
    var ledgerOK = !!(R && R.ledgerFresh && R.ledgerFresh() && R.didReady && R.didReady());
    if (it.postUri) {
      if (ledgerOK && R.classifyByPost) return R.classifyByPost(it) || ''; // DIDで確定 or 不明('')
      return ''; // 台帳未解決の postUri アイテムは触らない(安全側)
    }
    var m = String(it.videoId || '').match(/^(acc[12])-/);
    return m ? m[1] : '';
  }
  // 到着先の重複検出：強キー(postUri>videoId)優先。shortUrl はリビルド引継ぎで新旧2件が正当共有するため、
  //   postUri/videoId 両方が無い“薄い”アイテムに限定して照合する。
  function findDup_(arr, it) {
    var i;
    for (i = 0; i < arr.length; i++) {
      if (it.postUri && arr[i].postUri && arr[i].postUri === it.postUri) return i;
      if (it.videoId && arr[i].videoId && arr[i].videoId === it.videoId) return i;
    }
    if (!it.postUri && !it.videoId && it.shortUrl) { for (i = 0; i < arr.length; i++) { if (arr[i].shortUrl === it.shortUrl) return i; } }
    return -1;
  }
  function sanitizeOwnership_() { // 冪等・O(n)・ローカルのみ
    try {
      var accs = ['acc1', 'acc2'], bases = ['short_hist', 'verify_manual'];
      var store = {}, ymaps = {}, dirty = {}, ydirty = {}, moved = [];
      accs.forEach(function (a) { bases.forEach(function (b) { store[b + '__' + a] = loadArrFor_(b, a); }); ymaps[a] = loadYtMapFor_(a); });
      accs.forEach(function (from) {
        bases.forEach(function (base) {
          var src = store[base + '__' + from], keep = [];
          src.forEach(function (it) {
            var owner = ownerOf_(it);
            if (!owner || owner === from) { keep.push(it); return; }
            // リビルド系譜の分断防止：リビルド相手が同ストアに居て所有者不明ならペアごと保留(🩺へ委譲)
            if (it.rebuildOf && src.some(function (x) { return x.videoId === it.rebuildOf && !ownerOf_(x); })) { keep.push(it); return; }
            var dstBase = it.manual ? 'verify_manual' : base;
            var dst = store[dstBase + '__' + owner];
            var di = findDup_(dst, it);
            if (di >= 0) { // 既存を正とし欠損フィールドのみ補完(薄い復元行×実データの統合)
              var x = dst[di], fs = ['title', 'shortUrl', 'shareUrl', 'postUrl', 'postUri', 'videoId', 'workUrl', 'cid', 'workState', 'ytUrl'];
              for (var fi = 0; fi < fs.length; fi++) { if (!x[fs[fi]] && it[fs[fi]]) x[fs[fi]] = it[fs[fi]]; }
              if ((!x.ts || x.ts === 0) && it.ts) x.ts = it.ts;
            } else { dst.unshift(it); }
            dirty[dstBase + '__' + owner] = true; dirty[base + '__' + from] = true;
            var k = itemKey(it); // verify_yt 随伴移送(itemKeyは移動不変)
            if (ymaps[from][k] != null) { if (ymaps[owner][k] == null) ymaps[owner][k] = ymaps[from][k]; delete ymaps[from][k]; ydirty[from] = true; ydirty[owner] = true; }
            moved.push({ base: base, dstBase: dstBase, item: it, from: from, to: owner, by: (it.postUri ? 'post' : 'videoId'), at: new Date().getTime() });
          });
          if (keep.length !== src.length) store[base + '__' + from] = keep;
        });
      });
      Object.keys(dirty).forEach(function (kk) { var i = kk.lastIndexOf('__'); saveArrFor_(kk.slice(0, i), kk.slice(i + 2), store[kk]); });
      accs.forEach(function (a) { if (ydirty[a]) saveYtMapFor_(a, ymaps[a]); });
      if (moved.length) { try { localStorage.setItem('sanitize_move_log', JSON.stringify(moved)); } catch (e) {} }
      return moved.length;
    } catch (e) { return 0; }
  }
  // サニタイザの取り消し。(ローカルのみ逆適用。undoLastMoves_はシートへmove_rowを送るため共用しない)
  function undoSanitize_() {
    var log = []; try { log = JSON.parse(localStorage.getItem('sanitize_move_log') || '[]') || []; } catch (e) {}
    if (!log.length) { setStatus('元に戻せる自動移動がありません。'); return; }
    log.slice().reverse().forEach(function (mv) {
      var k = itemKey(mv.item);
      var dst = loadArrFor_(mv.dstBase, mv.to).filter(function (x) { return itemKey(x) !== k; });
      saveArrFor_(mv.dstBase, mv.to, dst);
      var src = loadArrFor_(mv.base, mv.from).filter(function (x) { return itemKey(x) !== k; });
      mv.item._ownerPin = mv.from; // ユーザーの意思＝この所属に固定。以後サニタイザは動かさない
      src.unshift(mv.item); saveArrFor_(mv.base, mv.from, src);
      var ym = loadYtMapFor_(mv.to); if (ym[k] != null) { var yf = loadYtMapFor_(mv.from); if (yf[k] == null) yf[k] = ym[k]; delete ym[k]; saveYtMapFor_(mv.to, ym); saveYtMapFor_(mv.from, yf); }
    });
    try { localStorage.removeItem('sanitize_move_log'); } catch (e) {}
    setStatus('↩️ 自動移動を元に戻しました。'); refresh();
  }
  // サニタイズ結果の通知HTML(更新完了メッセージに付記して上書き消失を防ぐ)＋↩️ボタン配線。
  function sanitizeNoteHtml_(n) {
    return n ? '<br>⚠️ ' + n + '件を正しいアカウントへ移動しました。(投稿者DID／背骨IDで判定) <button type="button" id="ytSanUndo" class="ghost" style="width:auto;font-size:12px;padding:4px 10px;">↩️ 元に戻す</button>' : '';
  }
  function wireSanUndo_() { var ub = $('ytSanUndo'); if (ub) ub.addEventListener('click', undoSanitize_); }
  function notifySanitized_(n) { // 単独通知(DID解決後の後追いサニタイズ用)
    if (!n) return;
    setStatus(sanitizeNoteHtml_(n).replace(/^<br>/, ''), true); wireSanUndo_();
  }
  // ── P1: YouTube実データ(題名・投稿時刻)で迷子のYT URLを行へつなぎ直す ─────────
  //   識別子(postUri/短縮URL/videoId)が何世代ずれていても成立する最後の照合手段。
  //   投稿題名とYouTube題名は「コメント+タグ」で同一生成されるため、正規化題名の一致で対応づく。
  //   同名投稿が複数ある場合は |YouTube公開時刻 − 投稿時刻| が最小(72h以内)のものを採用。
  //   確定分はアイテム本体の ytUrl へ書き戻す。(キー回転の影響を受けない恒久形)
  function restoreByYtData_(cb) {
    if (!apiKey()) { cb({ matched: 0, ambiguous: 0, candidates: 0, reason: 'APIキー未設定' }); return; }
    var m = loadYtMap();
    var hist = loadHist(), man = loadManual();
    var all = hist.concat(man);
    var keyset = {}; all.forEach(function (it) { keyset[itemKey(it)] = 1; });
    // 既にYT URLが引けている動画IDは候補・対象の両方から除外
    var usedVids = {}; all.forEach(function (it) { var v = ytIdOf(m[itemKey(it)] || it.ytUrl || ''); if (v) usedVids[v] = 1; });
    // 候補URL: 現アカウントの迷子マップ ＋ 直近シート照会のYT URL
    var vidToUrl = {};
    function addCand(u) { var v = ytIdOf(u); if (v && !usedVids[v] && !vidToUrl[v]) vidToUrl[v] = u; }
    Object.keys(m).forEach(function (k) { if (!keyset[k]) addCand(m[k]); });
    _sheetYtCandidates.forEach(addCand);
    var vids = Object.keys(vidToUrl);
    if (!vids.length) { cb({ matched: 0, ambiguous: 0, candidates: 0 }); return; }
    // YouTube照会(50件ずつ)→ 題名・公開時刻で照合
    var meta = {}, jobs = [];
    for (var bi = 0; bi < vids.length; bi += 50) {
      (function (batch) {
        jobs.push(fetchVideos(batch).then(function (r) {
          Object.keys(r).forEach(function (id) { if (id.indexOf('__') !== 0) meta[id] = r[id]; });
        }));
      })(vids.slice(bi, bi + 50));
    }
    Promise.all(jobs).then(function () {
      function norm(t) { return stripCommonTags(String(t || '')).replace(/\s+/g, '').trim(); }
      var matched = 0, ambiguous = 0, histDirty = false, manDirty = false;
      // 新しい順で処理(同名投稿が複数ある場合、各行が時刻の近い動画から順に取る)
      all.slice().sort(function (a, b) { return (b.ts || 0) - (a.ts || 0); }).forEach(function (it) {
        if (ytIdOf(m[itemKey(it)] || it.ytUrl || '')) return; // 解決済み
        var nt = norm(it.title); if (!nt) return;
        var hits = vids.filter(function (v) { return !usedVids[v] && meta[v] && meta[v].title && norm(meta[v].title) === nt; });
        if (!hits.length) return;
        if (hits.length > 1) {
          hits.sort(function (a, b) { return Math.abs((meta[a].published || 0) - (it.ts || 0)) - Math.abs((meta[b].published || 0) - (it.ts || 0)); });
          var d = Math.abs((meta[hits[0]].published || 0) - (it.ts || 0));
          if (!it.ts || d > 72 * 3600 * 1000) { ambiguous++; return; } // 時刻で確定できない同名は誤接続しない
          hits = [hits[0]];
        }
        var v = hits[0];
        it.ytUrl = vidToUrl[v] || ('https://www.youtube.com/shorts/' + v);
        usedVids[v] = 1;
        if (it.manual) manDirty = true; else histDirty = true;
        matched++;
      });
      if (histDirty) saveArr(histKey(), hist);
      if (manDirty) saveArr(manualKey(), man);
      cb({ matched: matched, ambiguous: ambiguous, candidates: vids.length });
    });
  }

  // 現状を人が読める形にまとめる。(iPhoneでも状況が分かる診断表示用)
  function diagnoseYt_() {
    var lines = [];
    ['acc1', 'acc2'].forEach(function (a) {
      var items = loadArrFor_('short_hist', a).concat(loadArrFor_('verify_manual', a));
      var map = loadYtMapFor_(a), withYt = 0, vids = {}, keys = {};
      items.forEach(function (it) { var k = itemKey(it); keys[k] = 1; var v = ytIdOf(map[k] || it.ytUrl || ''); if (v) { withYt++; vids[v] = 1; } });
      // 迷子＝マップにあるがitemに紐づかず、かつその動画がどの行にも表示されていないURL。(復元済みは数えない)
      var orphan = Object.keys(map).filter(function (k) { return !keys[k] && !vids[ytIdOf(map[k] || '')]; }).length;
      lines.push(acctName_(a) + '：履歴' + items.length + '件／YT URL付き' + withYt + '件／動画ID' + Object.keys(vids).length + '種／迷子のYT URL ' + orphan + '件');
    });
    lines.push('APIキー：' + (apiKey() ? '設定済' : '未設定') + '／記録GAS：' + (gasUrl_() ? '設定済' : '未設定'));
    return lines.join('<br>');
  }

  // 投稿本文からの当時割引/新作の復元を「1回だけ」自動実行。(フラグ管理・ボタン不要で確実に)
  function maybeRestorePromo_() {
    var FLAG = 'bsky_promo_restored_v1';
    try { if (localStorage.getItem(FLAG)) return; } catch (e) {}
    // 価格(定価)キャッシュが載ってから走らせたいので少し待つ。完了時のみフラグを立てる。(対象0件では立てない)
    setTimeout(function () {
      restorePctFromBsky_(function () { try { localStorage.setItem(FLAG, '1'); } catch (e) {} });
    }, 3500);
  }

  // Bluesky本文から「新作」「◯%オフ」を検出。(半角/全角%・オフ/OFF/割引・半額に対応)
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
  // onDone は実際に処理を走らせたときだけ完了後に呼ぶ。(対象0件のときは呼ばない＝フラグを立てず後で再試行可能に)
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
        if (updated) setStatus('✅ 投稿文から当時の割引/新作を反映：' + updated + '件。(記載なし ' + skipped + '件・両ch)');
        render();
        if (typeof onDone === 'function') onDone();
        return;
      }
      var slice = jobs.slice(i, i + BATCH);
      var q = slice.map(function (j) { return 'uris=' + encodeURIComponent(j.uri); }).join('&');
      setStatus('Blueskyの投稿本文を確認中…(' + Math.min(i, jobs.length) + '/' + jobs.length + ')');
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

  var tab = $('tabVerify'); if (tab) tab.addEventListener('click', function () { refresh(); setTimeout(maybeAutoGen, 400); maybeRestorePromo_(); maybeRestoreYt_(); maybeSmartRepair_(); fetchDeltas_(); });
  var rb = $('ytClickRefresh'); if (rb) rb.addEventListener('click', function () { purgeNegativeFanzaCache(); refresh(true); fetchDeltas_(true); });
  var fd = $('ytFetchDmm'); if (fd) fd.addEventListener('click', refetchFanza_);
  var ab = $('ytAddManual'); if (ab) ab.addEventListener('click', addManual);
  var bg = $('ytBulkGen'); if (bg) bg.addEventListener('click', function () { runBulkGen(false); });
  var sb = $('ytSyncSheet'); if (sb) sb.addEventListener('click', syncSheet);
  var pb = $('ytPruneSheet'); if (pb) pb.addEventListener('click', pruneSheet);
  // 🔧 YT情報を診断・修復：取り残しYT URLマップの再接続＋シートからのYT URL復元＋再取得を一括で行い、
  //   人が読める診断(各アカウントの履歴数/YT URL付き数/動画ID数/孤児数)を表示する。(iPhoneでも状況が分かる)
  var yrl = $('ytRepairLinks');
  if (yrl) yrl.addEventListener('click', function () {
    var moved = reconnectStrandedYt_();
    setStatus('🔧 YT情報を診断・修復中…(シート照合→YouTube題名照合の順で復元します)');
    restoreYtFromSheet_(function (restored) {
      // P1: 識別子で繋がらなかった分を、YouTube実データ(題名・投稿時刻)で照合して行へ書き戻す。
      restoreByYtData_(function (r2) {
        // refresh完了後に診断を表示。(announce=trueだとrefreshの「✅更新しました」が診断を上書きしてしまう)
        refresh().then(function () {
          setStatus('🔧 YT情報 診断・修復<br>取り残しマップ再接続：<b>' + moved + '</b>件／シート照合で復元：<b>' + restored + '</b>件／YouTube題名照合で復元：<b>' + r2.matched + '</b>件'
            + (r2.ambiguous ? '(同名で確定できず ' + r2.ambiguous + '件)' : '') + (r2.reason ? '(' + r2.reason + ')' : '') + '<br>'
            + diagnoseYt_()
            + '<br><span style="color:var(--sub);font-size:.9em;">※<b>迷子のYT URL</b>＝過去に保存したYouTube URLのうち、投稿の目印(短縮URLなど)が変わって行から外れてしまったもの。シートの背骨ID照合→YouTubeの題名・投稿時刻照合の順で自動でつなぎ直します。それでも残った行は、各行の🛠️編集からYouTube URLを入れると確実に戻ります。(今後は行本体に保存されるので迷子になりません)</span>', true);
        });
      });
    });
  });
  // 🩺 アカウント検証・修復：post_uri の DID で「別アカウントに紛れ込んだ履歴/シート行」を正しい側へ移す。
  // 🩺 検出→一覧を見せて確認→適用。(自動では動かさない)適用後は「元に戻す」可能。
  // 🕵 履歴消失の証拠を見る: recordLoss_ が自動採取した証拠を人が読める形で出す。
  //   ★Chamiに「消えた瞬間にF12で採取して」と頼まなくて済むようにするのが目的(受け身→攻め)。
  var le = $('ytLossEvidence');
  if (le) le.addEventListener('click', function () {
    var log = [];
    try { log = JSON.parse(localStorage.getItem('hist_loss_evidence') || '[]') || []; } catch (e) {}
    if (!log.length) { setStatus('🕵 履歴が減った記録はありません。(消失が起きた後にここを見てください)'); return; }
    var html = log.map(function (r, i) {
      return '<b>' + (i + 1) + '. ' + esc(String(r.at || '').replace('T', ' ').slice(0, 19)) + '</b>　' +
        esc(r.key || '') + '：<b style="color:#dc465a;">' + r.before + ' → ' + r.after + '</b> 件' +
        (r.lostIds && r.lostIds.length ? '<br>　消えたID: ' + esc(r.lostIds.join(', ')) : '') +
        (r.by ? '<br>　<span style="opacity:.7;font-size:11px;">呼び出し元: ' + esc(String(r.by).slice(0, 220)) + '</span>' : '');
    }).join('<br><br>');
    setStatus('🕵 履歴消失の証拠(新しい順・最大3件)<br>' + html, true);
    try { console.log('[go5 hist] 履歴消失の証拠', log); } catch (e) {}
  });

  var rp = $('ytRepairAcct');
  if (rp) rp.addEventListener('click', function () {
    setStatus('🩺 投稿の所属アカウントを検証中…(Bluesky投稿者・YouTubeチャンネルで判定)');
    detectAccountMoves_(function (r) {
      if (!r || !r.ok) { setStatus('⚠️ 検証できません：' + ((r && r.reason) || '不明')); return; }
      var strong = r.moves.filter(function (m) { return m.by === 'post' || m.by === 'channel'; });
      if (!strong.length) {
        setStatus('✅ 全て正しいアカウントに記録されています。(移動候補なし)'
          + (r.unknown ? ' ※判定材料が無い ' + r.unknown + '件は各✏️編集で手動移動できます。' : ''));
        return;
      }
      var msg = strong.length + '件が「別アカウントの投稿」と判定されました。移動しますか？\n\n' + movesSummary_(strong, r.ledger) + '\n\n(移動後も「元に戻す」ができます)';
      if (!window.confirm(msg)) { setStatus('移動を中止しました。(内容は変わっていません)'); return; }
      var n = applyMoves_(strong);
      setStatus('✅ ' + n + '件を移動しました。<button type="button" id="ytUndoMoves" class="ghost" style="width:auto;margin-left:8px;font-size:12px;padding:3px 10px;">↩️ 元に戻す</button>', true);
      var ub = $('ytUndoMoves'); if (ub) ub.addEventListener('click', undoLastMoves_);
      render(); maybeRestoreYt_();
    });
  });
  // 📥 シートから投稿履歴を復元。(非破壊)誤って別アカウントへ入った分は現アカウントへ戻す。
  // ★静的HTMLは ?v= でキャッシュ破棄できず、端末に古いHTMLが残るとボタンが出ないことがある。
  //   そのためJS(=?v=で更新される)側で、ボタンが無ければツールバーへ動的生成して確実に出す。
  var rh = $('ytRestoreHist');
  if (!rh) {
    var _bar = document.querySelector('.vlist-actions');
    if (_bar) {
      rh = document.createElement('button');
      rh.id = 'ytRestoreHist'; rh.type = 'button'; rh.className = 'ghost'; rh.textContent = '📥 シートから投稿履歴を復元';
      var _anchor = $('ytRepairAcct');
      if (_anchor && _anchor.parentNode === _bar) _bar.insertBefore(rh, _anchor.nextSibling); else _bar.appendChild(rh);
    }
  }
  if (rh) rh.addEventListener('click', function () {
    if (!window.confirm(acctName_(acct()) + ' の投稿履歴を、記録スプレッドシートから復元します。\n・別アカウントへ誤って入った投稿を ' + acctName_(acct()) + ' へ戻します\n・端末に無い投稿はシートから復活します\n(既にある投稿は消しません)\nよろしいですか？')) return;
    setStatus('📥 シートから投稿履歴を復元中…');
    restoreHistoryFromSheet_(function (r) {
      if (!r || !r.ok) { setStatus('⚠️ 復元できません：' + ((r && r.reason) || '不明')); return; }
      if (r.added || r.movedBack) {
        var restoreMsg = '✅ 復元しました：戻した投稿 ' + r.movedBack + '件／シートから復活 ' + r.added + '件。(シート ' + r.total + '件を照合)';
        setStatus(restoreMsg); render(); maybeRestoreYt_();
        // 復元だけではYouTube再生数・公開日時は取得されない(別途fetch要)ため、続けて自動更新する。
        refresh().then(function () { setStatus(restoreMsg + '(再生数・投稿日時も更新しました)'); });
      }
      else setStatus('✅ ' + acctName_(acct()) + ' の投稿履歴は既にシートと一致しています。(復元不要)');
    });
  });
  // 履歴を開いたときは「検出のみ」。(自動移動は廃止＝INC-64の教訓)候補があれば件数を知らせる。
  var _smartAutoDone = false;
  function maybeSmartRepair_() {
    if (_smartAutoDone) return; _smartAutoDone = true;
    setTimeout(function () {
      detectAccountMoves_(function (r) {
        if (!r || !r.ok) return; // 検出できない時は黙る(🩺を押せば理由が出る)
        var strong = r.moves.filter(function (m) { return m.by === 'post' || m.by === 'channel'; });
        if (strong.length) setStatus('⚠️ ' + strong.length + '件が別アカウントの投稿の可能性があります。「🩺 アカウント検証・修復」で内容を確認してください。(自動では動かしません)');
      });
    }, 2000);
  }
  // アカウント切替：投稿履歴を表示中なら再生数・クリック数も取得。(renderだけだと「…」のままになる)
  document.addEventListener('account-changed', function () { var pv = $('pageVerify'); if (pv && !pv.hidden) { refresh(); maybeRestoreYt_(); } else render(); });
  // 読み込み時点で既に投稿履歴タブを開いている場合も、取得＋自動生成＋当時割引/YT URLの復元／アカウント整理。(各1回)
  setTimeout(function () { var pv = $('pageVerify'); if (pv && !pv.hidden) { refresh(); maybeAutoGen(); maybeRestorePromo_(); maybeRestoreYt_(); maybeSmartRepair_(); fetchDeltas_(); } }, 2500);

  // 詳細設定タブの YouTube APIキー入力：端末内に保存・復元。(秘密扱い)
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
  // キャッシュのスキーマ版。取得内容の意味が変わったら上げる＝旧キャッシュを一度だけ強制再取得。
  //   sv=2: サークル名(author)を iteminfo.maker から取るよう修正(旧版はauthor空のまま固定されるため)
  var FZ_SV = 2;
  function fanzaNameCacheLoad() {
    try { return JSON.parse(localStorage.getItem('fanza_title_cache') || '{}'); } catch (e) { return {}; }
  }
  function fanzaNameCacheSave(c) {
    try { localStorage.setItem('fanza_title_cache', JSON.stringify(c)); } catch (e) {}
  }
  // 既存キャッシュから「ログイン/エラーページ等の“中身のある不正タイトル”」だけを一掃する。
  // ★空タイトル('')は消さない：negativeキャッシュ(30分)とpartial(画像のみ・1日)は正規の
  //   キャッシュ。以前ここで空も消していたため、失敗/画像のみ作品はタブを開くたび全件再取得
  //   になり「速くならない」原因になっていた(isBadFanzaTitle('')===true の巻き添え)。
  function purgeBadFanzaCache() {
    var c = fanzaNameCacheLoad();
    var changed = false;
    Object.keys(c).forEach(function (url) {
      if (!c[url]) { delete c[url]; changed = true; return; }
      var t = c[url].title;
      if (t && isBadFanzaTitle(t)) { delete c[url]; changed = true; } // 中身のある不正タイトルのみ削除
    });
    if (changed) fanzaNameCacheSave(c);
  }
  // ── 手動入力の作品情報(API未収録作品用)────────────────────────────────
  // 作品URL→{title,listPrice,price,releaseDate,genres[],updatedAt}。自動取得より常に優先。
  // 秘密キーではないので端末間クラウド同期(settings-io)にも自動で乗る。
  function fanzaManualLoad() { try { return JSON.parse(localStorage.getItem('fanza_manual_info') || '{}') || {}; } catch (e) { return {}; } }
  function fanzaManualSaveAll(m) { try { localStorage.setItem('fanza_manual_info', JSON.stringify(m)); } catch (e) {} }
  function fanzaManualOf_(url) { var m = fanzaManualLoad(); return (url && m[url]) || null; }
  // 手動価格を priceInfo 形式にマージ。(手動値があれば上書き。割引率は自動計算)
  function mergeManualPrice_(url, priceInfo) {
    var man = fanzaManualOf_(url);
    if (!man) return priceInfo;
    var base = priceInfo || { price: null, listPrice: null, discountPct: 0, releaseDate: '' };
    var out = { price: base.price, listPrice: base.listPrice, discountPct: base.discountPct || 0, releaseDate: man.releaseDate || base.releaseDate || '' };
    if (man.price != null || man.listPrice != null) {
      out.listPrice = man.listPrice != null ? man.listPrice : null;
      out.price = man.price != null ? man.price : out.listPrice;
      out.discountPct = (out.listPrice && out.price && out.price < out.listPrice) ? Math.round((1 - out.price / out.listPrice) * 100) : 0;
    }
    return out;
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
  // data-fanza-url が一致する現在の DOM 要素を全て更新(DOM 再描画後も正しく反映される)
  function setFanzaEls(fanzaUrl, title) {
    var man = fanzaManualOf_(fanzaUrl);
    if (man && man.title) title = man.title; // 手動入力の作品名が最優先
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
  // 作品状態バッジのHTML。(新作=緑 / 準新作=青緑 / 旧作=セピア)空/未指定は旧作扱い。
  function stateBadgeHtml_(ws) {
    var s = ws || '旧作';
    var cls = s === '新作' ? 'fp-state-new' : (s === '準新作' ? 'fp-state-semi' : 'fp-state-old');
    return '<span class="fp-state ' + cls + '">' + esc(s) + '</span>';
  }
  function yen_(n) { return '¥' + Number(n).toLocaleString('ja-JP'); }
  // 現在価格のHTML。セール時は「現定価/セール価格/○%off」、セール無しは「現定価」を通常色で。
  function fmtFanzaPriceHtml(p) {
    if (!p || p.price == null) return '';
    if (p.listPrice != null && p.discountPct > 0 && p.listPrice > p.price) {
      return '現定価:<span class="fp-list">' + yen_(p.listPrice) + '</span>' +
             ' <span class="fp-sale-lbl">セール価格:</span><span class="fp-sale">' + yen_(p.price) + '</span>' +
             ' <span class="fp-off">' + p.discountPct + '%off</span>';
    }
    return '現定価:<span class="fp-cur">' + yen_(p.price) + '</span>';
  }
  // 投稿時(当時)価格のHTML。全体を作品名と同じ淡色で表示。%offは現在と同様に枠で囲む。
  function fmtSnapPriceHtml(p) {
    if (!p || p.price == null) return '';
    if (p.listPrice != null && p.discountPct > 0 && p.listPrice > p.price) {
      return '定価:<span class="fp-snap-list">' + yen_(p.listPrice) + '</span> セール価格:' + yen_(p.price) + ' <span class="fp-snap-off">' + p.discountPct + '%off</span>';
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
  // data-fanza-author-url が一致する要素へサークル名(作者名)を反映。手動入力が最優先。
  function setFanzaAuthorEls(fanzaUrl, author) {
    var man = fanzaManualOf_(fanzaUrl);
    if (man && man.author) author = man.author;
    // サークル名の前にサークルマーク(候補タブと同じグレーの人物シルエット)を付ける。(Chami依頼2026-07-14「全部のタブに」)
    var ico = (typeof window.Go5CircleIcon === 'string') ? window.Go5CircleIcon : '';
    document.querySelectorAll('[data-fanza-author-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-author-url') !== fanzaUrl) return;
      el.innerHTML = author ? (ico + ' ' + esc(author)) : '';
    });
  }

  // 手動入力済みの作品情報を、描画直後に即時反映する。(フェッチ完了を待たず表示が遅れない)
  function applyManualInfoNow_() {
    var m = fanzaManualLoad();
    Object.keys(m).forEach(function (u) {
      setFanzaEls(u, '');        // 手動タイトルがあれば表示
      setFanzaPriceEls(u, null); // 手動価格/発売日があれば表示
      setFanzaAuthorEls(u, '');  // 手動サークル名があれば表示
    });
  }

  // data-fanza-thumb-url が一致するサムネ<img>へ画像を設定して表示。
  // src＝メイン画像。(モーダルと同じ・存在確認済みの大きい方)altSrc＝読込失敗時の代替。両方ダメなら非表示。
  function setFanzaThumbEls(fanzaUrl, src, altSrc) {
    if (!src && altSrc) { src = altSrc; altSrc = ''; }
    if (!src) return;
    document.querySelectorAll('img[data-fanza-thumb-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-thumb-url') !== fanzaUrl) return;
      el.onerror = function () {
        if (altSrc && el.getAttribute('src') !== altSrc) el.setAttribute('src', altSrc);
        else el.style.display = 'none';
      };
      if (el.getAttribute('src') !== src) el.setAttribute('src', src);
      el.style.display = '';
    });
  }

  // 作品詳細モーダル。(サムネクリックで開く)キャッシュから作品名/画像/ジャンル/発売日/サービスを表示。
  function openFanzaModal_(fanzaUrl) {
    var cache = fanzaNameCacheLoad();
    var c = cache[fanzaUrl] || {};
    var man = fanzaManualOf_(fanzaUrl) || {};
    var media = c.media || {}, pinfo = c.priceInfo || {};
    var title = man.title || c.title || (c.partial ? '(作品名を取得できません・アフィリエイトAPI未収録の作品)' : '(無題)');
    var big = media.thumb || media.thumbSmall || '';
    var samples = media.samples || [];
    var genres = (man.genres && man.genres.length) ? man.genres : (media.genres || []);
    var date = man.releaseDate || pinfo.releaseDate || '';
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
    // 画像ギャラリー：作品画像(先頭)＋サンプル画像。クリックでズームビューア。(スワイプ切替)
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
        '<div class="fz-meta"><span class="fz-lbl">サークル</span>' + esc((man.author || c.author || '') || '—') + '</div>' +
        '<div class="fz-meta"><span class="fz-lbl">発売日</span>' + esc(date ? String(date).slice(0, 10) : '—') + '</div>' +
        '<div class="fz-meta"><span class="fz-lbl">サービス/フロア</span>' + esc(svc || '—') + '</div>' +
      '</div>' +
      '<div class="fz-foot"><button type="button" class="fz-edit-btn">✏️ 作品情報を手動入力</button><a class="fz-open" href="' + esc(fanzaUrl) + '" target="_blank" rel="noopener">作品ページを開く ↗</a></div>';
    body.querySelectorAll('.fz-zoomable').forEach(function (im) {
      im.addEventListener('click', function () { openZoom_(_fzGallery, parseInt(im.getAttribute('data-zoom'), 10) || 0); });
    });
    var eb = body.querySelector('.fz-edit-btn');
    if (eb) eb.addEventListener('click', function () { openFanzaEdit_(fanzaUrl); });
    ov.hidden = false;
  }
  function closeFanzaModal_() { var ov = $('fzOverlay'); if (ov) ov.hidden = true; }

  // ── 作品情報の手動入力モーダル(詳細モーダルからさらに開く)────────────────
  // API未収録・取得不能な作品でも、作品名/定価/セール価格/発売日/ジャンルを手入力して表示できる。
  function openFanzaEdit_(fanzaUrl) {
    var ov = $('fzEditOverlay');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'fzEditOverlay';
      ov.className = 'fz-overlay';
      ov.hidden = true;
      ov.innerHTML =
        '<div class="fz-modal">' +
          '<button class="fz-close" type="button" aria-label="閉じる">✕</button>' +
          '<div class="fz-title">✏️ 作品情報を手動入力</div>' +
          '<div class="hint" style="margin:0 0 10px;">自動取得できない作品(API未収録等)向け。入力した値は<b>自動取得より優先</b>して表示されます。<br>全て空にして保存すると手動入力を解除。(自動取得に戻る)</div>' +
          '<label class="vedit-field">作品名<input id="fzeTitle" type="text" autocomplete="off" placeholder="作品の正式タイトル"></label>' +
          '<label class="vedit-field">サークル名(作者名)<input id="fzeAuthor" type="text" autocomplete="off" placeholder="サークル名"></label>' +
          '<div style="display:flex;gap:10px;">' +
            '<label class="vedit-field" style="flex:1;">定価(円)<input id="fzeList" type="text" inputmode="numeric" autocomplete="off" placeholder="1320"></label>' +
            '<label class="vedit-field" style="flex:1;">セール価格(円・無ければ空)<input id="fzePrice" type="text" inputmode="numeric" autocomplete="off" placeholder="924"></label>' +
          '</div>' +
          '<label class="vedit-field">発売日(作品状態の自動判定に使用)<input id="fzeDate" type="date"></label>' +
          '<label class="vedit-field">ジャンル(カンマ区切り・任意)<input id="fzeGenres" type="text" autocomplete="off" placeholder="巨乳, 中出し, 学園もの"></label>' +
          '<div class="vedit-actions"><div class="vedit-actions-main">' +
            '<button id="fzeCancel" type="button">キャンセル</button>' +
            '<button id="fzeSave" type="button">保存</button>' +
          '</div></div>' +
        '</div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) closeFanzaEdit_(); });
      ov.querySelector('.fz-close').addEventListener('click', closeFanzaEdit_);
      $('fzeCancel').addEventListener('click', closeFanzaEdit_);
      $('fzeSave').addEventListener('click', function () {
        var url = ov.getAttribute('data-url');
        if (!url) { closeFanzaEdit_(); return; }
        var t = ($('fzeTitle').value || '').trim();
        var au = ($('fzeAuthor').value || '').trim();
        var lp = parseInt(($('fzeList').value || '').replace(/[^\d]/g, ''), 10); if (isNaN(lp)) lp = null;
        var pr = parseInt(($('fzePrice').value || '').replace(/[^\d]/g, ''), 10); if (isNaN(pr)) pr = null;
        var rd = ($('fzeDate').value || '').trim();
        var gs = ($('fzeGenres').value || '').split(/[、,]/).map(function (s) { return s.trim(); }).filter(Boolean);
        var all = fanzaManualLoad();
        if (!t && !au && lp == null && pr == null && !rd && !gs.length) delete all[url]; // 全空＝解除
        else all[url] = { title: t, author: au, listPrice: lp, price: pr, releaseDate: rd, genres: gs, updatedAt: new Date().toISOString() };
        fanzaManualSaveAll(all);
        // 当時スナップが未保存の投稿には、この価格を当時として固定。(一覧の当時行にも出る)
        var lp2 = lp != null ? lp : pr, pr2 = pr != null ? pr : lp;
        if (pr2 != null) backfillSnap_(url, { price: pr2, listPrice: lp2, discountPct: (lp2 && pr2 && pr2 < lp2) ? Math.round((1 - pr2 / lp2) * 100) : 0 });
        closeFanzaEdit_(); closeFanzaModal_();
        render(); // 一覧へ即反映
        setDmmStatus(t ? '✏️ 手動の作品情報を保存しました：「' + esc(t) + '」' : '✏️ 手動の作品情報を更新しました。');
      });
    }
    // 毎回、既存の手動値→無ければ自動取得値で埋める
    var man = fanzaManualOf_(fanzaUrl) || {};
    var cache = fanzaNameCacheLoad(); var c = cache[fanzaUrl] || {}; var pinfo = c.priceInfo || {};
    $('fzeTitle').value = man.title || c.title || '';
    $('fzeAuthor').value = man.author || c.author || '';
    $('fzeList').value = man.listPrice != null ? man.listPrice : (pinfo.listPrice != null ? pinfo.listPrice : '');
    $('fzePrice').value = man.price != null ? man.price : (pinfo.price != null && pinfo.price !== pinfo.listPrice ? pinfo.price : '');
    $('fzeDate').value = String(man.releaseDate || pinfo.releaseDate || '').slice(0, 10);
    $('fzeGenres').value = (man.genres || []).join(', ');
    ov.setAttribute('data-url', fanzaUrl);
    ov.hidden = false;
    setTimeout(function () { var el = $('fzeTitle'); if (el) el.focus(); }, 50);
  }
  function closeFanzaEdit_() { var ov = $('fzEditOverlay'); if (ov) ov.hidden = true; }

  // 画像ズームビューア。(作品画像＋サンプルを1つのギャラリーとして、左右スワイプで切替。矢印ボタンなし)
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
    if (cnt) cnt.textContent = _zoomImgs.length > 1 ? (_zoomIdx + 1) + ' / ' + _zoomImgs.length + '(左右スワイプ)' : '';
  }
  function zoomGo_(dir) {
    if (_zoomImgs.length < 2) return;
    _zoomIdx = (_zoomIdx + dir + _zoomImgs.length) % _zoomImgs.length;
    renderZoom_();
  }
  function closeZoom_() { var z = $('fzZoom'); if (z) z.hidden = true; }

  // data-fanza-price-url が一致するDOM要素へ価格を反映＋発売日から現在の作品状態バッジを更新。
  // 手動入力の価格・発売日があれば自動取得より優先して表示する。
  function setFanzaPriceEls(fanzaUrl, priceInfo) {
    priceInfo = mergeManualPrice_(fanzaUrl, priceInfo);
    var html = fmtFanzaPriceHtml(priceInfo);
    document.querySelectorAll('[data-fanza-price-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-price-url') !== fanzaUrl) return;
      if (html) { el.innerHTML = html; el.style.display = ''; }
      else { el.innerHTML = ''; el.style.display = 'none'; }
    });
    // 発売日→現在の作品状態。投稿時より「新しい」ときだけ引き上げる。(格下げはしない)
    //   例: 投稿時=旧作/準新作 でも 現在=新作 なら 新作 に合わせる。(準新作も同様)両アカウント共通ロジック。
    var apiState = priceInfo && deriveWorkState_(priceInfo.releaseDate);
    if (apiState) {
      var cr = wsRank_(apiState);
      document.querySelectorAll('[data-fanza-state-url]').forEach(function (el) {
        if (el.getAttribute('data-fanza-state-url') !== fanzaUrl) return;
        if (cr > wsRank_((el.textContent || '').trim())) el.innerHTML = stateBadgeHtml_(apiState); // 引き上げのみ
      });
      reconcileWorkStateUp_(fanzaUrl, apiState); // 保存＋GAS反映(表示中アカウントの該当アイテム)
    }
  }
  // 作品状態の新しさ順位。(新作>準新作>旧作>未設定)
  function wsRank_(s) { return s === '新作' ? 3 : (s === '準新作' ? 2 : (s === '旧作' ? 1 : 0)); }
  // 現在の作品状態が投稿時より新しい該当アイテムの workState を引き上げて保存＋GAS反映。変更があれば再描画。
  var _wsRenderPending = false;
  function reconcileWorkStateUp_(fanzaUrl, currentState) {
    var cr = wsRank_(currentState); if (cr < 1) return;
    var changed = false;
    [['verify_manual', manualKey()], ['short_hist', histKey()]].forEach(function (p) {
      var arr = loadArr(p[1]), mod = false;
      arr.forEach(function (it) {
        if (it.workUrl !== fanzaUrl) return;
        if (wsRank_(it.workState || '旧作') < cr) { it.workState = currentState; mod = true; changed = true; if (it.videoId) pushItemToGas_(it); }
      });
      if (mod) saveArr(p[1], arr);
    });
    if (changed && !_wsRenderPending) { _wsRenderPending = true; setTimeout(function () { _wsRenderPending = false; render(); }, 1500); }
  }

  // ── FANZA取得の実行管理(世代トークン方式)──────────────────────────────
  // 旧実装は「実行中フラグ(_fanzaBusy)が立っている間、手動ボタンは一言出して黙って戻る」だった。
  // タブを開いた直後は“無表示の自動取得”が数十秒動いているため、その間にボタンを押すと
  // 表示が一向に変わらない＝根本原因。さらに処理チェーンが例外で死ぬとフラグが立ったまま永久停止。
  // 対策：
  //   ・手動実行は進行中の実行を「乗っ取る」(世代番号++。旧実行は次stepで世代不一致を見て静かに停止)
  //   ・自動実行だけ進行中なら遠慮する(ただし60秒進捗が無い実行は死んだとみなして開始＝スタック自動復帰)
  //   ・ボタンは絶対に無視されない：押せば必ず進捗表示つきで最初から取得が始まる
  var _fanzaGen = 0;        // 現在有効な実行の世代(新実行開始で++)
  var _fanzaActive = false; // 実行中フラグ(自動実行の遠慮判定用)
  var _fanzaTick = 0;       // 最終進捗時刻(watchdog：古いままなら実行は死んでいる)
  var _fanzaManual = false; // 現行世代が手動実行か(自動が手動を引き継ぐとき進捗表示も引き継ぐ)
  // manual=true(DMM作品情報取得ボタン)のときは進捗と完了/失敗をステータスへ表示する。
  // sweepDepth: 完了後の追い掛けスイープの深さ。(1段まで。キャッシュ保存不能な環境での無限ループ防止)
  function fillFanzaNames(manual, sweepDepth) {
    var targets = document.querySelectorAll('[data-fanza-url]');
    if (!targets.length) { if (manual) setDmmStatus('作品URLのある投稿がありません。'); return; }
    if (typeof window.FanzaCore === 'undefined' || typeof window.buildAffiliateLink === 'undefined') { if (manual) setDmmStatus('⚠️ FANZAモジュール未読込。少し待って再度お試しください。'); return; }
    var workerUrl = '';
    var sharedSecret = '';
    try { workerUrl = localStorage.getItem('fanza_worker_url') || ''; } catch (e) {}
    try { sharedSecret = localStorage.getItem('fanza_shared_secret') || ''; } catch (e) {}
    if (!workerUrl) { if (manual) setDmmStatus('⚠️ FANZAワーカーURLが未設定です。(⚙️詳細設定で設定してください)'); return; }
    purgeBadFanzaCache(); // 旧版で混入したログイン/エラータイトルを先に掃除
    var cache = fanzaNameCacheLoad();
    var now = new Date().getTime();
    var DAY = 86400000, NEG = 30 * 60000; // 題名キャッシュ=1日 / 「未取得(空)」キャッシュ=30分(瞬断からの復帰を速く)
    var jobs = [], seen = {};
    // 失敗表示用：作品URL→投稿(YouTube)の題名。どの投稿の取得が失敗したか明示するのに使う。
    // 手動追加アイテムは it.title が空のことがあるため、YouTube実題名(titleCache)でフォールバック。
    var titleByUrl = {};
    try {
      var ymapT = loadYtMap();
      allItems().forEach(function (it) {
        if (!it.workUrl) return;
        var t = it.title || '';
        if (!t) { var vid = ytIdOf(ymapT[itemKey(it)] || it.ytUrl || ''); t = (vid && titleCache[vid]) || ''; }
        if (!titleByUrl[it.workUrl] && t) titleByUrl[it.workUrl] = t;
      });
    } catch (e) {}
    targets.forEach(function (nameEl) {
      var url = nameEl.getAttribute('data-fanza-url');
      if (!url) return;
      var cached = cache[url];
      var displayed = false; // 既に何か表示したか(「…」で潰さない判定)
      if (cached) {
        var age = now - (cached.fetchedAt || 0);
        var freshFull = cached.title && !isBadFanzaTitle(cached.title) && age < DAY && cached.priceInfo && ('releaseDate' in cached.priceInfo) && cached.media && cached.sv === FZ_SV;
        var freshPartial = cached.partial && cached.media && cached.sv === FZ_SV && age < DAY;
        // ★stale-while-revalidate：古い/旧スキーマのキャッシュでも「まず即表示」して待たせない。
        //   新鮮ならここで確定。古ければ表示は残したまま下のjobsに積んで裏で静かに最新化する。
        if (cached.title && !isBadFanzaTitle(cached.title)) {
          setFanzaEls(url, cached.title); setFanzaAuthorEls(url, cached.author || '');
          if (cached.priceInfo) { setFanzaPriceEls(url, cached.priceInfo); if (freshFull) backfillSnap_(url, cached.priceInfo); } // 当時価格の固定は新鮮な価格のときだけ(古い価格を投稿時価格にしない)
          if (cached.media) setFanzaThumbEls(url, cached.media.thumb || cached.media.thumbSmall, cached.media.thumbSmall);
          displayed = true;
          if (freshFull) return;
        } else if (cached.partial && cached.media) {
          // 画像のみの部分情報(API未収録作品)：サムネ＋手動入力の作品名/価格を表示
          setFanzaEls(url, ''); setFanzaPriceEls(url, null); setFanzaAuthorEls(url, cached.author || '');
          setFanzaThumbEls(url, cached.media.thumb || cached.media.thumbSmall, cached.media.thumbSmall);
          displayed = true;
          if (freshPartial) return;
        } else if (!cached.title && !cached.partial && age < NEG) {
          setFanzaEls(url, ''); setFanzaPriceEls(url, null); setFanzaAuthorEls(url, ''); return; // 直近「未取得」→再取得しない(手動入力があれば表示)
        }
      }
      var res = window.buildAffiliateLink(url, '');
      if (!res || !res.ok || !res.cid) return;
      if (seen[url]) return; seen[url] = true;
      // prev＝表示中の旧キャッシュ。裏取得が失敗/降格しても旧内容を消さないための保険。(SWR)
      jobs.push({ url: url, cid: res.cid, el: nameEl, title: titleByUrl[url] || '', prev: cached || null });
      // 手動タイトル/旧キャッシュ表示がある場合は「…」で潰さない(見た目は即・裏で最新化)
      var manJ = fanzaManualOf_(url);
      if (manJ && manJ.title) { nameEl.textContent = manJ.title; nameEl.style.display = ''; }
      else if (!displayed) { nameEl.textContent = '…'; nameEl.style.display = ''; }
    });
    if (!jobs.length) { if (manual) setDmmStatus('✅ 作品情報は取得済みです。(再取得の必要はありません)'); return; }
    // 自動実行は、生きている実行が進行中なら遠慮。(重複取得を避ける)60秒進捗が無ければ死亡とみなし開始。
    // 手動実行はここを素通り＝進行中でも乗っ取って必ず開始する。(ボタンが無視されることは無い)
    if (!manual && _fanzaActive && (new Date().getTime() - _fanzaTick) < 60000) return;
    // 手動実行を(停止とみなして)自動が引き継ぐ場合は進捗表示も引き継ぐ＝「取得中…」表示が凍結しない。
    if (!manual && _fanzaActive && _fanzaManual) manual = true;
    // ★取得は3本並列(各系列は350ms間隔)＝直列1本より約3倍速。DMMは実測で30並列でも安定
    //   だが、安全域として3本に抑える。一時的な失敗のみ最大3回リトライ。恒久的失敗は1回で確定。
    var gen = ++_fanzaGen;  // 旧実行を無効化し、この実行が主導権を取る
    _fanzaActive = true; _fanzaTick = new Date().getTime(); _fanzaManual = !!manual;
    var GAP = 350, CONC = 3, next = 0, running = 0, processed = 0;
    var done = 0, fail = 0, partial = 0, total = jobs.length, fails = [], partials = [];
    // カウントダウン：初期見積り＝1件≈0.7秒。(3本並列)各件完了ごとに実測平均で補正しつつ毎秒-1。
    var startT = new Date().getTime(), etaSec = Math.max(1, Math.ceil(total * 0.7)), ticker = null;
    function dmmProgress() { if (manual) setDmmStatus('DMMから作品情報を取得中… (' + processed + '/' + total + ')・<b>終了まであと約 ' + Math.max(etaSec, 0) + ' 秒</b>'); }
    if (manual) {
      dmmProgress();
      ticker = setInterval(function () {
        if (gen !== _fanzaGen) { clearInterval(ticker); return; } // 乗っ取られた旧実行のカウントダウンは停止
        if (etaSec > 0) etaSec--;
        dmmProgress();
      }, 1000);
    }
    function fetchWithRetry(job, tries) {
      if (gen === _fanzaGen) _fanzaTick = new Date().getTime(); // 試行開始＝生存を刻む(長い1件でwatchdogに誤殺されない)
      return window.FanzaCore.fetchFanzaInfo(job.cid, workerUrl, sharedSecret, job.url || '').then(function (info) {
        if (gen !== _fanzaGen) return null; // 乗っ取り後の旧実行はリトライも継続もしない(静かに中止)
        if (info && info.title && !isBadFanzaTitle(info.title)) return info; // 成功
        // 恒久的失敗(作品が見つからない等)はリトライしない＝無駄な待ち時間を作らない。一時的失敗のみ再試行。
        var canRetry = info && info.__error ? !!info.retryable : true;
        if (tries > 0 && canRetry) return new Promise(function (r) { setTimeout(r, 1300); }).then(function () { return (gen === _fanzaGen) ? fetchWithRetry(job, tries - 1) : null; });
        return info || null;
      }).catch(function () {
        if (gen !== _fanzaGen) return null;
        if (tries > 0) return new Promise(function (r) { setTimeout(r, 1300); }).then(function () { return (gen === _fanzaGen) ? fetchWithRetry(job, tries - 1) : null; });
        return null;
      });
    }
    function finish() {
      _fanzaActive = false;
      if (ticker) { clearInterval(ticker); ticker = null; }
      if (manual) {
        var msg = '';
        if (!fails.length && !partials.length) msg = '✅ DMM作品情報を取得しました。(成功 ' + done + ' 件)';
        else {
          msg = 'DMM作品情報：成功 ' + done + (partial ? ' / 画像のみ ' + partial : '') + (fail ? ' / <b>失敗 ' + fail + '</b>' : '');
          if (partials.length) {
            msg += '<br><b>画像のみ取得(API未収録作品)：</b><br>' +
              partials.map(function (p) { return '・「' + esc(p.title || '(無題)') + '」'; }).join('<br>') +
              '<br>　└ サークル設定等でアフィリエイトAPIに収録されておらず、作品名・価格は取得できません。(サムネ/サンプル画像は表示します)';
          }
          if (fails.length) {
            msg += '<br><b>取得に失敗した投稿と原因：</b><br>' +
              fails.map(function (f) { return '・「' + esc(f.title || '(無題)') + '」<br>　└ ' + esc(f.reason); }).join('<br>');
          }
        }
        setDmmStatus(msg);
      }
      // 実行中に描画が変わって取り漏れた分を1段だけ追い掛け。(深さ制限＝キャッシュ保存不能環境でも無限ループしない)
      if ((sweepDepth || 0) < 1) setTimeout(function () { if (gen === _fanzaGen) fillFanzaNames(false, (sweepDepth || 0) + 1); }, 100);
    }
    function pump() {
      if (gen !== _fanzaGen) { if (ticker) clearInterval(ticker); return; } // 新しい実行に乗っ取られた→静かに終了
      _fanzaTick = new Date().getTime(); // watchdog：生存を刻む
      if (next >= jobs.length) {
        running--;
        if (running === 0) finish(); // 全系列が仕事を終えた時だけ完了処理(in-flight分の集計を待つ)
        return;
      }
      var job = jobs[next++];
      dmmProgress();
      fetchWithRetry(job, 2).then(function (info) {
        if (gen !== _fanzaGen) return; // 乗っ取り後の旧実行はキャッシュ・DOM・集計へ一切書かない
        var c = fanzaNameCacheLoad();
        if (info && info.title && !isBadFanzaTitle(info.title)) {
          var pinfo = { price: info.price, listPrice: info.listPrice, discountPct: info.discountPct || 0, releaseDate: info.releaseDate || '' };
          var media = { thumb: info.thumb || '', thumbSmall: info.thumbSmall || info.thumb || '', samples: info.samples || [], genres: info.genres || [], service: info.service || '', floor: info.floor || '' };
          c[job.url] = { title: info.title, author: info.author || '', priceInfo: pinfo, media: media, sv: FZ_SV, fetchedAt: new Date().getTime() };
          fanzaNameCacheSave(c); setFanzaEls(job.url, info.title); setFanzaAuthorEls(job.url, info.author || ''); setFanzaPriceEls(job.url, pinfo); backfillSnap_(job.url, pinfo);
          setFanzaThumbEls(job.url, media.thumb || media.thumbSmall, media.thumbSmall); done++;
        } else if (info && info.partial && (info.thumb || info.thumbSmall)) {
          // 旧キャッシュにフル作品名があるのに今回partialに降格＝APIから一時的に外れただけ。
          // 旧フル情報を維持(表示・キャッシュとも触らない)＝作品名が無言で消えるのを防ぐ。
          if (job.prev && job.prev.title && !isBadFanzaTitle(job.prev.title)) { done++; }
          else {
            // 画像のみの部分情報(API未収録＋ページ取得不能の作品)：サムネ・サンプルだけ保存/表示。
            var mediaP = { thumb: info.thumb || '', thumbSmall: info.thumbSmall || info.thumb || '', samples: info.samples || [], genres: [], service: info.service || '', floor: info.floor || '' };
            c[job.url] = { title: '', author: '', partial: true, priceInfo: null, media: mediaP, sv: FZ_SV, fetchedAt: new Date().getTime() };
            fanzaNameCacheSave(c); setFanzaEls(job.url, ''); setFanzaPriceEls(job.url, null); setFanzaAuthorEls(job.url, '');
            setFanzaThumbEls(job.url, mediaP.thumb || mediaP.thumbSmall, mediaP.thumbSmall); partial++;
            if (manual) partials.push({ title: job.title });
          }
        } else if (job.prev && (job.prev.title || job.prev.partial)) {
          // 取得失敗だが表示中の旧データがある＝旧内容を維持。(SWR：失敗時はstale保持)DOM/キャッシュとも触らない。
          done++;
        } else {
          c[job.url] = { title: '', priceInfo: null, media: null, fetchedAt: new Date().getTime() }; // 未取得は30分だけキャッシュ(再ハンマー防止＆早期復帰)
          fanzaNameCacheSave(c); setFanzaEls(job.url, ''); setFanzaPriceEls(job.url, null); fail++;
          if (manual) fails.push({ title: job.title, reason: (info && info.__error && info.reason) ? info.reason : '作品が見つかりません' });
        }
      }).catch(function () {
        if (gen !== _fanzaGen) return;
        // 表示中の旧データがあれば維持。(通信エラーで作品名を消さない)
        if (job.prev && (job.prev.title || job.prev.partial)) { done++; return; }
        // 旧データが無い場合のみネガティブキャッシュを書く。(追い掛けスイープの再実行を止めるため)
        var c2 = fanzaNameCacheLoad();
        c2[job.url] = { title: '', priceInfo: null, media: null, fetchedAt: new Date().getTime() };
        fanzaNameCacheSave(c2);
        setFanzaEls(job.url, ''); setFanzaPriceEls(job.url, null); fail++;
        if (manual) fails.push({ title: job.title, reason: '通信エラー' });
      }).then(laneNext, laneNext); // 成功/例外どちらでも系列を必ず継続(拒否ハンドラ欠落による系列死を防止)
    }
    // 1件処理後の共通後処理＝この系列の次へ。gen不一致時は何もしない。(乗っ取られた系列を止める)
    function laneNext() {
      if (gen !== _fanzaGen) return;
      processed++;
      if (manual && processed > 0) { var avg = (new Date().getTime() - startT) / processed; etaSec = Math.ceil(avg * (total - processed) / 1000); }
      dmmProgress();
      setTimeout(pump, GAP); // この系列の次の1件へ(間隔をあけて)
    }
    // 3本の取得系列を150msずつずらして起動(同時バーストを避ける)
    var starters = Math.min(CONC, jobs.length);
    running = starters;
    for (var w = 0; w < starters; w++) setTimeout(pump, w * 150);
  }

  // 「DMM 作品情報を取得」ボタン：表示中アイテムのFANZAキャッシュを消して、DMM APIから強制再取得。
  // ※実行中でも「取得中です…」で無視せず、進行中の実行を乗っ取って必ず最初から取得する。(世代トークン方式)
  function refetchFanza_() {
    var urls = {};
    document.querySelectorAll('[data-fanza-url]').forEach(function (el) { var u = el.getAttribute('data-fanza-url'); if (u) urls[u] = 1; });
    if (!Object.keys(urls).length) { setDmmStatus('作品URLのある投稿がありません。'); return; }
    var c = fanzaNameCacheLoad(), changed = false;
    Object.keys(urls).forEach(function (u) { if (c[u]) { delete c[u]; changed = true; } }); // キャッシュ削除＝強制再取得
    if (changed) fanzaNameCacheSave(c);
    fillFanzaNames(true);   // 進捗・完了を表示しつつ取得(進行中の自動取得があっても乗っ取る)
  }

  var _rankMode = (function () { try { return localStorage.getItem('rank_mode') || 'views'; } catch (e) { return 'views'; } })();
  // 投稿(YouTube公開)からの経過時間バケットごとに再生数スナップショットを自動記録。
  //   ※アプリが再生数を取得した時にだけ観測できる＝そのバケットの許容窓内に開いた投稿だけ記録される。
  //   各バケットは「基準時刻〜基準+許容(基準の50%)」で初観測した再生数を固定。過去投稿は対象外＝未記録。
  var SNAP_BUCKETS = [
    { key: 'b30', min: 30, label: '30分' },
    { key: 'b60', min: 60, label: '1時間' },
    { key: 'b120', min: 120, label: '2時間' },
    { key: 'b360', min: 360, label: '6時間' },
    { key: 'b1440', min: 1440, label: '24時間' },
    { key: 'b4320', min: 4320, label: '72時間' }
  ];
  var snapCache = (function () { try { return JSON.parse(localStorage.getItem('view_snaps') || '{}') || {}; } catch (e) { return {}; } })(); // vid -> {b30:{v,ageMin},...}
  function snapPersist_() { try { localStorage.setItem('view_snaps', JSON.stringify(snapCache)); } catch (e) {} }
  function captureSnaps_() {
    var now = new Date().getTime(), changed = false;
    Object.keys(viewsCache).forEach(function (vid) {
      var pub = publishedCache[vid];
      if (!pub || viewsCache[vid] == null) return;
      var ageMin = (now - pub) / 60000;
      var rec = snapCache[vid] || {};
      SNAP_BUCKETS.forEach(function (b) {
        if (rec[b.key]) return;
        var tol = Math.max(15, b.min * 0.5);
        if (ageMin >= b.min && ageMin <= b.min + tol) { rec[b.key] = { v: viewsCache[vid], ageMin: Math.round(ageMin) }; changed = true; }
      });
      if (Object.keys(rec).length) snapCache[vid] = rec;
    });
    if (changed) snapPersist_();
  }
  function fmtAge_(min) { return min == null ? '' : (min < 90 ? min + '分後' : (Math.round(min / 6) / 10) + 'h後'); }

  // ── ランキングタブ(両アカウント合算・3モード切替)──────────────────────────────
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
        if (it.remade) return; // 被リビルド(リビルド版に置き換え済み)はランキングに出さない＝新しい方だけ載る
        var k = itemKey(it);
        var yt = ymap[k] || it.ytUrl || '';
        var vid = ytIdOf(yt);
        if (!vid) return;
        combined.push({ it: it, vid: vid, yt: yt, acct: a });
      });
    });

    // vid で重複排除(同じ動画が両アカウントに存在する場合、先に出た方のみ)
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

    var RANK_MODES = [
      { key: 'views', label: '総合(再生数)' },
      { key: 'clicks', label: 'クリック数' },
      { key: 'pv', label: '▶ピーク' },   // 再生の最大瞬間風速(▶＝再生数の絵文字。一番伸びた区間の再生/時)
      { key: 'pc', label: '<img class="emico" src="assets/icons/ic-link.png" alt="クリック">ピーク' } // クリックの最大瞬間風速(クリック絵文字＝ic-link)
    ].concat(SNAP_BUCKETS.map(function (b) { return { key: b.key, label: b.label }; })); // 30分/1時間/2時間/6時間/24時間/72時間
    // 旧モード名(early)は廃止。保存済みなら b120(2時間)へ読み替え。
    if (_rankMode === 'early') _rankMode = 'b120';

    function doRender() {
      captureSnaps_();
      var isBucket = _rankMode.charAt(0) === 'b';
      var bucketDef = isBucket ? SNAP_BUCKETS.filter(function (b) { return b.key === _rankMode; })[0] : null;
      var pk0 = peakCache || {};
      var rows = uniq.map(function (x) {
        var it = x.it;
        var code = codeOf(it.shortUrl || '');
        var snap = (isBucket && snapCache[x.vid]) ? snapCache[x.vid][_rankMode] : null;
        var pk = pk0[x.vid] || {};
        var cats = ATTR_DEFS.map(function (a) { return it[a.key] ? '<span class="vtag vtag-' + a.key + '">' + a.label + '</span>' : ''; }).join('');
        return {
          vid: x.vid, yt: x.yt, acct: x.acct,
          title: titleCache[x.vid] || it.title || (it.manual ? '(手動追加)' : '(無題)'),
          views: (x.vid in viewsCache) ? viewsCache[x.vid] : null,
          clicks: (function () { var c = (code && code in clicksCache) ? clicksCache[code] : null; return (it.rebuildMerged && it.rebuildBaseClicks != null) ? ((c != null ? c : 0) + it.rebuildBaseClicks) : c; })(), // 結合は総合値(この投稿＋リビルド前。自分が0/未取得でも被リビルド分は加算)
          code: code,
          snapV: snap ? snap.v : null, snapAge: snap ? snap.ageMin : null,
          peakV: pk.vRate != null ? pk.vRate : null, peakVWin: pk.vWin || '',
          peakC: pk.cRate != null ? pk.cRate : null, peakCWin: pk.cWin || '',
          ts: it.ts || (publishedCache[x.vid] || 0),
          bskyHref: it.shareUrl || it.shortUrl || it.postUrl || '',
          workUrl: it.workUrl || '', workState: it.workState || '旧作', cats: cats
        };
      });
      // ソート対象の値。views/clicks/bXX(バケット)/pv・pc(最大瞬間風速)
      function metricVal(r) {
        if (_rankMode === 'clicks') return r.clicks;
        if (_rankMode === 'pv') return r.peakV;
        if (_rankMode === 'pc') return r.peakC;
        if (isBucket) return r.snapV;
        return r.views;
      }
      // 未記録(値なし)は除外。(総合=再生数モードは一覧の基本なので除外しない)
      if (_rankMode !== 'views') rows = rows.filter(function (r) { return metricVal(r) != null; });
      rows.sort(function (a, b) {
        var av = metricVal(a), bv = metricVal(b);
        if (av == null && bv == null) return (b.views || 0) - (a.views || 0);
        if (av == null) return 1; if (bv == null) return -1;
        return bv - av;
      });
      var tabsHtml = '<div class="rank-tabs">' + RANK_MODES.map(function (m) {
        return '<button class="rank-tab' + (m.key === _rankMode ? ' active' : '') + '" data-mode="' + m.key + '" type="button">' + m.label + '</button>';
      }).join('') + '</div>';
      var noteHtml = isBucket
        ? '<div class="rank-note">投稿から約' + bucketDef.label + '時点の再生数ランキング(自動記録・この機能導入後の投稿が対象。「(◯後)」は実記録時刻。未記録は非表示)。</div>'
        : (_rankMode === 'clicks' ? '<div class="rank-note">短縮URLのクリック数ランキング。(クリックURLの無い投稿は非表示)</div>'
          : (_rankMode === 'pv' ? '<div class="rank-note">再生数の最大瞬間風速ランキング。(一番伸びた時間帯の1時間あたり再生数。GASが自動記録・スプレッドシート保存。未記録は非表示)</div>'
            : (_rankMode === 'pc' ? '<div class="rank-note">クリック数の最大瞬間風速ランキング。(一番伸びた時間帯の1時間あたりクリック数。GASが自動記録・保存。未記録は非表示)</div>' : '')));
      var emptyHtml = rows.length ? '' : '<p class="hint" style="padding:10px 14px;">このランキングに表示できる記録がまだありません。</p>';
      el.innerHTML = tabsHtml + noteHtml + emptyHtml + '<div class="rank-list">' +
        rows.map(function (r, i) {
          var rank = i + 1;
          var topCls = rank <= 3 ? ' rank-top' + rank : '';
          var dispTitle = esc(stripCommonTags(r.title));
          // 右端の画像列: 作品サムネ(タップで作品詳細=サンプル一覧) + 動画生成に使った保存画像(タップで拡大)
          var rcid = '';
          try { if (r.workUrl && window.buildAffiliateLink) { var _nu = window.normalizeWorkUrl ? window.normalizeWorkUrl(r.workUrl) : r.workUrl; var _rr = _nu ? window.buildAffiliateLink(_nu, '') : null; if (_rr && _rr.ok) rcid = _rr.cid; } } catch (e) {}
          var refSrc = '';
          try { if (rcid && window.Go5Cand && window.Go5Cand.refImgs) { var _ri = window.Go5Cand.refImgs(rcid); refSrc = (_ri && _ri[0]) || ''; } } catch (e) {}
          var thumbColHtml = (r.workUrl || refSrc)
            ? '<div class="rank-thumbcol">' +
                (r.workUrl ? '<img class="rank-thumb" data-fanza-thumb-url="' + esc(r.workUrl) + '" alt="作品サムネ(タップで詳細)" title="タップで作品詳細(サンプル画像)" loading="lazy" style="display:none;">' : '') +
                (refSrc ? '<img class="rank-refimg" data-rank-refimg="' + esc(rcid) + '" src="' + esc(refSrc) + '" alt="動画で使った画像(タップで拡大)" title="動画で使った画像(タップで拡大)" loading="lazy">' : '') +
              '</div>'
            : '';
          var dateStr = fmtTsFull(r.ts);
          var acctLabel = ACCT_NAME[r.acct] || r.acct;
          // 指標スパン。(並びの中でソート対象を rank-main で強調)バケットモードのみ先頭にスナップ値。
          var mViews = '<span class="' + (_rankMode === 'views' ? 'rank-main' : '') + '" title="YouTube再生数">▶ ' + (r.views != null ? num(r.views) : (apiKey() ? '…' : '–')) + '</span>';
          var mClicks = '<span class="' + (_rankMode === 'clicks' ? 'rank-main' : '') + '" title="Bsky投稿クリック数"><img class="emico" src="assets/icons/ic-link.png" alt="クリック"> ' + (r.clicks != null ? num(r.clicks) : (r.code ? '…' : '–')) + '</span>';
          var mBucket = isBucket ? '<span class="rank-main" title="投稿から約' + bucketDef.label + 'の再生数">⏱ ' + num(r.snapV) + '<span class="rank-sub">(' + fmtAge_(r.snapAge) + ')</span></span>' : '';
          var mPeak = (_rankMode === 'pv' || _rankMode === 'pc')
            ? '<span class="rank-main" title="最大瞬間風速">🌀 ' + num(_rankMode === 'pv' ? r.peakV : r.peakC) + '/時<span class="rank-sub">(' + esc(_rankMode === 'pv' ? r.peakVWin : r.peakCWin) + ')</span></span>'
            : '';
          return '<div class="rank-row' + topCls + '">' +
            '<span class="rank-num">' + rank + '</span>' +
            '<div class="rank-info">' +
              (dateStr || r.workUrl ? '<div class="rank-date">' + esc(dateStr) + (r.workUrl ? '<span class="rank-author" data-fanza-author-url="' + esc(r.workUrl) + '"></span>' : '') + '</div>' : '') +
              '<div class="rank-title-row">' +
                '<span class="rank-acct rank-acct-' + esc(r.acct) + '">' + esc(acctLabel) + '</span>' +
                '<div class="rank-title rank-title-' + esc(r.acct) + '">' +
                  dispTitle + // 作品↗/YouTube↗が下にあるため、題名はリンク化せず普通のテキストで表示
                '</div>' +
              '</div>' +
              (r.workUrl ? '<div class="fanza-name-row" data-fanza-url="' + esc(r.workUrl) + '" style="display:none;"></div>' : '') +
              '<div class="fanza-price-row">' +
                '<span class="fp-state-slot"' + (r.workUrl ? ' data-fanza-state-url="' + esc(r.workUrl) + '"' : '') + '>' + stateBadgeHtml_(r.workState) + '</span>' +
                (r.workUrl ? '<span class="fanza-price" data-fanza-price-url="' + esc(r.workUrl) + '" style="display:none;"></span>' : '') +
              '</div>' +
              (r.cats ? '<div class="vrow-tags">' + r.cats + '</div>' : '') +
              '<div class="vmetrics">' +
                mPeak + mBucket + mViews + mClicks +
                (r.bskyHref ? '<a class="vlink vlink-bsky" href="' + esc(r.bskyHref) + '" target="_blank" rel="noopener">Bsky↗</a>' : '') +
                (r.yt ? '<a class="vlink vlink-yt" href="' + esc(r.yt) + '" target="_blank" rel="noopener">YouTube↗</a>' : '') +
                (r.workUrl ? '<a class="vlink vlink-work" href="' + esc(r.workUrl) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
              '</div>' +
            '</div>' +
            thumbColHtml +
          '</div>';
        }).join('') +
      '</div>';
      // サブタブ配線
      el.querySelectorAll('.rank-tab').forEach(function (b) {
        b.addEventListener('click', function () {
          _rankMode = b.getAttribute('data-mode');
          try { localStorage.setItem('rank_mode', _rankMode); } catch (e) {}
          doRender();
        });
      });
      // 右端の画像列: 作品サムネ→作品詳細(サンプル一覧)モーダル / 動画生成に使った画像→ズーム(スワイプ)
      el.querySelectorAll('img.rank-thumb').forEach(function (im) {
        im.addEventListener('click', function () { openFanzaModal_(im.getAttribute('data-fanza-thumb-url')); });
      });
      el.querySelectorAll('[data-rank-refimg]').forEach(function (im) {
        im.addEventListener('click', function () { if (window.Go5Cand && window.Go5Cand.zoomRefImgs) window.Go5Cand.zoomRefImgs(im.getAttribute('data-rank-refimg')); });
      });
      applyManualInfoNow_(); // 手動入力の作品情報は描画直後に即表示
      fillFanzaNames();
    }

    // 再生数・クリック数のうちキャッシュに無いものを取得してから描画。
    var missingV = uniq.map(function (x) { return x.vid; }).filter(function (v) { return !(v in viewsCache); });
    var missingC = uniq.map(function (x) { return codeOf(x.it.shortUrl || ''); }).filter(function (c) { return c && !(c in clicksCache); });
    if (missingV.length || missingC.length) {
      el.innerHTML = '<p style="color:var(--sub);font-size:13px;padding:8px 14px;">再生数・クリック数を取得中…</p>';
      var jobs = [];
      var vbatches = [];
      for (var i = 0; i < missingV.length; i += 50) { vbatches.push(missingV.slice(i, i + 50)); }
      vbatches.forEach(function (b) {
        jobs.push(fetchVideos(b).then(function (m) {
          var err = m.__error || ''; delete m.__error; if (err && !lastErr) lastErr = err;
          delete m.__queried; // メタキーを消してからキャッシュ反映(yt_meta_cacheへのゴミ混入防止)
          Object.keys(m).forEach(function (id) {
            var rec = m[id] || {};
            if (rec.views != null) viewsCache[id] = rec.views;
            if (rec.published != null) publishedCache[id] = rec.published;
            if (rec.title) titleCache[id] = rec.title;
          });
          ytMetaPersist(m);
        }));
      });
      if (missingC.length) jobs.push(fetchAllClicks_()); // 未取得コードは /api/list で一括(旧: コード毎に1本=無料枠を焼く)
      Promise.all(jobs).then(function () { clicksPersist_(); doRender(); });
    } else {
      doRender();
    }
    // ピーク/差分(GAS)を取得したら再描画。(ピーク2モードに反映)
    fetchDeltas_(false, doRender);
  }
  try { window.YtRank = { renderRank: renderRank }; } catch (e) {}
  // 短縮URL→現在のクリック数。(bluesky.jsのリビルド引き継ぎが「リビルド前スナップショット」取得に使う)
  try { window.Go5Clicks = { of: function (shortUrl) { var c = codeOf(shortUrl || ''); return (c && (c in clicksCache)) ? clicksCache[c] : null; } }; } catch (e) {}
})();
