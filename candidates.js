/**
 * candidates.js — 「💡 候補」タブ。(ランキングと予約の間)
 *
 * ① 候補リスト(既定サブタブ):
 *    作品URLを入れると候補として記録。アフィリンク付きURL(al.fanza.co.jp/?lurl=…)でも
 *    素の作品URLへ正規化して保存。作品名/サークル名/サムネ/現在価格/セール◯%offを表示。
 *    複数記録・削除可。データは両アカウント共通。(localStorage: cand_items)
 * ② サークルタブ(＋タブを追加で生成):
 *    特定サークルの全作品を縦一覧表示。並び替え(発売日新/古・売上(人気)・直近1週間で売れてる・値引き率)。
 *    ジャンル・作品状態(新作/準新作/旧作)バッジも表示。各作品に「非表示」、上部「非表示リストを
 *    表示」で再表示可。サークルの特定に必要な入力: サークルID(数字) / サークルページURL
 *    (…article=maker/id=数字…) / そのサークルの作品URL1つ(→APIでサークルIDを自動解決) のどれか1つ。
 *    タブはPC=ドラッグ、スマホ=長押し→ドラッグで並べ替え可。(固定の候補/＋タブを除く)
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
  function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} reqSyncFor_(k); }
  // 同期対象の候補キーが変わったら即時同期を要求。(デバウンス＋最小間隔はGo5Sync側で吸収)
  //   キャッシュ系(cand_sales/cand_mk2 等)では発火させない＝no-op同期の無駄打ちを避ける。
  function reqSync_() { try { if (window.Go5Sync && window.Go5Sync.requestSync) window.Go5Sync.requestSync(); } catch (e) {} }
  function reqSyncFor_(k) { if (/^cand_(items|tabs)(__|$)/.test(k) || /^cand_hidden__/.test(k) || k === 'cand_hide_posted') reqSync_(); }
  // 継続改善制度の行動ログ。(意味のある操作のみ・失敗は無害)
  function klog_(action, objType, objId, meta) { try { if (window.Go5Kaizen) window.Go5Kaizen.log('candidates', action, objType, objId, meta); } catch (e) {} }
  function workerCfg() {
    var u = '', s = '';
    try { u = (localStorage.getItem('fanza_worker_url') || '').trim(); s = (localStorage.getItem('fanza_shared_secret') || '').trim(); } catch (e) {}
    return { url: u.replace(/\/+$/, ''), secret: s };
  }
  function yen(n) { return (n != null && !isNaN(n)) ? '¥' + Number(n).toLocaleString('ja-JP') : '—'; }
  function fmtDate(s) { return String(s || '').slice(0, 10); }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  // 発売日→作品状態。(新作=30日以内/準新作=90日以内/旧作=それ以降)yt-clicks.jsのderiveWorkState_と同ロジック。
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
  // 作品URLのホストで判定：book.dmm.(com|co.jp) = FANZA Books、それ以外(dmm.co.jp同人等) = 同人。(コミックス)
  function workKindOf_(url) { return /book\.dmm\.(com|co\.jp)/i.test(url || '') ? 'Books' : '同人'; }
  function workKindBadgeHtml_(url) {
    var kind = workKindOf_(url);
    return '<span class="fp-kind ' + (kind === 'Books' ? 'fp-kind-books' : 'fp-kind-doujin') + '">' + kind + '</span>';
  }
  // ジャンルタグに「AI」を含むものがあれば AI 作品とみなす。(わかる範囲のベストエフォート判定)
  function isAiWork_(genres) { return (genres || []).some(function (g) { return /AI/i.test(String(g || '')); }); }

  // サークルを表すアイコン。旧「🏷」絵文字の置き換え＝グレーの人物シルエット(添付画像)をSVG化。
  //   白背景は描かない＝透過。width/height=1em で文字サイズに追従。inline-blockで前後の文字と揃う。
  var CIRCLE_ICON = '<svg class="cand-circle-ico" viewBox="0 0 100 100" width="1em" height="1em" aria-hidden="true" focusable="false" style="display:inline-block;vertical-align:-0.15em;">' +
    '<ellipse cx="50" cy="33" rx="25" ry="30" fill="#c2c4c7"/>' +
    '<path fill="#c2c4c7" d="M50 57C33 57 21 64 15 74 10 82 8 91 8 100L92 100C92 91 90 82 85 74 79 64 67 57 50 57Z"/>' +
    '</svg>';
  // サークル名マークを他タブ(投稿履歴/ランキング)でも使えるよう公開(Chami依頼2026-07-14「あのマークを全部のタブに」)。
  try { window.Go5CircleIcon = CIRCLE_ICON; } catch (e) {}

  // ── PC(広い画面)向け：候補カードの列数(ユーザーが選べる・スマホでは無効) ──
  var K_PCCOLS = 'cand_pc_cols';
  var PCCOLS_MIN = 1, PCCOLS_MAX = 5, PCCOLS_DEF = 2;
  function candCols_() { var n = parseInt(lsGet(K_PCCOLS, String(PCCOLS_DEF)), 10); return (n >= PCCOLS_MIN && n <= PCCOLS_MAX) ? n : PCCOLS_DEF; }
  function applyCandCols_(n) { try { document.documentElement.style.setProperty('--cand-cols', String(n)); } catch (e) {} }
  applyCandCols_(candCols_()); // モジュール読み込み時に一度反映(以後は選択時のみ更新)
  // 列数セレクタのHTML。(renderMain/renderMakerの両ヘッダーで共通。PCのみCSSで表示)
  function candColsCtlHtml_() {
    var cur = candCols_(), opts = '';
    for (var n = PCCOLS_MIN; n <= PCCOLS_MAX; n++) opts += '<option value="' + n + '"' + (n === cur ? ' selected' : '') + '>' + n + '列</option>';
    return '<div class="cand-cols-ctl"><label class="hint" style="margin:0;white-space:nowrap;">表示列数</label><select id="candColsSel">' + opts + '</select></div>';
  }
  function wireCandColsCtl_() {
    var sel = $('candColsSel');
    if (sel) sel.addEventListener('change', function () { var n = parseInt(this.value, 10) || PCCOLS_DEF; lsSet(K_PCCOLS, n); applyCandCols_(n); });
  }

  // ── 保存キー ──
  var K_ITEMS = 'cand_items';   // 候補リスト(共通): [{url,cid,title,author,thumb,listPrice,price,discountPct,addedAt}]
  var K_TABS = 'cand_tabs';    // サークルタブ: [{id,name,makerId,makerName}]
  function hiddenKey(tabId) { return 'cand_hidden__' + tabId; }
  // 削除の墓標(トゥームストーン)キー: { cid: 削除ts }。同期で他端末へ伝播し、union後に「削除ts>=addedAt」の候補を
  //   除外する＝「消したものは消えたまま」を成立させる。(再収集は addedAt が新しいので自動復活。INC 2026-07-15)
  function delKey(tabId) { return (!tabId || tabId === 'main') ? 'cand_del' : 'cand_del__' + tabId; }
  function tombstoneCid_(tabId, cid) {
    var k = delKey(tabId), m = lsGet(k, '{}'); if (!m || typeof m !== 'object' || Array.isArray(m)) m = {};
    m[cid] = new Date().getTime(); lsSet(k, m);
  }
  // ★キャッシュ版数(v2)：v170前の「最大400件しか取れていない不完全キャッシュ」を確実に無効化する。
  //   これを上げると全ユーザーの旧キャッシュが読まれなくなり、次回表示で全件を取り直す。
  function cacheKey(makerId, mode) { return 'cand_mk2__' + makerId + '__' + mode; }
  var CACHE_TTL = 3 * 3600 * 1000;
  // 更新サーチ(🔁 force)の最小再取得間隔。この時間内の二度目はキャッシュ再利用で無駄打ちを防ぐ。
  //   FANZAのサークル新作は日単位でしか変わらないため、数十秒内の再取得は情報が同じ＝負荷だけ増える。
  //   🔁は「今すぐ最新に」ボタンなので、連打/焦りの再タップだけを吸収する短めの値にする(値変更はここ1箇所)。
  var MAKER_REFRESH_MIN_MS = 60 * 1000; // 60秒

  var _activeTab = 'main'; // 'main' | サークルタブid
  var _sort = 'added_desc';
  var _showHidden = false;
  var _filterSale = false; // 絞り込み：ONでセール中(値引き)の作品のみ表示
  // 絞り込み：現在価格が _priceMax 円以下の作品のみ表示(0=無効)。localStorageで永続。
  var _priceMax = (function () { try { var n = parseInt(localStorage.getItem('cand_price_max') || '0', 10); return (n > 0) ? n : 0; } catch (e) { return 0; } })();
  // アカウント別「投稿済みを非表示」トグル。(両方同時ONで、いずれかで投稿済みの作品を隠せる)localStorageで永続。
  var _hidePosted = (function () { try { return JSON.parse(localStorage.getItem('cand_hide_posted') || '{}') || {}; } catch (e) { return {}; } })();
  function saveHidePosted_() { try { localStorage.setItem('cand_hide_posted', JSON.stringify(_hidePosted)); } catch (e) {} }
  function isHiddenByPosted_(cid) {
    if (!cid) return false;
    if (_hidePosted.acc1 && postedItemForCid_(cid, 'acc1')) return true;
    if (_hidePosted.acc2 && postedItemForCid_(cid, 'acc2')) return true;
    return false;
  }
  // 「◯◯✔非表示」トグル2つ(非表示リストの上段・右寄せ)のHTML。_ACCTS は描画時に定義済み。
  function candHidePostedRowHtml_() {
    return '<div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;justify-content:flex-end;">' +
      '<button id="candHidePosted1" type="button" class="cand-hidep-toggle' + (_hidePosted.acc1 ? ' active' : '') + '" title="' + esc(_ACCTS[0][1]) + 'で投稿済みの作品を一覧から隠す">' + esc(_ACCTS[0][1]) + '✔非表示</button>' +
      '<button id="candHidePosted2" type="button" class="cand-hidep-toggle' + (_hidePosted.acc2 ? ' active' : '') + '" title="' + esc(_ACCTS[1][1]) + 'で投稿済みの作品を一覧から隠す">' + esc(_ACCTS[1][1]) + '✔非表示</button>' +
    '</div>';
  }
  // 上記トグルの配線。両方独立にON/OFFでき、いずれかで投稿済みなら非表示。(isHiddenByPosted_)
  function wireHidePostedButtons_(rerender) {
    var b1 = $('candHidePosted1'), b2 = $('candHidePosted2');
    if (b1) b1.addEventListener('click', function () { _hidePosted.acc1 = !_hidePosted.acc1; saveHidePosted_(); this.classList.toggle('active', !!_hidePosted.acc1); rerender(); });
    if (b2) b2.addEventListener('click', function () { _hidePosted.acc2 = !_hidePosted.acc2; saveHidePosted_(); this.classList.toggle('active', !!_hidePosted.acc2); rerender(); });
  }
  var _suppressNextClick = false; // タブ並べ替え(ドラッグ/長押し)直後のクリック(タブ切替)を1回だけ抑止
  // 並べ替え対象外の固定タブ。(🦋バズ・💡候補)左端の2つは動かさない。
  function isFixedCandTab_(id) { return id === 'main' || id === 'buzz' || id === 'all'; }

  var SORTS = [
    { key: 'added_desc', label: '追加日が新しい順' },
    { key: 'price_asc', label: '現価格が安い順' },
    { key: 'date_desc', label: '発売日が新しい順' },
    { key: 'date_asc', label: '発売日が古い順' },
    { key: 'rank', label: '売上(人気)が多い順' },
    { key: 'rank7d', label: '直近1週間で売れてる順' },
    { key: 'discount_desc', label: '値引き率が高い順' }
  ];
  // 「直近1週間で売れてる順」の注記。
  var RANK7D_NOTE = '※「直近1週間で売れてる順」は、実売本数(販売数)の週次差分があればそれで、無ければレビュー件数の伸びで並べます。差分は記録が溜まる数日後から出ます。';
  var SALES_NOTE = '※DMMの販売数(実売本数)は日本IPの詳細ページにのみ有り、サーバー(海外IP)からは取得不可のため、PCで「販売数を取得.bat」を実行して取り込みます。(未取得の間はレビュー件数を代理表示)';

  // ── レビュー件数スナップショット(「直近1週間で売れてる順」の差分計算用)──
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
  // 約1週間前のスナップとの差分。(＝直近1週間で増えたレビュー数≒売れた数の近似)基準が新しすぎ/無ければ null。
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

  // ── 実売本数(販売数)：worker/api/fanza-sales(=PC取得→KV)から取得。端末に24hキャッシュ。──
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
  // 未取得cidを worker へ問い合わせ。(＝未取得はPC取得キューへ自動登録)取得できたら cb。(changed,missingCount)
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
  // 指定cidの販売数キャッシュを無効化。(🔁リロードで最新を取り直すため)
  function invalidateSales_(cids) { var c = salesCache(); (cids || []).forEach(function (cid) { delete c[cid]; }); lsSet(K_SALES, c); }

  // ── 候補の「タイトル/発売日 未取得」を自動でバックフィル ──
  //   追加した直後、FANZA workerがその時たまたま部分情報(画像のみ)しか返せなかった作品は
  //   title/date が空のまま残り、作品状態(新作/準新作/旧作)バッジも出ない。販売数(fetchSalesFor)と
  //   同じパターンで、表示のたびに未取得ぶんを控えめに再取得し、取れたら候補データへ書き戻す。
  var K_INFOMISS = 'cand_infomiss'; // {cid: atMs}  直近の再取得試行時刻(無駄打ち防止)
  var INFOMISS_RETRY_TTL = 20 * 60 * 1000; // 同じcidの再試行は20分に1回まで
  function needsInfoBackfill_(it) { return !it || !it.cid || !it.title || it.title === '(タイトル未取得)' || !it.date; }
  function backfillMissingInfo_(key, items, cb) {
    if (!window.FanzaCore) { cb(false); return; }
    var cfg = workerCfg(); if (!cfg.url) { cb(false); return; }
    var miss = lsGet(K_INFOMISS, '{}'), now = new Date().getTime();
    var targets = items.filter(function (it) {
      if (!needsInfoBackfill_(it)) return false;
      var last = miss[it.cid]; return !last || (now - last) >= INFOMISS_RETRY_TTL;
    }).slice(0, 12); // 一度に叩きすぎない(無駄打ち防止・worker保護)
    if (!targets.length) { cb(false); return; }
    var pending = targets.length, updates = {}; // cid -> 取得できた差分フィールド
    targets.forEach(function (it) {
      miss[it.cid] = now;
      window.FanzaCore.fetchFanzaInfo(it.cid, cfg.url, cfg.secret, it.url).then(function (info) {
        if (info && info.title) {
          updates[it.cid] = {
            title: info.title, author: info.author || undefined,
            date: info.releaseDate || undefined, listPrice: info.listPrice, price: info.price,
            discountPct: info.discountPct || undefined, genres: (info.genres && info.genres.length) ? info.genres : undefined,
            thumb: info.thumb || info.thumbSmall || undefined, reviewCount: info.reviewCount, reviewAvg: info.reviewAvg
          };
        }
        if (--pending === 0) finish();
      }).catch(function () { if (--pending === 0) finish(); });
    });
    // ★書き戻しは「今の実際のlocalStorage配列」を読み直してcidで当てる(他の変更を巻き戻さない・
    //   同期の競合ガードと同じ考え方＝古い参照(items)ではなく現在値に対して差分だけ適用)。
    function finish() {
      lsSet(K_INFOMISS, miss);
      var cids = Object.keys(updates);
      if (!cids.length) { cb(false); return; }
      var cur = lsGet(key, '[]'), changed = false;
      cur.forEach(function (it) {
        var u = it && it.cid != null ? updates[it.cid] : null; if (!u) return;
        Object.keys(u).forEach(function (f) { if (u[f] !== undefined) it[f] = u[f]; });
        changed = true;
      });
      if (changed) lsSet(key, cur);
      cb(changed);
    }
  }

  // ── 現在描画中カードの cid→item 索引(サムネ/投稿画像モーダルが item を引くため)──
  var _cardIndex = {};
  function itemByCid_(cid) { return _cardIndex[cid] || null; }

  // ── 作品ごとの保存画像(refimg=生成用の元画像＋コメント＋Twitter URL / bskyimg=Bluesky添付用)──
  //   保存先は IndexedDB。(容量は端末の空きに応じて数百MB〜＝iOS Safariの localStorage 約5MB壁を回避)
  //   読みは同期のままにしたいので、起動時に全画像をメモリ(_imgMem)へハイドレートし以後は同期参照。
  //   書きは _imgMem を即更新＋IDBへ非同期反映。(write-through)IDB非対応時は localStorage フォールバック。
  var _imgMem = { ref: {}, bsky: {}, post: {} };
  var _idbOk = !!(window.Go5Idb && window.Go5Idb.available());
  // ★IDB→メモリへの展開(hydrateImages_)は非同期。完了前は _imgMem が空なので refImgOf() が
  //   「実際にはIDBに在るのに null」を返す=モーダルのpendingが全項目空で作られ、そのまま保存すると
  //   refImgSaveのempty判定に入り【画像もコメントも削除】されていた。(Chami報告2026-07-17
  //   「動画生成へ進むと候補用画像とコメントが候補から消える・作り直せない」の真因。画像が多い/重い
  //   ほど展開が遅く、間欠的に発火する。commit 2a16fceが直したのは別件=書込完了待ちで、この競合は
  //   残っていたためChamiの「多分治ってない」は正しかった)
  //   → 展開の完了フラグと待ち合わせを持ち、(1)未展開のうちは破壊的な空保存を拒否 (2)モーダルは
  //     展開を待ってから開く、の二段で防ぐ。
  var _hydrated = false;
  var _hydrateWaiters = [];
  function markHydrated_() { _hydrated = true; _hydrateWaiters.splice(0).forEach(function (f) { try { f(); } catch (e) {} }); }
  function whenImagesReady_(cb) {                 // 展開済みなら即時、未了なら完了時に呼ぶ(最大3秒で諦めて続行)
    if (_hydrated || !_idbOk) { cb(); return; }
    var done = false, fire = function () { if (done) return; done = true; cb(); };
    _hydrateWaiters.push(fire);
    setTimeout(fire, 3000);                       // 保険(展開が異常に遅い/失敗しても操作は止めない)
  }
  function refImgKey(cid) { return 'cand_refimg__' + cid; }   // localStorage互換キー(フォールバック/移行用)
  function bskyImgKey(cid) { return 'cand_bskyimg__' + cid; }
  function idbKey(kind, cid) { return kind + ':' + cid; }     // IDBキー 'ref:<cid>' / 'bsky:<cid>'
  function idbFail_(e) { try { console.warn('[go5 idb] 画像保存に失敗(メモリには保持)', e); } catch (_) {} }

  function refImgOf(cid) {
    if (_idbOk) return _imgMem.ref[cid] || null;
    try { return JSON.parse(localStorage.getItem(refImgKey(cid)) || 'null'); } catch (e) { return null; }
  }
  // 保存画像を常に配列で返す。(旧形式 {img:単発} → [img] に正規化・新形式は {imgs:[...]}. 37ページ級の複数コマ保持に対応)
  function refImgsOf_(cid) {
    var r = refImgOf(cid); if (!r) return [];
    if (Array.isArray(r.imgs)) return r.imgs.filter(Boolean);
    return r.img ? [r.img] : [];
  }
  function refImgHas(cid) {
    var r = refImgOf(cid); if (!r) return false; // 1回の読みで判定(フォールバック時の多重JSON.parse回避)
    var has = Array.isArray(r.imgs) ? r.imgs.some(Boolean) : !!r.img;
    return !!(has || r.comment || r.memo || r.twitterUrl || r.twitterUrl2);
  }
  function refImgSave(cid, data) {
    // data.imgs(配列・新)または data.img(単発・旧)を受け付け、{imgs, img:先頭} で保存。(img は旧読み手互換用)
    var imgs = data ? (Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : (data.img ? [data.img] : [])) : [];
    var empty = !data || (!imgs.length && !data.comment && !data.memo && !data.twitterUrl && !data.twitterUrl2);
    // ★展開前(_imgMemが空)の「空データ=削除」は、読めていないだけの既存データを消す事故になる。
    //   未展開のうちは破壊的な空保存を拒否する。(明示削除はUIから展開後に行われるので実害なし)
    if (empty && _idbOk && !_hydrated) { try { console.warn('[go5 cand] 画像展開前の空保存を拒否(既存データ保護)', cid); } catch (e) {} return false; }
    var rec = empty ? null : { imgs: imgs, img: imgs[0] || '', comment: data.comment || '', memo: data.memo || '', twitterUrl: data.twitterUrl || '', twitterUrl2: data.twitterUrl2 || '', at: new Date().getTime() };
    if (_idbOk) {
      if (rec) _imgMem.ref[cid] = rec; else delete _imgMem.ref[cid];
      // IDB書込みのPromiseを返す(常にtruthy=従来のtrueと同じ扱いで既存の if(okRef)/if(!refImgSave()) と互換)。
      // 呼び出し元が画面遷移の前に書込み完了を確認したい場合は await/.then() できる(例: #refImgToMovie)。
      var p = (rec ? window.Go5Idb.set(idbKey('ref', cid), rec) : window.Go5Idb.del(idbKey('ref', cid))).catch(idbFail_);
      reqSync_(); // 参照画像(動画生成用)の保存直後に即時同期＝他端末で即反映(画像はR2へ)
      if (rec) klog_('ref_image_saved', 'work', cid, { imgs: imgs.length });
      return p; // IDBは容量に余裕。非同期失敗は稀(メモリ保持＋ログ)
    }
    try {
      if (!rec) { localStorage.removeItem(refImgKey(cid)); return true; }
      localStorage.setItem(refImgKey(cid), JSON.stringify(rec));
      return true;
    } catch (e) { return false; } // 容量超過など
  }

  function bskyImgOf(cid) {
    if (_idbOk) return _imgMem.bsky[cid] || null;
    try { return JSON.parse(localStorage.getItem(bskyImgKey(cid)) || 'null'); } catch (e) { return null; }
  }
  function bskyImgHas(cid) { var r = bskyImgOf(cid); return !!(r && r.img); }
  function bskyImgSave(cid, img) {
    if (!img && _idbOk && !_hydrated) { try { console.warn('[go5 cand] 画像展開前の空保存を拒否(既存データ保護)', cid); } catch (e) {} return false; } // refImgSaveと同じ理由
    var rec = img ? { img: img, at: new Date().getTime() } : null;
    if (_idbOk) {
      if (rec) _imgMem.bsky[cid] = rec; else delete _imgMem.bsky[cid];
      (rec ? window.Go5Idb.set(idbKey('bsky', cid), rec) : window.Go5Idb.del(idbKey('bsky', cid))).catch(idbFail_);
      reqSync_(); // Bluesky添付画像の保存直後にも即時同期
      return true;
    }
    try {
      if (!rec) { localStorage.removeItem(bskyImgKey(cid)); return true; }
      localStorage.setItem(bskyImgKey(cid), JSON.stringify(rec));
      return true;
    } catch (e) { return false; }
  }

  // ── 投稿画像(🛠️編集で後付け添付・履歴アイテム単位＝videoId/itemKey をキーに複数枚保存)──
  //   作品cid単位の refimg(動画の元画像)とは別系統。1枚目が投稿履歴カードに表示され、タップで全枚数をズーム。
  function postImgsOf_(key) {
    if (!key) return [];
    var r = _idbOk ? _imgMem.post[key] : (function () { try { return JSON.parse(localStorage.getItem('hist_postimg__' + key) || 'null'); } catch (e) { return null; } })();
    return (r && Array.isArray(r.imgs)) ? r.imgs.filter(Boolean) : [];
  }
  function postImgSave_(key, imgs) {
    if (!key) return false;
    imgs = (imgs || []).filter(Boolean);
    // ★refImgSave/bskyImgSaveと同じ穴(v=349で塞ぎ忘れていた3つ目のストア)。post画像も同じ
    //   非同期IDB系なので、展開前は postImgsOf_ が「実際は在るのにnull」を返す=空で保存すると
    //   既存の投稿画像を削除してしまう。未展開中の破壊的な空保存を拒否する。(B-2棚卸しで発見)
    if (!imgs.length && _idbOk && !_hydrated) { try { console.warn('[go5 cand] 画像展開前の空保存を拒否(既存データ保護)', key); } catch (e) {} return false; }
    var rec = imgs.length ? { imgs: imgs, at: new Date().getTime() } : null;
    if (_idbOk) {
      if (rec) _imgMem.post[key] = rec; else delete _imgMem.post[key];
      (rec ? window.Go5Idb.set(idbKey('post', key), rec) : window.Go5Idb.del(idbKey('post', key))).catch(idbFail_);
      return true;
    }
    try {
      var lk = 'hist_postimg__' + key;
      if (!rec) { localStorage.removeItem(lk); return true; }
      localStorage.setItem(lk, JSON.stringify(rec));
      return true;
    } catch (e) { return false; } // 容量超過など
  }

  // 起動時：IDBから全画像をメモリへ + localStorageの旧画像をIDBへ移行して5MB枠を解放。
  function hydrateImages_() {
    if (!_idbOk) return;
    window.Go5Idb.entries().then(function (all) {
      Object.keys(all || {}).forEach(function (k) {
        var v = all[k];
        if (k.indexOf('ref:') === 0) _imgMem.ref[k.slice(4)] = v;
        else if (k.indexOf('bsky:') === 0) _imgMem.bsky[k.slice(5)] = v;
        else if (k.indexOf('post:') === 0) _imgMem.post[k.slice(5)] = v;
      });
      return migrateLocalImages_();
    }).then(function () {
      markHydrated_(); // ここから先は _imgMem が真値=空保存の拒否を解除し、待たせていたモーダルを進める
      // 画像がメモリに載ったので、候補タブ表示中なら描画し直す。(サムネ・✓バッジを反映)
      try { var pc = document.getElementById('pageCand'); if (pc && !pc.hidden) render(); } catch (e) {}
    }).catch(function (e) {
      // オープン/読み取りに失敗＝この環境ではIDB不可。localStorageフォールバックへ切り替え。(旧データはそのまま読める)
      _idbOk = false; try { console.warn('[go5 idb] 利用不可のためlocalStorageで継続', e); } catch (_) {}
      markHydrated_(); // localStorageは同期で読める=以後は待たせない・拒否もしない
    });
  }
  // localStorage の cand_refimg__* / cand_bskyimg__* を IDB へ移して localStorage から削除。(冪等・IDB書込成功後にのみ削除＝データロス防止)
  function migrateLocalImages_() {
    var keys = [];
    try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (k && (k.indexOf('cand_refimg__') === 0 || k.indexOf('cand_bskyimg__') === 0)) keys.push(k); } } catch (e) {}
    var jobs = keys.map(function (k) {
      var isRef = k.indexOf('cand_refimg__') === 0;
      var cid = k.slice(isRef ? 'cand_refimg__'.length : 'cand_bskyimg__'.length);
      var val; try { val = JSON.parse(localStorage.getItem(k) || 'null'); } catch (e) { val = null; }
      if (!val) { try { localStorage.removeItem(k); } catch (e) {} return Promise.resolve(); }
      if (isRef) _imgMem.ref[cid] = val; else _imgMem.bsky[cid] = val;
      return window.Go5Idb.set(idbKey(isRef ? 'ref' : 'bsky', cid), val)
        .then(function () { try { localStorage.removeItem(k); } catch (e) {} })
        .catch(idbFail_); // 失敗時はlocalStorageに残す(次回再試行)
    });
    return Promise.all(jobs);
  }
  // クリップボードの文字列を対象inputへ貼り付け。([data-paste=inputId] のボタンを配線)
  function wirePaste_(root) {
    (root || document).querySelectorAll('.paste-btn[data-paste]').forEach(function (b) {
      if (b._wired) return; b._wired = true;
      b.addEventListener('click', function () {
        var inp = document.getElementById(b.getAttribute('data-paste')); if (!inp) return;
        var orig = b.textContent;
        function restore(label) { b.textContent = label || orig; if (label) setTimeout(function () { b.textContent = orig; }, 1600); }
        if (navigator.clipboard && navigator.clipboard.readText) {
          b.textContent = '読み取り中…'; // 即時の視覚反応(「押しても無反応」を無くす)
          var settled = false;
          // iOSは画面に出る「ペースト」許可をタップしないと readText が返らないことがある→タイムアウトで案内
          var timer = setTimeout(function () { if (settled) return; settled = true; restore(); inp.focus(); alert('クリップボードを読み取れませんでした。iOSでは表示される「ペースト」の吹き出しをタップしてください。入力欄の長押し貼り付けも使えます。'); }, 8000);
          navigator.clipboard.readText().then(function (t) {
            if (settled) return; settled = true; clearTimeout(timer);
            t = (t || '').trim();
            if (!t) { restore(); inp.focus(); alert('クリップボードが空か、読み取りが許可されませんでした。入力欄を長押しして貼り付けてください。'); return; }
            inp.value = t; inp.focus();
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            restore('✓ 貼り付け');
          }).catch(function () {
            if (settled) return; settled = true; clearTimeout(timer);
            restore(); inp.focus(); alert('クリップボードを読み取れませんでした。入力欄を長押しして貼り付けてください。');
          });
        } else { inp.focus(); alert('この環境ではボタン貼り付けに未対応です。入力欄を長押しして貼り付けてください。'); }
      });
    });
  }
  // input要素のHTMLに「📋貼り付け」ボタンを横付けした行を返す。(inputはflex:1で伸びる)
  function pasteRow_(inputHtml, inputId) {
    return '<div style="display:flex;gap:6px;align-items:stretch;">' + inputHtml +
      '<button type="button" class="ghost paste-btn" data-paste="' + inputId + '" title="コピー中の文字を貼り付け" style="flex:0 0 auto;width:max-content;margin:0;white-space:nowrap;padding:0 12px;">貼り付け</button></div>';
  }
  // 画像ファイル→縮小dataURL。(長辺1280px・JPEG)localStorage肥大とQuota超過を防ぐ。
  function fileToScaledDataUrl(file, cb) {
    if (!file || !/^image\//.test(file.type || '')) { cb(null, '画像ファイルを選んでください'); return; }
    var fr = new FileReader();
    fr.onload = function () {
      var im = new Image();
      im.onload = function () {
        var max = 1280, w = im.naturalWidth || im.width, h = im.naturalHeight || im.height;
        if (w > max || h > max) { var s = max / Math.max(w, h); w = Math.round(w * s); h = Math.round(h * s); }
        try {
          var cv = document.createElement('canvas'); cv.width = w; cv.height = h;
          cv.getContext('2d').drawImage(im, 0, 0, w, h);
          cb(cv.toDataURL('image/jpeg', 0.85), null);
        } catch (e) { cb(fr.result, null); }
      };
      im.onerror = function () { cb(null, '画像を読み込めませんでした'); };
      im.src = fr.result;
    };
    fr.onerror = function () { cb(null, 'ファイルを読み込めませんでした'); };
    fr.readAsDataURL(file);
  }
  // クリップボードにコピーされた画像を取り出して縮小dataURLで返す。cb。(dataUrl, err)
  function pasteImageFromClipboard_(cb) {
    if (!(navigator.clipboard && navigator.clipboard.read)) { cb(null, 'この端末では画像の貼り付けに未対応です(「画像を選ぶ」をお使いください)'); return; }
    navigator.clipboard.read().then(function (items) {
      for (var i = 0; i < items.length; i++) {
        var t = (items[i].types || []).filter(function (x) { return /^image\//.test(x); })[0];
        if (t) { items[i].getType(t).then(function (blob) { fileToScaledDataUrl(blob, cb); }).catch(function () { cb(null, '画像を取り出せませんでした'); }); return; }
      }
      cb(null, 'クリップボードに画像がありません(先に画像をコピーしてください)');
    }).catch(function () { cb(null, 'クリップボードを読み取れませんでした(貼り付けの許可が必要です)'); });
  }

  // ── サンプル画像キャッシュ(サムネモーダル用。cid毎にサンプルURL配列を保持)──
  var K_SAMPLES = 'cand_samples';
  function samplesCacheGet(cid) { var c = lsGet(K_SAMPLES, '{}')[cid]; return (c && Array.isArray(c.imgs)) ? c : null; }
  function samplesCacheSet(cid, imgs, thumb) { var all = lsGet(K_SAMPLES, '{}'); all[cid] = { imgs: imgs || [], thumb: thumb || '', at: new Date().getTime() }; lsSet(K_SAMPLES, all); }

  // ── サムネ/サンプル画像モーダル(投稿履歴の詳細ビューと同じ .fz-* を流用したライトボックス)──
  var _imgOverlay = null;
  function ensureImgOverlay_() {
    if (_imgOverlay) return _imgOverlay;
    var ov = document.createElement('div'); ov.className = 'fz-overlay'; ov.hidden = true;
    ov.innerHTML = '<div class="fz-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
    document.body.appendChild(ov);
    ov.addEventListener('click', function (e) { if (e.target === ov) ov.hidden = true; });
    ov.querySelector('.fz-close').addEventListener('click', function () { ov.hidden = true; });
    _imgOverlay = ov; return ov;
  }
  function renderImgModal_(title, big, samples, note) {
    var ov = ensureImgOverlay_();
    var gallery = []; if (big) gallery.push(big); (samples || []).forEach(function (s) { gallery.push(s); });
    var sBase = big ? 1 : 0;
    ov.querySelector('.fz-body').innerHTML =
      '<div class="fz-title">' + esc(title || '(無題)') + '</div>' +
      (big ? '<div class="fz-hero"><img class="fz-zoomable" data-z="0" src="' + esc(big) + '" alt="タップで拡大"></div>' : '') +
      (samples && samples.length
        ? '<div class="fz-samples">' + samples.map(function (s, i) { return '<img class="fz-zoomable" data-z="' + (sBase + i) + '" src="' + esc(s) + '" alt="" loading="lazy">'; }).join('') + '</div>'
        : (note ? '<div class="hint" style="text-align:center;padding:6px 0 2px;">' + esc(note) + '</div>' : ''));
    ov.querySelectorAll('.fz-zoomable').forEach(function (im) { im.addEventListener('click', function () { openImgZoom_(gallery, parseInt(im.getAttribute('data-z'), 10) || 0); }); });
    ov.hidden = false;
  }
  function openThumbModal_(it) {
    if (!it) return;
    var big = it.thumb || '';
    if (it.samples && it.samples.length) { renderImgModal_(it.title, big, it.samples); return; }
    var cached = samplesCacheGet(it.cid);
    if (cached && cached.imgs.length) { renderImgModal_(it.title, cached.thumb || big, cached.imgs); return; }
    renderImgModal_(it.title, big, null, '⏳ サンプル画像を取得中…');
    var cfg = workerCfg();
    if (window.FanzaCore && cfg.url && it.cid) {
      window.FanzaCore.fetchFanzaInfo(it.cid, cfg.url, cfg.secret, it.url).then(function (info) {
        if (_imgOverlay && _imgOverlay.hidden) return; // 閉じられていたら反映しない
        if (info && info.samples && info.samples.length) {
          samplesCacheSet(it.cid, info.samples, info.thumb || big);
          renderImgModal_(it.title, info.thumb || big, info.samples);
        } else { renderImgModal_(it.title, big, null, 'この作品にはサンプル画像がありません。'); }
      }).catch(function () { if (_imgOverlay && !_imgOverlay.hidden) renderImgModal_(it.title, big, null, 'サンプル画像を取得できませんでした。'); });
    } else { renderImgModal_(it.title, big, null, 'サンプル画像の取得にはFANZA Workerの設定が必要です。'); }
  }
  // 画像ズーム。(左右スワイプで切替).fz-zoom を流用。
  var _zoom = null, _zoomList = [], _zi = 0, _zoomReorder = null, _zoomAdd = null, _zoomCaps = null; // _zoomCaps=各ページの見出し(画像の上に表示・投稿履歴の「動画生成で使用した画像」等)
  function ensureZoom_() {
    if (_zoom) return _zoom;
    var z = document.createElement('div'); z.className = 'fz-zoom'; z.hidden = true;
    z.innerHTML = '<button class="fz-zoom-close" type="button" aria-label="閉じる">✕</button>' +
      '<button class="fz-zoom-tofirst" type="button" hidden>この画像を1ページ目にする</button>' +
      '<button class="fz-zoom-add" type="button" hidden>＋ 画像を貼り付けて新規追加</button>' +
      '<div class="fz-zoom-cap" hidden></div><img class="fz-zoom-img" alt=""><div class="fz-zoom-count"></div><div class="fz-zoom-msg"></div>';
    document.body.appendChild(z);
    z.addEventListener('click', function (e) { if (e.target === z) z.hidden = true; });
    z.querySelector('.fz-zoom-close').addEventListener('click', function () { z.hidden = true; });
    // 「この画像を1ページ目にする」＝表示中(2ページ目以降)の画像を先頭へ。旧1ページ目は2ページ目へずれる。
    z.querySelector('.fz-zoom-tofirst').addEventListener('click', function () {
      if (!_zoomReorder || _zi <= 0) return;
      var nl = _zoomReorder(_zi);
      if (nl && nl.length) { _zoomList = nl.slice(); _zi = 0; zoomShow_(); }
    });
    // 「画像を貼り付けて新規追加」＝クリップボードの画像を挿入・保存し、1ページ目に表示。(投稿編集と同じ保存先に同期)
    z.querySelector('.fz-zoom-add').addEventListener('click', function () {
      if (!_zoomAdd) return;
      var msg = z.querySelector('.fz-zoom-msg'); if (msg) msg.textContent = '貼り付け中…';
      _zoomAdd(function (nl, err) {
        if (nl && nl.length) { _zoomList = nl.slice(); _zi = 0; zoomShow_(); if (msg) msg.textContent = '1ページ目に追加しました'; setTimeout(function () { if (msg) msg.textContent = ''; }, 1400); }
        else if (msg) { msg.textContent = err || '画像を貼り付けできませんでした'; setTimeout(function () { if (msg) msg.textContent = ''; }, 2200); }
      });
    });
    var sx = null, sy = null;
    z.addEventListener('touchstart', function (e) { var t = e.changedTouches[0]; sx = t.clientX; sy = t.clientY; }, { passive: true });
    z.addEventListener('touchend', function (e) {
      if (sx == null) return; var t = e.changedTouches[0], dx = t.clientX - sx, dy = t.clientY - sy;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) zoomGo_(dx < 0 ? 1 : -1);
      sx = sy = null;
    }, { passive: true });
    _zoom = z; return z;
  }
  function zoomShow_() {
    var z = ensureZoom_();
    z.querySelector('.fz-zoom-img').src = _zoomList[_zi] || '';
    z.querySelector('.fz-zoom-count').textContent = _zoomList.length ? (_zi + 1) + ' / ' + _zoomList.length : ''; // 画像の下に「現在 / 総ページ数」を白字で常時表示
    var cap = z.querySelector('.fz-zoom-cap'); // 画像の上の見出し(このページの画像が何に使われたか)
    if (cap) { var ct = (_zoomCaps && _zoomCaps[_zi]) || ''; cap.textContent = ct; cap.hidden = !ct; }
    var tf = z.querySelector('.fz-zoom-tofirst'); if (tf) tf.hidden = !(_zoomReorder && _zi > 0); // 2ページ目以降だけ表示
    var ab = z.querySelector('.fz-zoom-add'); if (ab) ab.hidden = !_zoomAdd; // 貼り付け追加が可能な文脈でのみ表示
    z.hidden = false;
  }
  function zoomGo_(d) { if (!_zoomList.length) return; _zi = (_zi + d + _zoomList.length) % _zoomList.length; zoomShow_(); }
  // opts.onReorder(currentIdx) で「1ページ目にする」ボタン、opts.onPasteAdd(done) で「貼り付けて新規追加」ボタンを出す。
  //   onPasteAdd はクリップボード画像を先頭へ追加・保存し done(新画像配列, err) を呼ぶ。(先頭＝新しい1ページ目)
  function openImgZoom_(images, idx, opts) {
    if (!images || !images.length) return;
    _zoomReorder = (opts && typeof opts.onReorder === 'function') ? opts.onReorder : null;
    _zoomAdd = (opts && typeof opts.onPasteAdd === 'function') ? opts.onPasteAdd : null;
    _zoomCaps = (opts && Array.isArray(opts.captions)) ? opts.captions.slice() : null; // ページ別見出し(任意)
    _zoomList = images.slice(); _zi = Math.min(Math.max(0, idx || 0), _zoomList.length - 1); zoomShow_();
  }
  // 「画像を貼り付けて新規追加」：クリップボード画像を cid の refimg 先頭へ追加・保存し一覧再描画。(投稿編集と同じ保存先に同期)
  function pasteAddRefImgToFirst_(cid, done) {
    pasteImageFromClipboard_(function (durl, err) {
      if (err || !durl) { done(null, err || '画像がコピーされていません'); return; }
      var cur = refImgOf(cid) || {}, imgs = refImgsOf_(cid);
      imgs.unshift(durl); // 先頭＝1ページ目
      refImgSave(cid, { imgs: imgs, comment: cur.comment, memo: cur.memo, twitterUrl: cur.twitterUrl, twitterUrl2: cur.twitterUrl2 });
      try { if (_activeTab) render(); } catch (e) {}
      done(imgs.slice(), null);
    });
  }
  // refimg(投稿編集の保存画像)の並べ替え：cidの画像配列で i 番目を先頭へ移動＋保存＋一覧再描画。返り値＝新配列。
  function reorderRefImgToFirst_(cid, i) {
    var cur = refImgOf(cid) || {}, imgs = refImgsOf_(cid);
    if (i <= 0 || i >= imgs.length) return imgs;
    var img = imgs.splice(i, 1)[0]; imgs.unshift(img); // 先頭へ＝旧1ページ目は2ページ目へずれる
    refImgSave(cid, { imgs: imgs, comment: cur.comment, memo: cur.memo, twitterUrl: cur.twitterUrl, twitterUrl2: cur.twitterUrl2 });
    try { if (_activeTab) render(); } catch (e) {}
    return imgs;
  }

  var _ACCTS = [['acc1', '月詠み'], ['acc2', '宵桜艶帖']];
  // ── 投稿履歴の cid→item 索引(チャンネル別・メモ化) ──
  //   候補cidは buildAffiliateLink(normalizeWorkUrl(raw)) の出力。履歴側も同じ正規化→解析で
  //   cidを求めないと、アフィリンク付きURL(al.fanza.co.jp/?lurl=…)や計測パラメータ付きURLが
  //   silentに紐付かない(投稿済みpillが光らない)不具合になる。索引は履歴配列の「件数＋先頭ts」
  //   を鍵にメモ化し、新規投稿が入れば自動で作り直す。(フルリロード不要)
  var _postedIdxCache = {}; // { account: { sig: string, map: {cid:item} } }
  // 履歴アイテムから作品cidを求める。(複数経路)順に: 明示cidフィールド → workUrlを正規化+解析 → cid形状の推定。
  function cidOfHistItem_(it) {
    if (!it) return '';
    // ① 明示的な cid フィールド。(将来の復元でシートの作品cidを串刺しで持たせた場合)
    var direct = it.cid || it.workCid || '';
    if (direct) return String(direct);
    // ② 作品URL → normalizeWorkUrl(lurl展開・計測パラメータ除去)→ buildAffiliateLink で候補と同じcidを得る。
    var u = it.workUrl || '';
    if (u && window.buildAffiliateLink) {
      var url = window.normalizeWorkUrl ? window.normalizeWorkUrl(u) : u;
      var r = url ? window.buildAffiliateLink(url, '') : null;
      if (r && r.ok && r.cid) return r.cid;
    }
    return '';
  }
  // チャンネルの cid→item 索引を(必要なら作り直して)返す。
  function postedIndexFor_(account) {
    if (typeof window.Go5PostedItems !== 'function') return {};
    var items = window.Go5PostedItems(account) || [];
    var sig = items.length + ':' + ((items[0] && items[0].ts) || '') + ':' + ((items[items.length - 1] && items[items.length - 1].ts) || '');
    var cached = _postedIdxCache[account];
    if (cached && cached.sig === sig) return cached.map;
    var map = {};
    for (var i = 0; i < items.length; i++) {
      var cid = cidOfHistItem_(items[i]);
      if (cid && !map[cid]) map[cid] = items[i]; // 先頭＝新しい順なので最新の投稿を優先
    }
    _postedIdxCache[account] = { sig: sig, map: map };
    return map;
  }
  // 索引を明示的に無効化。(一覧描画の起点で呼び、確実に新規投稿を拾う)
  function invalidatePostedIndex_() { _postedIdxCache = {}; }
  // 指定アカウントの投稿履歴(short_hist)＋手動追加(verify_manual)から、この作品(cid)のエントリを全て外す。
  //   「このアカウントでは投稿していないのに投稿済み判定になる」誤検出を、内容を確認した上で解消する用途。
  function removePostedForAcct_(cid, account) {
    if (!cid || !account) return 0;
    var removed = 0;
    ['short_hist__', 'verify_manual__'].forEach(function (pre) {
      var key = pre + account, arr;
      try { arr = JSON.parse(localStorage.getItem(key) || '[]') || []; } catch (e) { arr = []; }
      var kept = arr.filter(function (x) { return cidOfHistItem_(x) !== cid; });
      if (kept.length !== arr.length) {
        removed += (arr.length - kept.length);
        try { localStorage.setItem(key, JSON.stringify(kept)); } catch (e) {}
      }
    });
    invalidatePostedIndex_();
    return removed;
  }
  // この作品(cid)を、指定チャンネルで投稿した投稿履歴アイテムを返す。(cid照合・無ければ null)
  function postedItemForCid_(cid, account) {
    if (!cid) return null;
    return postedIndexFor_(account)[cid] || null;
  }
  // バッジ行に並べるチャンネル表記。投稿済み＝ボタン化(クリックで投稿詳細)＋テーマ色。未投稿＝ボタン化せず淡色表記。
  function acctBadgesHtml_(cid) {
    return _ACCTS.map(function (a) {
      var posted = !!postedItemForCid_(cid, a[0]);
      if (posted) {
        return '<span class="cand-acct-pill cand-acct-' + a[0] + ' posted" role="button" tabindex="0" ' +
          'data-posted-acct="' + a[0] + '" data-posted-cid="' + esc(cid) + '" title="' + esc(a[1]) + 'で投稿済み(タップで投稿内容)">' +
          esc(a[1]) + ' <b>✔</b></span>';
      }
      return '<span class="cand-acct-pill cand-acct-' + a[0] + ' notposted" title="' + esc(a[1]) + '(未投稿)">' + esc(a[1]) + '</span>';
    }).join('');
  }
  // 投稿履歴アイテムから投稿日時(ms)を頑健に取り出す。ts欠落時も背骨ID(videoId=acc-YYYYMMDD-HHMM-)から復元
  //   ＝「月詠み✔なのに投稿日が出ない」バグの根治。(シート復元でpostedAt空・手動移動でtsが0/欠落でも日付が出る)
  function postedTsOf_(it) {
    if (!it) return 0;
    if (it.ts && it.ts > 0) return it.ts;
    var cand = it.postedAt || it.posted_at || it.at;
    if (cand) { var p = (typeof cand === 'number') ? cand : Date.parse(cand); if (p) return p; }
    if (window.IdGen && window.IdGen.tsOfId) { var t = window.IdGen.tsOfId(it.videoId); if (t) return t; }
    return 0;
  }
  // 投稿済み作品：Books等のバッジとチャンネルpillの間に、投稿日(YYYY/M/D)+✔ をチャンネルテーマ色で表示。
  function postedDatesHtml_(cid) {
    return _ACCTS.map(function (a) {
      var it = postedItemForCid_(cid, a[0]);
      if (!it) return '';
      var ts = postedTsOf_(it);
      if (!ts) return ''; // 日時が全経路で取れない稀ケースのみ非表示
      var d = new Date(ts);
      var ds = d.getFullYear() + '/' + (d.getMonth() + 1) + '/' + d.getDate();
      return '<span class="cand-posted-date cand-acct-' + a[0] + '" title="' + esc(a[1]) + 'で ' + esc(ds) + ' に投稿済み">' + esc(ds) + ' ✔</span>';
    }).join('');
  }
  // Bluesky公開APIから、その投稿に添付された画像URL配列を取得。(未認証・CORS)cb。(images[]|null)
  function fetchPostImages_(postUri, cb) {
    if (!postUri) { cb(null); return; }
    fetch('https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts?uris=' + encodeURIComponent(postUri))
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var post = j && j.posts && j.posts[0];
        var emb = post && post.embed;
        var imgs = (emb && emb.images) ? emb.images.map(function (im) { return im.fullsize || im.thumb; }).filter(Boolean) : [];
        cb(imgs);
      }).catch(function () { cb(null); });
  }
  // 投稿詳細モーダル：投稿済みチャンネルのpillをタップ→いつ/何で投稿したか(履歴内容＋実際の投稿画像)を表示。
  var _postedOverlay = null;
  function openPostedDetailModal_(cid, account, label) {
    var it = postedItemForCid_(cid, account); if (!it) return;
    var ov = _postedOverlay;
    if (!ov) {
      ov = document.createElement('div'); ov.className = 'fz-overlay'; ov.hidden = true;
      ov.innerHTML = '<div class="fz-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) ov.hidden = true; });
      ov.querySelector('.fz-close').addEventListener('click', function () { ov.hidden = true; });
      _postedOverlay = ov;
    }
    var when = it.ts ? fmtTs(it.ts) : '(日時不明)';
    var rows = '';
    function row(k, v) { return v ? '<div class="pd-row"><span class="pd-k">' + k + '</span><span class="pd-v">' + v + '</span></div>' : ''; }
    rows += row('投稿日時', esc(when));
    // 題名末尾のハッシュタグ(#マンガ紹介 等のYTタグ)は投稿詳細では省略して見やすく。
    var cleanTitle = String(it.title || '').replace(/(\s*#[^\s#]+)+\s*$/, '').trim();
    rows += row('題名', esc(cleanTitle));
    if (it.goal) rows += row('狙い', esc(it.goal));
    if (it.cmtType) rows += row('コメント型', esc(it.cmtType));
    if (it.workState) rows += row('作品状態', esc(it.workState));
    var link = it.postUrl || it.shareUrl || it.shortUrl || '';
    if (link) rows += row('投稿', '<a href="' + esc(link) + '" target="_blank" rel="noopener" style="color:#1d9bf0;">Blueskyで開く↗</a>');
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      '<div class="fz-title" style="background:#fffef9;color:#111;padding:8px 12px;border-radius:8px;margin:2px 34px 10px 0;">' + esc(label) + ' で投稿済み</div>' +
      rows +
      '<div class="pd-imgs-label hint" style="margin-top:8px;">投稿した画像</div>' +
      '<div id="pdImgs" class="pd-imgs"><div class="hint">⏳ 画像を取得中…</div></div>' +
      // 誤検出の解消：このアカウントで実際には投稿していない場合、この作品の判定(履歴)を外す。
      '<button id="pdRemove" type="button" class="ghost" style="width:max-content;margin-top:14px;font-size:12.5px;color:#c0392b;border-color:#c0392b;">🚫 ' + esc(label) + 'では投稿していない(この判定を消す)</button>' +
      '<div class="hint" style="margin-top:4px;">この作品を「' + esc(label) + '」の投稿履歴から外します。(誤検出の解消用)実際の投稿記録が消えるので、投稿済みが正しい場合は押さないでください。</div>';
    ov.hidden = false;
    var rmBtn = ov.querySelector('#pdRemove');
    if (rmBtn) rmBtn.addEventListener('click', function () {
      if (!window.confirm('「' + cleanTitle + '」を ' + label + ' の投稿履歴から外します。\nランキングや投稿履歴タブからも消えます。よろしいですか？')) return;
      var n = removePostedForAcct_(cid, account);
      ov.hidden = true;
      try { render(); } catch (e) {} // 候補一覧を再描画＝pillが「未投稿」表示に戻る
    });
    // 実際の投稿画像を取得。(無ければ候補に保存済みの画像でフォールバック)
    fetchPostImages_(it.postUri, function (imgs) {
      var box = ov.querySelector('#pdImgs'); if (!box) return;
      var list = (imgs && imgs.length) ? imgs : refImgsOf_(cid);
      if (!list || !list.length) { box.innerHTML = '<div class="hint">画像を取得できませんでした。</div>'; return; }
      box.innerHTML = list.map(function (src) { return '<img class="pd-img fz-zoomable" src="' + esc(src) + '" loading="lazy" alt="投稿画像">'; }).join('');
      box.querySelectorAll('.pd-img').forEach(function (im, i) { im.addEventListener('click', function () { openImgZoom_(list.slice(), i); }); });
    });
  }
  // カードの「投稿済みpill」の配線：タップで投稿詳細モーダル。(未投稿pillは data-posted-acct を持たない＝無反応)
  function wireAcctRow_(root) {
    root.querySelectorAll('[data-posted-acct]').forEach(function (b) {
      var handler = function (e) { e.stopPropagation(); var a = b.getAttribute('data-posted-acct'), c = b.getAttribute('data-posted-cid'); var lbl = (a === 'acc2') ? '宵桜艶帖' : '月詠み'; openPostedDetailModal_(c, a, lbl); };
      b.addEventListener('click', handler);
      b.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(e); } });
    });
  }

  // ── 投稿画像モーダル(複数画像＋メモを保存)──
  var _refOverlay = null;
  var _refOpenSeq = 0; // モーダルを開くたびに増える通し番号(遅い非同期処理が古いpendingへ書き込むのを防ぐ)
  function openRefImgModal_(it, onSaved) {
    if (!it) return;
    // ★画像の展開(IDB→メモリ)が終わる前に開くと、pendingが空で作られ「動画生成へ/保存」で
    //   既存の画像・コメントを消してしまう。展開を待ってから開く。(Chami報告2026-07-17の真因)
    if (_idbOk && !_hydrated) { whenImagesReady_(function () { openRefImgModal_(it, onSaved); }); return; }
    var mySeq = ++_refOpenSeq;
    var ov = _refOverlay;
    if (!ov) {
      ov = document.createElement('div'); ov.className = 'fz-overlay'; ov.hidden = true;
      ov.innerHTML = '<div class="fz-modal refimg-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) ov.hidden = true; });
      ov.querySelector('.fz-close').addEventListener('click', function () { ov.hidden = true; });
      _refOverlay = ov;
    }
    var cur = refImgOf(it.cid) || {};
    var curImgs = Array.isArray(cur.imgs) ? cur.imgs.filter(Boolean) : (cur.img ? [cur.img] : []);
    // pending.imgs=保存候補の画像列(複数可・37ページ級の連続貼り付けOK)・idx=表示中(「動画生成へ」で採用される1枚)
    // X/Bluesky URL は refimg 側に無ければ候補アイテム側(it.twitterUrl=カードのXリンクの出所)からフォールバック
    //   。(カードにXリンクが出ているのにモーダルの欄が空になる不一致を防ぐ)
    var pending = { imgs: curImgs.slice(), idx: 0, comment: cur.comment || '', twitterUrl: cur.twitterUrl || it.twitterUrl || '', memo: cur.memo || '', twitterUrl2: cur.twitterUrl2 || '' };
    var isTw = !!(it.isTwitter || it.twitterUrl); // Twitterのみ候補(埋め込みポストURLあり)
    // 作品URLのプレフィル：候補が実際に作品URLを持つ(!isTwitter かつ it.url がDMM/book等)なら、
    //   twitterUrl の有無に関わらずそのまま欄に表示。(＝カードの「作品↗」と同じ判定)X起点(it.url=ポストURL)は空。
    var workUrlPrefill = (!it.isTwitter && it.url) ? it.url : '';
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      '<div class="fz-title refimg-title" style="background:none;color:#fff;padding:0 36px 0 0;margin:0 0 6px;font-weight:700;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">' + esc(it.title || it.cid) + '</div>' +
      // PC(広い画面)専用：メモ・2つ目URLをボタンを押さず直接編集できる列。(CSSで左列に配置・保存ボタンで一緒に反映)
      // スマホはCSSで非表示のまま＝従来どおり「メモ・URL追加」ボタンから小モーダルで編集。
      '<div class="refimg-pc-memo">' +
        '<label class="hint" style="display:block;margin-bottom:2px;">メモ</label>' +
        '<input id="refImgMemoInline" type="text" class="cand-refimg-line" autocomplete="off" placeholder="メモ(コメントが無い時にカードへ水色で表示)">' +
        '<label class="hint" style="display:block;margin:10px 0 2px;">X / Bluesky URL(2つ目・カードに X2↗ / B2↗ で表示)</label>' +
        '<div style="display:flex;gap:6px;align-items:stretch;">' +
          '<input id="refImgUrl2Inline" type="text" inputmode="url" class="cand-refimg-line" autocomplete="off" placeholder="2つ目のX/Bluesky URLを貼り付け" style="flex:1;min-width:0;">' +
          '<button type="button" class="ghost paste-btn" data-paste="refImgUrl2Inline" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
        '</div>' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">' +
        '<span class="hint" style="margin:0;flex:1;">動画生成用の画像</span>' +
        '<button id="refImgToMovie" type="button" class="primary" style="width:auto;margin:0;flex:0 0 auto;font-size:13px;padding:8px 14px;">動画生成へ</button>' +
      '</div>' +
      '<div id="refImgPreview" class="cand-refimg-preview"></div>' +
      '<div class="cand-img-btnrow">' +
        '<label class="ghost cand-refimg-pick">画像を選ぶ<input id="refImgFile" type="file" accept="image/*" multiple style="display:none;"></label>' +
        '<button id="refImgPaste" type="button" class="ghost" style="background:#fffef9;color:#111;border-color:#d8d2bf;">画像を貼り付け</button>' +
        '<button id="refImgClear" type="button" class="ghost cand-img-clear" style="background:#fffef9;color:#111;border-color:#d8d2bf;">消す</button>' +
      '</div>' +
      '<label class="hint" style="display:block;margin-bottom:2px;">コメント</label>' +
      '<input id="refImgComment" type="text" class="cand-refimg-line" autocomplete="off" placeholder="コメント">' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">X / Bluesky URL</label>' +
      '<div style="display:flex;gap:6px;align-items:stretch;">' +
        '<input id="refImgTwitter" type="text" inputmode="url" class="cand-refimg-line" autocomplete="off" placeholder="https://x.com/… " style="flex:1;min-width:0;">' +
        '<button type="button" class="ghost paste-btn" data-paste="refImgTwitter" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
      '</div>' +
      '<label class="hint" style="display:block;margin:10px 0 2px;font-size:11px;white-space:nowrap;">アフィリンク付き作品URLを貼ると、正式な作品URLに自動変換</label>' +
      '<div style="display:flex;gap:6px;align-items:stretch;">' +
        '<input id="refImgWorkUrl" type="text" inputmode="url" class="cand-refimg-line" autocomplete="off" placeholder="作品URLを貼り付け" value="' + esc(workUrlPrefill) + '" style="flex:1;min-width:0;">' +
        '<button type="button" class="ghost paste-btn" data-paste="refImgWorkUrl" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:10px;align-items:stretch;">' +
        '<button id="refImgSave" type="button" class="primary" style="flex:2;">保存</button>' +
        '<button id="refMemoAdd" type="button" class="cand-memo-addbtn" style="flex:1;" title="メモとX/Bluesky URLを追加"><span class="cma-stack"><span>メモ</span><span>URL</span></span><span class="cma-add">追加</span></button>' +
        '<button id="refImgCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">閉じる</button>' +
      '</div><div id="refImgMsg" class="hint" style="min-height:1.2em;"></div>';
    var previewEl = body.querySelector('#refImgPreview');
    function navTo(i) { var n = pending.imgs.length; if (!n) return; pending.idx = (i + n) % n; drawPreview(); }
    function drawPreview() {
      var n = pending.imgs.length;
      if (pending.idx >= n) pending.idx = Math.max(0, n - 1);
      if (!n) { previewEl.innerHTML = '<div class="hint" style="text-align:center;padding:18px;border:1px dashed var(--line);border-radius:8px;">画像は未保存です(貼り付けで追加・複数枚OK)</div>'; return; }
      previewEl.innerHTML =
        '<div class="cand-refimg-stage">' +
          '<img src="' + esc(pending.imgs[pending.idx]) + '" alt="" class="fz-zoomable" style="max-width:100%;max-height:40vh;border-radius:8px;border:1px solid var(--line);display:block;margin:0 auto;">' +
          (n > 1 ? '<button type="button" class="cand-refimg-nav prev" aria-label="前へ">‹</button><button type="button" class="cand-refimg-nav next" aria-label="次へ">›</button>' : '') +
        '</div>' +
        '<div class="hint" style="text-align:center;margin-top:3px;">' +
          (n > 1 ? '🖼 複数あり ' + (pending.idx + 1) + ' / ' + n + '(スワイプで切替・<b>表示中の画像が「動画生成へ」で使われます</b>)' : '画像 1枚') +
        '</div>';
      previewEl.querySelector('img').addEventListener('click', function () {
        openImgZoom_(pending.imgs.slice(), pending.idx, {
          onReorder: function (i) {
            if (i <= 0 || i >= pending.imgs.length) return pending.imgs.slice();
            var img = pending.imgs.splice(i, 1)[0]; pending.imgs.unshift(img); pending.idx = 0; drawPreview(); // 旧1枚目は2枚目へずれる(保存で確定)
            return pending.imgs.slice();
          },
          onPasteAdd: function (done) {
            pasteImageFromClipboard_(function (durl, err) {
              if (err || !durl) { done(null, err || '画像がコピーされていません'); return; }
              pending.imgs.unshift(durl); pending.idx = 0; drawPreview(); // 先頭＝1ページ目(保存で確定)
              done(pending.imgs.slice(), null);
            });
          }
        });
      });
      var pv = previewEl.querySelector('.prev'), nx = previewEl.querySelector('.next');
      if (pv) pv.addEventListener('click', function (e) { e.stopPropagation(); navTo(pending.idx - 1); });
      if (nx) nx.addEventListener('click', function (e) { e.stopPropagation(); navTo(pending.idx + 1); });
    }
    // プレビュー上の左右スワイプで切替(ズーム(fz-zoom)側は既存実装でスワイプ対応済み)。
    var _tsx = null, _tsy = null;
    previewEl.addEventListener('touchstart', function (e) { var t = e.changedTouches[0]; _tsx = t.clientX; _tsy = t.clientY; }, { passive: true });
    previewEl.addEventListener('touchend', function (e) {
      if (_tsx == null) return; var t = e.changedTouches[0], dx = t.clientX - _tsx, dy = t.clientY - _tsy; _tsx = _tsy = null;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) navTo(pending.idx + (dx < 0 ? 1 : -1));
    }, { passive: true });
    drawPreview();
    body.querySelector('#refImgComment').value = pending.comment;
    body.querySelector('#refImgTwitter').value = pending.twitterUrl;
    body.querySelector('#refImgMemoInline').value = pending.memo || '';
    body.querySelector('#refImgUrl2Inline').value = pending.twitterUrl2 || '';
    body.querySelector('#refImgFile').addEventListener('change', function () {
      var files = [], fl = this.files || [], fi;
      for (fi = 0; fi < fl.length; fi++) files.push(fl[fi]);
      this.value = '';
      if (!files.length) return;
      body.querySelector('#refImgMsg').textContent = '画像を処理中…(' + files.length + '枚)';
      // 1枚ずつ順に処理。(大量選択時のメモリ圧迫を防ぐ・選択順も保たれる)
      var added = 0, failed = 0, batch = [];
      (function step(i) {
        if (mySeq !== _refOpenSeq) return; // モーダルが開き直された＝この処理結果は破棄
        if (i >= files.length) {
          if (added) { pending.imgs = batch.concat(pending.imgs); pending.idx = 0; } // ★追加画像を先頭(1枚目)へ(標準)
          drawPreview();
          body.querySelector('#refImgMsg').textContent = added
            ? (added + '枚を追加しました(先頭＝1枚目に配置)' + (failed ? '(' + failed + '枚は読み込めず)' : '') + '(計' + pending.imgs.length + '枚・保存で確定)')
            : '画像を読み込めませんでした';
          return;
        }
        fileToScaledDataUrl(files[i], function (durl) {
          if (mySeq !== _refOpenSeq) return;
          if (durl) { batch.push(durl); added++; } else failed++;
          step(i + 1);
        });
      })(0);
    });
    body.querySelector('#refImgPaste').addEventListener('click', function () {
      body.querySelector('#refImgMsg').textContent = '画像を貼り付け中…';
      pasteImageFromClipboard_(function (durl, err) {
        if (mySeq !== _refOpenSeq) return; // モーダルが開き直された＝破棄
        if (err) { body.querySelector('#refImgMsg').textContent = err; return; }
        pending.imgs.unshift(durl); pending.idx = 0; drawPreview(); // ★追加画像を先頭(1枚目)へ(置換せず追加・複数枚OK)
        body.querySelector('#refImgMsg').textContent = '貼り付けました。(1枚目に追加・計' + pending.imgs.length + '枚)続けて貼り付けできます(保存で確定)';
      });
    });
    body.querySelector('#refImgClear').addEventListener('click', function () {
      var n = pending.imgs.length;
      if (!n) { drawPreview(); return; }
      if (!window.confirm(n > 1 ? ('表示中の画像(' + (pending.idx + 1) + '/' + n + ')を削除しますか？') : '本当に画像を削除しますか？')) return;
      pending.imgs.splice(pending.idx, 1);
      if (pending.idx >= pending.imgs.length) pending.idx = Math.max(0, pending.imgs.length - 1);
      drawPreview();
      body.querySelector('#refImgMsg').textContent = '画像を削除しました(保存で確定・残り' + pending.imgs.length + '枚)';
    });
    // PC専用インライン欄(メモ・2つ目URL)を pending へ取り込む。(ボタンを押さず保存/動画生成へで一緒に反映)
    //   スマホはCSSでこの欄自体を表示しない＝値は常に空文字のまま→pending.memo/twitterUrl2を上書きしない
    //   。(非表示要素の空値でモバイル利用中の「メモ・URL追加」小モーダルの内容を消さないための安全策)
    function syncPcMemoInline_() {
      var memoEl = body.querySelector('#refImgMemoInline'), url2El = body.querySelector('#refImgUrl2Inline');
      if (memoEl && memoEl.offsetParent !== null) pending.memo = memoEl.value || '';
      if (url2El && url2El.offsetParent !== null) pending.twitterUrl2 = (url2El.value || '').trim();
    }
    // 動画生成へ：このモーダルの作品データを動画作成タブへ引き継いで移動する。
    body.querySelector('#refImgToMovie').addEventListener('click', function () {
      pending.comment = body.querySelector('#refImgComment').value || '';
      pending.twitterUrl = (body.querySelector('#refImgTwitter').value || '').trim();
      syncPcMemoInline_();
      var workVal = (body.querySelector('#refImgWorkUrl') && body.querySelector('#refImgWorkUrl').value || '').trim();
      if (!workVal && !it.isTwitter && it.url) workVal = it.url; // 欄が空でも候補が作品URLを持つなら使う(動画側へ確実に反映)
      var workUrl = workVal ? (window.normalizeWorkUrl ? window.normalizeWorkUrl(workVal) : workVal) : '';
      // 画像・コメントの保存完了を待ってから遷移(IDB書込みがfire-and-forgetのまま画面遷移で
      // 取りこぼされないように・完了確認)。okでもエラーでもPromiseは必ず解決するため待ち逃げしない。
      Promise.resolve(refImgSave(it.cid, pending)).then(function () {
        transferToMovie_(it, pending.imgs[pending.idx] || '', pending.comment, workUrl); // ★表示中の画像を採用
        if (onSaved) onSaved();
        ov.hidden = true;
      });
    });
    body.querySelector('#refImgCancel').addEventListener('click', function () { ov.hidden = true; });
    // メモ・URL追加：親の入力を pending に取り込んでから小モーダルを開く。(親の未保存入力を失わない)
    body.querySelector('#refMemoAdd').addEventListener('click', function () {
      pending.comment = body.querySelector('#refImgComment').value || '';
      pending.twitterUrl = (body.querySelector('#refImgTwitter').value || '').trim();
      openMemoUrlModal_(it.cid, pending, body, onSaved);
    });
    body.querySelector('#refImgSave').addEventListener('click', function () {
      pending.comment = body.querySelector('#refImgComment').value || '';
      pending.twitterUrl = (body.querySelector('#refImgTwitter').value || '').trim();
      syncPcMemoInline_();
      var workRaw = (body.querySelector('#refImgWorkUrl') && body.querySelector('#refImgWorkUrl').value || '').trim();
      // 作品URL欄が空、またはプレフィル値から変更が無ければ何もしない。(無駄なAPI呼び出し/意図しないaddedAtリセットを防止)
      if (workRaw && workRaw !== workUrlPrefill) {
        body.querySelector('#refImgMsg').textContent = isTw ? '作品候補に変換中…' : '作品URLを更新中…';
        applyWorkUrl_(it, workRaw, pending, function (ok, err) {
          if (!ok) { body.querySelector('#refImgMsg').textContent = (err || '変換できません'); return; }
          body.querySelector('#refImgMsg').textContent = isTw ? '作品候補に変換しました' : '作品URLを更新しました';
          if (onSaved) onSaved();
          if (_activeTab) render();
          setTimeout(function () { ov.hidden = true; }, 700);
        });
        return;
      }
      if (!refImgSave(it.cid, pending)) { body.querySelector('#refImgMsg').textContent = '保存できません(このブラウザの保存枠が不足。古い候補の画像を「消す」で減らしてください)'; return; }
      body.querySelector('#refImgMsg').textContent = '保存しました';
      if (onSaved) onSaved();
      setTimeout(function () { ov.hidden = true; }, 600);
    });
    wirePaste_(body);
    ov.hidden = false;
  }

  // ── メモ＋X/Bluesky URL 追加モーダル(投稿編集モーダルから開く小モーダル・縦は内容に応じて短め)──
  //   メモはコメントが無い時にカードへ水色で表示。URLは「2つ目のURL」(twitterUrl2)＝親の1つ目とは別枠。
  //   記録するとカードで1つ目リンクの横に X2↗ / B2↗(Blueskyは B)が出る。既存URLはここには入れない。(空欄)
  var _memoOverlay = null;
  function openMemoUrlModal_(cid, pending, mainBody, onSaved) {
    var ov = _memoOverlay;
    if (!ov) {
      ov = document.createElement('div'); ov.className = 'fz-overlay memo-overlay'; ov.hidden = true;
      ov.innerHTML = '<div class="fz-modal memo-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) ov.hidden = true; });
      ov.querySelector('.fz-close').addEventListener('click', function () { ov.hidden = true; });
      _memoOverlay = ov;
    }
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      '<div class="fz-title" style="background:none;color:#fff;padding:0 36px 0 0;margin:0 0 10px;font-weight:700;">メモ・URLを追加</div>' +
      '<label class="hint" style="display:block;margin-bottom:2px;">メモ</label>' +
      '<input id="memoText" type="text" class="cand-refimg-line" autocomplete="off" placeholder="メモ(コメントが無い時にカードへ水色で表示)">' +
      '<label class="hint" style="display:block;margin:10px 0 2px;">X / Bluesky URL(2つ目・カードに X2↗ / B2↗ で表示)</label>' +
      '<div style="display:flex;gap:6px;align-items:stretch;">' +
        '<input id="memoUrl" type="text" inputmode="url" class="cand-refimg-line" autocomplete="off" placeholder="2つ目のX/Bluesky URLを貼り付け" style="flex:1;min-width:0;">' +
        '<button type="button" class="ghost paste-btn" data-paste="memoUrl" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:14px;">' +
        '<button id="memoSave" type="button" class="primary" style="flex:1;">保存</button>' +
        '<button id="memoClose" type="button" class="ghost" style="flex:0 0 auto;width:auto;">閉じる</button>' +
      '</div><div id="memoMsg" class="hint" style="min-height:1.2em;"></div>';
    body.querySelector('#memoText').value = pending.memo || '';
    body.querySelector('#memoUrl').value = pending.twitterUrl2 || ''; // ★2つ目のURL＝既存(1つ目)は入れず空欄で開始
    wirePaste_(body);
    body.querySelector('#memoClose').addEventListener('click', function () { ov.hidden = true; });
    body.querySelector('#memoSave').addEventListener('click', function () {
      pending.memo = body.querySelector('#memoText').value || '';
      pending.twitterUrl2 = (body.querySelector('#memoUrl').value || '').trim(); // 2つ目のURLとして保存(親の1つ目には触れない)
      if (!refImgSave(cid, pending)) { body.querySelector('#memoMsg').textContent = '保存できません(保存枠不足)'; return; }
      body.querySelector('#memoMsg').textContent = '保存しました';
      if (onSaved) onSaved();
      try { if (_activeTab) render(); } catch (e) {}
      setTimeout(function () { ov.hidden = true; }, 600);
    });
    ov.hidden = false;
  }
  // 動画作成タブへ切替え、候補の作品データ(前景画像/作者/コメント/作品URL)を各入力欄へ埋め込む。
  //   ※drafts.js の applyDraft_ と同じ手法：#author/#top/#movieWorkUrl を値+イベントで設定、
  //     前景画像は data-URL→File にして window.Go5SetForegroundFile() で #photo に反映。
  function transferToMovie_(it, imgDataUrl, comment, workUrl) {
    var mv = document.getElementById('tabMovie'); if (mv) mv.click(); // affiliate.js の showTab へ委譲
    // input と change の両方を発火：キャンバス再描画は change を、YouTube題名(ytTitle)の再構築は input を聴くため、
    // 片方だけだと題名が前作のまま更新されない。(コメント→題名の反映漏れ)両方投げて確実に上書きする。
    function setVal(id, val) {
      var el = document.getElementById(id);
      if (el && val != null) {
        el.value = val;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
    setVal('author', it.author || '');   // 作者＝サークル名
    setVal('top', comment || '');         // コメント(＝YouTube題名の素。無ければ空で上書き＝前作の題名を残さない)
    // 新規作成の初期化: カテゴリ+狙い+コメント型+リビルド+2行モードを前作から引き継がずリセット。
    // カテゴリは候補が持つジャンルで即時自動チェック。(ジャンル未取得ならFANZA取得が後から自動チェックする)
    if (window.Go5NewMovieReset) window.Go5NewMovieReset();
    else if (window.Go5MovieAttrs) window.Go5MovieAttrs.reset();
    if (window.Go5MovieAttrs && it.genres && it.genres.length) window.Go5MovieAttrs.applyGenres(it.genres, it.cid || '');
    if (workUrl) setVal('movieWorkUrl', workUrl); // 作品URL(正規化済み)
    // 割引率・金額を候補が保持する実データから販促ラベルへ直接反映する(Chami依頼2026-07-18)。
    //   従来は movieWorkUrl のセット→FANZA再取得(fetchMovieWorkInfo)頼みで、worker未設定/取得失敗時は
    //   bluesky.js:1539で早期returnしnotifyが呼ばれず、ラベルが該当作品の値を読まず不一致になっていた。
    //   候補は追加/更新時に該当作品の listPrice/price/discountPct を保持済み=これを直接渡せば即一致。
    //   cidは workUrl 由来で算出し、後続 fetchMovieWorkInfo の begin(cid) と一致させる(値を消させない)。
    //   worker再取得が成功すれば現行価格で上書き(それも該当作品の値)=いずれにせよ前作の値は残らない。
    try {
      if (window.Go5PromoLabel && window.Go5PromoLabel.notify && (it.price != null || it.listPrice != null)) {
        var _pr = (workUrl && window.buildAffiliateLink) ? window.buildAffiliateLink(workUrl, '') : null;
        var _pcid = (_pr && _pr.ok) ? _pr.cid : (it.cid || '');
        window.Go5PromoLabel.notify({ cid: _pcid, title: it.title || '作品', listPrice: it.listPrice, price: it.price, discountPct: it.discountPct || 0 });
      }
    } catch (e) {}
    if (imgDataUrl && window.Go5SetForegroundFile) {
      fetch(imgDataUrl).then(function (r) { return r.blob(); }).then(function (blob) {
        window.Go5SetForegroundFile(new File([blob], 'candidate.jpg', { type: blob.type || 'image/jpeg' }));
      }).catch(function () {});
    }
    // U-2「一気に作成」：作品データを流し込んだら、作成ボタンまで運んで光らせる＝残り1タップ。(行動量支援)
    focusMakeButton_();
  }
  // 作成ボタン(#makeBtn)を画面内へスクロール＋一時ハイライト＋フォーカス。無ければ先頭へ。
  function focusMakeButton_() {
    setTimeout(function () {
      var mk = document.getElementById('makeBtn');
      if (!mk) { try { window.scrollTo(0, 0); } catch (e) {} return; }
      try { mk.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) { try { window.scrollTo(0, 0); } catch (e2) {} }
      try { mk.focus({ preventScroll: true }); } catch (e) {}
      mk.classList.add('cta-ready-pulse');
      setTimeout(function () { mk.classList.remove('cta-ready-pulse'); }, 2400);
    }, 260); // タブ切替の描画が終わってから
  }
  // 保存直後に、その候補カードのサムネ＋コメント/メモを即時反映。(一覧を全再描画せず＝スクロール位置を保つ)
  //   ★コメント/メモは candCard と同一構造(cand-comment-row / cand-manage-row)で組み直し fitOneLineTexts_ で
  //     1行化する＝「保存直後に改行、リロードで直る」不整合を解消。(INC)
  function updateCardRefThumb_(cardEl, cid) {
    if (!cardEl) return;
    var col = cardEl.querySelector('.cand-thumbcol');
    if (col) {
      var imgs = refImgsOf_(cid), src = imgs[0] || '';
      var thumb = col.querySelector('.cand-refimg-thumb');
      var badge = col.querySelector('.cand-refimg-multi');
      if (src) {
        if (!thumb) {
          thumb = document.createElement('img');
          thumb.className = 'cand-refimg-thumb';
          thumb.setAttribute('data-refimgview', cid);
          thumb.setAttribute('loading', 'lazy');
          thumb.alt = '動画生成用の画像(タップで拡大)';
          thumb.title = '動画生成用の画像(タップで拡大)';
          thumb.addEventListener('click', function () { var a = refImgsOf_(cid); if (a.length) openImgZoom_(a, 0, { onReorder: function (i) { return reorderRefImgToFirst_(cid, i); }, onPasteAdd: function (done) { pasteAddRefImgToFirst_(cid, done); } }); });
          col.appendChild(thumb);
        }
        thumb.src = src;
        thumb.classList.toggle('multi', imgs.length > 1); // 複数あり＝アンバー枠で表現(バッジ表記は廃止)
        if (badge && badge.parentNode) badge.parentNode.removeChild(badge); // 旧バッジの掃除
      } else {
        if (thumb && thumb.parentNode) thumb.parentNode.removeChild(thumb);
        if (badge && badge.parentNode) badge.parentNode.removeChild(badge);
      }
      var stray = col.querySelector('.cand-refimg-comment'); // 旧構造(サムネ列に折り返すコメント)の名残を掃除
      if (stray && stray.parentNode) stray.parentNode.removeChild(stray);
    }
    syncCardLower_(cardEl, cid);
  }
  // カード下部(コメント行＋メモ/非表示・🗑行)を candCard と同一構造で組み直す。
  //   非表示/🗑ボタンはノードごと移動してリスナーを温存。最後に fitOneLineTexts_ で必ず1行化。
  function syncCardLower_(cardEl, cid) {
    var info = cardEl.querySelector('.cand-info'), actions = cardEl.querySelector('.cand-actions');
    if (!info || !actions) return;
    var rr = refImgOf(cid) || {}, cmt = rr.comment || '', memo = rr.memo || '';
    var noComment = !cmt && !memo;
    var actionBtns = [].slice.call(cardEl.querySelectorAll('.cand-hide-btn')); // 非表示/再表示/🗑(リスナー保持のため移動)
    // 旧: コメント行/管理行/旧メモdiv/作品リンク行内のスペーサを撤去(ボタンは上で確保済み)
    [].slice.call(cardEl.querySelectorAll('.cand-comment-row, .cand-manage-row, .cand-refimg-memo, .cand-actions-mspacer'))
      .forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
    cardEl.classList.toggle('cand-nocomment', noComment);
    if (noComment) {
      var sp = document.createElement('span'); sp.className = 'cand-actions-mspacer'; actions.appendChild(sp);
      actionBtns.forEach(function (b) { actions.appendChild(b); }); // 作品リンク行の右端へ統合
    } else {
      if (cmt) {
        var crow = document.createElement('div'); crow.className = 'cand-comment-row';
        var cspan = document.createElement('span'); cspan.className = 'cand-manage-comment'; cspan.textContent = cmt;
        crow.appendChild(cspan); cardEl.appendChild(crow);
      }
      var mrow = document.createElement('div'); mrow.className = 'cand-manage-row';
      if (memo) { var mspan = document.createElement('span'); mspan.className = 'cand-manage-memo'; mspan.textContent = memo; mrow.appendChild(mspan); }
      else { var msp = document.createElement('span'); msp.className = 'cand-manage-spacer'; mrow.appendChild(msp); }
      actionBtns.forEach(function (b) { mrow.appendChild(b); });
      cardEl.appendChild(mrow);
    }
    fitOneLineTexts_(cardEl);
  }
  // 候補(Twitter起点/DMM起点どちらも)に作品URLを適用：正規化した作品URLへ変換/更新し、画像・メモ・Twitter URLを引き継ぐ。(旧項目を置換)
  function applyWorkUrl_(oldItem, workUrlRaw, refData, cb) {
    var url = window.normalizeWorkUrl ? window.normalizeWorkUrl(workUrlRaw) : (workUrlRaw || '').trim();
    var r = (url && window.buildAffiliateLink) ? window.buildAffiliateLink(url, '') : null;
    if (!r || !r.ok) { cb(false, 'FANZAの作品URLではないようです'); return; }
    var tabId = _activeTab, key = itemsKey(tabId), items = lsGet(key, '[]'), oldCid = oldItem.cid;
    if (r.cid !== oldCid && items.some(function (x) { return x.cid === r.cid; })) { cb(false, 'この作品は既に追加されています(重複追加しません)'); return; }
    // 画像・コメント・メモ・Twitter URL(1つ目/2つ目)を新cidへ移す(★memo/twitterUrl2も引き継ぐ・旧実装は落としていた)
    var okRef = refImgSave(r.cid, { imgs: Array.isArray(refData.imgs) ? refData.imgs : (refData.img ? [refData.img] : []), comment: refData.comment || '', memo: refData.memo || '', twitterUrl: refData.twitterUrl || oldItem.twitterUrl || '', twitterUrl2: refData.twitterUrl2 || '' });
    var bimg = (bskyImgOf(oldCid) || {}).img;
    var okB = bimg ? bskyImgSave(r.cid, bimg) : true;
    // 新cidへの保存が成功した時だけ旧cidを消す(localStorageフォールバック時の容量超過で唯一のコピーを失わない)
    if (oldCid !== r.cid && okRef && okB) { refImgSave(oldCid, null); bskyImgSave(oldCid, null); }
    var newItem = { url: url, cid: r.cid, twitterUrl: refData.twitterUrl || oldItem.twitterUrl || '', title: '(タイトル未取得)', addedAt: oldItem.addedAt || new Date().getTime() };
    var idx = -1; items.forEach(function (x, i) { if (x.cid === oldCid) idx = i; });
    if (idx >= 0) items[idx] = newItem; else items.unshift(newItem);
    lsSet(key, items);
    var cfg = workerCfg();
    var finish = function (info) {
      var arr = lsGet(key, '[]');
      arr.forEach(function (x) {
        if (x.cid !== r.cid || !info || !info.title) return;
        x.title = info.title; x.author = info.author || ''; x.thumb = info.thumb || info.thumbSmall || '';
        x.listPrice = info.listPrice; x.price = info.price; x.discountPct = info.discountPct || 0;
        x.date = info.releaseDate || ''; x.genres = info.genres || [];
        x.reviewCount = info.reviewCount; x.reviewAvg = info.reviewAvg;
        if (info.samples && info.samples.length) x.samples = info.samples;
      });
      lsSet(key, arr); recordReviewSnapshots(arr); cb(true);
    };
    if (window.FanzaCore && cfg.url) window.FanzaCore.fetchFanzaInfo(r.cid, cfg.url, cfg.secret, url).then(function (info) { finish(info && info.title ? info : null); }).catch(function () { finish(null); });
    else finish(null);
  }

  // ── Bluesky添付画像モーダル(1枚を保存。投稿画像とは別枠)──
  var _bskyOverlay = null;
  function openBskyImgModal_(it, onSaved) {
    if (!it) return;
    var ov = _bskyOverlay;
    if (!ov) {
      ov = document.createElement('div'); ov.className = 'fz-overlay'; ov.hidden = true;
      ov.innerHTML = '<div class="fz-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) ov.hidden = true; });
      ov.querySelector('.fz-close').addEventListener('click', function () { ov.hidden = true; });
      _bskyOverlay = ov;
    }
    var pending = { img: (bskyImgOf(it.cid) || {}).img || '' };
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      '<div class="fz-title">🦋 Bluesky添付画像 ／ ' + esc(it.title || it.cid) + '</div>' +
      '<div class="hint" style="margin-bottom:8px;">Bluesky投稿時に<b>添付する画像</b>を1枚保存できます。</div>' +
      '<div id="bskyImgPreview" class="cand-refimg-preview"></div>' +
      '<div class="cand-img-btnrow">' +
        '<label class="ghost cand-refimg-pick">🖼 画像を選ぶ<input id="bskyImgFile" type="file" accept="image/*" style="display:none;"></label>' +
        '<button id="bskyImgPaste" type="button" class="ghost">📋 画像を貼り付け</button>' +
        '<button id="bskyImgClear" type="button" class="ghost cand-img-clear">消す</button>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:10px;">' +
        '<button id="bskyImgSave" type="button" class="primary" style="flex:1;">保存</button>' +
        '<button id="bskyImgCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">閉じる</button>' +
      '</div><div id="bskyImgMsg" class="hint" style="min-height:1.2em;"></div>';
    var previewEl = body.querySelector('#bskyImgPreview');
    function drawPreview() { previewEl.innerHTML = pending.img ? '<img src="' + pending.img + '" alt="" class="fz-zoomable" style="max-width:100%;max-height:40vh;border-radius:8px;border:1px solid var(--line);">' : '<div class="hint" style="text-align:center;padding:18px;border:1px dashed var(--line);border-radius:8px;">画像は未保存です</div>'; if (pending.img) { var z = previewEl.querySelector('img'); z.addEventListener('click', function () { openImgZoom_([pending.img], 0); }); } }
    drawPreview();
    body.querySelector('#bskyImgFile').addEventListener('change', function () {
      var f = this.files && this.files[0]; if (!f) return;
      body.querySelector('#bskyImgMsg').textContent = '⏳ 画像を処理中…';
      fileToScaledDataUrl(f, function (durl, err) {
        if (err) { body.querySelector('#bskyImgMsg').textContent = '⚠️ ' + err; return; }
        pending.img = durl; drawPreview(); body.querySelector('#bskyImgMsg').textContent = '画像を差し替えました(保存で確定)';
      });
    });
    body.querySelector('#bskyImgPaste').addEventListener('click', function () {
      body.querySelector('#bskyImgMsg').textContent = '⏳ 画像を貼り付け中…';
      pasteImageFromClipboard_(function (durl, err) {
        if (err) { body.querySelector('#bskyImgMsg').textContent = '⚠️ ' + err; return; }
        pending.img = durl; drawPreview(); body.querySelector('#bskyImgMsg').textContent = 'コピー画像を貼り付けました(保存で確定)';
      });
    });
    body.querySelector('#bskyImgClear').addEventListener('click', function () { pending.img = ''; drawPreview(); body.querySelector('#bskyImgMsg').textContent = '画像を消しました(保存で確定)'; });
    body.querySelector('#bskyImgCancel').addEventListener('click', function () { ov.hidden = true; });
    body.querySelector('#bskyImgSave').addEventListener('click', function () {
      if (!bskyImgSave(it.cid, pending.img)) { body.querySelector('#bskyImgMsg').textContent = '⚠️ 保存できません(このブラウザの保存枠が不足。古い候補の画像を減らしてください)'; return; }
      body.querySelector('#bskyImgMsg').textContent = '✅ 保存しました';
      if (onSaved) onSaved();
      setTimeout(function () { ov.hidden = true; }, 600);
    });
    ov.hidden = false;
  }

  // コメント/メモを必ず1行に収める。(可変フォント)幅に収まらない時だけ実測しながらフォントを縮小＝折り返さない・極力省略しない。
  function fitOneLineTexts_(root) {
    var els = (root || document).querySelectorAll('.cand-manage-comment, .cand-manage-memo, .cand-refimg-memo');
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      el.style.fontSize = ''; // 既定(13px)へ戻して測る
      var cw = el.clientWidth; if (!cw) continue;
      if (el.scrollWidth <= cw + 1) continue; // 既に1行に収まっている
      var base = parseFloat(getComputedStyle(el).fontSize) || 13;
      // 幅比で初期見積り→実測で微調整。(収まるまで1pxずつ下げる。下限7px)
      var px = Math.max(7, Math.floor(base * (cw / el.scrollWidth)));
      el.style.fontSize = px + 'px';
      var guard = 0;
      while (el.scrollWidth > cw + 1 && px > 7 && guard < 12) { px -= 1; el.style.fontSize = px + 'px'; guard++; }
    }
  }
  // カード共通の配線：サムネのタップで画像モーダル／🖼投稿画像ボタン。
  function wireCardCommon_(el) {
    wireAcctRow_(el); // カード右上のチャンネル切替＋投稿済み表示
    fitOneLineTexts_(el); // コメント/メモを1行に収める(可変フォント)
    el.querySelectorAll('[data-thumbcid]').forEach(function (im) {
      im.addEventListener('click', function () { openThumbModal_(itemByCid_(im.getAttribute('data-thumbcid'))); });
    });
    // 保存済みの動画生成用画像(サムネ下の縦長画像)：タップで拡大プレビュー。
    el.querySelectorAll('[data-refimgview]').forEach(function (im) {
      im.addEventListener('click', function () { var rc = im.getAttribute('data-refimgview'); var imgs = refImgsOf_(rc); if (imgs.length) openImgZoom_(imgs, 0, { onReorder: function (i) { return reorderRefImgToFirst_(rc, i); }, onPasteAdd: function (done) { pasteAddRefImgToFirst_(rc, done); } }); }); // 複数あればスワイプ＋1ページ目にする＋貼り付け新規追加
    });
    el.querySelectorAll('[data-refimg]').forEach(function (b) {
      b.addEventListener('click', function () {
        var cid = b.getAttribute('data-refimg'), it = itemByCid_(cid); if (!it) return;
        openRefImgModal_(it, function () {
          var has = refImgHas(cid);
          b.classList.toggle('has-img', has);
          // 文言は常に「投稿編集」。★保存後だけ🖼/✓が付いて初期描画(2459行)と食い違っていたため
          //   統一した(Chami依頼2026-07-17「🖼️と✅は必要ない。編集投稿のままにしといて」)。
          //   画像の有無は has-img クラス(枠色)で示すのでバッジは不要。
          b.textContent = '投稿編集';
          updateCardRefThumb_(b.closest ? b.closest('.cand-card') : null, cid); // 保存直後に一覧のサムネへ反映(リロード不要)
        });
      });
    });
    el.querySelectorAll('[data-bsky]').forEach(function (b) {
      b.addEventListener('click', function () {
        var cid = b.getAttribute('data-bsky'), it = itemByCid_(cid); if (!it) return;
        openBskyImgModal_(it, function () {
          var has = bskyImgHas(cid);
          b.classList.toggle('has-img', has);
          b.innerHTML = has ? '🦋✓' : '🦋';
        });
      });
    });
  }
  // 「▶今すぐ取得」ボタンの共通配線。(notceParentId=通知メッセージを差し込む要素id)
  function bindPcRun_(btn, noticeParentId) {
    btn.addEventListener('click', function () {
      var b = this; b.disabled = true; var t0 = b.textContent; b.textContent = '⏳ 要求中…';
      klog_('fetch_now_requested', '', '', null);
      requestPcRun(function (ok, err) {
        var friendly = err === 'kv_quota_exceeded' ? '本日の上限に達しました(明日また使えます)' : (err || '失敗');
        b.textContent = ok ? '✅ 要求しました' : '⚠️ ' + friendly;
        if (ok) { var el = $(noticeParentId); if (el) { var p = document.createElement('p'); p.className = 'hint'; p.style.padding = '4px 6px'; p.style.color = '#c0392b'; p.textContent = '▶ PCへ取得を要求しました。PCの電源が入っていれば数分以内に取得→🔁で反映されます。'; el.insertBefore(p, el.firstChild); } }
        setTimeout(function () { b.textContent = t0; b.disabled = false; }, 4000);
      });
    });
  }
  // ── 1タブに複数サークル ──
  //   サークルタブは makers:[{id,name},…] を持てる。レガシー tab.makerId/makerName は
  //   先頭サークルと同期して後方互換を保つ。(他コードが tab.makerId を見ても壊れない)
  //   makersOf は新旧どちらの形でも {id,name} 配列を返す。
  function makersOf(tab) {
    if (tab && Array.isArray(tab.makers) && tab.makers.length) {
      return tab.makers.map(function (m) { return { id: String(m.id), name: m.name || '' }; });
    }
    if (tab && tab.makerId) return [{ id: String(tab.makerId), name: tab.makerName || tab.name || '' }];
    return [];
  }
  function makerIdsOf(tab) { return makersOf(tab).map(function (m) { return m.id; }); }
  function isMakerTab_(tab) { return makersOf(tab).length > 0; }
  // タブのサークル一覧を書き換え、レガシー単一フィールドを先頭に同期して保存。
  function writeMakers_(tabId, makers) {
    var norm = (makers || []).map(function (m) { return { id: String(m.id), name: m.name || '' }; });
    var tabs = lsGet(K_TABS, '[]');
    tabs.forEach(function (t) {
      if (t.id !== tabId) return;
      t.makers = norm;
      if (norm.length) { t.makerId = norm[0].id; t.makerName = norm[0].name; }
      else { delete t.makerId; delete t.makerName; }
    });
    lsSet(K_TABS, tabs);
  }

  // サークルを販売数の「追跡対象」としてworkerへ登録/解除。登録済みサークルは
  // PCバッチ(販売数を取得.bat)が「タブを表示しなくても」全作品の販売数を自動取得する。
  function trackMaker(makerId, makerName, remove) {
    if (!makerId) return;
    var flagKey = 'cand_tracked__' + makerId;
    if (!remove && localStorage.getItem(flagKey)) return; // 登録済みなら送らない(解除は常に送る)
    var cfg = workerCfg(); if (!cfg.url) return;
    fetch(cfg.url + '/api/fanza-sales-track', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret },
      body: JSON.stringify(remove ? { makerId: makerId, remove: true } : { makerId: makerId, name: makerName || '' })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.ok) { if (remove) localStorage.removeItem(flagKey); else localStorage.setItem(flagKey, '1'); }
    }).catch(function () {}); // 失敗しても次の機会(ensureTrackedAll)に再送される
  }
  // 既存タブの移行用: 全サークルタブを追跡登録。(登録済みはローカルフラグでスキップ＝実質1回だけ)
  function ensureTrackedAll() {
    lsGet(K_TABS, '[]').forEach(function (t) { makersOf(t).forEach(function (m) { trackMaker(m.id, m.name || t.name || ''); }); });
  }
  // 「▶今すぐ取得」: どの端末のWebアプリからでもPCへ実行要求を送る。(PC常駐タスクが数分以内に拾う)
  // 実スクレイプは日本IPのPCでしか動かないので、これは実行予約のみ。
  function requestPcRun(cb) {
    var cfg = workerCfg(); if (!cfg.url) { cb && cb(false, 'FANZA Workerが未設定です(⚙️詳細設定)'); return; }
    fetch(cfg.url + '/api/fanza-sales-run', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret }, body: '{}' })
      .then(function (r) { return r.json(); }).then(function (d) { cb && cb(!!(d && d.ok), (d && d.error) || ''); })
      .catch(function () { cb && cb(false, '通信エラー'); });
  }

  // ── サークル作品の取得(全ページ＋全同人フロアの巡回はworker側で完結・フロントは1回呼ぶだけ) ──
  //   force=true でキャッシュを無視して取り直す。(🔁リロードボタン用)
  function fetchMakerItems(makerId, mode, cb, force) {
    // date/discountは sort=date、rank・rank7dは同一データ(sort=rank)を使用。
    var apiMode = (mode === 'rank' || mode === 'rank7d') ? 'rank' : 'date';
    var ck = cacheKey(makerId, apiMode);
    var c = lsGet(ck, 'null');
    var hasCache = c && c.at && Array.isArray(c.items) && c.items.length;
    if (!force) {
      if (hasCache && (new Date().getTime() - c.at) < CACHE_TTL) { cb(c.items, null); return; }
    } else {
      // 更新サーチ(🔁): forceでも直近 MAKER_REFRESH_MIN_MS 以内の二度目は再取得せずキャッシュを返す(負荷軽減)。
      if (hasCache && (new Date().getTime() - c.at) < MAKER_REFRESH_MIN_MS) { cb(c.items, null, true); return; }
    }
    var cfg = workerCfg();
    if (!cfg.url) { cb(null, 'FANZA Workerが未設定です(⚙️詳細設定)'); return; }
    fetch(cfg.url + '/api/fanza-maker-list', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret },
      body: JSON.stringify({ makerId: makerId, sort: apiMode })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (!d || !d.ok) { cb(null, (d && d.error) === 'bad_secret' ? '共有シークレット不一致(⚙️詳細設定)' : ('取得エラー: ' + ((d && d.error) || '不明'))); return; }
      var items = d.items || [];
      // 空データはキャッシュしない。(一時失敗やサークル未収録を固定化しない)
      if (items.length) { lsSet(ck, { at: new Date().getTime(), items: items }); recordReviewSnapshots(items); }
      cb(items, null);
    }).catch(function () { cb(null, '通信エラー'); });
  }
  // 複数サークルをまとめて取得し、cidで重複排除してマージ。(1タブに複数サークルを表示する用)
  //   一部サークルが失敗しても成功分は表示。全滅時のみエラーを返す。
  function fetchMakerItemsMulti(makerIds, mode, cb, force) {
    var ids = (makerIds || []).filter(Boolean);
    if (!ids.length) { cb(null, 'サークルが登録されていません'); return; }
    if (ids.length === 1) { fetchMakerItems(ids[0], mode, cb, force); return; }
    var results = new Array(ids.length), firstErr = null, done = 0, throttledN = 0, netN = 0;
    ids.forEach(function (id, i) {
      fetchMakerItems(id, mode, function (items, err, throttled) {
        if (err) { if (!firstErr) firstErr = err; } else { results[i] = items || []; if (throttled) throttledN++; else netN++; }
        if (++done === ids.length) {
          var merged = [], seen = {};
          results.forEach(function (arr) {
            (arr || []).forEach(function (it) {
              if (it && it.cid != null && !seen[it.cid]) { seen[it.cid] = true; merged.push(it); }
            });
          });
          if (!merged.length && firstErr) { cb(null, firstErr); return; }
          cb(merged, null, force && netN === 0 && throttledN > 0); // 全サークルが再取得スキップ＝throttled扱い
        }
      }, force);
    });
  }
  function priceOf(it) { return (it.price != null) ? it.price : (it.listPrice != null ? it.listPrice : Infinity); }
  function isOnSale_(it) { return !!(it && it.listPrice != null && it.price != null && it.discountPct > 0 && it.price < it.listPrice); } // price=0(100%OFF)もセール扱い
  // 作品の「現在価格」(セール中はセール後価格)。無ければ定価、どちらも無ければnull(=価格不明)。
  function priceOf_(it) { if (!it) return null; if (it.price != null && it.price !== '') return Number(it.price); if (it.listPrice != null && it.listPrice !== '') return Number(it.listPrice); return null; }
  // 価格絞り込みを通過するか。_priceMax=0は無効(全通過)。価格不明の作品は通す(隠さない)。
  function passPrice_(it) { if (!_priceMax) return true; var p = priceOf_(it); return (p == null || isNaN(p)) ? true : (p <= _priceMax); }
  // 価格絞り込み入力のHTML(セール絞込の隣に置く・両render共通)。
  function priceFilterHtml_() {
    return '<label class="cand-filter-price" style="margin:0;display:inline-flex;align-items:center;gap:4px;">' +
      '<input id="candPriceMax" type="number" inputmode="numeric" min="0" step="100" placeholder="円以下" value="' + (_priceMax ? _priceMax : '') + '" style="width:88px;">' +
      '<span>円以下</span></label>';
  }
  // 価格絞り込み入力を配線(値変更で保存＋再描画)。rerenderは各タブの再描画関数。
  function wirePriceFilter_(rerender) {
    var el = $('candPriceMax'); if (!el) return;
    el.addEventListener('change', function () {
      var n = parseInt(this.value || '0', 10); _priceMax = (n > 0) ? n : 0;
      try { localStorage.setItem('cand_price_max', String(_priceMax)); } catch (e) {}
      rerender();
    });
  }
  function sortItems(items, mode) {
    var a = items.slice();
    if (mode === 'added_desc') a.sort(function (x, y) { return (y.addedAt || 0) - (x.addedAt || 0); });
    else if (mode === 'price_asc') a.sort(function (x, y) { return priceOf(x) - priceOf(y) || String(y.date).localeCompare(String(x.date)); });
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

  // ── サークルIDの解決(数字 / maker URL / 作品URL) ──
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
    var tabBtns = '<button class="cand-tab cand-tab-buzz' + (_activeTab === 'buzz' ? ' active' : '') + '" data-ct="buzz" type="button">🦋 バズ</button>' +
      '<button class="cand-tab' + (_activeTab === 'main' ? ' active' : '') + '" data-ct="main" type="button">💡 候補</button>' +
      '<button class="cand-tab' + (_activeTab === 'all' ? ' active' : '') + '" data-ct="all" type="button">📚 全候補</button>' +
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

    if (_activeTab === 'buzz') renderBuzz();
    else if (_activeTab === 'all') renderAll_();
    else if (_activeTab === 'main') renderMain('main');
    else {
      var tab = null; tabs.forEach(function (t) { if (t.id === _activeTab) tab = t; });
      if (!tab) { _activeTab = 'main'; renderMain('main'); }
      else if (isMakerTab_(tab)) renderMaker(_activeTab);   // サークル作品一覧タブ(1つ以上のサークル)
      else renderMain(tab.id);                          // 独立した候補リストタブ(タブ名だけのタブ)
    }
  }
  // 候補アイテムの保存先: メインは cand_items、独立タブは各タブ固有キー。(表示を共有しない)
  function itemsKey(tabId) { return (!tabId || tabId === 'main') ? K_ITEMS : 'cand_items__' + tabId; }

  // 全候補cid集合をD1へ同期(部門が「全候補だけ」を読めるように)。変化時のみPOST=無駄打ち防止。
  //   送るのは除外タブ反映後の"キュレート集合"(価格/セール絞込は表示専用なので含めない)。
  function syncCandidatePool_(cids) {
    try {
      var cfg = workerCfg();
      if (!cfg || !cfg.url || !cfg.secret) return; // worker未設定なら同期しない(表示は動く)
      var uniq = []; var seen = {};
      (cids || []).forEach(function (c) { if (c && !seen[c]) { seen[c] = true; uniq.push(c); } });
      var hash = uniq.slice().sort().join(',');
      var last = ''; try { last = localStorage.getItem('cand_pool_hash') || ''; } catch (e) {}
      if (hash === last) return; // 前回と同じ集合＝送らない
      fetch(cfg.url + '/api/candidate-pool', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret },
        body: JSON.stringify({ cids: uniq })
      }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
        if (j && j.ok) { try { localStorage.setItem('cand_pool_hash', hash); } catch (e) {} }
      }).catch(function () { /* 同期失敗は表示に影響しない(次回再送) */ });
    } catch (e) {}
  }

  // ── 📚全候補タブ: 候補(main)+独立タブ+全サークルタブの作品を集約表示(cidで重複排除)。
  //    タブの✏️編集で excludeFromAll=true にしたタブは除外。各部門はこの集合を読む(段階2でD1へ橋渡し予定)。
  //    集約読み取り中心のビューなので個別の非表示/削除ボタンは出さない(各タブ側で行う)。サークル作品は非同期取得。
  function renderAll_() {
    var body = $('candBody');
    if (!body) return;
    var tabs = lsGet(K_TABS, '[]');
    var sortOpts = SORTS.map(function (s) { return '<option value="' + s.key + '"' + (s.key === _sort ? ' selected' : '') + '>' + s.label + '</option>'; }).join('');
    body.innerHTML = '<div class="card" style="padding:10px 12px;">' +
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
        '<select id="candSort" style="flex:1;min-width:140px;">' + sortOpts + '</select>' +
      '</div>' +
      '<div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;">' +
        '<label class="cand-filter-sale" style="margin:0;"><input id="candFilterSale" type="checkbox"' + (_filterSale ? ' checked' : '') + '><span>セール中のみ</span></label>' +
        priceFilterHtml_() +
        candColsCtlHtml_() +
      '</div>' +
      '<div class="hint" style="margin-top:6px;">💡候補・独立タブ・全サークルタブの作品をまとめて表示します。タブの✏️編集で「全候補に含まない」にしたタブは除外(各部門もこの一覧の作品だけを読みます)。</div>' +
      '</div>' +
      '<div id="candList"><p class="hint" style="padding:8px;">⏳ 全候補を集約中…</p></div>';
    $('candSort').addEventListener('change', function () { _sort = this.value; renderAll_(); });
    $('candFilterSale').addEventListener('change', function () { _filterSale = this.checked; renderAll_(); });
    wirePriceFilter_(function () { renderAll_(); });
    wireCandColsCtl_();

    // 保存アイテム(main + 独立listタブ・除外でない)を集約し、サークルidを収集。
    var seen = {}, stored = [];
    function addItems(a) { (a || []).forEach(function (it) { if (it && it.cid != null && !seen[it.cid]) { seen[it.cid] = true; stored.push(it); } }); }
    addItems(lsGet(K_ITEMS, '[]')); // 💡候補(main)は常に含む
    var makerIds = [];
    tabs.forEach(function (t) {
      if (t.excludeFromAll) return; // このタブを全候補に含まない
      if (isMakerTab_(t)) makerIdsOf(t).forEach(function (id) { if (makerIds.indexOf(id) < 0) makerIds.push(id); });
      else addItems(lsGet('cand_items__' + t.id, '[]')); // 独立した候補リストタブ
    });

    function finish(makerItems) {
      var el = $('candList');
      if (!el || _activeTab !== 'all') return; // 集約中にタブが変わっていたら破棄
      var all = stored.slice();
      (makerItems || []).forEach(function (it) { if (it && it.cid != null && !seen[it.cid]) { seen[it.cid] = true; all.push(it); } });
      // 部門ブリッジ: 除外反映後の全候補cid(表示フィルタ前=キュレート集合)をD1へ同期。
      syncCandidatePool_(all.map(function (it) { return it.cid; }));
      var arr = sortItems(all, _sort).filter(function (it) {
        if (_filterSale && !isOnSale_(it)) return false;
        if (!passPrice_(it)) return false;
        if (isHiddenByPosted_(it.cid)) return false; // アカウント別「投稿済みを非表示」は全候補でも尊重
        return true;
      });
      _cardIndex = {}; arr.forEach(function (it) { _cardIndex[it.cid] = it; });
      if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">表示できる作品がありません。(💡候補やサークルタブに作品を追加してください)</p>'; return; }
      var topCids = arr.slice(0, 60).map(function (it) { return it.cid; });
      el.innerHTML = '<p class="hint" style="padding:2px 6px;">📚 全候補 ' + arr.length + '件</p>' +
        arr.map(function (it) { return candCard(it, ''); }).join('');
      wireCardCommon_(el);
      fetchSalesFor(topCids, function (changed) { if (changed && _activeTab === 'all') renderAll_(); });
    }
    if (makerIds.length) fetchMakerItemsMulti(makerIds, _sort, function (items) { finish(items || []); });
    else finish([]);
  }

  // ── タブの並べ替え：PC=ドラッグ、スマホ=長押し→ドラッグ(Pointer Eventsでマウス/タッチ統一) ──
  //   固定の「💡候補」「＋タブを追加」は並べ替え対象外。サークルタブ同士のみ入れ替え可能。
  function wireTabDrag_() {
    var bar = document.querySelector('.cand-tabs');
    if (!bar) return;
    var LONG_PRESS_MS = 350, MOVE_THRESHOLD = 6;
    var longPressTimer = null, startX = 0, startY = 0;
    var dragging = false, dragEl = null, dragMoved = false;

    function reorderable() {
      return [].slice.call(bar.querySelectorAll('.cand-tab[data-ct]')).filter(function (b) { return !isFixedCandTab_(b.getAttribute('data-ct')); });
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
      if (isFixedCandTab_(btn.getAttribute('data-ct'))) return; // 固定タブ(🦋バズ/💡候補)は並べ替え起点にしない
      btn.addEventListener('pointerdown', function (e) {
        startX = e.clientX; startY = e.clientY;
        if (e.pointerType === 'touch') {
          longPressTimer = setTimeout(function () { longPressTimer = null; beginDrag(btn); }, LONG_PRESS_MS);
        } else {
          // マウス/ペン：微小な移動でドラッグ開始(クリックと区別)
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
    var order = [].slice.call(bar.querySelectorAll('.cand-tab[data-ct]')).map(function (b) { return b.getAttribute('data-ct'); }).filter(function (id) { return !isFixedCandTab_(id); });
    var tabs = lsGet(K_TABS, '[]');
    var byId = {}; tabs.forEach(function (t) { byId[t.id] = t; });
    var newTabs = order.map(function (id) { return byId[id]; }).filter(Boolean);
    lsSet(K_TABS, newTabs);
    render();
  }

  // ── ＋タブを追加(名前＋サークル特定情報→決定) ──
  function showAddTabForm() {
    var f = $('candAddForm');
    if (!f) return;
    f.style.display = '';
    f.innerHTML = '<div class="card" style="margin:10px 0;">' +
      '<div class="field-label" style="margin-top:0;">タブを追加</div>' +
      '<label class="hint" style="display:block;margin:0 0 2px;">タブ名(必須・後から編集可)</label>' +
      '<input id="candTabName" type="text" placeholder="タブの名前" autocomplete="off">' +
      '<div class="hint" style="margin-top:6px;">タブ名だけで決定すると、💡候補とは別に独立して作品URLを貯められる<b>候補タブ</b>になります。<br>特定サークルの作品一覧タブにしたい場合だけ、下の欄にサークル情報を入れてください。(任意)</div>' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">サークル情報(任意): 作品URL / サークルID / サークルURL</label>' +
      pasteRow_('<input id="candTabSrc" type="text" inputmode="url" placeholder="空欄なら「ただの候補タブ」になります" autocomplete="off" style="flex:1;">', 'candTabSrc') +
      '<div style="display:flex;gap:8px;margin-top:10px;">' +
      '<button id="candTabOk" type="button" class="primary" style="flex:1;font-size:.9rem;padding:10px;">決定</button>' +
      '<button id="candTabCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">やめる</button>' +
      '</div><div id="candTabMsg" class="hint" style="min-height:1.3em;"></div></div>';
    var _nameAuto = true; // ユーザーが手入力するまでは自動反映を許可
    var _resolved = null; // {src, makerId, makerName} 自動判定の結果を決定時に再利用(二重解決回避)
    $('candTabName').addEventListener('input', function () { _nameAuto = false; });
    // 作品URL等を入れたら、サークル名を自動でタブ名へ反映。(手入力済みなら尊重)
    function autoFillName() {
      var src = ($('candTabSrc').value || '').trim();
      if (!src || (_resolved && _resolved.src === src)) return;
      var msg = $('candTabMsg');
      msg.textContent = '⏳ サークル名を取得中…';
      resolveMakerId(src, function (makerId, makerName, err) {
        if (!$('candTabSrc') || ($('candTabSrc').value || '').trim() !== src) return; // 入力が変わっていたら破棄
        if (!makerId) { _resolved = null; msg.textContent = '⚠️ ' + err; return; }
        _resolved = { src: src, makerId: makerId, makerName: makerName || '' };
        msg.textContent = '✅ サークルを特定しました' + (makerName ? '：' + makerName : '(ID ' + makerId + ')');
        if (_nameAuto && makerName) { $('candTabName').value = makerName; }
      });
    }
    $('candTabSrc').addEventListener('change', autoFillName);
    $('candTabSrc').addEventListener('blur', autoFillName);
    wirePaste_(f);
    $('candTabCancel').addEventListener('click', function () { f.style.display = 'none'; f.innerHTML = ''; });
    $('candTabOk').addEventListener('click', function () {
      var name = ($('candTabName').value || '').trim();
      var src = ($('candTabSrc').value || '').trim();
      var msg = $('candTabMsg');
      // サークル情報が無ければ「独立した候補タブ」。(タブ名だけでOK)
      if (!src) {
        if (!name) { msg.textContent = '⚠️ タブ名を入れてください'; return; }
        var tabsL = lsGet(K_TABS, '[]');
        var listTab = { id: 'ct' + new Date().getTime(), name: name, kind: 'list' };
        tabsL.push(listTab); lsSet(K_TABS, tabsL);
        _activeTab = listTab.id; render();
        return;
      }
      function addTab(makerId, makerName) {
        var tabs = lsGet(K_TABS, '[]');
        var tab = { id: 'ct' + new Date().getTime(), name: name || makerName || ('サークル' + makerId), makerId: makerId, makerName: makerName || '', makers: [{ id: String(makerId), name: makerName || '' }] };
        tabs.push(tab); lsSet(K_TABS, tabs);
        trackMaker(makerId, makerName || tab.name); // 登録した時点でPCバッチの販売数自動取得の対象にする
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

  // ══════════════════════════════════════════════════════════════════
  //  🦋 バズタブ：月詠み(acc1)/宵桜(acc2)がフォローしているBlueskyアカウントの
  //  最近の投稿を、エンゲージメント(いいね+リポスト+返信+引用)の多い順に並べる。
  //  Bluesky公開API(public.api.bsky.app・未認証・CORS可)のみ使用。
  //  ※Blueskyは表示回数(インプレッション)を公開しないため、エンゲージメントが唯一の勢い指標。
  //  API量を抑えるため：フォロー取得ページ数・叩くフィード数・並列数・キャッシュに上限を設ける。
  // ══════════════════════════════════════════════════════════════════
  var BSKY_PUB = 'https://public.api.bsky.app/xrpc/';
  var K_BUZZ = 'cand_buzz_cache';       // {at, accKey, posts:[...]}(アカウント別ではなく対象集合キーで判定)
  var BUZZ_TTL = 30 * 60 * 1000;        // 30分キャッシュ(🔁で強制更新)
  var BUZZ_FOLLOW_PAGES = 3;            // 各アカのフォロー取得ページ数上限(×100件)
  var BUZZ_MAX_FEEDS = 120;             // getAuthorFeed を叩く最大フォロー先数(API量の上限)
  var BUZZ_FEED_LIMIT = 15;             // 1フォロー先あたり取得する投稿数
  var BUZZ_CONCURRENCY = 5;             // 同時fetch数(フォロー数×フィードで膨らむのを抑える)
  var BUZZ_RECENT_DAYS = 14;            // これより古い投稿は対象外
  var BUZZ_SHOW = 60;                   // 表示件数
  var _buzzLoading = false;

  // ハンドルとDIDのどちらかがあるアカウントのみ対象。(🦋投稿タブ⚙設定で保存済み)
  function buzzAccounts_() {
    return ['acc1', 'acc2'].map(function (a) {
      var h = '', d = '';
      try { h = (localStorage.getItem('bsky_handle__' + a) || '').trim().replace(/^@/, ''); } catch (e) {}
      try { d = (localStorage.getItem('bsky_did__' + a) || '').trim(); } catch (e) {}
      return { acc: a, handle: h, did: d };
    }).filter(function (o) { return o.handle || o.did; });
  }
  function buzzAccKey_(accs) { return accs.map(function (o) { return o.acc + ':' + (o.did || o.handle); }).join('|'); }

  function bskyGet_(method, params) {
    var q = Object.keys(params).map(function (k) { return k + '=' + encodeURIComponent(params[k]); }).join('&');
    return fetch(BSKY_PUB + method + '?' + q).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }
  // ハンドル→DID。(未キャッシュ時のみ解決し bsky_did__ に保存)
  function resolveBuzzDid_(o) {
    if (o.did && /^did:/.test(o.did)) return Promise.resolve(o.did);
    if (!o.handle) return Promise.resolve('');
    return bskyGet_('com.atproto.identity.resolveHandle', { handle: o.handle }).then(function (j) {
      var did = j && j.did ? j.did : '';
      if (did) { try { localStorage.setItem('bsky_did__' + o.acc, did); } catch (e) {} }
      return did;
    });
  }
  // 1アカウントの全フォロー先を取得。(ページング・BUZZ_FOLLOW_PAGES上限)
  function fetchFollows_(did) {
    var out = [], cursor = '';
    function step(page) {
      if (page >= BUZZ_FOLLOW_PAGES) return Promise.resolve(out);
      var p = { actor: did, limit: 100 }; if (cursor) p.cursor = cursor;
      return bskyGet_('app.bsky.graph.getFollows', p).then(function (j) {
        if (!j || !j.follows) return out;
        j.follows.forEach(function (f) { if (f && f.did) out.push({ did: f.did, handle: f.handle, name: f.displayName || '', avatar: f.avatar || '' }); });
        cursor = j.cursor || '';
        if (!cursor) return out;
        return step(page + 1);
      });
    }
    return step(0);
  }
  // 並列プール。(同時active数を conc に制限)worker(item,idx)→Promise。結果を index順に返す。
  function buzzPool_(items, worker, conc) {
    return new Promise(function (resolve) {
      var i = 0, active = 0, results = [];
      function next() {
        if (i >= items.length && active === 0) { resolve(results); return; }
        while (active < conc && i < items.length) {
          (function (item, idx) {
            active++;
            Promise.resolve(worker(item, idx)).then(function (r) { results[idx] = r; }, function () { results[idx] = null; }).then(function () { active--; next(); });
          })(items[i], i); i++;
        }
      }
      next();
    });
  }
  function buzzPostUrl_(uri, handle) {
    var m = String(uri || '').match(/\/app\.bsky\.feed\.post\/([^/]+)$/);
    var rkey = m ? m[1] : '';
    return (handle && rkey) ? ('https://bsky.app/profile/' + handle + '/post/' + rkey) : '';
  }
  function buzzThumb_(embed) {
    var e = embed || {};
    if (e.images && e.images[0]) return e.images[0].thumb || '';
    if (e.media && e.media.images && e.media.images[0]) return e.media.images[0].thumb || ''; // recordWithMedia
    return '';
  }

  // 取得本体：キャッシュ→DID解決→フォロー統合(DIDでunion)→フィード取得→エンゲージメント順。
  function loadBuzz_(force, onDone) {
    var accs = buzzAccounts_();
    if (!accs.length) { onDone({ error: 'noacct' }); return; }
    var accKey = buzzAccKey_(accs);
    if (!force) {
      var cached = lsGet(K_BUZZ, 'null');
      if (cached && cached.accKey === accKey && (new Date().getTime() - cached.at) < BUZZ_TTL) {
        onDone({ posts: cached.posts, at: cached.at, cached: true }); return;
      }
    }
    _buzzLoading = true;
    Promise.all(accs.map(resolveBuzzDid_)).then(function (dids) {
      var valid = dids.filter(function (d) { return d; });
      if (!valid.length) { _buzzLoading = false; onDone({ error: 'nodid' }); return; }
      return Promise.all(valid.map(fetchFollows_)).then(function (lists) {
        // 両アカが同じ人をフォローしていても1回だけ＝DIDでunion＋重複削除。
        var byDid = {};
        lists.forEach(function (arr) { (arr || []).forEach(function (f) { if (f && f.did && !byDid[f.did]) byDid[f.did] = f; }); });
        valid.forEach(function (d) { delete byDid[d]; }); // 自分自身は除外
        var BUZZ_EXCLUDE_HANDLES = { 'bsky.app': true, 'jp.bsky.app': true }; // Bluesky公式アカウントは対象外
        var follows = Object.keys(byDid).map(function (d) { return byDid[d]; }).filter(function (f) { return !BUZZ_EXCLUDE_HANDLES[f.handle]; });
        var targets = follows.slice(0, BUZZ_MAX_FEEDS);
        var truncated = follows.length > targets.length;
        var cutoff = new Date().getTime() - BUZZ_RECENT_DAYS * 86400000;
        return buzzPool_(targets, function (f) {
          return bskyGet_('app.bsky.feed.getAuthorFeed', { actor: f.did, limit: BUZZ_FEED_LIMIT, filter: 'posts_no_replies' }).then(function (j) {
            if (!j || !j.feed) return [];
            var arr = [];
            j.feed.forEach(function (it) {
              if (it.reason) return; // リポスト(reason付き)は本人の投稿ではないので除外
              var p = it.post; if (!p || !p.record) return;
              var whenStr = p.indexedAt || p.record.createdAt || '';
              var when = Date.parse(whenStr);
              if (!isNaN(when) && when < cutoff) return;
              arr.push({
                uri: p.uri,
                handle: (p.author && p.author.handle) || f.handle,
                name: (p.author && p.author.displayName) || f.name || '',
                avatar: (p.author && p.author.avatar) || f.avatar || '',
                text: p.record.text || '',
                like: p.likeCount || 0, repost: p.repostCount || 0, reply: p.replyCount || 0, quote: p.quoteCount || 0,
                at: whenStr,
                thumb: buzzThumb_(p.embed)
              });
            });
            return arr;
          });
        }, BUZZ_CONCURRENCY).then(function (chunks) {
          var all = [];
          (chunks || []).forEach(function (c) { if (c) all = all.concat(c); });
          all.forEach(function (p) { p.eng = p.like + p.repost + p.reply + p.quote; });
          all.sort(function (a, b) { return b.eng - a.eng || (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0); });
          var posts = all.slice(0, BUZZ_SHOW);
          lsSet(K_BUZZ, { at: new Date().getTime(), accKey: accKey, posts: posts });
          _buzzLoading = false;
          onDone({ posts: posts, at: new Date().getTime(), followCount: follows.length, truncated: truncated });
        });
      });
    }).catch(function () { _buzzLoading = false; onDone({ error: 'fetch' }); });
  }

  // ── バズタブDOM ──
  function renderBuzz() {
    var body = $('candBody');
    if (!body) return;
    var accs = buzzAccounts_();
    var head = '<div class="card" style="padding:10px 12px;">' +
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
      '<div style="flex:1;font-weight:700;color:var(--accent);">🦋 フォロー中のバズ投稿</div>' +
      '<button id="buzzReload" type="button" class="ghost" title="最新を取り直す" style="flex:0 0 auto;width:auto;margin:0;font-size:15px;padding:6px 10px;">🔁</button>' +
      '</div>' +
      '<div class="hint" style="margin-top:6px;">フォローしている人の直近' + BUZZ_RECENT_DAYS + '日の投稿を、<b>反応の多い順</b>に並べます。' +
      'Blueskyは表示回数(インプレッション)を公開していないため、<b>エンゲージメント(❤️いいね+🔁リポスト+💬返信+❝引用)</b>が唯一の勢いの指標です。</div>' +
      '</div>';
    if (!accs.length) {
      body.innerHTML = head + '<div class="card"><div class="hint">⚠️ Blueskyのハンドルが未設定です。🦋投稿タブの⚙設定でハンドル(@…)を保存すると、そのアカウントのフォローが対象になります。</div></div>';
      wireBuzzReload_();
      return;
    }
    var namesLabel = accs.map(function (o) { return '@' + (o.handle || o.did.slice(0, 14) + '…'); }).join(' / ');
    body.innerHTML = head +
      '<div class="hint" style="margin:6px 2px;">対象アカウント：' + esc(namesLabel) + '</div>' +
      '<div id="buzzList"><div class="card"><div class="hint">⏳ フォローと投稿を集計中…(初回・更新直後は少し時間がかかります)</div></div></div>';
    wireBuzzReload_();
    renderBuzzList_(false);
  }
  function wireBuzzReload_() {
    var b = $('buzzReload');
    if (b) b.addEventListener('click', function () { if (_buzzLoading) return; renderBuzzList_(true); });
  }
  function renderBuzzList_(force) {
    var list = $('buzzList');
    if (list && force) list.innerHTML = '<div class="card"><div class="hint">⏳ 最新を取得中…</div></div>';
    loadBuzz_(force, function (res) {
      var el = $('buzzList');
      if (!el) return; // タブが切り替わっていたら破棄
      if (res.error === 'noacct' || res.error === 'nodid') { el.innerHTML = '<div class="card"><div class="hint">⚠️ フォロー情報を取得できませんでした。🦋投稿タブの⚙設定でハンドルをご確認ください。</div></div>'; return; }
      if (res.error) { el.innerHTML = '<div class="card"><div class="hint">⚠️ 取得に失敗しました。時間をおいて🔁で再試行してください。</div></div>'; return; }
      var posts = res.posts || [];
      if (!posts.length) { el.innerHTML = '<div class="card"><div class="hint">直近' + BUZZ_RECENT_DAYS + '日でフォロー先の投稿が見つかりませんでした。</div></div>'; return; }
      var meta = '<div class="hint" style="margin:2px 2px 4px;">' +
        (res.cached ? '🕘 ' + fmtTs(res.at) + ' 時点のキャッシュ(🔁で更新)' : '✅ ' + fmtTs(res.at) + ' に更新') +
        (res.truncated ? '　※フォローが多いため上位' + BUZZ_MAX_FEEDS + '人ぶんを対象にしています' : '') +
        '</div>';
      el.innerHTML = meta + posts.map(buzzCardHtml_).join('');
    });
  }
  function buzzCardHtml_(p) {
    var url = buzzPostUrl_(p.uri, p.handle);
    var av = p.avatar ? '<img class="buzz-av" src="' + esc(p.avatar) + '" loading="lazy" alt="">' : '<div class="buzz-av buzz-av-ph"></div>';
    var txt = esc(p.text || '').replace(/\n/g, '<br>');
    var thumb = p.thumb ? '<img class="buzz-thumb" src="' + esc(p.thumb) + '" loading="lazy" alt="">' : '';
    var when = p.at ? fmtTs(Date.parse(p.at)) : '';
    return '<div class="cand-card buzz-card">' +
      av +
      '<div class="cand-info">' +
        '<div class="buzz-head"><span class="buzz-name">' + esc(p.name || p.handle) + '</span> <span class="buzz-handle">@' + esc(p.handle) + '</span>' + (when ? '<span class="buzz-time">・' + esc(when) + '</span>' : '') + '</div>' +
        (txt ? '<div class="buzz-text">' + txt + '</div>' : '') +
        thumb +
        '<div class="buzz-stats">' +
          '<span class="buzz-eng">🔥 ' + p.eng + '</span>' +
          '<span>❤️ ' + p.like + '</span><span>🔁 ' + p.repost + '</span><span>💬 ' + p.reply + '</span><span>❝ ' + p.quote + '</span>' +
          (url ? '<a class="vlink" href="' + esc(url) + '" target="_blank" rel="noopener" style="margin-left:auto;">開く↗</a>' : '') +
        '</div>' +
      '</div></div>';
  }

  // ── 候補リスト(既定の💡候補 と 独立した候補タブ で共用。tabIdごとに保存先が独立) ──
  //   サークルタブと同じヘッダ(並び替え／🔁／▶今すぐ取得／✏️編集／🙈非表示)を持つ。
  // 作品URL追加フォーム。(モーダル化＝恒常表示をやめて省スペース)入力はダーク面用の白字。(.cand-refimg-line)
  function addFormHtml_(isMain) {
    var slots = '';
    for (var si = 0; si < 4; si++) slots += '<button type="button" class="cand-add-imgslot" data-slot="' + si + '"><span class="cand-add-slot-hint">＋<br>画像<br>貼り付け</span></button>';
    return '' +
      '<div class="fz-title" style="background:none;color:#fff;padding:0 46px 0 0;margin:0 0 6px;font-weight:700;line-height:1.3;">📥 作品URLを' + (isMain ? '候補' : 'このタブ') + 'に追加</div>' +
      '<div class="hint">アフィリンク付きURL(al.fanza.co.jp/?lurl=…)でもOK。素の作品URLに直して記録します。' + (isMain ? '' : '<br>💡候補とは別に、このタブに独立して保存されます。') + '</div>' +
      '<div style="margin-top:6px;">' + pasteRow_('<input id="candUrl" type="text" inputmode="url" class="cand-refimg-line" placeholder="https://…(作品URL or アフィリンク)" autocomplete="off" style="flex:1;min-width:0;">', 'candUrl') + '</div>' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">X / Bluesky の投稿URL(任意)— <b>これだけでも追加できます</b></label>' +
      '<div>' + pasteRow_('<input id="candTwitter" type="text" inputmode="url" class="cand-refimg-line" placeholder="https://x.com/…/status/… か https://bsky.app/profile/…/post/…" autocomplete="off" style="flex:1;min-width:0;">', 'candTwitter') + '</div>' +
      '<label class="hint" style="display:block;margin:10px 0 2px;">動画生成用の画像(任意・最大4枚)— ボタンを押すとコピー中の画像が左から入ります</label>' +
      '<div class="cand-add-imgrow">' + slots + '</div>' +
      '<div style="margin-top:6px;display:flex;">' +
        '<label class="ghost cand-refimg-pick" style="width:auto;flex:0 0 auto;margin:0;">画像を選ぶ<input id="candAddImgFile" type="file" accept="image/*" multiple style="display:none;"></label>' +
      '</div>' +
      // ボタン幅は固定せず内容(テキスト)に追従。(width:max-content)続行ボタンは小さめ＝メモ欄を広く。
      '<div style="display:flex;gap:8px;margin-top:8px;align-items:stretch;">' +
        '<input id="candMemo" type="text" class="cand-refimg-line" placeholder="メモ(任意・候補のメモに保存)" autocomplete="off" style="flex:1;min-width:0;">' +
        '<button id="candAdd" type="button" class="primary" style="margin:0;font-size:.78rem;padding:8px 10px;width:max-content;flex:0 0 auto;white-space:nowrap;">' + (isMain ? '候補に追加 / 続行' : 'このタブに追加 / 続行') + '</button>' +
      '</div>' +
      '<div id="candMsg" class="hint" style="min-height:1.3em;"></div>' +
      '<div style="border-top:1px solid var(--line);margin:10px 0 0;padding-top:10px;">' +
        '<div class="hint">サークルの作品をまとめて' + (isMain ? '候補' : 'このタブ') + 'に追加できます。<br>(サークルID / サークルURL / 作品URLのどれか)</div>' +
        '<div style="margin-top:6px;">' + pasteRow_('<input id="candBulkSrc" type="text" inputmode="url" class="cand-refimg-line" placeholder="サークルID / サークルURL / 作品URL" autocomplete="off" style="flex:1;min-width:0;">', 'candBulkSrc') + '</div>' +
        // サークル作品を全て追加 と 候補に追加/閉じる を並列。(どちらも幅は内容に追従・狭い端末でも1行に収まるよう小さめ)
        '<div style="display:flex;gap:6px;margin-top:8px;align-items:center;flex-wrap:wrap;">' +
          '<button id="candBulkAdd" type="button" class="ghost" style="margin:0;width:max-content;white-space:nowrap;font-size:.72rem;padding:7px 9px;">サークル作品を全て追加</button>' +
          '<button id="candAddClose" type="button" class="primary" style="margin:0 0 0 auto;width:max-content;white-space:nowrap;font-size:.72rem;padding:7px 9px;">' + (isMain ? '候補に追加 / 閉じる' : 'このタブに追加 / 閉じる') + '</button>' +
        '</div>' +
        '<div id="candBulkMsg" class="hint" style="min-height:1.3em;"></div>' +
      '</div>';
  }
  // 追加モーダルの画像スロット。(最大4・左詰め)候補追加時に「動画生成用の画像」として一緒に保存される。
  var _addModalImgs = [];
  function renderAddSlots_() {
    if (!_addOverlay) return;
    var btns = _addOverlay.querySelectorAll('.cand-add-imgslot');
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i], src = _addModalImgs[i] || '';
      if (src) {
        b.className = 'cand-add-imgslot filled';
        b.innerHTML = '<img src="' + esc(src) + '" alt=""><span class="cand-add-slot-x" data-clearslot="' + i + '">✕</span>';
      } else {
        b.className = 'cand-add-imgslot';
        b.innerHTML = '<span class="cand-add-slot-hint">＋<br>画像<br>貼り付け</span>';
      }
    }
  }
  function wireAddSlots_(body) {
    body.querySelectorAll('.cand-add-imgslot').forEach(function (b) {
      b.addEventListener('click', function (e) {
        // ✕(削除)：そのスロットを消して左詰め
        var x = e.target && e.target.getAttribute && e.target.getAttribute('data-clearslot');
        if (x != null && x !== '') { _addModalImgs.splice(parseInt(x, 10), 1); renderAddSlots_(); return; }
        var slot = parseInt(b.getAttribute('data-slot'), 10);
        var msg = $('candMsg'); if (msg) msg.textContent = '画像を貼り付け中…';
        pasteImageFromClipboard_(function (durl, err) {
          if (err) { if (msg) msg.textContent = err; return; }
          if (_addModalImgs[slot]) _addModalImgs[slot] = durl;      // 充填済みスロット＝差し替え
          else { _addModalImgs.push(durl); if (_addModalImgs.length > 4) _addModalImgs.length = 4; } // 空き＝左から詰める
          renderAddSlots_();
          if (msg) msg.textContent = '画像を貼り付けました(' + _addModalImgs.filter(Boolean).length + '/4枚・追加ボタンで確定)';
        });
      });
    });
  }
  // 追加確定時に呼ぶ：スロット画像を候補の動画生成用画像として保存し、スロットを空にする。
  function attachAddImgs_(cid) {
    var imgs = _addModalImgs.filter(Boolean);
    var memoEl = $('candMemo');
    var memo = (memoEl && memoEl.value || '').trim(); // メモ欄に入力があれば候補のメモへ保存
    if (!cid) return;
    if (imgs.length || memo) {
      var cur = refImgOf(cid) || {};
      refImgSave(cid, { imgs: imgs.length ? imgs : (cur.imgs || []), comment: cur.comment || '', memo: memo || cur.memo || '', twitterUrl: cur.twitterUrl || '', twitterUrl2: cur.twitterUrl2 || '' });
    }
    if (memoEl) memoEl.value = ''; // 追加後はメモ欄をクリア(続ける時に持ち越さない)
    _addModalImgs = [];
    renderAddSlots_();
  }
  var _addOverlay = null;
  function openAddModal_(tabId, isMain) {
    var ov = _addOverlay;
    if (!ov) {
      ov = document.createElement('div'); ov.className = 'fz-overlay'; ov.hidden = true;
      ov.innerHTML = '<div class="fz-modal add-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) ov.hidden = true; });
      ov.querySelector('.fz-close').addEventListener('click', function () { ov.hidden = true; });
      _addOverlay = ov;
    }
    var body = ov.querySelector('.fz-body');
    _addModalImgs = []; // 開くたびにスロットを白紙に
    body.innerHTML = addFormHtml_(isMain);
    $('candAdd').addEventListener('click', function () { addCandidate(tabId); }); // 追加して続ける(開いたまま)
    $('candAddClose').addEventListener('click', function () { addCandidate(tabId, function () { ov.hidden = true; }); }); // 追加して閉じる
    $('candBulkAdd').addEventListener('click', function () { bulkAddCircle(tabId); });
    // 「画像を選ぶ」(複数可): ファイルからもスロットへ左詰めで追加。(1枚ずつ順に処理=メモリ圧迫回避)
    var addFile = $('candAddImgFile');
    if (addFile) addFile.addEventListener('change', function () {
      var files = [], fl = this.files || [], fi;
      for (fi = 0; fi < fl.length; fi++) files.push(fl[fi]);
      this.value = '';
      if (!files.length) return;
      var msg = $('candMsg'); if (msg) msg.textContent = '画像を処理中…(' + files.length + '枚)';
      var added = 0, failed = 0;
      (function step(i) {
        if (i >= files.length) {
          renderAddSlots_();
          if (msg) msg.textContent = added ? ('画像を追加しました(' + _addModalImgs.filter(Boolean).length + '/4枚' + (failed ? '・' + failed + '枚は読み込めず' : '') + '・追加ボタンで確定)') : '画像を読み込めませんでした';
          return;
        }
        fileToScaledDataUrl(files[i], function (durl) {
          if (durl && _addModalImgs.length < 4) { _addModalImgs.push(durl); added++; } else if (!durl) failed++;
          step(i + 1);
        });
      })(0);
    });
    wirePaste_(body);
    wireAddSlots_(body);
    ov.hidden = false;
  }

  function renderMain(tabId) {
    tabId = tabId || 'main';
    var body = $('candBody');
    var isMain = (tabId === 'main');
    var sortOpts = SORTS.map(function (s) { return '<option value="' + s.key + '"' + (s.key === _sort ? ' selected' : '') + '>' + s.label + '</option>'; }).join('');
    var header = '<div class="card" style="padding:10px 12px;">' +
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
      '<select id="candSort" style="flex:1;min-width:140px;">' + sortOpts + '</select>' +
      '<button id="candReload" type="button" class="ghost" title="価格・販売数を取り直す" style="flex:0 0 auto;width:auto;margin:0;font-size:15px;padding:6px 10px;">🔁</button>' +
      '<button id="candPcRun" type="button" class="ghost" title="PCへ「今すぐ販売数を取得」を要求(PCの電源が必要)" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">▶ 今すぐ取得</button>' +
      (isMain ? '' : '<button id="candEditTab" type="button" class="ghost" title="タブ名を変更・タブを削除" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">✏️ 編集</button>') +
      '<button id="candAddOpen" type="button" class="primary" style="flex:0 0 auto;width:auto;margin:0;font-size:12px;padding:6px 12px;">➕ ' + (isMain ? '追加' : 'このタブに追加') + '</button>' +
      '</div>' +
      // アカウント別「投稿済みを非表示」トグル。(非表示リストの上段・右寄せ)両方同時ON可。
      candHidePostedRowHtml_() +
      // 省スペース行：セール絞込(左)＋列数(PCのみ)＋非表示トグル(右端・状態で色と文言が変化)
      '<div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;">' +
        '<label class="cand-filter-sale" style="margin:0;"><input id="candFilterSale" type="checkbox"' + (_filterSale ? ' checked' : '') + '><span>セール中のみ</span></label>' +
        priceFilterHtml_() +
        candColsCtlHtml_() +
        '<span style="flex:1 1 auto;"></span>' +
        '<button id="candShowHidden" type="button" class="cand-hidden-toggle' + (_showHidden ? ' active' : '') + '" style="flex:0 0 auto;width:auto;margin:0;font-size:12px;padding:6px 11px;">' + (_showHidden ? '👁 通常表示に戻す' : '非表示リスト') + '</button>' +
      '</div>' +
      (_sort === 'rank7d' ? '<div class="hint" style="margin-top:6px;">' + esc(RANK7D_NOTE) + '</div>' : '') +
      ((_sort === 'rank' || _sort === 'rank7d') ? '<div class="hint" style="margin-top:4px;">' + esc(SALES_NOTE) + '</div>' : '') +
      '</div>';
    body.innerHTML = header + '<div id="candEditForm"></div>' + '<div id="candList"></div>';
    $('candSort').addEventListener('change', function () { _sort = this.value; renderCandList(tabId); });
    $('candShowHidden').addEventListener('click', function () { _showHidden = !_showHidden; this.classList.toggle('active', _showHidden); this.textContent = _showHidden ? '👁 通常表示に戻す' : '非表示リスト'; renderCandList(tabId); });
    $('candFilterSale').addEventListener('change', function () { _filterSale = this.checked; renderCandList(tabId); });
    wirePriceFilter_(function () { renderCandList(tabId); });
    wireCandColsCtl_();
    wireHidePostedButtons_(function () { renderCandList(tabId); });
    $('candReload').addEventListener('click', function () { refreshCandItems(tabId); });
    bindPcRun_($('candPcRun'), 'candList');
    $('candAddOpen').addEventListener('click', function () { openAddModal_(tabId, isMain); });
    if (!isMain) {
      var tab = null; lsGet(K_TABS, '[]').forEach(function (t) { if (t.id === tabId) tab = t; });
      var eb = $('candEditTab'); if (eb && tab) eb.addEventListener('click', function () { showEditTabForm(tab); });
    }
    wirePaste_(body);
    renderCandList(tabId);
  }
  // Twitter(X)のURLを判定・正規化。status付き→cid=tw_<id>、それ以外のx/twitterURLも許容。
  function parseTwitterUrl_(raw) {
    var s = String(raw || '').trim(); if (!s) return { ok: false };
    var m = s.match(/https?:\/\/(?:www\.|mobile\.)?(?:twitter\.com|x\.com)\/([^\/?#]+)\/status\/(\d+)/i);
    if (m) return { ok: true, user: m[1], id: m[2], url: 'https://x.com/' + m[1] + '/status/' + m[2], cid: 'tw_' + m[2] };
    var m2 = s.match(/https?:\/\/(?:www\.|mobile\.)?(?:twitter\.com|x\.com)\/[^\s]+/i);
    if (m2) { var u = m2[0].split('?')[0]; return { ok: true, user: '', id: '', url: u, cid: 'tw_' + u.replace(/[^0-9A-Za-z_]/g, '').slice(-40) }; }
    return { ok: false };
  }
  // Bluesky の投稿URL(https://bsky.app/profile/<handle>/post/<rkey>)を判定・正規化。
  function parseBskyUrl_(raw) {
    var s = String(raw || '').trim(); if (!s) return { ok: false };
    var m = s.match(/https?:\/\/(?:www\.)?bsky\.app\/profile\/([^\/?#]+)\/post\/([0-9a-z]+)/i);
    if (m) return { ok: true, user: m[1], id: m[2], url: 'https://bsky.app/profile/' + m[1] + '/post/' + m[2], cid: 'bs_' + m[2], kind: 'bsky' };
    return { ok: false };
  }
  // X(Twitter) / Bluesky どちらの投稿URLも受け付ける。(kind='x'|'bsky')
  function parseSnsUrl_(raw) {
    var t = parseTwitterUrl_(raw); if (t.ok) { t.kind = 'x'; return t; }
    return parseBskyUrl_(raw);
  }
  function addTwitterCandidate_(tabId, tw, inp, twInp, msg, onDone) {
    var key = itemsKey(tabId), items = lsGet(key, '[]');
    if (items.some(function (x) { return x.twitterUrl === tw.url || x.cid === tw.cid; })) { msg.textContent = 'ℹ️ この投稿は既に追加されています(重複追加しません)'; return; }
    var isB = tw.kind === 'bsky';
    var title = isB ? (tw.user ? ('🦋 @' + tw.user + ' のポスト') : '🦋 Blueskyのポスト')
                    : (tw.user ? ('🐦 @' + tw.user + ' のポスト') : '🐦 X(Twitter)のポスト');
    items.unshift({ url: tw.url, cid: tw.cid, twitterUrl: tw.url, isTwitter: true, title: title, addedAt: new Date().getTime() });
    lsSet(key, items);
    attachAddImgs_(tw.cid); // 追加モーダルの画像スロットも一緒に保存(動画生成用)
    if (inp) inp.value = ''; if (twInp) twInp.value = '';
    msg.textContent = isB ? '✅ Blueskyの投稿URLを追加しました' : '✅ Twitter(X)のURLを追加しました';
    renderCandList(tabId);
    if (onDone) onDone(); // 「追加して閉じる」＝追加完了後にモーダルを閉じる
  }
  function addCandidate(tabId, onDone) {
    tabId = tabId || 'main';
    var key = itemsKey(tabId);
    var inp = $('candUrl'), twInp = $('candTwitter'), msg = $('candMsg');
    var raw = (inp && inp.value || '').trim();
    var twRaw = (twInp && twInp.value || '').trim();
    var url = window.normalizeWorkUrl ? window.normalizeWorkUrl(raw) : raw;
    var r = (raw && url && window.buildAffiliateLink) ? window.buildAffiliateLink(url, '') : null;
    // ①作品URLがFANZA作品として有効 → 従来のFANZA候補(Twitter URLがあれば紐づけて保存)
    if (raw && r && r.ok) {
      var twForWork = parseSnsUrl_(twRaw); // X / Bluesky どちらの投稿URLでも紐づけ可
      var items0 = lsGet(key, '[]');
      // 重複チェック: 同じcidが既にある場合はサブデータ(X/BlueskyURL・画像・メモ)のみ追記
      var dupIdx = -1;
      for (var di = 0; di < items0.length; di++) { if (items0[di] && items0[di].cid === r.cid) { dupIdx = di; break; } }
      if (dupIdx >= 0) {
        var existItem = items0[dupIdx];
        var newImgs = _addModalImgs.filter(Boolean);
        var memoElDup = $('candMemo');
        var newMemo = (memoElDup && memoElDup.value || '').trim();
        var newTwUrl = twForWork.ok ? twForWork.url : '';
        var cur = refImgOf(r.cid) || {};
        var curImgs = Array.isArray(cur.imgs) ? cur.imgs.filter(Boolean) : (cur.img ? [cur.img] : []);
        var curTw = existItem.twitterUrl || cur.twitterUrl || '';
        var curTw2 = cur.twitterUrl2 || '';
        var mergedTw = curTw, mergedTw2 = curTw2;
        var mergedAny = false;
        // X/BlueskyURL: 1つ目が空なら設定、1つ目と異なりかつ2つ目が空なら2つ目へ
        if (newTwUrl && newTwUrl !== curTw && newTwUrl !== curTw2) {
          if (!curTw) { mergedTw = newTwUrl; existItem.twitterUrl = newTwUrl; mergedAny = true; }
          else if (!curTw2) { mergedTw2 = newTwUrl; mergedAny = true; }
        }
        // 画像: 末尾へ追加(最大8枚)
        var mergedImgs = curImgs.slice();
        newImgs.forEach(function (img) { if (mergedImgs.length < 8) { mergedImgs.push(img); mergedAny = true; } });
        // メモ: 無ければ設定、あれば改行追記
        var mergedMemo = cur.memo || '';
        if (newMemo && newMemo !== mergedMemo) {
          mergedMemo = mergedMemo ? (mergedMemo + '\n' + newMemo) : newMemo;
          mergedAny = true;
        }
        if (mergedAny) {
          lsSet(key, items0);
          refImgSave(r.cid, { imgs: mergedImgs, comment: cur.comment || '', memo: mergedMemo, twitterUrl: mergedTw, twitterUrl2: mergedTw2 });
          if (inp) inp.value = ''; if (twInp) twInp.value = ''; if (memoElDup) memoElDup.value = '';
          _addModalImgs = []; renderAddSlots_();
          msg.textContent = 'ℹ️ 既に追加済み — X/画像/メモを追記しました';
          renderCandList(tabId);
          if (onDone) onDone();
        } else {
          msg.textContent = 'ℹ️ この作品は既に追加されています(重複追加しません)';
        }
        return;
      }
      msg.textContent = '⏳ 作品情報を取得中…';
      var cfg = workerCfg();
      var put = function (info) {
        var items = lsGet(key, '[]');
        var it = {
          url: url, cid: r.cid,
          title: (info && info.title) || '(タイトル未取得)',
          author: (info && info.author) || '',
          thumb: (info && (info.thumb || info.thumbSmall)) || '',
          listPrice: info ? info.listPrice : null, price: info ? info.price : null,
          discountPct: info ? (info.discountPct || 0) : 0,
          date: (info && info.releaseDate) || '',
          genres: (info && info.genres) || [],
          reviewCount: info ? info.reviewCount : null,
          reviewAvg: info ? info.reviewAvg : null,
          addedAt: new Date().getTime()
        };
        if (info && info.samples && info.samples.length) it.samples = info.samples; // 詳細モーダル用
        if (twForWork.ok) it.twitterUrl = twForWork.url; // X / Bluesky の投稿URLも一緒に保存
        items.unshift(it);
        lsSet(key, items);
        attachAddImgs_(r.cid); // 追加モーダルの画像スロットも一緒に保存(動画生成用・左から順)
        inp.value = ''; if (twInp) twInp.value = ''; msg.textContent = '✅ 追加しました';
        renderCandList(tabId);
        if (onDone) onDone(); // 「追加して閉じる」＝追加完了後にモーダルを閉じる
      };
      if (window.FanzaCore && cfg.url) {
        window.FanzaCore.fetchFanzaInfo(r.cid, cfg.url, cfg.secret, url).then(function (info) {
          put(info && info.title ? info : null);
        }).catch(function () { put(null); });
      } else put(null);
      return;
    }
    // ②作品URLが無い/FANZA以外 → Twitter(X)のURLだけで追加(Twitter欄優先、無ければ作品欄に貼られたX URLも可)
    var tw = parseSnsUrl_(twRaw); if (!tw.ok) tw = parseSnsUrl_(raw); // X / Bluesky どちらでも単独追加可
    if (tw.ok) { addTwitterCandidate_(tabId, tw, inp, twInp, msg, onDone); return; }
    // ③どちらでもない
    msg.textContent = (raw || twRaw) ? '⚠️ FANZAの作品URL か X / Bluesky の投稿URLを入れてください' : '⚠️ URLを入力してください';
  }
  // サークルの全作品を、指定タブ(候補/独立タブ)へまとめて追加。(重複cidは除外・タブ名は不変)
  function bulkAddCircle(tabId) {
    var src = ($('candBulkSrc').value || '').trim(), msg = $('candBulkMsg');
    if (!src) { msg.textContent = '⚠️ サークル情報を入れてください'; return; }
    msg.textContent = '⏳ サークルを特定中…';
    resolveMakerId(src, function (makerId, makerName, err) {
      if (!makerId) { msg.textContent = '⚠️ ' + err; return; }
      msg.textContent = '⏳ 作品一覧を取得中…(多いと時間がかかります)';
      fetchMakerItems(makerId, 'date', function (works, err2) {
        if (err2) { msg.textContent = '⚠️ ' + err2; return; }
        var res = appendWorks_(itemsKey(tabId), works || []);
        msg.textContent = '✅ ' + res.added + '件を追加しました' + (res.dup ? '(重複' + res.dup + '件は除外)' : '');
        $('candBulkSrc').value = '';
        renderCandList(tabId);
      }, true); // force=キャッシュ無視で最新の全件
    });
  }
  // サークルモードから: 表示中サークルの全作品を「💡候補」へ追加。(重複除外・確認あり)
  function addWorksToMain_(works, btn, circleName) {
    if (!works || !works.length) return;
    if (!window.confirm('「' + (circleName || 'このサークル') + '」の全' + works.length + '作品を「💡候補」に追加しますか？')) return;
    var res = appendWorks_(K_ITEMS, works);
    if (btn) { btn.textContent = '✅ ' + res.added + '件を候補へ' + (res.dup ? '(重複' + res.dup + '件除外)' : ''); setTimeout(function () { btn.textContent = '💡 全作品を候補に追加'; }, 3500); }
  }
  // 作品配列を保存キーへ追記。(cid重複は除外)追加数・重複数を返す。
  function appendWorks_(key, works) {
    var items = lsGet(key, '[]'), have = {}; items.forEach(function (x) { have[x.cid] = true; });
    var added = 0, dup = 0;
    works.forEach(function (w) {
      if (!w || !w.cid) return;
      if (have[w.cid]) { dup++; return; }
      items.push({ url: w.url, cid: w.cid, title: w.title, author: w.makerName || w.author || '', thumb: w.thumb || '', listPrice: w.listPrice, price: w.price, discountPct: w.discountPct || 0, date: w.date || '', genres: w.genres || [], reviewCount: w.reviewCount, reviewAvg: w.reviewAvg, addedAt: new Date().getTime() });
      have[w.cid] = true; added++;
    });
    lsSet(key, items); recordReviewSnapshots(items);
    if (added > 0) klog_('candidate_added', 'work', (works[0] && works[0].cid) || '', { added: added, dup: dup });
    return { added: added, dup: dup };
  }
  // 🔁: このタブの各作品の価格・販売数を最新化。(FANZA再取得＋販売数キャッシュ無効化)
  function refreshCandItems(tabId) {
    var key = itemsKey(tabId), items = lsGet(key, '[]');
    if (!items.length) { renderCandList(tabId); return; }
    var cids = items.map(function (it) { return it.cid; });
    var msgEl = $('candMsg');
    var cfg = workerCfg();
    var done = function () { lsSet(key, items); recordReviewSnapshots(items); if (msgEl) msgEl.textContent = ''; invalidateSales_(cids); renderCandList(tabId); };
    if (!window.FanzaCore || !cfg.url) { done(); return; }
    if (msgEl) msgEl.textContent = '⏳ 価格・情報を更新中…';
    var pending = items.length;
    items.forEach(function (it) {
      window.FanzaCore.fetchFanzaInfo(it.cid, cfg.url, cfg.secret, it.url).then(function (info) {
        if (info && info.title) {
          it.title = info.title; if (info.author) it.author = info.author;
          it.listPrice = info.listPrice; it.price = info.price; it.discountPct = info.discountPct || 0;
          if (info.releaseDate) it.date = info.releaseDate;
          if (info.genres && info.genres.length) it.genres = info.genres;
          if (info.thumb || info.thumbSmall) it.thumb = info.thumb || info.thumbSmall;
          if (info.samples && info.samples.length) it.samples = info.samples;
          if (info.reviewCount != null) it.reviewCount = info.reviewCount;
          if (info.reviewAvg != null) it.reviewAvg = info.reviewAvg;
        }
        if (--pending === 0) done();
      }).catch(function () { if (--pending === 0) done(); });
    });
  }
  function renderCandList(tabId) {
    tabId = tabId || 'main';
    invalidatePostedIndex_(); // 投稿済み判定の索引を作り直す(前回描画以降の新規投稿を確実に反映)
    var key = itemsKey(tabId);
    var el = $('candList');
    var all = lsGet(key, '[]');
    if (!all.length) { el.innerHTML = '<p class="hint" style="padding:4px 6px;">まだ候補がありません。上の欄に作品URLを入れて追加してください。</p>'; return; }
    var hidden = lsGet(hiddenKey(tabId), '[]'), hset = {}; hidden.forEach(function (c) { hset[c] = true; });
    var arr = sortItems(all, _sort).filter(function (it) {
      if (!(_showHidden ? hset[it.cid] : !hset[it.cid])) return false;
      if (_filterSale && !isOnSale_(it)) return false;
      if (!passPrice_(it)) return false;
      if (!_showHidden && isHiddenByPosted_(it.cid)) return false; // アカウント別「投稿済みを非表示」
      return true;
    });
    _cardIndex = {}; arr.forEach(function (it) { _cardIndex[it.cid] = it; });
    if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">' + (_showHidden ? '非表示にした作品はありません。' : '表示できる候補がありません。') + '</p>'; return; }
    var topCids = arr.slice(0, 60).map(function (it) { return it.cid; });
    var salesMiss = missingCount(topCids);
    var head = '<p class="hint" style="padding:2px 6px;">' + (_showHidden ? '🙈 非表示中 ' : '') + arr.length + '件' + (_showHidden ? '(「再表示」で戻せます)' : ' / 非表示 ' + hidden.length + '件') +
      (!_showHidden && salesMiss > 0 ? '<br>💰 販売数(実売)は上位' + salesMiss + '件がPC取得待ち。「▶今すぐ取得」を押すか、自動取得を待って🔁で反映されます。(PCの電源が必要)' : '') + '</p>';
    el.innerHTML = head + arr.map(function (it) {
      var act = _showHidden
        ? '<button type="button" class="cand-hide-btn" data-unhide="' + esc(it.cid) + '">👁 再表示</button> <button type="button" class="cand-hide-btn cand-del-btn" data-delcid="' + esc(it.cid) + '" title="削除" aria-label="削除">🗑️</button>'
        : '<button type="button" class="cand-hide-btn" data-hidecid="' + esc(it.cid) + '">非表示</button> <button type="button" class="cand-hide-btn cand-del-btn" data-delcid="' + esc(it.cid) + '" title="削除" aria-label="削除">🗑️</button>';
      return candCard(it, act);
    }).join('');
    wireCardCommon_(el);
    el.querySelectorAll('[data-hidecid]').forEach(function (b) {
      b.addEventListener('click', function () { if (!window.confirm('非表示にしますか？')) return; var h = lsGet(hiddenKey(tabId), '[]'), c = b.getAttribute('data-hidecid'); if (h.indexOf(c) < 0) h.push(c); lsSet(hiddenKey(tabId), h); renderCandList(tabId); });
    });
    el.querySelectorAll('[data-unhide]').forEach(function (b) {
      b.addEventListener('click', function () { var c = b.getAttribute('data-unhide'); lsSet(hiddenKey(tabId), lsGet(hiddenKey(tabId), '[]').filter(function (x) { return x !== c; })); renderCandList(tabId); });
    });
    el.querySelectorAll('[data-delcid]').forEach(function (b) {
      b.addEventListener('click', function () {
        var c = b.getAttribute('data-delcid'), items2 = lsGet(key, '[]');
        var it = items2.filter(function (x) { return x.cid === c; })[0];
        if (!it || !window.confirm('「' + (it.title || c) + '」をこのタブから削除しますか？')) return;
        lsSet(key, items2.filter(function (x) { return x.cid !== c; }));
        tombstoneCid_(tabId, c); // ★削除を墓標に記録＝同期で他端末にも伝播し復活を防ぐ(INC 2026-07-15)
        renderCandList(tabId);
      });
    });
    // 候補作品の実売本数を取得。(未取得はPC取得キューへ)反映されたら再描画。
    fetchSalesFor(topCids, function (changed) { if (changed && _activeTab === tabId) renderCandList(tabId); });
    // タイトル/発売日が未取得の候補を控えめに再取得。(追加直後の一時的な部分取得を自動で埋める)
    backfillMissingInfo_(key, arr, function (changed) { if (changed && _activeTab === tabId) renderCandList(tabId); });
  }

  // ── サークルタブ ──
  function renderMaker(tabId, force) {
    invalidatePostedIndex_(); // 投稿済み判定の索引を作り直す(前回描画以降の新規投稿を確実に反映)
    var tabs = lsGet(K_TABS, '[]');
    var tab = null; tabs.forEach(function (t) { if (t.id === tabId) tab = t; });
    var body = $('candBody');
    if (!tab) { _activeTab = 'main'; render(); return; }
    var sortOpts = SORTS.map(function (s) { return '<option value="' + s.key + '"' + (s.key === _sort ? ' selected' : '') + '>' + s.label + '</option>'; }).join('');
    body.innerHTML = '<div class="card" style="padding:10px 12px;">' +
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
      '<select id="candSort" style="flex:1;min-width:140px;">' + sortOpts + '</select>' +
      '<button id="candReload" type="button" class="ghost" title="全件を取り直す(キャッシュを無視)" style="flex:0 0 auto;width:auto;margin:0;font-size:15px;padding:6px 10px;">🔁</button>' +
      '<button id="candPcRun" type="button" class="ghost" title="PCへ「今すぐ販売数を取得」を要求(PCの電源が必要)" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">▶ 今すぐ取得</button>' +
      '<button id="candEditTab" type="button" class="ghost" title="タブ名・サークルを編集" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">✏️ 編集</button>' +
      '</div>' +
      // アカウント別「投稿済みを非表示」トグル。(非表示リストの上段・右寄せ)両方同時ON可。
      candHidePostedRowHtml_() +
      // 省スペース行：セール絞込(左)＋列数(PCのみ)＋非表示トグル(右端・状態で色と文言が変化)
      '<div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;">' +
        '<label class="cand-filter-sale" style="margin:0;"><input id="candFilterSale" type="checkbox"' + (_filterSale ? ' checked' : '') + '><span>セール中のみ</span></label>' +
        priceFilterHtml_() +
        candColsCtlHtml_() +
        '<span style="flex:1 1 auto;"></span>' +
        '<button id="candShowHidden" type="button" class="cand-hidden-toggle' + (_showHidden ? ' active' : '') + '" style="flex:0 0 auto;width:auto;margin:0;font-size:12px;padding:6px 11px;">' + (_showHidden ? '👁 通常表示に戻す' : '非表示リスト') + '</button>' +
      '</div>' +
      (_sort === 'rank7d' ? '<div class="hint" style="margin-top:6px;">' + esc(RANK7D_NOTE) + '</div>' : '') +
      ((_sort === 'rank' || _sort === 'rank7d') ? '<div class="hint" style="margin-top:4px;">' + esc(SALES_NOTE) + '</div>' : '') +
      '</div>' +
      '<div id="candEditForm"></div>' +
      '<div id="candMakerList"><p class="hint" style="padding:8px;">' + (force ? '🔁 全件を取り直しています…' : '⏳ サークルの作品を取得中…') + '</p></div>';
    $('candSort').addEventListener('change', function () { _sort = this.value; renderMaker(tabId); });
    $('candShowHidden').addEventListener('click', function () { _showHidden = !_showHidden; renderMaker(tabId); });
    $('candFilterSale').addEventListener('change', function () { _filterSale = this.checked; renderMaker(tabId); });
    wirePriceFilter_(function () { renderMaker(tabId); });
    wireCandColsCtl_();
    wireHidePostedButtons_(function () { renderMaker(tabId); });
    $('candReload').addEventListener('click', function () { renderMaker(tabId, true); });
    bindPcRun_($('candPcRun'), 'candMakerList');
    $('candEditTab').addEventListener('click', function () { showEditTabForm(tab); });
    var makerIds = makerIdsOf(tab);
    fetchMakerItemsMulti(makerIds, _sort, function (items, err, throttled) {
      var el = $('candMakerList');
      if (!el || _activeTab !== tabId) return;
      if (err) { el.innerHTML = '<p class="hint" style="padding:8px;">⚠️ ' + esc(err) + '</p>'; return; }
      var throttleNote = throttled ? '<p class="hint" style="padding:2px 6px;">🕘 さっき取得したばかりです。負荷軽減のため直近の結果を表示中(約1分後の🔁で最新を取り直せます)。</p>' : '';
      // タブ名が自動生成の「サークルNNN」のままで、一覧からサークル名が取れたら本名へ自動修正。(単一サークルのタブのみ)
      if (makerIds.length === 1 && items && items.length && items[0].makerName && /^サークル\d+$/.test(tab.name || '')) {
        var tabs2 = lsGet(K_TABS, '[]');
        tabs2.forEach(function (t) {
          if (t.id !== tabId) return;
          t.name = items[0].makerName; t.makerName = items[0].makerName;
          if (Array.isArray(t.makers) && t.makers.length) t.makers[0].name = items[0].makerName;
        });
        lsSet(K_TABS, tabs2);
        render(); return; // タブバーを本名で再描画(この後の描画は再入で行われる)
      }
      var hidden = lsGet(hiddenKey(tabId), '[]');
      var hset = {}; hidden.forEach(function (c) { hset[c] = true; });
      var arr = sortItems(items, _sort).filter(function (it) {
        if (!(_showHidden ? hset[it.cid] : !hset[it.cid])) return false;
        if (_filterSale && !isOnSale_(it)) return false;
        if (!passPrice_(it)) return false;
        if (!_showHidden && isHiddenByPosted_(it.cid)) return false; // アカウント別「投稿済みを非表示」
        return true;
      });
      if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">' + (_showHidden ? '非表示にした作品はありません。' : '表示できる作品がありません。') + '</p>'; return; }
      _cardIndex = {}; arr.forEach(function (it) { _cardIndex[it.cid] = it; });
      // 実売本数(販売数)を先頭60件ぶん取得。(未取得はPC取得キューへ自動登録)反映されたら再描画。
      var topCids = arr.slice(0, 60).map(function (it) { return it.cid; });
      var salesMiss = missingCount(topCids);
      var head = throttleNote + '<div style="display:flex;justify-content:flex-end;padding:2px 6px 6px;">' +
        '<button id="candBulkToCand" type="button" class="ghost" style="width:auto;margin:0;font-size:12.5px;padding:6px 10px;">💡 全作品を候補に追加</button></div>' +
        '<p class="hint" style="padding:2px 6px;">' + (_showHidden ? '🙈 非表示中の作品 ' : '') + arr.length + '件' + (makerIds.length > 1 ? '(' + makerIds.length + 'サークル)' : '') + (_showHidden ? '(「再表示」で戻せます)' : ' / 非表示 ' + hidden.length + '件・不足なら🔁リロード') +
        (!_showHidden && salesMiss > 0 ? '<br>💰 販売数(実売)は上位' + salesMiss + '件がPC取得待ち。「▶今すぐ取得」を押すか、自動取得を待って🔁で反映されます。(PCの電源が必要)' : '') + '</p>';
      el.innerHTML = head + arr.map(function (it) {
        var btn = _showHidden
          ? '<button type="button" class="cand-hide-btn" data-unhide="' + esc(it.cid) + '">👁 再表示</button>'
          : '<button type="button" class="cand-hide-btn" data-hide="' + esc(it.cid) + '">非表示</button>';
        return candCard(it, btn);
      }).join('');
      wireCardCommon_(el);
      var bulkBtn = $('candBulkToCand');
      if (bulkBtn) bulkBtn.addEventListener('click', function () { addWorksToMain_(items, bulkBtn, tab.name); });
      if (!_showHidden && !force) fetchSalesFor(topCids, function (changed) { if (changed && _activeTab === tabId) renderMaker(tabId); });
      el.querySelectorAll('[data-hide]').forEach(function (b) {
        b.addEventListener('click', function () {
          if (!window.confirm('非表示にしますか？')) return;
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

  // ── タブ編集モーダル(タブ名の変更・サークルの追加/削除・タブ削除) ──
  //   サークルタブは1タブに複数サークルを持てる。現在のサークルを一覧表示し、追加/個別削除できる。
  function showEditTabForm(tab) {
    var f = $('candEditForm');
    if (!f) return;
    // 最新のtab状態を取り直す(追加/削除で再入した時に反映)
    lsGet(K_TABS, '[]').forEach(function (t) { if (t.id === tab.id) tab = t; });
    var isMaker = isMakerTab_(tab); // サークルタブのみ「サークル一覧＋追加」欄を出す(候補タブは名前のみ編集)
    var makers = makersOf(tab);
    var makersHtml = '';
    if (isMaker) {
      makersHtml =
        '<label class="hint" style="display:block;margin:8px 0 2px;">このタブに表示するサークル(複数可)</label>' +
        '<div id="candEditMakers">' + makers.map(function (m) {
          return '<div style="display:flex;align-items:center;gap:8px;margin:4px 0;">' +
            '<span style="flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + CIRCLE_ICON + ' ' + esc(m.name || ('サークル' + m.id)) + ' <span class="hint">(ID ' + esc(m.id) + ')</span></span>' +
            '<button type="button" class="ghost cand-maker-del" data-mkid="' + esc(m.id) + '" style="flex:0 0 auto;width:auto;margin:0;font-size:12px;padding:4px 9px;color:#c0392b;border-color:#c0392b;"' + (makers.length <= 1 ? ' disabled title="最後の1件は外せません(タブ削除を使ってください)"' : '') + '>🗑</button>' +
          '</div>';
        }).join('') + '</div>' +
        '<label class="hint" style="display:block;margin:8px 0 2px;">サークルを追加(ID / サークルURL / 作品URL)</label>' +
        pasteRow_('<input id="candEditSrc" type="text" inputmode="url" autocomplete="off" placeholder="追加したいサークルを入れて「＋ 追加」" style="flex:1;">', 'candEditSrc') +
        '<button id="candEditAddMaker" type="button" class="ghost" style="width:max-content;margin:6px 0 0;font-size:12.5px;padding:6px 11px;">＋ サークルを追加</button>';
    }
    f.innerHTML = '<div class="card" style="margin:8px 0;">' +
      '<div class="field-label" style="margin-top:0;">✏️ タブを編集</div>' +
      '<label class="hint" style="display:block;margin-bottom:2px;">タブ名(長い場合は短く編集できます)</label>' +
      '<input id="candEditName" type="text" autocomplete="off" value="' + esc(tab.name) + '">' +
      makersHtml +
      '<label class="cand-filter-sale" style="display:flex;align-items:center;gap:6px;margin:12px 0 2px;"><input id="candEditExclude" type="checkbox"' + (tab.excludeFromAll ? ' checked' : '') + '><span>このタブを📚全候補に含めない(各部門の読み取りからも除外)</span></label>' +
      '<div style="display:flex;gap:8px;margin-top:8px;">' +
      '<button id="candEditSave" type="button" class="primary" style="flex:1;font-size:.9rem;padding:10px;">保存</button>' +
      '<button id="candEditDel" type="button" class="ghost" style="flex:0 0 auto;width:auto;color:#c0392b;border-color:#c0392b;">タブ削除</button>' +
      '<button id="candEditCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">やめる</button>' +
      '</div><div id="candEditMsg" class="hint" style="min-height:1.3em;"></div></div>';
    wirePaste_(f);
    $('candEditCancel').addEventListener('click', function () { f.innerHTML = ''; render(); });
    // サークルを個別に外す。(他タブが使っていなければ追跡解除)外したら編集フォームを再描画。
    f.querySelectorAll('.cand-maker-del').forEach(function (b) {
      b.addEventListener('click', function () {
        if (b.disabled) return;
        var mkid = String(b.getAttribute('data-mkid'));
        var cur = makersOf(tab);
        if (cur.length <= 1) return;
        if (!window.confirm('このサークルをタブから外しますか？')) return;
        writeMakers_(tab.id, cur.filter(function (m) { return String(m.id) !== mkid; }));
        if (!lsGet(K_TABS, '[]').some(function (t) { return makerIdsOf(t).indexOf(mkid) >= 0; })) trackMaker(mkid, '', true);
        showEditTabForm(tab);
      });
    });
    // サークルを追加。(重複は弾く)追加したら編集フォームを再描画。
    var addBtn = $('candEditAddMaker');
    if (addBtn) addBtn.addEventListener('click', function () {
      var src = ($('candEditSrc').value || '').trim();
      var msg = $('candEditMsg');
      if (!src) { msg.textContent = '⚠️ 追加するサークル情報を入れてください'; return; }
      msg.textContent = '⏳ サークルを特定中…';
      resolveMakerId(src, function (makerId, makerName, err) {
        if (!makerId) { msg.textContent = '⚠️ ' + err; return; }
        var cur = makersOf(tab);
        if (cur.some(function (m) { return String(m.id) === String(makerId); })) { msg.textContent = '⚠️ そのサークルは既に追加済みです'; return; }
        cur.push({ id: String(makerId), name: makerName || ('サークル' + makerId) });
        writeMakers_(tab.id, cur);
        trackMaker(makerId, makerName || ''); // 追加した時点でPCバッチの販売数自動取得の対象にする
        showEditTabForm(tab);
      });
    });
    $('candEditDel').addEventListener('click', function () {
      if (!window.confirm('タブ「' + tab.name + '」を削除しますか？' + (isMaker ? '(非表示リストも消えます)' : '(このタブに貯めた候補も消えます)'))) return;
      var rest = lsGet(K_TABS, '[]').filter(function (t) { return t.id !== tab.id; });
      lsSet(K_TABS, rest);
      try { localStorage.removeItem(hiddenKey(tab.id)); } catch (e) {}
      try { localStorage.removeItem(itemsKey(tab.id)); } catch (e) {} // 候補タブの保存アイテムも破棄
      // 他タブが使っていないサークルはPCバッチの追跡対象から外す
      makerIdsOf(tab).forEach(function (mid) {
        if (!rest.some(function (t) { return makerIdsOf(t).indexOf(mid) >= 0; })) trackMaker(mid, '', true);
      });
      _activeTab = 'main'; render();
    });
    $('candEditSave').addEventListener('click', function () {
      var name = ($('candEditName').value || '').trim();
      if (!name) { $('candEditMsg').textContent = '⚠️ タブ名を入れてください'; return; }
      var exclude = !!($('candEditExclude') && $('candEditExclude').checked); // 📚全候補に含めない
      var tabs = lsGet(K_TABS, '[]');
      tabs.forEach(function (t) { if (t.id === tab.id) { t.name = name; t.excludeFromAll = exclude; } });
      lsSet(K_TABS, tabs);
      f.innerHTML = ''; render(); // タブバー再描画＋一覧再取得
    });
  }

  // 作品カード。(候補/サークル共通・縦並び)actionHtml=右下のボタン。(削除/非表示/再表示)
  function candCard(it, actionHtml) {
    var sale = isOnSale_(it);
    var priceHtml = '<span class="cand-price-lbl">現価格:</span> ' + (sale
      ? '<span class="cand-list-price">' + yen(it.listPrice) + '</span> <b class="cand-sale">' + yen(it.price) + '</b> <span class="cand-off">' + it.discountPct + '%off</span>'
      : '<b>' + yen(it.price != null ? it.price : it.listPrice) + '</b>');
    var sub = [];
    if (it.author || it.makerName) sub.push(CIRCLE_ICON + ' ' + esc(it.author || it.makerName));
    if (it.date) sub.push('発売 ' + esc(fmtDate(it.date)));
    if (it.addedAt) sub.push('<span class="cand-added">追加 ' + esc(fmtTs(it.addedAt)) + '</span>');
    var ws = deriveWorkState_(it.date);
    var badgesHtml = (ws ? stateBadgeHtml_(ws) : '') + ((!it.isTwitter && it.url) ? workKindBadgeHtml_(it.url) : '') + (isAiWork_(it.genres) ? '<span class="fp-kind fp-kind-ai">AI</span>' : '');
    var genresHtml = (it.genres && it.genres.length)
      ? '<div class="fz-genres" style="margin-top:4px;">' + it.genres.slice(0, 5).map(function (g) { return '<span class="fz-genre">' + esc(g) + '</span>'; }).join('') + '</div>'
      : '';
    // 売れ行きの数値。販売数(実売)とレビュー件数を「並べて」常に表示する(Chami指定2026-07-14)。
    //   従来はどちらか一方だけ=追加方法で表示が割れていた。以後は両方を1行に「・」で連結する。
    var rc = it.reviewCount;
    var avg = (it.reviewAvg != null && it.reviewAvg !== '') ? (' ★' + it.reviewAvg) : '';
    var num = function (n) { return Number(n).toLocaleString('ja-JP'); };
    var sales = salesOf(it.cid); // number=実売 / null=PC未取得 / undefined=未問い合わせ
    // ① 販売数パート。取得済み=実数 / PC未取得(null)=取得待ち / 未問い合わせ(undefined)=省略。
    var salesPart = '';
    if (typeof sales === 'number') {
      salesPart = '販売数 ' + num(sales) + '本';
      // rank7d でも「+0本」は出さない=週次の伸びが正の時だけ🔥を前置(全部0に見える誤解を解消)。
      if (_sort === 'rank7d') {
        var sd = weekSalesDelta(it.cid, sales);
        if (sd != null && sd > 0) salesPart = '🔥 直近1週間 +' + num(sd) + '本 (累計 ' + num(sales) + '本)';
      }
    } else if (sales === null) {
      salesPart = '販売数 取得待ち'; // PC(日本IP)のバッチ取得待ち
    }
    // ② レビューパート。件数があれば常に併記(販売数の横)。
    var reviewPart = (rc != null) ? ('レビュー ' + num(rc) + '件' + avg) : '';
    var joined = [salesPart, reviewPart].filter(Boolean).join(' ・ ');
    var salesHtml = joined ? '<div class="cand-sales">' + joined + '</div>' : '';
    var hasRef = refImgHas(it.cid);
    var hasBsky = bskyImgHas(it.cid);
    var refImgs = refImgsOf_(it.cid);          // 動画生成用に保存した画像(複数可)
    var refImgSrc = refImgs[0] || '';
    var _refRec = refImgOf(it.cid) || {};
    var refCmt = _refRec.comment || ''; // 保存済みコメント(動画生成用画像の真下に全文表示)
    var refMemo = _refRec.memo || '';   // メモ(コメントが無い時にカードへ水色で代替表示)
    // 動画生成用の画像は作品サムネの真下(左の画像列)に少し余白を開けて縦積み。点線の区切りは廃止。
    var refImgHtml = refImgSrc ? '<img class="cand-refimg-thumb' + (refImgs.length > 1 ? ' multi' : '') + '" data-refimgview="' + esc(it.cid) + '" src="' + esc(refImgSrc) + '" loading="lazy" alt="動画生成用の画像(タップで拡大)" title="動画生成用の画像(タップで拡大' + (refImgs.length > 1 ? '・複数あり' : '') + ')">' : '';
    // メモ(コメントの上・水色)とコメント(🙈/🗑と同じ管理行の左)は下の return 内で直接組み立てる。
    // 投稿済み作品はカード大枠をチャンネルのイメージカラーで太線囲み。両channel投稿は月詠み(外)＋宵桜(内)の二重。
    var _pAcc1 = !!postedItemForCid_(it.cid, 'acc1'), _pAcc2 = !!postedItemForCid_(it.cid, 'acc2');
    var _postCls = (_pAcc1 && _pAcc2) ? ' cand-posted-both' : (_pAcc1 ? ' cand-posted-acc1' : (_pAcc2 ? ' cand-posted-acc2' : ''));
    var _noComment = !refCmt && !refMemo; // コメント/メモ無し＝非表示/🗑を作品リンク行に統合し余白を縮小
    if (_noComment) _postCls += ' cand-nocomment';
    // 作品リンク群。(作品↗ / X↗ / X2↗ / 投稿編集 / 🦋)無コメント時は全幅行で非表示/🗑と同列に置くため変数化。
    var _actionsInner =
      ((!it.isTwitter && it.url) ? '<a class="vlink vlink-work" href="' + esc(it.url) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
      (it.twitterUrl ? (function (su) { var isB = /bsky\.app\//.test(su); return '<a class="vlink" href="' + esc(su) + '" target="_blank" rel="noopener" style="color:' + (isB ? '#1185fe' : '#1d9bf0') + ';">' + (isB ? 'B↗' : 'X↗') + '</a>'; })(it.twitterUrl) : '') +
      (_refRec.twitterUrl2 ? (function (su) { var isB = /bsky\.app\//.test(su); return '<a class="vlink" href="' + esc(su) + '" target="_blank" rel="noopener" style="color:' + (isB ? '#1185fe' : '#1d9bf0') + ';">' + (isB ? 'B2↗' : 'X2↗') + '</a>'; })(_refRec.twitterUrl2) : '') +
      '<button type="button" class="cand-refimg-btn' + (hasRef ? ' has-img' : '') + '" data-refimg="' + esc(it.cid) + '">投稿編集</button>' +
      '<button type="button" class="cand-bsky-btn' + (hasBsky ? ' has-img' : '') + '" data-bsky="' + esc(it.cid) + '" title="Bluesky投稿に添付する画像を保存">🦋' + (hasBsky ? '✓' : '') + '</button>';
    return '<div class="cand-card' + _postCls + '">' +
      '<div class="cand-thumbcol">' +
        (it.thumb ? '<img class="cand-thumb cand-thumb-click" data-thumbcid="' + esc(it.cid) + '" src="' + esc(it.thumb) + '" loading="lazy" alt="タップで画像を表示">' : '<div class="cand-thumb cand-thumb-ph"></div>') +
        refImgHtml +
      '</div>' +
      '<div class="cand-info">' +
        // 新作/同人バッジと同じ行にチャンネル表記を並べる(バッジ＝左／チャンネル＝右寄せ。投稿済み＝pillボタン／未投稿＝淡色表記)
        //   投稿済みなら Books 等と pill の間に「投稿日 ✔」をチャンネルテーマ色で表示。
        '<div class="cand-badges-row">' + badgesHtml + '<span class="cand-acct-group">' + postedDatesHtml_(it.cid) + acctBadgesHtml_(it.cid) + '</span></div>' +
        '<div class="cand-title">' + esc(it.title || '(無題)') + '</div>' +
        (sub.length ? '<div class="cand-sub">' + sub.join('　') + '</div>' : '') +
        genresHtml +
        ((it.price != null || it.listPrice != null) ? '<div class="cand-price">' + priceHtml + '</div>' : '') +
        salesHtml +
        // 作品リンク行。(cand-info内＝画像の右の定位置)コメント/メモ無し時は同じ行の右端に 非表示/🗑 を統合。
        '<div class="cand-actions">' + _actionsInner + (_noComment ? '<span class="cand-actions-mspacer"></span>' + actionHtml : '') + '</div>' +
      '</div>' +
      // コメント(黒・全幅・必ず1行＝可変縮小)＝独立行。
      (refCmt ? '<div class="cand-comment-row"><span class="cand-manage-comment">' + esc(refCmt) + '</span></div>' : '') +
      // メモ(水色・左・必ず1行)＋ 非表示/🗑(右)を同じ行に統合＝余白節約。コメント/メモ無し時は作品リンク行に統合済み。
      (_noComment ? '' :
        '<div class="cand-manage-row">' + (refMemo ? '<span class="cand-manage-memo">' + esc(refMemo) + '</span>' : '<span class="cand-manage-spacer"></span>') + actionHtml + '</div>') +
      '</div>';
  }

  // ランキングタブ(yt-clicks.js)から「動画生成用に保存した画像」を参照するための公開API。
  try { window.Go5Cand = {
    render: render,
    refImgs: refImgsOf_,                                        // cid → 動画生成用の保存画像の配列(無ければ[])
    bskyImg: function (cid) { var r = bskyImgOf(cid); return (r && r.img) || ''; }, // cid → Bluesky添付画像(無ければ'')
    zoomImages: function (images, idx, opts) { openImgZoom_((images || []).filter(Boolean), idx || 0, opts); }, // 任意の画像配列をズーム。(スワイプ)opts.captions=ページ別見出し
    zoomRefImgs: function (cid) { var a = refImgsOf_(cid); if (a.length) openImgZoom_(a, 0, { onReorder: function (i) { return reorderRefImgToFirst_(cid, i); }, onPasteAdd: function (done) { pasteAddRefImgToFirst_(cid, done); } }); }, // タップで全画像ズーム＋1ページ目にする＋貼り付け新規追加
    postImgs: postImgsOf_,                                      // 履歴キー → 🛠️編集で添付した投稿画像の配列(無ければ[])
    postImgHas: function (key) { return postImgsOf_(key).length > 0; },
    postImgSave: postImgSave_,                                  // 履歴キー + 画像配列 を保存(write-through)
    // ── 🛠️編集の画像添付(貼り付け＋用途選択・Chami依頼2026-07-15)用の公開API ──
    pasteImage: function (cb) { return pasteImageFromClipboard_(cb); }, // クリップボード画像→dataURL(cb(durl,err))
    refImgsSet: function (cid, arr) { if (!cid) return false; var cur = refImgOf(cid) || {}; return refImgSave(cid, { imgs: (arr || []).filter(Boolean), comment: cur.comment || '', memo: cur.memo || '', twitterUrl: cur.twitterUrl || '', twitterUrl2: cur.twitterUrl2 || '' }); }, // 動画で使った画像(配列)を差し替え保存(コメント等は保持)
    bskyImgSet: function (cid, durl) { if (!cid) return false; return bskyImgSave(cid, durl || ''); } // Bluesky添付画像(単発)を設定/クリア
  }; } catch (e) {}
  hydrateImages_(); // IDBから画像をメモリへ＋旧localStorage画像を移行(5MB枠を解放)
  // 既存タブの移行: 登録済みサークルをPCバッチの追跡対象へ(登録済みはフラグでスキップ＝通信は初回のみ)
  ensureTrackedAll();
}());
