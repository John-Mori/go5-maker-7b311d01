/**
 * candidates.js — 「💡 候補」タブ（ランキングと予約の間）。
 *
 * ① 候補リスト（既定サブタブ）:
 *    作品URLを入れると候補として記録。アフィリンク付きURL(al.fanza.co.jp/?lurl=…)でも
 *    素の作品URLへ正規化して保存。作品名/サークル名/サムネ/現在価格/セール◯%offを表示。
 *    複数記録・削除可。データは両アカウント共通(localStorage: cand_items)。
 * ② サークルタブ（＋タブを追加で生成）:
 *    特定サークルの全作品を縦一覧表示。並び替え(発売日新/古・売上(人気)・直近1週間で売れてる・値引き率)。
 *    ジャンル・作品状態(新作/準新作/旧作)バッジも表示。各作品に「非表示」、上部「非表示リストを
 *    表示」で再表示可。サークルの特定に必要な入力: サークルID(数字) / サークルページURL
 *    (…article=maker/id=数字…) / そのサークルの作品URL1つ(→APIでサークルIDを自動解決) のどれか1つ。
 *    タブはPC=ドラッグ、スマホ=長押し→ドラッグで並べ替え可（固定の候補/＋タブを除く）。
 *    🔁リロード=キャッシュ無視で全件取り直し／✏️編集=タブ名変更・サークル貼り替え・削除。
 *    ＋タブ追加で作品URLを入れるとサークル名が自動でタブ名に入る。
 *
 * 依存: window.normalizeWorkUrl / buildAffiliateLink (affiliate-core.js),
 *       window.FanzaCore.fetchFanzaInfo (fanza-core.js), fanza-worker /api/fanza-maker-list。
 */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function lsGet(k, def) { try { return JSON.parse(localStorage.getItem(k) || def); } catch (e) { return JSON.parse(def); } }
  function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  function workerCfg() {
    var u = '', s = '';
    try { u = (localStorage.getItem('fanza_worker_url') || '').trim(); s = (localStorage.getItem('fanza_shared_secret') || '').trim(); } catch (e) {}
    return { url: u.replace(/\/+$/, ''), secret: s };
  }
  function yen(n) { return (n != null && !isNaN(n)) ? '¥' + Number(n).toLocaleString('ja-JP') : '—'; }
  function fmtDate(s) { return String(s || '').slice(0, 10); }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  // 発売日→作品状態（新作=30日以内/準新作=90日以内/旧作=それ以降）。yt-clicks.jsのderiveWorkState_と同ロジック。
  function deriveWorkState_(dateStr) {
    if (!dateStr) return '';
    var t = Date.parse(String(dateStr).replace(' ', 'T'));
    if (isNaN(t)) return '';
    var days = (new Date().getTime() - t) / 86400000;
    if (days <= 30) return '新作';
    if (days <= 90) return '準新作';
    return '旧作';
  }
  function stateBadgeHtml_(ws) {
    var cls = ws === '新作' ? 'fp-state-new' : (ws === '準新作' ? 'fp-state-semi' : 'fp-state-old');
    return '<span class="fp-state ' + cls + '">' + esc(ws) + '</span>';
  }

  // ── 保存キー ──
  var K_ITEMS = 'cand_items';   // 候補リスト(共通): [{url,cid,title,author,thumb,listPrice,price,discountPct,addedAt}]
  var K_TABS = 'cand_tabs';    // サークルタブ: [{id,name,makerId,makerName}]
  function hiddenKey(tabId) { return 'cand_hidden__' + tabId; }
  // ★キャッシュ版数(v2)：v170前の「最大400件しか取れていない不完全キャッシュ」を確実に無効化する。
  //   これを上げると全ユーザーの旧キャッシュが読まれなくなり、次回表示で全件を取り直す。
  function cacheKey(makerId, mode) { return 'cand_mk2__' + makerId + '__' + mode; }
  var CACHE_TTL = 3 * 3600 * 1000;

  var _activeTab = 'main'; // 'main' | サークルタブid
  var _sort = 'date_desc';
  var _showHidden = false;
  var _suppressNextClick = false; // タブ並べ替え(ドラッグ/長押し)直後のクリック(タブ切替)を1回だけ抑止

  var SORTS = [
    { key: 'price_asc', label: '現在価格が安い順' },
    { key: 'date_desc', label: '発売日が新しい順' },
    { key: 'date_asc', label: '発売日が古い順' },
    { key: 'rank', label: '売上(人気)が多い順' },
    { key: 'rank7d', label: '直近1週間で売れてる順' },
    { key: 'discount_desc', label: '値引き率が高い順' }
  ];
  // 「直近1週間で売れてる順」の注記。
  var RANK7D_NOTE = '※「直近1週間で売れてる順」は、実売本数(販売数)の週次差分があればそれで、無ければレビュー件数の伸びで並べます。差分は記録が溜まる数日後から出ます。';
  var SALES_NOTE = '※DMMの販売数(実売本数)は日本IPの詳細ページにのみ有り、サーバー(海外IP)からは取得不可のため、PCで「販売数を取得.bat」を実行して取り込みます(未取得の間はレビュー件数を代理表示)。';

  // ── レビュー件数スナップショット（「直近1週間で売れてる順」の差分計算用）──
  //   cid毎に {at,c} を最大8件・45日以内で保持。12時間に1回だけ記録して肥大化を防ぐ。
  var K_RVSNAP = 'cand_rvsnap';
  function recordReviewSnapshots(items) {
    var snap = lsGet(K_RVSNAP, '{}'), now = new Date().getTime(), changed = false, cutoff = now - 45 * 86400000;
    (items || []).forEach(function (it) {
      if (!it || it.cid == null || it.reviewCount == null) return;
      var arr = snap[it.cid] || [];
      var last = arr[arr.length - 1];
      if (!last || (now - last.at) > 12 * 3600 * 1000) {
        arr.push({ at: now, c: it.reviewCount });
        snap[it.cid] = arr.filter(function (s) { return s.at >= cutoff; }).slice(-8);
        changed = true;
      }
    });
    if (changed) lsSet(K_RVSNAP, snap);
  }
  // 約1週間前のスナップとの差分（＝直近1週間で増えたレビュー数≒売れた数の近似）。基準が新しすぎ/無ければ null。
  function weekReviewDelta(cid, currentCount) {
    if (currentCount == null) return null;
    var snap = lsGet(K_RVSNAP, '{}'), arr = snap[cid];
    if (!arr || !arr.length) return null;
    var target = new Date().getTime() - 7 * 86400000, best = null;
    arr.forEach(function (s) { if (!best || Math.abs(s.at - target) < Math.abs(best.at - target)) best = s; });
    if (!best) return null;
    var ageDays = (new Date().getTime() - best.at) / 86400000;
    if (ageDays < 3) return null; // 基準が新しすぎ＝まだ1週間分の差分が測れない
    return Math.max(0, currentCount - best.c);
  }

  // ── 実売本数（販売数）：worker/api/fanza-sales(=PC取得→KV)から取得。端末に24hキャッシュ。──
  //   販売数はDMM詳細ページにのみ有り、海外IP(worker)は取れない→PC(日本IP)がスクレイプ保存したものを読む。
  var K_SALES = 'cand_sales';       // {cid:{n:(number|null), at}}
  var K_SALESSNAP = 'cand_salessnap'; // {cid:[{at,n}]}  週次差分用
  var SALES_TTL = 24 * 3600 * 1000, SALES_MISS_TTL = 15 * 60 * 1000;
  function salesCache() { return lsGet(K_SALES, '{}'); }
  function salesOf(cid) { // number=実売 / null=未取得(PC待ち) / undefined=キャッシュ切れ
    var c = salesCache()[cid]; if (!c) return undefined;
    var ttl = (c.n == null ? SALES_MISS_TTL : SALES_TTL);
    return (new Date().getTime() - c.at < ttl) ? c.n : undefined;
  }
  function recordSalesSnapshots(salesMap) {
    var snap = lsGet(K_SALESSNAP, '{}'), now = new Date().getTime(), changed = false, cutoff = now - 45 * 86400000;
    Object.keys(salesMap || {}).forEach(function (cid) {
      var n = salesMap[cid]; if (n == null) return;
      var arr = snap[cid] || [], last = arr[arr.length - 1];
      if (!last || (now - last.at) > 12 * 3600 * 1000) {
        arr.push({ at: now, n: n }); snap[cid] = arr.filter(function (s) { return s.at >= cutoff; }).slice(-8); changed = true;
      }
    });
    if (changed) lsSet(K_SALESSNAP, snap);
  }
  function weekSalesDelta(cid, currentN) {
    if (currentN == null) return null;
    var arr = lsGet(K_SALESSNAP, '{}')[cid]; if (!arr || !arr.length) return null;
    var target = new Date().getTime() - 7 * 86400000, best = null;
    arr.forEach(function (s) { if (!best || Math.abs(s.at - target) < Math.abs(best.at - target)) best = s; });
    if (!best || (new Date().getTime() - best.at) / 86400000 < 3) return null;
    return Math.max(0, currentN - best.n);
  }
  // 未取得cidを worker へ問い合わせ（＝未取得はPC取得キューへ自動登録）。取得できたら cb(changed,missingCount)。
  function fetchSalesFor(cids, cb) {
    var cache = salesCache(), need = [], now = new Date().getTime();
    cids.forEach(function (cid) { var c = cache[cid]; var ttl = (c && c.n == null ? SALES_MISS_TTL : SALES_TTL); if (!c || (now - c.at) >= ttl) need.push(cid); });
    need = need.filter(function (v, i, a) { return a.indexOf(v) === i; });
    if (!need.length) { cb(false, missingCount(cids)); return; }
    var cfg = workerCfg(); if (!cfg.url) { cb(false, 0); return; }
    var chunks = []; for (var i = 0; i < need.length; i += 30) chunks.push(need.slice(i, i + 30));
    var pending = chunks.length, changed = false;
    chunks.forEach(function (ch) {
      fetch(cfg.url + '/api/fanza-sales', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret }, body: JSON.stringify({ cids: ch }) })
        .then(function (r) { return r.json(); }).then(function (d) {
          if (d && d.ok) {
            var c = salesCache(), t = new Date().getTime(), s = d.sales || {};
            ch.forEach(function (cid) { if (s[cid] != null) { c[cid] = { n: s[cid], at: t }; changed = true; } else { c[cid] = { n: null, at: t }; } });
            lsSet(K_SALES, c); recordSalesSnapshots(s);
          }
          if (--pending === 0) cb(changed, missingCount(cids));
        }).catch(function () { if (--pending === 0) cb(changed, missingCount(cids)); });
    });
  }
  function missingCount(cids) { var c = salesCache(); var n = 0; cids.forEach(function (cid) { if (!c[cid] || c[cid].n == null) n++; }); return n; }

  // ── サークル作品の取得（全ページ＋全同人フロアの巡回はworker側で完結・フロントは1回呼ぶだけ） ──
  //   force=true でキャッシュを無視して取り直す（🔁リロードボタン用）。
  function fetchMakerItems(makerId, mode, cb, force) {
    // date/discountは sort=date、rank・rank7dは同一データ(sort=rank)を使用。
    var apiMode = (mode === 'rank' || mode === 'rank7d') ? 'rank' : 'date';
    var ck = cacheKey(makerId, apiMode);
    if (!force) {
      var c = lsGet(ck, 'null');
      if (c && c.at && (new Date().getTime() - c.at) < CACHE_TTL && Array.isArray(c.items) && c.items.length) { cb(c.items, null); return; }
    }
    var cfg = workerCfg();
    if (!cfg.url) { cb(null, 'FANZA Workerが未設定です(⚙️詳細設定)'); return; }
    fetch(cfg.url + '/api/fanza-maker-list', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret },
      body: JSON.stringify({ makerId: makerId, sort: apiMode })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d || !d.ok) { cb(null, (d && d.error) === 'bad_secret' ? '共有シークレット不一致(⚙️詳細設定)' : ('取得エラー: ' + ((d && d.error) || '不明'))); return; }
      var items = d.items || [];
      // 空データはキャッシュしない（一時失敗やサークル未収録を固定化しない）。
      if (items.length) { lsSet(ck, { at: new Date().getTime(), items: items }); recordReviewSnapshots(items); }
      cb(items, null);
    }).catch(function () { cb(null, '通信エラー'); });
  }
  function priceOf(it) { return (it.price != null) ? it.price : (it.listPrice != null ? it.listPrice : Infinity); }
  function sortItems(items, mode) {
    var a = items.slice();
    if (mode === 'price_asc') a.sort(function (x, y) { return priceOf(x) - priceOf(y) || String(y.date).localeCompare(String(x.date)); });
    else if (mode === 'date_asc') a.sort(function (x, y) { return String(x.date).localeCompare(String(y.date)); });
    else if (mode === 'date_desc') a.sort(function (x, y) { return String(y.date).localeCompare(String(x.date)); });
    else if (mode === 'discount_desc') a.sort(function (x, y) { return (y.discountPct || 0) - (x.discountPct || 0) || String(y.date).localeCompare(String(x.date)); });
    else if (mode === 'rank7d') {
      // 直近1週間の伸びが大きい順。実売本数の差分が取れればそれを最優先、無ければレビュー増、
      // どちらも無ければ販売数(実売)総数→レビュー総数(人気の近似)で並べる。
      var score = function (it) {
        var sd = weekSalesDelta(it.cid, salesOf(it.cid));
        if (sd != null) return [3, sd];
        var rd = weekReviewDelta(it.cid, it.reviewCount);
        if (rd != null) return [2, rd];
        var sv = salesOf(it.cid); if (typeof sv === 'number') return [1, sv];
        return [0, it.reviewCount || 0];
      };
      a.sort(function (x, y) { var sx = score(x), sy = score(y); return sy[0] - sx[0] || sy[1] - sx[1]; });
    }
    // rank はAPIの並び(人気順)をそのまま使う
    return a;
  }

  // ── サークルIDの解決（数字 / maker URL / 作品URL） ──
  function resolveMakerId(input, cb) {
    var t = (input || '').trim();
    if (!t) { cb(null, null, '入力が空です'); return; }
    if (/^\d{1,10}$/.test(t)) { cb(t, '', null); return; }
    var mm = t.match(/article=maker\/id=(\d+)/) || t.match(/[?&/]maker[_/]?id=?(\d+)/i);
    if (mm) { cb(mm[1], '', null); return; }
    // 作品URL → fanza-item でサークルID(authorId)を解決
    var url = (window.normalizeWorkUrl ? window.normalizeWorkUrl(t) : t);
    var r = window.buildAffiliateLink ? window.buildAffiliateLink(url, '') : null;
    if (!r || !r.ok) { cb(null, null, '作品URL/サークルIDを認識できませんでした'); return; }
    var cfg = workerCfg();
    if (!window.FanzaCore || !cfg.url) { cb(null, null, 'FANZA Workerが未設定です(⚙️詳細設定)'); return; }
    window.FanzaCore.fetchFanzaInfo(r.cid, cfg.url, cfg.secret, url).then(function (info) {
      if (info && info.title && info.authorId) cb(info.authorId, info.author || '', null);
      else if (info && info.title) cb(null, null, '作品は取得できましたがサークルIDが含まれていません(API未収録?)');
      else cb(null, null, '作品情報を取得できませんでした' + (info && info.reason ? '(' + info.reason + ')' : ''));
    }).catch(function () { cb(null, null, '通信エラー'); });
  }

  // ── DOM ──
  function render() {
    var page = $('pageCand');
    if (!page) return;
    var tabs = lsGet(K_TABS, '[]');
    var tabBtns = '<button class="cand-tab' + (_activeTab === 'main' ? ' active' : '') + '" data-ct="main" type="button">💡 候補</button>' +
      tabs.map(function (t) {
        return '<button class="cand-tab' + (_activeTab === t.id ? ' active' : '') + '" data-ct="' + esc(t.id) + '" type="button">' + esc(t.name) + '</button>';
      }).join('') +
      '<button class="cand-tab cand-tab-add" id="candAddTab" type="button">＋ タブを追加</button>';

    var html = '<main><div class="cand-tabs">' + tabBtns + '</div><div id="candAddForm" style="display:none;"></div><div id="candBody"></div></main>';
    page.innerHTML = html;

    page.querySelectorAll('.cand-tab[data-ct]').forEach(function (b) {
      b.addEventListener('click', function () {
        if (_suppressNextClick) { _suppressNextClick = false; return; } // 直前の並べ替え操作の後続クリックは無視
        _activeTab = b.getAttribute('data-ct'); _showHidden = false; render();
      });
    });
    var addBtn = $('candAddTab');
    if (addBtn) addBtn.addEventListener('click', showAddTabForm);
    wireTabDrag_();

    if (_activeTab === 'main') renderMain();
    else renderMaker(_activeTab);
  }

  // ── タブの並べ替え：PC=ドラッグ、スマホ=長押し→ドラッグ（Pointer Eventsでマウス/タッチ統一） ──
  //   固定の「💡候補」「＋タブを追加」は並べ替え対象外。サークルタブ同士のみ入れ替え可能。
  function wireTabDrag_() {
    var bar = document.querySelector('.cand-tabs');
    if (!bar) return;
    var LONG_PRESS_MS = 350, MOVE_THRESHOLD = 6;
    var longPressTimer = null, startX = 0, startY = 0;
    var dragging = false, dragEl = null, dragMoved = false;

    function reorderable() {
      return [].slice.call(bar.querySelectorAll('.cand-tab[data-ct]')).filter(function (b) { return b.getAttribute('data-ct') !== 'main'; });
    }
    function beginDrag(btn) {
      dragging = true; dragEl = btn; dragMoved = false;
      btn.classList.add('cand-tab-dragging');
      document.addEventListener('pointermove', onDragMove);
      document.addEventListener('pointerup', onDragEnd);
      document.addEventListener('pointercancel', onDragEnd);
    }
    function onDragMove(e) {
      if (!dragging || !dragEl) return;
      dragMoved = true;
      var list = reorderable();
      for (var i = 0; i < list.length; i++) {
        var sib = list[i];
        if (sib === dragEl) continue;
        var r = sib.getBoundingClientRect();
        if (e.clientX < r.left + r.width / 2) { bar.insertBefore(dragEl, sib); return; }
        if (i === list.length - 1) { var addBtn = $('candAddTab'); if (addBtn) bar.insertBefore(dragEl, addBtn); }
      }
    }
    function onDragEnd() {
      document.removeEventListener('pointermove', onDragMove);
      document.removeEventListener('pointerup', onDragEnd);
      document.removeEventListener('pointercancel', onDragEnd);
      if (dragEl) dragEl.classList.remove('cand-tab-dragging');
      var moved = dragMoved;
      dragging = false; dragEl = null; dragMoved = false;
      if (moved) { _suppressNextClick = true; setTimeout(function () { _suppressNextClick = false; }, 300); commitTabOrder_(); }
    }

    bar.querySelectorAll('.cand-tab[data-ct]').forEach(function (btn) {
      if (btn.getAttribute('data-ct') === 'main') return; // 固定タブは並べ替え起点にしない
      btn.addEventListener('pointerdown', function (e) {
        startX = e.clientX; startY = e.clientY;
        if (e.pointerType === 'touch') {
          longPressTimer = setTimeout(function () { longPressTimer = null; beginDrag(btn); }, LONG_PRESS_MS);
        } else {
          // マウス/ペン：微小な移動でドラッグ開始（クリックと区別）
          var onMove = function (me) {
            if (Math.abs(me.clientX - startX) > MOVE_THRESHOLD || Math.abs(me.clientY - startY) > MOVE_THRESHOLD) {
              document.removeEventListener('pointermove', onMove);
              document.removeEventListener('pointerup', onUp);
              beginDrag(btn);
            }
          };
          var onUp = function () { document.removeEventListener('pointermove', onMove); document.removeEventListener('pointerup', onUp); };
          document.addEventListener('pointermove', onMove);
          document.addEventListener('pointerup', onUp);
        }
      });
      btn.addEventListener('pointermove', function (e) {
        if (longPressTimer && (Math.abs(e.clientX - startX) > MOVE_THRESHOLD || Math.abs(e.clientY - startY) > MOVE_THRESHOLD)) {
          clearTimeout(longPressTimer); longPressTimer = null; // 通常のスクロール/タップとして扱う
        }
      });
      btn.addEventListener('pointerup', function () { if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; } });
      btn.addEventListener('pointercancel', function () { if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; } });
    });
  }
  function commitTabOrder_() {
    var bar = document.querySelector('.cand-tabs');
    if (!bar) return;
    var order = [].slice.call(bar.querySelectorAll('.cand-tab[data-ct]')).map(function (b) { return b.getAttribute('data-ct'); }).filter(function (id) { return id !== 'main'; });
    var tabs = lsGet(K_TABS, '[]');
    var byId = {}; tabs.forEach(function (t) { byId[t.id] = t; });
    var newTabs = order.map(function (id) { return byId[id]; }).filter(Boolean);
    lsSet(K_TABS, newTabs);
    render();
  }

  // ── ＋タブを追加（名前＋サークル特定情報→決定） ──
  function showAddTabForm() {
    var f = $('candAddForm');
    if (!f) return;
    f.style.display = '';
    f.innerHTML = '<div class="card" style="margin:10px 0;">' +
      '<div class="field-label" style="margin-top:0;">サークルタブを追加</div>' +
      '<div class="hint">必要な情報はどれか1つ: ①そのサークルの作品URL1つ(サークル名を自動判定) ②サークルID(数字) ③サークルページURL(…article=maker/id=数字…)</div>' +
      '<input id="candTabSrc" type="text" inputmode="url" placeholder="作品URL / サークルID / サークルURL" autocomplete="off" style="margin-top:8px;">' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">タブ名（作品URLなら自動で入ります・後から編集可）</label>' +
      '<input id="candTabName" type="text" placeholder="タブの名前" autocomplete="off">' +
      '<div style="display:flex;gap:8px;margin-top:8px;">' +
      '<button id="candTabOk" type="button" class="primary" style="flex:1;font-size:.9rem;padding:10px;">決定</button>' +
      '<button id="candTabCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">やめる</button>' +
      '</div><div id="candTabMsg" class="hint" style="min-height:1.3em;"></div></div>';
    var _nameAuto = true; // ユーザーが手入力するまでは自動反映を許可
    var _resolved = null; // {src, makerId, makerName} 自動判定の結果を決定時に再利用（二重解決回避）
    $('candTabName').addEventListener('input', function () { _nameAuto = false; });
    // 作品URL等を入れたら、サークル名を自動でタブ名へ反映（手入力済みなら尊重）。
    function autoFillName() {
      var src = ($('candTabSrc').value || '').trim();
      if (!src || (_resolved && _resolved.src === src)) return;
      var msg = $('candTabMsg');
      msg.textContent = '⏳ サークル名を取得中…';
      resolveMakerId(src, function (makerId, makerName, err) {
        if (!$('candTabSrc') || ($('candTabSrc').value || '').trim() !== src) return; // 入力が変わっていたら破棄
        if (!makerId) { _resolved = null; msg.textContent = '⚠️ ' + err; return; }
        _resolved = { src: src, makerId: makerId, makerName: makerName || '' };
        msg.textContent = '✅ サークルを特定しました' + (makerName ? '：' + makerName : '（ID ' + makerId + '）');
        if (_nameAuto && makerName) { $('candTabName').value = makerName; }
      });
    }
    $('candTabSrc').addEventListener('change', autoFillName);
    $('candTabSrc').addEventListener('blur', autoFillName);
    $('candTabCancel').addEventListener('click', function () { f.style.display = 'none'; f.innerHTML = ''; });
    $('candTabOk').addEventListener('click', function () {
      var name = ($('candTabName').value || '').trim();
      var src = ($('candTabSrc').value || '').trim();
      var msg = $('candTabMsg');
      if (!src) { msg.textContent = '⚠️ サークルの特定情報を入れてください'; return; }
      function addTab(makerId, makerName) {
        var tabs = lsGet(K_TABS, '[]');
        var tab = { id: 'ct' + new Date().getTime(), name: name || makerName || ('サークル' + makerId), makerId: makerId, makerName: makerName || '' };
        tabs.push(tab); lsSet(K_TABS, tabs);
        _activeTab = tab.id; render();
      }
      if (_resolved && _resolved.src === src) { addTab(_resolved.makerId, _resolved.makerName); return; }
      msg.textContent = '⏳ サークルを特定中…';
      resolveMakerId(src, function (makerId, makerName, err) {
        if (!makerId) { msg.textContent = '⚠️ ' + err; return; }
        addTab(makerId, makerName);
      });
    });
  }

  // ── 候補リスト（既定サブタブ） ──
  function renderMain() {
    var body = $('candBody');
    var items = lsGet(K_ITEMS, '[]');
    body.innerHTML = '<div class="card">' +
      '<div class="field-label" style="margin-top:0;">📥 作品URLを候補に追加</div>' +
      '<div class="hint">アフィリンク付きURL(al.fanza.co.jp/?lurl=…)でもOK。素の作品URLに直して記録します。</div>' +
      '<input id="candUrl" type="text" inputmode="url" placeholder="https://…(作品URL or アフィリンク)" autocomplete="off" style="margin-top:6px;">' +
      '<button id="candAdd" type="button" class="primary" style="margin-top:8px;font-size:.9rem;padding:10px;">➕ 候補に追加</button>' +
      '<div id="candMsg" class="hint" style="min-height:1.3em;"></div>' +
      '</div><div id="candList"></div>';
    $('candAdd').addEventListener('click', addCandidate);
    renderCandList();
  }
  function addCandidate() {
    var inp = $('candUrl'), msg = $('candMsg');
    var url = window.normalizeWorkUrl ? window.normalizeWorkUrl(inp.value) : (inp.value || '').trim();
    if (!url) { msg.textContent = '⚠️ URLを認識できませんでした'; return; }
    var r = window.buildAffiliateLink ? window.buildAffiliateLink(url, '') : null;
    if (!r || !r.ok) { msg.textContent = '⚠️ FANZAの作品URLではないようです'; return; }
    var items = lsGet(K_ITEMS, '[]');
    if (items.some(function (x) { return x.cid === r.cid; })) { msg.textContent = 'ℹ️ すでに候補にあります'; return; }
    msg.textContent = '⏳ 作品情報を取得中…';
    var cfg = workerCfg();
    var put = function (info) {
      items.unshift({
        url: url, cid: r.cid,
        title: (info && info.title) || '(タイトル未取得)',
        author: (info && info.author) || '',
        thumb: (info && (info.thumbSmall || info.thumb)) || '',
        listPrice: info ? info.listPrice : null, price: info ? info.price : null,
        discountPct: info ? (info.discountPct || 0) : 0,
        date: (info && info.releaseDate) || '',
        genres: (info && info.genres) || [],
        addedAt: new Date().getTime()
      });
      lsSet(K_ITEMS, items);
      inp.value = ''; msg.textContent = '✅ 追加しました';
      renderCandList();
    };
    if (window.FanzaCore && cfg.url) {
      window.FanzaCore.fetchFanzaInfo(r.cid, cfg.url, cfg.secret, url).then(function (info) {
        put(info && info.title ? info : null);
      }).catch(function () { put(null); });
    } else put(null);
  }
  function renderCandList() {
    var el = $('candList');
    var items = lsGet(K_ITEMS, '[]');
    if (!items.length) { el.innerHTML = '<p class="hint" style="padding:4px 6px;">まだ候補がありません。上の欄に作品URLを入れて追加してください。</p>'; return; }
    el.innerHTML = items.map(function (it, i) {
      return candCard(it, '<button type="button" class="cand-hide-btn" data-del="' + i + '">🗑 削除</button>');
    }).join('');
    el.querySelectorAll('[data-del]').forEach(function (b) {
      b.addEventListener('click', function () {
        var items2 = lsGet(K_ITEMS, '[]');
        var it = items2[parseInt(b.getAttribute('data-del'), 10)];
        if (!it || !window.confirm('「' + (it.title || it.cid) + '」を候補から削除しますか？')) return;
        items2.splice(parseInt(b.getAttribute('data-del'), 10), 1);
        lsSet(K_ITEMS, items2); renderCandList();
      });
    });
    // 候補作品の実売本数を取得（未取得はPC取得キューへ）。反映されたら再描画。
    fetchSalesFor(items.map(function (it) { return it.cid; }), function (changed) { if (changed && _activeTab === 'main') renderCandList(); });
  }

  // ── サークルタブ ──
  function renderMaker(tabId, force) {
    var tabs = lsGet(K_TABS, '[]');
    var tab = null; tabs.forEach(function (t) { if (t.id === tabId) tab = t; });
    var body = $('candBody');
    if (!tab) { _activeTab = 'main'; render(); return; }
    var sortOpts = SORTS.map(function (s) { return '<option value="' + s.key + '"' + (s.key === _sort ? ' selected' : '') + '>' + s.label + '</option>'; }).join('');
    body.innerHTML = '<div class="card" style="padding:10px 12px;">' +
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
      '<select id="candSort" style="flex:1;min-width:140px;">' + sortOpts + '</select>' +
      '<button id="candReload" type="button" class="ghost" title="全件を取り直す(キャッシュを無視)" style="flex:0 0 auto;width:auto;margin:0;font-size:15px;padding:6px 10px;">🔁</button>' +
      '<button id="candEditTab" type="button" class="ghost" title="タブ名・サークルを編集" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">✏️ 編集</button>' +
      '<button id="candShowHidden" type="button" class="ghost" style="flex:0 0 auto;width:auto;margin:0;font-size:12px;padding:6px 10px;">' + (_showHidden ? '👁 通常表示に戻す' : '🙈 非表示リストを表示') + '</button>' +
      '</div>' +
      (_sort === 'rank7d' ? '<div class="hint" style="margin-top:6px;">' + esc(RANK7D_NOTE) + '</div>' : '') +
      ((_sort === 'rank' || _sort === 'rank7d') ? '<div class="hint" style="margin-top:4px;">' + esc(SALES_NOTE) + '</div>' : '') +
      '</div>' +
      '<div id="candEditForm"></div>' +
      '<div id="candMakerList"><p class="hint" style="padding:8px;">' + (force ? '🔁 全件を取り直しています…' : '⏳ サークルの作品を取得中…') + '</p></div>';
    $('candSort').addEventListener('change', function () { _sort = this.value; renderMaker(tabId); });
    $('candShowHidden').addEventListener('click', function () { _showHidden = !_showHidden; renderMaker(tabId); });
    $('candReload').addEventListener('click', function () { renderMaker(tabId, true); });
    $('candEditTab').addEventListener('click', function () { showEditTabForm(tab); });
    fetchMakerItems(tab.makerId, _sort, function (items, err) {
      var el = $('candMakerList');
      if (!el || _activeTab !== tabId) return;
      if (err) { el.innerHTML = '<p class="hint" style="padding:8px;">⚠️ ' + esc(err) + '</p>'; return; }
      // タブ名が自動生成の「サークルNNN」のままで、一覧からサークル名が取れたら本名へ自動修正。
      if (items && items.length && items[0].makerName && /^サークル\d+$/.test(tab.name || '')) {
        var tabs2 = lsGet(K_TABS, '[]');
        tabs2.forEach(function (t) { if (t.id === tabId) { t.name = items[0].makerName; t.makerName = items[0].makerName; } });
        lsSet(K_TABS, tabs2);
        render(); return; // タブバーを本名で再描画（この後の描画は再入で行われる）
      }
      var hidden = lsGet(hiddenKey(tabId), '[]');
      var hset = {}; hidden.forEach(function (c) { hset[c] = true; });
      var arr = sortItems(items, _sort).filter(function (it) { return _showHidden ? hset[it.cid] : !hset[it.cid]; });
      if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">' + (_showHidden ? '非表示にした作品はありません。' : '表示できる作品がありません。') + '</p>'; return; }
      // 実売本数(販売数)を先頭60件ぶん取得（未取得はPC取得キューへ自動登録）。反映されたら再描画。
      var topCids = arr.slice(0, 60).map(function (it) { return it.cid; });
      var salesMiss = missingCount(topCids);
      var head = '<p class="hint" style="padding:2px 6px;">' + (_showHidden ? '🙈 非表示中の作品 ' : '') + arr.length + '件' + (_showHidden ? '(「再表示」で戻せます)' : ' / 非表示 ' + hidden.length + '件・不足なら🔁リロード') +
        (!_showHidden && salesMiss > 0 ? '<br>💰 販売数(実売)は上位' + salesMiss + '件がPC取得待ち。PCで「販売数を取得.bat」を実行→🔁で反映されます。' : '') + '</p>';
      el.innerHTML = head + arr.map(function (it) {
        var btn = _showHidden
          ? '<button type="button" class="cand-hide-btn" data-unhide="' + esc(it.cid) + '">👁 再表示</button>'
          : '<button type="button" class="cand-hide-btn" data-hide="' + esc(it.cid) + '">🙈 非表示</button>';
        return candCard(it, btn);
      }).join('');
      if (!_showHidden && !force) fetchSalesFor(topCids, function (changed) { if (changed && _activeTab === tabId) renderMaker(tabId); });
      el.querySelectorAll('[data-hide]').forEach(function (b) {
        b.addEventListener('click', function () {
          var h = lsGet(hiddenKey(tabId), '[]'); var c = b.getAttribute('data-hide');
          if (h.indexOf(c) < 0) h.push(c); lsSet(hiddenKey(tabId), h); renderMaker(tabId);
        });
      });
      el.querySelectorAll('[data-unhide]').forEach(function (b) {
        b.addEventListener('click', function () {
          var c = b.getAttribute('data-unhide');
          lsSet(hiddenKey(tabId), lsGet(hiddenKey(tabId), '[]').filter(function (x) { return x !== c; }));
          renderMaker(tabId);
        });
      });
    }, force);
  }

  // ── タブ編集モーダル（タブ名の変更・サークルの貼り替え・削除） ──
  function showEditTabForm(tab) {
    var f = $('candEditForm');
    if (!f) return;
    f.innerHTML = '<div class="card" style="margin:8px 0;">' +
      '<div class="field-label" style="margin-top:0;">✏️ タブを編集</div>' +
      '<label class="hint" style="display:block;margin-bottom:2px;">タブ名（長い場合は短く編集できます）</label>' +
      '<input id="candEditName" type="text" autocomplete="off" value="' + esc(tab.name) + '">' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">サークルを貼り替える（任意：ID/サークルURL/作品URL）</label>' +
      '<input id="candEditSrc" type="text" inputmode="url" autocomplete="off" placeholder="変更しないなら空のまま">' +
      '<div style="display:flex;gap:8px;margin-top:8px;">' +
      '<button id="candEditSave" type="button" class="primary" style="flex:1;font-size:.9rem;padding:10px;">保存</button>' +
      '<button id="candEditDel" type="button" class="ghost" style="flex:0 0 auto;width:auto;color:#c0392b;border-color:#c0392b;">タブ削除</button>' +
      '<button id="candEditCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">やめる</button>' +
      '</div><div id="candEditMsg" class="hint" style="min-height:1.3em;"></div></div>';
    $('candEditCancel').addEventListener('click', function () { f.innerHTML = ''; });
    $('candEditDel').addEventListener('click', function () {
      if (!window.confirm('タブ「' + tab.name + '」を削除しますか？(非表示リストも消えます)')) return;
      lsSet(K_TABS, lsGet(K_TABS, '[]').filter(function (t) { return t.id !== tab.id; }));
      try { localStorage.removeItem(hiddenKey(tab.id)); } catch (e) {}
      _activeTab = 'main'; render();
    });
    $('candEditSave').addEventListener('click', function () {
      var name = ($('candEditName').value || '').trim();
      var src = ($('candEditSrc').value || '').trim();
      var msg = $('candEditMsg');
      function applyTab(makerId, makerName) {
        var tabs = lsGet(K_TABS, '[]');
        tabs.forEach(function (t) {
          if (t.id !== tab.id) return;
          t.name = name || makerName || t.name;
          if (makerId) { t.makerId = makerId; if (makerName) t.makerName = makerName; }
        });
        lsSet(K_TABS, tabs);
        render(); // タブバー再描画＋一覧再取得
      }
      if (src) {
        msg.textContent = '⏳ サークルを特定中…';
        resolveMakerId(src, function (makerId, makerName, err) {
          if (!makerId) { msg.textContent = '⚠️ ' + err; return; }
          applyTab(makerId, makerName);
        });
      } else {
        if (!name) { msg.textContent = '⚠️ タブ名を入れてください'; return; }
        applyTab(null, '');
      }
    });
  }

  // 作品カード（候補/サークル共通・縦並び）。actionHtml=右下のボタン(削除/非表示/再表示)。
  function candCard(it, actionHtml) {
    var sale = it.listPrice && it.price && it.discountPct > 0 && it.price < it.listPrice;
    var priceHtml = sale
      ? '<span class="cand-list-price">' + yen(it.listPrice) + '</span> <b class="cand-sale">' + yen(it.price) + '</b> <span class="cand-off">' + it.discountPct + '%off</span>'
      : '<b>' + yen(it.price != null ? it.price : it.listPrice) + '</b>';
    var sub = [];
    if (it.author || it.makerName) sub.push('🏷 ' + esc(it.author || it.makerName));
    if (it.date) sub.push('発売 ' + esc(fmtDate(it.date)));
    if (it.addedAt) sub.push('追加 ' + esc(fmtTs(it.addedAt)));
    var ws = deriveWorkState_(it.date);
    var badgesHtml = ws ? stateBadgeHtml_(ws) : '';
    var genresHtml = (it.genres && it.genres.length)
      ? '<div class="fz-genres" style="margin-top:4px;">' + it.genres.slice(0, 5).map(function (g) { return '<span class="fz-genre">' + esc(g) + '</span>'; }).join('') + '</div>'
      : '';
    // 売れ行きの数値。実売本数(販売数)がPC取得済みなら実数を最優先。無ければレビュー件数(代理指標)。
    var rc = it.reviewCount;
    var avg = (it.reviewAvg != null && it.reviewAvg !== '') ? (' ★' + it.reviewAvg) : '';
    var num = function (n) { return Number(n).toLocaleString('ja-JP'); };
    var sales = salesOf(it.cid); // number=実売 / null=PC未取得 / undefined=未問い合わせ
    var salesHtml = '';
    if (typeof sales === 'number') {
      // 実売本数あり（最優先）
      if (_sort === 'rank7d') {
        var sd = weekSalesDelta(it.cid, sales);
        salesHtml = (sd != null)
          ? '<div class="cand-sales">🔥 直近1週間の販売：<b>+' + num(sd) + '本</b>（累計 ' + num(sales) + '本・実売）</div>'
          : '<div class="cand-sales">💰 販売数：<b>' + num(sales) + '本</b>（実売）<span style="font-weight:400;color:var(--sub);">・週差分は記録が溜まり次第</span></div>';
      } else {
        salesHtml = '<div class="cand-sales">💰 販売数：<b>' + num(sales) + '本</b>（実売）</div>';
      }
    } else if (_sort === 'rank7d') {
      var wd = weekReviewDelta(it.cid, rc);
      if (wd != null) salesHtml = '<div class="cand-sales">🔥 直近1週間の伸び：<b>レビュー +' + num(wd) + '件</b>' + (rc != null ? '（累計' + num(rc) + '件）' : '') + '</div>';
      else if (rc != null) salesHtml = '<div class="cand-sales">🔥 売れ行きの目安：<b>レビュー ' + num(rc) + '件</b>' + avg + '<span style="font-weight:400;color:var(--sub);">（販売数はPC取得待ち）</span></div>';
    } else if (_sort === 'rank' && rc != null) {
      salesHtml = '<div class="cand-sales">🔥 売れ行きの目安：<b>レビュー ' + num(rc) + '件</b>' + avg + '</div>';
    } else if (rc != null && rc > 0) {
      salesHtml = '<div class="cand-sub">レビュー ' + num(rc) + '件' + avg + '</div>';
    }
    return '<div class="cand-card">' +
      (it.thumb ? '<img class="cand-thumb" src="' + esc(it.thumb) + '" loading="lazy" alt="">' : '<div class="cand-thumb cand-thumb-ph"></div>') +
      '<div class="cand-info">' +
        (badgesHtml ? '<div style="margin-bottom:3px;">' + badgesHtml + '</div>' : '') +
        '<div class="cand-title">' + esc(it.title || '(無題)') + '</div>' +
        (sub.length ? '<div class="cand-sub">' + sub.join('　') + '</div>' : '') +
        genresHtml +
        salesHtml +
        '<div class="cand-price">' + priceHtml + '</div>' +
        '<div class="cand-actions">' +
          (it.url ? '<a class="vlink vlink-work" href="' + esc(it.url) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
          '<span style="flex:1 1 auto;"></span>' + // 非表示/再表示/削除ボタンを右端へ寄せる
          actionHtml +
        '</div>' +
      '</div></div>';
  }

  try { window.Go5Cand = { render: render }; } catch (e) {}
}());
