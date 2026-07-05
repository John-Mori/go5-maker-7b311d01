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
  // 作品URLのホストで判定：book.dmm.(com|co.jp) = FANZA Books、それ以外(dmm.co.jp同人等) = 同人(コミックス)。
  function workKindOf_(url) { return /book\.dmm\.(com|co\.jp)/i.test(url || '') ? 'Books' : '同人'; }
  function workKindBadgeHtml_(url) {
    var kind = workKindOf_(url);
    return '<span class="fp-kind ' + (kind === 'Books' ? 'fp-kind-books' : 'fp-kind-doujin') + '">' + kind + '</span>';
  }
  // ジャンルタグに「AI」を含むものがあれば AI 作品とみなす（わかる範囲のベストエフォート判定）。
  function isAiWork_(genres) { return (genres || []).some(function (g) { return /AI/i.test(String(g || '')); }); }

  // ── 保存キー ──
  var K_ITEMS = 'cand_items';   // 候補リスト(共通): [{url,cid,title,author,thumb,listPrice,price,discountPct,addedAt}]
  var K_TABS = 'cand_tabs';    // サークルタブ: [{id,name,makerId,makerName}]
  function hiddenKey(tabId) { return 'cand_hidden__' + tabId; }
  // ★キャッシュ版数(v2)：v170前の「最大400件しか取れていない不完全キャッシュ」を確実に無効化する。
  //   これを上げると全ユーザーの旧キャッシュが読まれなくなり、次回表示で全件を取り直す。
  function cacheKey(makerId, mode) { return 'cand_mk2__' + makerId + '__' + mode; }
  var CACHE_TTL = 3 * 3600 * 1000;

  var _activeTab = 'main'; // 'main' | サークルタブid
  var _sort = 'added_desc';
  var _showHidden = false;
  var _filterSale = false; // 絞り込み：ONでセール中(値引き)の作品のみ表示
  var _suppressNextClick = false; // タブ並べ替え(ドラッグ/長押し)直後のクリック(タブ切替)を1回だけ抑止
  // 並べ替え対象外の固定タブ（🦋バズ・💡候補）。左端の2つは動かさない。
  function isFixedCandTab_(id) { return id === 'main' || id === 'buzz'; }

  var SORTS = [
    { key: 'added_desc', label: '追加日が新しい順' },
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
  // 指定cidの販売数キャッシュを無効化（🔁リロードで最新を取り直すため）。
  function invalidateSales_(cids) { var c = salesCache(); (cids || []).forEach(function (cid) { delete c[cid]; }); lsSet(K_SALES, c); }

  // ── 現在描画中カードの cid→item 索引（サムネ/投稿画像モーダルが item を引くため）──
  var _cardIndex = {};
  function itemByCid_(cid) { return _cardIndex[cid] || null; }

  // ── 作品ごとの保存画像（refimg=生成用の元画像＋コメント＋Twitter URL / bskyimg=Bluesky添付用）──
  //   保存先は IndexedDB（容量は端末の空きに応じて数百MB〜＝iOS Safariの localStorage 約5MB壁を回避）。
  //   読みは同期のままにしたいので、起動時に全画像をメモリ(_imgMem)へハイドレートし以後は同期参照。
  //   書きは _imgMem を即更新＋IDBへ非同期反映（write-through）。IDB非対応時は localStorage フォールバック。
  var _imgMem = { ref: {}, bsky: {} };
  var _idbOk = !!(window.Go5Idb && window.Go5Idb.available());
  function refImgKey(cid) { return 'cand_refimg__' + cid; }   // localStorage互換キー（フォールバック/移行用）
  function bskyImgKey(cid) { return 'cand_bskyimg__' + cid; }
  function idbKey(kind, cid) { return kind + ':' + cid; }     // IDBキー 'ref:<cid>' / 'bsky:<cid>'
  function idbFail_(e) { try { console.warn('[go5 idb] 画像保存に失敗（メモリには保持）', e); } catch (_) {} }

  function refImgOf(cid) {
    if (_idbOk) return _imgMem.ref[cid] || null;
    try { return JSON.parse(localStorage.getItem(refImgKey(cid)) || 'null'); } catch (e) { return null; }
  }
  // 保存画像を常に配列で返す（旧形式 {img:単発} → [img] に正規化・新形式は {imgs:[...]}. 37ページ級の複数コマ保持に対応）。
  function refImgsOf_(cid) {
    var r = refImgOf(cid); if (!r) return [];
    if (Array.isArray(r.imgs)) return r.imgs.filter(Boolean);
    return r.img ? [r.img] : [];
  }
  function refImgHas(cid) {
    var r = refImgOf(cid); if (!r) return false; // 1回の読みで判定（フォールバック時の多重JSON.parse回避）
    var has = Array.isArray(r.imgs) ? r.imgs.some(Boolean) : !!r.img;
    return !!(has || r.comment || r.twitterUrl);
  }
  function refImgSave(cid, data) {
    // data.imgs（配列・新）または data.img（単発・旧）を受け付け、{imgs, img:先頭} で保存（img は旧読み手互換用）。
    var imgs = data ? (Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : (data.img ? [data.img] : [])) : [];
    var empty = !data || (!imgs.length && !data.comment && !data.twitterUrl);
    var rec = empty ? null : { imgs: imgs, img: imgs[0] || '', comment: data.comment || '', twitterUrl: data.twitterUrl || '', at: new Date().getTime() };
    if (_idbOk) {
      if (rec) _imgMem.ref[cid] = rec; else delete _imgMem.ref[cid];
      (rec ? window.Go5Idb.set(idbKey('ref', cid), rec) : window.Go5Idb.del(idbKey('ref', cid))).catch(idbFail_);
      return true; // IDBは容量に余裕。非同期失敗は稀（メモリ保持＋ログ）
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
    var rec = img ? { img: img, at: new Date().getTime() } : null;
    if (_idbOk) {
      if (rec) _imgMem.bsky[cid] = rec; else delete _imgMem.bsky[cid];
      (rec ? window.Go5Idb.set(idbKey('bsky', cid), rec) : window.Go5Idb.del(idbKey('bsky', cid))).catch(idbFail_);
      return true;
    }
    try {
      if (!rec) { localStorage.removeItem(bskyImgKey(cid)); return true; }
      localStorage.setItem(bskyImgKey(cid), JSON.stringify(rec));
      return true;
    } catch (e) { return false; }
  }

  // 起動時：IDBから全画像をメモリへ + localStorageの旧画像をIDBへ移行して5MB枠を解放。
  function hydrateImages_() {
    if (!_idbOk) return;
    window.Go5Idb.entries().then(function (all) {
      Object.keys(all || {}).forEach(function (k) {
        var v = all[k];
        if (k.indexOf('ref:') === 0) _imgMem.ref[k.slice(4)] = v;
        else if (k.indexOf('bsky:') === 0) _imgMem.bsky[k.slice(5)] = v;
      });
      return migrateLocalImages_();
    }).then(function () {
      // 画像がメモリに載ったので、候補タブ表示中なら描画し直す（サムネ・✓バッジを反映）。
      try { var pc = document.getElementById('pageCand'); if (pc && !pc.hidden) render(); } catch (e) {}
    }).catch(function (e) {
      // オープン/読み取りに失敗＝この環境ではIDB不可。localStorageフォールバックへ切り替え（旧データはそのまま読める）。
      _idbOk = false; try { console.warn('[go5 idb] 利用不可のためlocalStorageで継続', e); } catch (_) {}
    });
  }
  // localStorage の cand_refimg__* / cand_bskyimg__* を IDB へ移して localStorage から削除（冪等・IDB書込成功後にのみ削除＝データロス防止）。
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
        .catch(idbFail_); // 失敗時はlocalStorageに残す（次回再試行）
    });
    return Promise.all(jobs);
  }
  // クリップボードの文字列を対象inputへ貼り付け（[data-paste=inputId] のボタンを配線）。
  function wirePaste_(root) {
    (root || document).querySelectorAll('.paste-btn[data-paste]').forEach(function (b) {
      if (b._wired) return; b._wired = true;
      b.addEventListener('click', function () {
        var inp = document.getElementById(b.getAttribute('data-paste')); if (!inp) return;
        if (navigator.clipboard && navigator.clipboard.readText) {
          navigator.clipboard.readText().then(function (t) { inp.value = (t || '').trim(); inp.focus(); inp.dispatchEvent(new Event('change')); })
            .catch(function () { inp.focus(); alert('クリップボードを読み取れませんでした。入力欄を長押しして貼り付けてください。'); });
        } else { inp.focus(); alert('この環境ではボタン貼り付けに未対応です。入力欄を長押しして貼り付けてください。'); }
      });
    });
  }
  // input要素のHTMLに「📋貼り付け」ボタンを横付けした行を返す（inputはflex:1で伸びる）。
  function pasteRow_(inputHtml, inputId) {
    return '<div style="display:flex;gap:6px;align-items:stretch;">' + inputHtml +
      '<button type="button" class="ghost paste-btn" data-paste="' + inputId + '" title="コピー中の文字を貼り付け" style="flex:0 0 auto;width:auto;margin:0;white-space:nowrap;padding:0 12px;">📋 貼り付け</button></div>';
  }
  // 画像ファイル→縮小dataURL(長辺1280px・JPEG)。localStorage肥大とQuota超過を防ぐ。
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
  // クリップボードにコピーされた画像を取り出して縮小dataURLで返す。cb(dataUrl, err)。
  function pasteImageFromClipboard_(cb) {
    if (!(navigator.clipboard && navigator.clipboard.read)) { cb(null, 'この端末では画像の貼り付けに未対応です（「画像を選ぶ」をお使いください）'); return; }
    navigator.clipboard.read().then(function (items) {
      for (var i = 0; i < items.length; i++) {
        var t = (items[i].types || []).filter(function (x) { return /^image\//.test(x); })[0];
        if (t) { items[i].getType(t).then(function (blob) { fileToScaledDataUrl(blob, cb); }).catch(function () { cb(null, '画像を取り出せませんでした'); }); return; }
      }
      cb(null, 'クリップボードに画像がありません（先に画像をコピーしてください）');
    }).catch(function () { cb(null, 'クリップボードを読み取れませんでした（貼り付けの許可が必要です）'); });
  }

  // ── サンプル画像キャッシュ（サムネモーダル用。cid毎にサンプルURL配列を保持）──
  var K_SAMPLES = 'cand_samples';
  function samplesCacheGet(cid) { var c = lsGet(K_SAMPLES, '{}')[cid]; return (c && Array.isArray(c.imgs)) ? c : null; }
  function samplesCacheSet(cid, imgs, thumb) { var all = lsGet(K_SAMPLES, '{}'); all[cid] = { imgs: imgs || [], thumb: thumb || '', at: new Date().getTime() }; lsSet(K_SAMPLES, all); }

  // ── サムネ/サンプル画像モーダル（投稿履歴の詳細ビューと同じ .fz-* を流用したライトボックス）──
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
  // 画像ズーム（左右スワイプで切替）。.fz-zoom を流用。
  var _zoom = null, _zoomList = [], _zi = 0;
  function ensureZoom_() {
    if (_zoom) return _zoom;
    var z = document.createElement('div'); z.className = 'fz-zoom'; z.hidden = true;
    z.innerHTML = '<button class="fz-zoom-close" type="button" aria-label="閉じる">✕</button><img class="fz-zoom-img" alt=""><div class="fz-zoom-count"></div>';
    document.body.appendChild(z);
    z.addEventListener('click', function (e) { if (e.target === z) z.hidden = true; });
    z.querySelector('.fz-zoom-close').addEventListener('click', function () { z.hidden = true; });
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
    z.querySelector('.fz-zoom-count').textContent = _zoomList.length > 1 ? (_zi + 1) + ' / ' + _zoomList.length : '';
    z.hidden = false;
  }
  function zoomGo_(d) { if (!_zoomList.length) return; _zi = (_zi + d + _zoomList.length) % _zoomList.length; zoomShow_(); }
  function openImgZoom_(images, idx) { if (!images || !images.length) return; _zoomList = images.slice(); _zi = Math.min(Math.max(0, idx || 0), _zoomList.length - 1); zoomShow_(); }

  // この作品(cid)が各チャンネルで投稿済みか（投稿履歴の workUrl→cid 照合）。{acc1,acc2} を返す。
  var _ACCTS = [['acc1', '月詠み'], ['acc2', '宵桜艶帖']];
  function postedChannelsForCid_(cid) {
    var out = { acc1: false, acc2: false };
    if (!cid || typeof window.Go5PostedWorkUrls !== 'function') return out;
    _ACCTS.forEach(function (a) {
      var urls = window.Go5PostedWorkUrls(a[0]) || [];
      out[a[0]] = urls.some(function (u) {
        var r = window.buildAffiliateLink ? window.buildAffiliateLink(u, '') : null;
        return r && r.ok && r.cid === cid;
      });
    });
    return out;
  }
  function curAccount_() { try { return window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'; } catch (e) { return 'acc1'; } }
  // モーダル右上のアカウント切替ボタン列（該当chで投稿済みなら「投稿済」表示＝重複投稿の抑止）。
  function acctRowHtml_(cid) {
    var posted = postedChannelsForCid_(cid), cur = curAccount_();
    return '<div class="cand-acct-row">' + _ACCTS.map(function (a) {
      var p = posted[a[0]];
      return '<button type="button" class="cand-acct-btn cand-acct-' + a[0] + (a[0] === cur ? ' active' : '') + (p ? ' posted' : '') + '" data-acct="' + a[0] + '" title="' + (p ? 'このチャンネルで投稿済み' : 'このチャンネルに切替') + '">' +
        esc(a[1]) + (p ? '<span class="cand-acct-posted">✓投稿済</span>' : '') + '</button>';
    }).join('') + '</div>';
  }
  function wireAcctRow_(body) {
    body.querySelectorAll('[data-acct]').forEach(function (b) {
      b.addEventListener('click', function () {
        var a = b.getAttribute('data-acct');
        var hdr = document.getElementById(a === 'acc2' ? 'acctBtn2' : 'acctBtn1');
        if (hdr) hdr.click(); // アプリの現在アカウントを切替（テーマ/背景/設定も追従）
        body.querySelectorAll('[data-acct]').forEach(function (x) { x.classList.toggle('active', x.getAttribute('data-acct') === a); });
      });
    });
  }

  // ── 投稿画像モーダル（複数画像＋メモを保存）──
  var _refOverlay = null;
  var _refOpenSeq = 0; // モーダルを開くたびに増える通し番号（遅い非同期処理が古いpendingへ書き込むのを防ぐ）
  function openRefImgModal_(it, onSaved) {
    if (!it) return;
    var mySeq = ++_refOpenSeq;
    var ov = _refOverlay;
    if (!ov) {
      ov = document.createElement('div'); ov.className = 'fz-overlay'; ov.hidden = true;
      ov.innerHTML = '<div class="fz-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
      document.body.appendChild(ov);
      ov.addEventListener('click', function (e) { if (e.target === ov) ov.hidden = true; });
      ov.querySelector('.fz-close').addEventListener('click', function () { ov.hidden = true; });
      _refOverlay = ov;
    }
    var cur = refImgOf(it.cid) || {};
    var curImgs = Array.isArray(cur.imgs) ? cur.imgs.filter(Boolean) : (cur.img ? [cur.img] : []);
    // pending.imgs=保存候補の画像列（複数可・37ページ級の連続貼り付けOK）・idx=表示中（「動画生成へ」で採用される1枚）
    var pending = { imgs: curImgs.slice(), idx: 0, comment: cur.comment || '', twitterUrl: cur.twitterUrl || '' };
    var isTw = !!(it.isTwitter || it.twitterUrl); // Twitterのみ候補（埋め込みポストURLあり）
    // 作品URLのプレフィル：候補が実際に作品URLを持つ（!isTwitter かつ it.url がDMM/book等）なら、
    //   twitterUrl の有無に関わらずそのまま欄に表示（＝カードの「作品↗」と同じ判定）。X起点(it.url=ポストURL)は空。
    var workUrlPrefill = (!it.isTwitter && it.url) ? it.url : '';
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      acctRowHtml_(it.cid) +
      '<div class="fz-title" style="background:#fffef9;color:#111;padding:8px 12px;border-radius:8px;margin:2px 34px 10px 0;">' + esc(it.title || it.cid) + '</div>' +
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
      '<label class="hint" style="display:block;margin:8px 0 2px;">Twitter URL</label>' +
      '<div style="display:flex;gap:6px;align-items:stretch;">' +
        '<input id="refImgTwitter" type="text" inputmode="url" class="cand-refimg-line" autocomplete="off" placeholder="https://x.com/… " style="flex:1;min-width:0;">' +
        '<button type="button" class="ghost paste-btn" data-paste="refImgTwitter" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
      '</div>' +
      '<label class="hint" style="display:block;margin:10px 0 2px;font-size:11px;white-space:nowrap;">アフィリンク付き作品URLを貼ると、正式な作品URLに自動変換</label>' +
      '<div style="display:flex;gap:6px;align-items:stretch;">' +
        '<input id="refImgWorkUrl" type="text" inputmode="url" class="cand-refimg-line" autocomplete="off" placeholder="作品URLを貼り付け" value="' + esc(workUrlPrefill) + '" style="flex:1;min-width:0;">' +
        '<button type="button" class="ghost paste-btn" data-paste="refImgWorkUrl" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
      '</div>' +
      '<div style="display:flex;gap:8px;margin-top:10px;">' +
        '<button id="refImgSave" type="button" class="primary" style="flex:1;">保存</button>' +
        '<button id="refImgCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">閉じる</button>' +
      '</div><div id="refImgMsg" class="hint" style="min-height:1.2em;"></div>';
    var previewEl = body.querySelector('#refImgPreview');
    function navTo(i) { var n = pending.imgs.length; if (!n) return; pending.idx = (i + n) % n; drawPreview(); }
    function drawPreview() {
      var n = pending.imgs.length;
      if (pending.idx >= n) pending.idx = Math.max(0, n - 1);
      if (!n) { previewEl.innerHTML = '<div class="hint" style="text-align:center;padding:18px;border:1px dashed var(--line);border-radius:8px;">画像は未保存です（貼り付けで追加・複数枚OK）</div>'; return; }
      previewEl.innerHTML =
        '<div class="cand-refimg-stage">' +
          '<img src="' + esc(pending.imgs[pending.idx]) + '" alt="" class="fz-zoomable" style="max-width:100%;max-height:40vh;border-radius:8px;border:1px solid var(--line);display:block;margin:0 auto;">' +
          (n > 1 ? '<button type="button" class="cand-refimg-nav prev" aria-label="前へ">‹</button><button type="button" class="cand-refimg-nav next" aria-label="次へ">›</button>' : '') +
        '</div>' +
        '<div class="hint" style="text-align:center;margin-top:3px;">' +
          (n > 1 ? '🖼 複数あり ' + (pending.idx + 1) + ' / ' + n + '（スワイプで切替・<b>表示中の画像が「動画生成へ」で使われます</b>）' : '画像 1枚') +
        '</div>';
      previewEl.querySelector('img').addEventListener('click', function () { openImgZoom_(pending.imgs.slice(), pending.idx); });
      var pv = previewEl.querySelector('.prev'), nx = previewEl.querySelector('.next');
      if (pv) pv.addEventListener('click', function (e) { e.stopPropagation(); navTo(pending.idx - 1); });
      if (nx) nx.addEventListener('click', function (e) { e.stopPropagation(); navTo(pending.idx + 1); });
    }
    // プレビュー上の左右スワイプで切替（ズーム(fz-zoom)側は既存実装でスワイプ対応済み）。
    var _tsx = null, _tsy = null;
    previewEl.addEventListener('touchstart', function (e) { var t = e.changedTouches[0]; _tsx = t.clientX; _tsy = t.clientY; }, { passive: true });
    previewEl.addEventListener('touchend', function (e) {
      if (_tsx == null) return; var t = e.changedTouches[0], dx = t.clientX - _tsx, dy = t.clientY - _tsy; _tsx = _tsy = null;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) navTo(pending.idx + (dx < 0 ? 1 : -1));
    }, { passive: true });
    drawPreview();
    body.querySelector('#refImgComment').value = pending.comment;
    body.querySelector('#refImgTwitter').value = pending.twitterUrl;
    body.querySelector('#refImgFile').addEventListener('change', function () {
      var files = [], fl = this.files || [], fi;
      for (fi = 0; fi < fl.length; fi++) files.push(fl[fi]);
      this.value = '';
      if (!files.length) return;
      body.querySelector('#refImgMsg').textContent = '画像を処理中…（' + files.length + '枚）';
      // 1枚ずつ順に処理（大量選択時のメモリ圧迫を防ぐ・選択順も保たれる）。
      var added = 0, failed = 0;
      (function step(i) {
        if (mySeq !== _refOpenSeq) return; // モーダルが開き直された＝この処理結果は破棄
        if (i >= files.length) {
          if (added) pending.idx = pending.imgs.length - 1;
          drawPreview();
          body.querySelector('#refImgMsg').textContent = added
            ? (added + '枚を追加しました' + (failed ? '（' + failed + '枚は読み込めず）' : '') + '（計' + pending.imgs.length + '枚・保存で確定）')
            : '画像を読み込めませんでした';
          return;
        }
        fileToScaledDataUrl(files[i], function (durl) {
          if (mySeq !== _refOpenSeq) return;
          if (durl) { pending.imgs.push(durl); added++; } else failed++;
          step(i + 1);
        });
      })(0);
    });
    body.querySelector('#refImgPaste').addEventListener('click', function () {
      body.querySelector('#refImgMsg').textContent = '画像を貼り付け中…';
      pasteImageFromClipboard_(function (durl, err) {
        if (mySeq !== _refOpenSeq) return; // モーダルが開き直された＝破棄
        if (err) { body.querySelector('#refImgMsg').textContent = err; return; }
        pending.imgs.push(durl); pending.idx = pending.imgs.length - 1; drawPreview(); // 既存があっても置換せず追加（複数枚OK）
        body.querySelector('#refImgMsg').textContent = '貼り付けました（' + pending.imgs.length + '枚目）。続けて貼り付けできます（保存で確定）';
      });
    });
    body.querySelector('#refImgClear').addEventListener('click', function () {
      var n = pending.imgs.length;
      if (!n) { drawPreview(); return; }
      if (!window.confirm(n > 1 ? ('表示中の画像（' + (pending.idx + 1) + '/' + n + '）を削除しますか？') : '本当に画像を削除しますか？')) return;
      pending.imgs.splice(pending.idx, 1);
      if (pending.idx >= pending.imgs.length) pending.idx = Math.max(0, pending.imgs.length - 1);
      drawPreview();
      body.querySelector('#refImgMsg').textContent = '画像を削除しました（保存で確定・残り' + pending.imgs.length + '枚）';
    });
    // 動画生成へ：このモーダルの作品データを動画作成タブへ引き継いで移動する。
    body.querySelector('#refImgToMovie').addEventListener('click', function () {
      pending.comment = body.querySelector('#refImgComment').value || '';
      pending.twitterUrl = (body.querySelector('#refImgTwitter').value || '').trim();
      var workVal = (body.querySelector('#refImgWorkUrl') && body.querySelector('#refImgWorkUrl').value || '').trim();
      if (!workVal && !it.isTwitter && it.url) workVal = it.url; // 欄が空でも候補が作品URLを持つなら使う（動画側へ確実に反映）
      var workUrl = workVal ? (window.normalizeWorkUrl ? window.normalizeWorkUrl(workVal) : workVal) : '';
      refImgSave(it.cid, pending); // 画像・コメントを失わないよう保存（best-effort）
      transferToMovie_(it, pending.imgs[pending.idx] || '', pending.comment, workUrl); // ★表示中の画像を採用
      if (onSaved) onSaved();
      ov.hidden = true;
    });
    body.querySelector('#refImgCancel').addEventListener('click', function () { ov.hidden = true; });
    body.querySelector('#refImgSave').addEventListener('click', function () {
      pending.comment = body.querySelector('#refImgComment').value || '';
      pending.twitterUrl = (body.querySelector('#refImgTwitter').value || '').trim();
      var workRaw = (body.querySelector('#refImgWorkUrl') && body.querySelector('#refImgWorkUrl').value || '').trim();
      // 作品URL欄が空、またはプレフィル値から変更が無ければ何もしない（無駄なAPI呼び出し/意図しないaddedAtリセットを防止）。
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
      if (!refImgSave(it.cid, pending)) { body.querySelector('#refImgMsg').textContent = '保存できません（このブラウザの保存枠が不足。古い候補の画像を「消す」で減らしてください）'; return; }
      body.querySelector('#refImgMsg').textContent = '保存しました';
      if (onSaved) onSaved();
      setTimeout(function () { ov.hidden = true; }, 600);
    });
    wirePaste_(body);
    wireAcctRow_(body);
    ov.hidden = false;
  }
  // 動画作成タブへ切替え、候補の作品データ（前景画像/作者/コメント/作品URL）を各入力欄へ埋め込む。
  //   ※drafts.js の applyDraft_ と同じ手法：#author/#top/#movieWorkUrl を値+イベントで設定、
  //     前景画像は data-URL→File にして window.Go5SetForegroundFile() で #photo に反映。
  function transferToMovie_(it, imgDataUrl, comment, workUrl) {
    var mv = document.getElementById('tabMovie'); if (mv) mv.click(); // affiliate.js の showTab へ委譲
    function setVal(id, val, evt) {
      var el = document.getElementById(id);
      if (el && val != null) { el.value = val; el.dispatchEvent(new Event(evt || 'change', { bubbles: true })); }
    }
    setVal('author', it.author || '', 'change');   // 作者＝サークル名
    setVal('top', comment || '', 'change');         // コメント（無ければ空＝作品名は入れない）
    if (workUrl) setVal('movieWorkUrl', workUrl, 'input'); // 作品URL（正規化済み）
    if (imgDataUrl && window.Go5SetForegroundFile) {
      fetch(imgDataUrl).then(function (r) { return r.blob(); }).then(function (blob) {
        window.Go5SetForegroundFile(new File([blob], 'candidate.jpg', { type: blob.type || 'image/jpeg' }));
      }).catch(function () {});
    }
    // U-2「一気に作成」：作品データを流し込んだら、作成ボタンまで運んで光らせる＝残り1タップ（行動量支援）。
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
  // 保存直後に、その候補カードの「動画生成用サムネ」を即時反映（一覧を全再描画せず＝スクロール位置を保つ）。
  function updateCardRefThumb_(cardEl, cid) {
    if (!cardEl) return;
    var col = cardEl.querySelector('.cand-thumbcol'); if (!col) return;
    var imgs = refImgsOf_(cid), src = imgs[0] || '';
    var thumb = col.querySelector('.cand-refimg-thumb');
    var badge = col.querySelector('.cand-refimg-multi');
    if (src) {
      if (!thumb) {
        thumb = document.createElement('img');
        thumb.className = 'cand-refimg-thumb';
        thumb.setAttribute('data-refimgview', cid);
        thumb.setAttribute('loading', 'lazy');
        thumb.alt = '動画生成用の画像（タップで拡大）';
        thumb.title = '動画生成用の画像（タップで拡大）';
        thumb.addEventListener('click', function () { var a = refImgsOf_(cid); if (a.length) openImgZoom_(a, 0); });
        col.appendChild(thumb);
      }
      thumb.src = src;
      if (imgs.length > 1) {
        if (!badge) { badge = document.createElement('span'); badge.className = 'cand-refimg-multi'; col.appendChild(badge); }
        badge.textContent = '🖼 複数あり ×' + imgs.length;
      } else if (badge && badge.parentNode) {
        badge.parentNode.removeChild(badge);
      }
    } else {
      if (thumb && thumb.parentNode) thumb.parentNode.removeChild(thumb);
      if (badge && badge.parentNode) badge.parentNode.removeChild(badge);
    }
  }
  // 候補（Twitter起点/DMM起点どちらも）に作品URLを適用：正規化した作品URLへ変換/更新し、画像・メモ・Twitter URLを引き継ぐ（旧項目を置換）。
  function applyWorkUrl_(oldItem, workUrlRaw, refData, cb) {
    var url = window.normalizeWorkUrl ? window.normalizeWorkUrl(workUrlRaw) : (workUrlRaw || '').trim();
    var r = (url && window.buildAffiliateLink) ? window.buildAffiliateLink(url, '') : null;
    if (!r || !r.ok) { cb(false, 'FANZAの作品URLではないようです'); return; }
    var tabId = _activeTab, key = itemsKey(tabId), items = lsGet(key, '[]'), oldCid = oldItem.cid;
    if (r.cid !== oldCid && items.some(function (x) { return x.cid === r.cid; })) { cb(false, 'この作品は既に追加されています（重複追加しません）'); return; }
    // 画像・メモ・Twitter URL を新cidへ移す
    var okRef = refImgSave(r.cid, { imgs: Array.isArray(refData.imgs) ? refData.imgs : (refData.img ? [refData.img] : []), comment: refData.comment || '', twitterUrl: refData.twitterUrl || oldItem.twitterUrl || '' });
    var bimg = (bskyImgOf(oldCid) || {}).img;
    var okB = bimg ? bskyImgSave(r.cid, bimg) : true;
    // 新cidへの保存が成功した時だけ旧cidを消す（localStorageフォールバック時の容量超過で唯一のコピーを失わない）
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

  // ── Bluesky添付画像モーダル（1枚を保存。投稿画像とは別枠）──
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
        pending.img = durl; drawPreview(); body.querySelector('#bskyImgMsg').textContent = '画像を差し替えました（保存で確定）';
      });
    });
    body.querySelector('#bskyImgPaste').addEventListener('click', function () {
      body.querySelector('#bskyImgMsg').textContent = '⏳ 画像を貼り付け中…';
      pasteImageFromClipboard_(function (durl, err) {
        if (err) { body.querySelector('#bskyImgMsg').textContent = '⚠️ ' + err; return; }
        pending.img = durl; drawPreview(); body.querySelector('#bskyImgMsg').textContent = 'コピー画像を貼り付けました（保存で確定）';
      });
    });
    body.querySelector('#bskyImgClear').addEventListener('click', function () { pending.img = ''; drawPreview(); body.querySelector('#bskyImgMsg').textContent = '画像を消しました（保存で確定）'; });
    body.querySelector('#bskyImgCancel').addEventListener('click', function () { ov.hidden = true; });
    body.querySelector('#bskyImgSave').addEventListener('click', function () {
      if (!bskyImgSave(it.cid, pending.img)) { body.querySelector('#bskyImgMsg').textContent = '⚠️ 保存できません（このブラウザの保存枠が不足。古い候補の画像を減らしてください）'; return; }
      body.querySelector('#bskyImgMsg').textContent = '✅ 保存しました';
      if (onSaved) onSaved();
      setTimeout(function () { ov.hidden = true; }, 600);
    });
    ov.hidden = false;
  }

  // カード共通の配線：サムネのタップで画像モーダル／🖼投稿画像ボタン。
  function wireCardCommon_(el) {
    el.querySelectorAll('[data-thumbcid]').forEach(function (im) {
      im.addEventListener('click', function () { openThumbModal_(itemByCid_(im.getAttribute('data-thumbcid'))); });
    });
    // 保存済みの動画生成用画像（サムネ下の縦長画像）：タップで拡大プレビュー。
    el.querySelectorAll('[data-refimgview]').forEach(function (im) {
      im.addEventListener('click', function () { var imgs = refImgsOf_(im.getAttribute('data-refimgview')); if (imgs.length) openImgZoom_(imgs, 0); }); // 複数あれば全部スワイプで見られる
    });
    el.querySelectorAll('[data-refimg]').forEach(function (b) {
      b.addEventListener('click', function () {
        var cid = b.getAttribute('data-refimg'), it = itemByCid_(cid); if (!it) return;
        openRefImgModal_(it, function () {
          var has = refImgHas(cid);
          b.classList.toggle('has-img', has);
          b.innerHTML = has ? '🖼 投稿編集✓' : '🖼 投稿編集';
          updateCardRefThumb_(b.closest ? b.closest('.cand-card') : null, cid); // 保存直後に一覧のサムネへ反映（リロード不要）
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
  // 「▶今すぐ取得」ボタンの共通配線（notceParentId=通知メッセージを差し込む要素id）。
  function bindPcRun_(btn, noticeParentId) {
    btn.addEventListener('click', function () {
      var b = this; b.disabled = true; var t0 = b.textContent; b.textContent = '⏳ 要求中…';
      requestPcRun(function (ok, err) {
        b.textContent = ok ? '✅ 要求しました' : '⚠️ ' + (err || '失敗');
        if (ok) { var el = $(noticeParentId); if (el) { var p = document.createElement('p'); p.className = 'hint'; p.style.padding = '4px 6px'; p.style.color = '#c0392b'; p.textContent = '▶ PCへ取得を要求しました。PCの電源が入っていれば数分以内に取得→🔁で反映されます。'; el.insertBefore(p, el.firstChild); } }
        setTimeout(function () { b.textContent = t0; b.disabled = false; }, 4000);
      });
    });
  }
  // サークルを販売数の「追跡対象」としてworkerへ登録/解除。登録済みサークルは
  // PCバッチ(販売数を取得.bat)が「タブを表示しなくても」全作品の販売数を自動取得する。
  function trackMaker(makerId, makerName, remove) {
    if (!makerId) return;
    var flagKey = 'cand_tracked__' + makerId;
    if (!remove && localStorage.getItem(flagKey)) return; // 登録済みなら送らない（解除は常に送る）
    var cfg = workerCfg(); if (!cfg.url) return;
    fetch(cfg.url + '/api/fanza-sales-track', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret },
      body: JSON.stringify(remove ? { makerId: makerId, remove: true } : { makerId: makerId, name: makerName || '' })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d && d.ok) { if (remove) localStorage.removeItem(flagKey); else localStorage.setItem(flagKey, '1'); }
    }).catch(function () {}); // 失敗しても次の機会(ensureTrackedAll)に再送される
  }
  // 既存タブの移行用: 全サークルタブを追跡登録（登録済みはローカルフラグでスキップ＝実質1回だけ）。
  function ensureTrackedAll() {
    lsGet(K_TABS, '[]').forEach(function (t) { if (t.makerId) trackMaker(t.makerId, t.makerName || t.name || ''); });
  }
  // 「▶今すぐ取得」: どの端末のWebアプリからでもPCへ実行要求を送る（PC常駐タスクが数分以内に拾う）。
  // 実スクレイプは日本IPのPCでしか動かないので、これは実行予約のみ。
  function requestPcRun(cb) {
    var cfg = workerCfg(); if (!cfg.url) { cb && cb(false, 'FANZA Workerが未設定です(⚙️詳細設定)'); return; }
    fetch(cfg.url + '/api/fanza-sales-run', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret }, body: '{}' })
      .then(function (r) { return r.json(); }).then(function (d) { cb && cb(!!(d && d.ok), (d && d.error) || ''); })
      .catch(function () { cb && cb(false, '通信エラー'); });
  }

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
  function isOnSale_(it) { return !!(it && it.listPrice && it.price && it.discountPct > 0 && it.price < it.listPrice); }
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
    var tabBtns = '<button class="cand-tab cand-tab-buzz' + (_activeTab === 'buzz' ? ' active' : '') + '" data-ct="buzz" type="button">🦋 バズ</button>' +
      '<button class="cand-tab' + (_activeTab === 'main' ? ' active' : '') + '" data-ct="main" type="button">💡 候補</button>' +
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
    else if (_activeTab === 'main') renderMain('main');
    else {
      var tab = null; tabs.forEach(function (t) { if (t.id === _activeTab) tab = t; });
      if (!tab) { _activeTab = 'main'; renderMain('main'); }
      else if (tab.makerId) renderMaker(_activeTab);   // サークル作品一覧タブ
      else renderMain(tab.id);                          // 独立した候補リストタブ（タブ名だけのタブ）
    }
  }
  // 候補アイテムの保存先: メインは cand_items、独立タブは各タブ固有キー（表示を共有しない）。
  function itemsKey(tabId) { return (!tabId || tabId === 'main') ? K_ITEMS : 'cand_items__' + tabId; }

  // ── タブの並べ替え：PC=ドラッグ、スマホ=長押し→ドラッグ（Pointer Eventsでマウス/タッチ統一） ──
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
    var order = [].slice.call(bar.querySelectorAll('.cand-tab[data-ct]')).map(function (b) { return b.getAttribute('data-ct'); }).filter(function (id) { return !isFixedCandTab_(id); });
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
      '<div class="field-label" style="margin-top:0;">タブを追加</div>' +
      '<label class="hint" style="display:block;margin:0 0 2px;">タブ名（必須・後から編集可）</label>' +
      '<input id="candTabName" type="text" placeholder="タブの名前" autocomplete="off">' +
      '<div class="hint" style="margin-top:6px;">タブ名だけで決定すると、💡候補とは別に独立して作品URLを貯められる<b>候補タブ</b>になります。<br>特定サークルの作品一覧タブにしたい場合だけ、下の欄にサークル情報を入れてください（任意）。</div>' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">サークル情報（任意）: 作品URL / サークルID / サークルURL</label>' +
      pasteRow_('<input id="candTabSrc" type="text" inputmode="url" placeholder="空欄なら「ただの候補タブ」になります" autocomplete="off" style="flex:1;">', 'candTabSrc') +
      '<div style="display:flex;gap:8px;margin-top:10px;">' +
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
    wirePaste_(f);
    $('candTabCancel').addEventListener('click', function () { f.style.display = 'none'; f.innerHTML = ''; });
    $('candTabOk').addEventListener('click', function () {
      var name = ($('candTabName').value || '').trim();
      var src = ($('candTabSrc').value || '').trim();
      var msg = $('candTabMsg');
      // サークル情報が無ければ「独立した候補タブ」（タブ名だけでOK）。
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
        var tab = { id: 'ct' + new Date().getTime(), name: name || makerName || ('サークル' + makerId), makerId: makerId, makerName: makerName || '' };
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
  var K_BUZZ = 'cand_buzz_cache';       // {at, accKey, posts:[...]}（アカウント別ではなく対象集合キーで判定）
  var BUZZ_TTL = 30 * 60 * 1000;        // 30分キャッシュ（🔁で強制更新）
  var BUZZ_FOLLOW_PAGES = 3;            // 各アカのフォロー取得ページ数上限（×100件）
  var BUZZ_MAX_FEEDS = 120;             // getAuthorFeed を叩く最大フォロー先数（API量の上限）
  var BUZZ_FEED_LIMIT = 15;             // 1フォロー先あたり取得する投稿数
  var BUZZ_CONCURRENCY = 5;             // 同時fetch数（フォロー数×フィードで膨らむのを抑える）
  var BUZZ_RECENT_DAYS = 14;            // これより古い投稿は対象外
  var BUZZ_SHOW = 60;                   // 表示件数
  var _buzzLoading = false;

  // ハンドルとDIDのどちらかがあるアカウントのみ対象（🦋投稿タブ⚙設定で保存済み）。
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
  // ハンドル→DID（未キャッシュ時のみ解決し bsky_did__ に保存）。
  function resolveBuzzDid_(o) {
    if (o.did && /^did:/.test(o.did)) return Promise.resolve(o.did);
    if (!o.handle) return Promise.resolve('');
    return bskyGet_('com.atproto.identity.resolveHandle', { handle: o.handle }).then(function (j) {
      var did = j && j.did ? j.did : '';
      if (did) { try { localStorage.setItem('bsky_did__' + o.acc, did); } catch (e) {} }
      return did;
    });
  }
  // 1アカウントの全フォロー先を取得（ページング・BUZZ_FOLLOW_PAGES上限）。
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
  // 並列プール（同時active数を conc に制限）。worker(item,idx)→Promise。結果を index順に返す。
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
      'Blueskyは表示回数(インプレッション)を公開していないため、<b>エンゲージメント（❤️いいね+🔁リポスト+💬返信+❝引用）</b>が唯一の勢いの指標です。</div>' +
      '</div>';
    if (!accs.length) {
      body.innerHTML = head + '<div class="card"><div class="hint">⚠️ Blueskyのハンドルが未設定です。🦋投稿タブの⚙設定でハンドル(@…)を保存すると、そのアカウントのフォローが対象になります。</div></div>';
      wireBuzzReload_();
      return;
    }
    var namesLabel = accs.map(function (o) { return '@' + (o.handle || o.did.slice(0, 14) + '…'); }).join(' / ');
    body.innerHTML = head +
      '<div class="hint" style="margin:6px 2px;">対象アカウント：' + esc(namesLabel) + '</div>' +
      '<div id="buzzList"><div class="card"><div class="hint">⏳ フォローと投稿を集計中…（初回・更新直後は少し時間がかかります）</div></div></div>';
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
        (res.cached ? '🕘 ' + fmtTs(res.at) + ' 時点のキャッシュ（🔁で更新）' : '✅ ' + fmtTs(res.at) + ' に更新') +
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

  // ── 候補リスト（既定の💡候補 と 独立した候補タブ で共用。tabIdごとに保存先が独立） ──
  //   サークルタブと同じヘッダ（並び替え／🔁／▶今すぐ取得／✏️編集／🙈非表示）を持つ。
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
      '<button id="candShowHidden" type="button" class="ghost" style="flex:0 0 auto;width:auto;margin:0;font-size:12px;padding:6px 10px;">' + (_showHidden ? '👁 通常表示に戻す' : '🙈 非表示リストを表示') + '</button>' +
      '</div>' +
      '<label class="cand-filter-sale"><input id="candFilterSale" type="checkbox"' + (_filterSale ? ' checked' : '') + '><span>セール中の作品のみ表示</span></label>' +
      (_sort === 'rank7d' ? '<div class="hint" style="margin-top:6px;">' + esc(RANK7D_NOTE) + '</div>' : '') +
      ((_sort === 'rank' || _sort === 'rank7d') ? '<div class="hint" style="margin-top:4px;">' + esc(SALES_NOTE) + '</div>' : '') +
      '</div>';
    var addCard = '<div class="card">' +
      '<div class="field-label" style="margin-top:0;">📥 作品URLを' + (isMain ? '候補' : 'このタブ') + 'に追加</div>' +
      '<div class="hint">アフィリンク付きURL(al.fanza.co.jp/?lurl=…)でもOK。素の作品URLに直して記録します。' + (isMain ? '' : '<br>💡候補とは別に、このタブに独立して保存されます。') + '</div>' +
      '<div style="margin-top:6px;">' + pasteRow_('<input id="candUrl" type="text" inputmode="url" placeholder="https://…(作品URL or アフィリンク)" autocomplete="off" style="flex:1;">', 'candUrl') + '</div>' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">Twitter(X)のURL（任意）— <b>これだけでも追加できます</b></label>' +
      '<div>' + pasteRow_('<input id="candTwitter" type="text" inputmode="url" placeholder="https://x.com/…/status/… を貼り付け" autocomplete="off" style="flex:1;">', 'candTwitter') + '</div>' +
      '<button id="candAdd" type="button" class="primary" style="margin-top:8px;font-size:.9rem;padding:10px;">➕ ' + (isMain ? '候補に追加' : 'このタブに追加') + '</button>' +
      '<div id="candMsg" class="hint" style="min-height:1.3em;"></div>' +
      '<div style="border-top:1px solid var(--line);margin:10px 0 0;padding-top:10px;">' +
        '<div class="hint">サークルの作品を<b>まとめて</b>' + (isMain ? '候補' : 'このタブ') + 'に追加できます（サークルID / サークルURL / 作品URLのどれか）。タブ名は変わりません。</div>' +
        '<div style="margin-top:6px;">' + pasteRow_('<input id="candBulkSrc" type="text" inputmode="url" placeholder="サークルID / サークルURL / 作品URL" autocomplete="off" style="flex:1;">', 'candBulkSrc') + '</div>' +
        '<button id="candBulkAdd" type="button" class="ghost" style="margin-top:8px;width:auto;">🏭 サークルの作品を全部追加</button>' +
        '<div id="candBulkMsg" class="hint" style="min-height:1.3em;"></div>' +
      '</div>' +
      '</div>';
    body.innerHTML = header + '<div id="candEditForm"></div>' + addCard + '<div id="candList"></div>';
    $('candSort').addEventListener('change', function () { _sort = this.value; renderCandList(tabId); });
    $('candShowHidden').addEventListener('click', function () { _showHidden = !_showHidden; renderCandList(tabId); });
    $('candFilterSale').addEventListener('change', function () { _filterSale = this.checked; renderCandList(tabId); });
    $('candReload').addEventListener('click', function () { refreshCandItems(tabId); });
    bindPcRun_($('candPcRun'), 'candList');
    $('candAdd').addEventListener('click', function () { addCandidate(tabId); });
    $('candBulkAdd').addEventListener('click', function () { bulkAddCircle(tabId); });
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
  function addTwitterCandidate_(tabId, tw, inp, twInp, msg) {
    var key = itemsKey(tabId), items = lsGet(key, '[]');
    if (items.some(function (x) { return x.twitterUrl === tw.url || x.cid === tw.cid; })) { msg.textContent = 'ℹ️ すでにこのタブにあります'; return; }
    items.unshift({ url: tw.url, cid: tw.cid, twitterUrl: tw.url, isTwitter: true, title: tw.user ? ('🐦 @' + tw.user + ' のポスト') : '🐦 X(Twitter)のポスト', addedAt: new Date().getTime() });
    lsSet(key, items);
    if (inp) inp.value = ''; if (twInp) twInp.value = '';
    msg.textContent = '✅ Twitter(X)のURLを追加しました';
    renderCandList(tabId);
  }
  function addCandidate(tabId) {
    tabId = tabId || 'main';
    var key = itemsKey(tabId);
    var inp = $('candUrl'), twInp = $('candTwitter'), msg = $('candMsg');
    var raw = (inp && inp.value || '').trim();
    var twRaw = (twInp && twInp.value || '').trim();
    var url = window.normalizeWorkUrl ? window.normalizeWorkUrl(raw) : raw;
    var r = (raw && url && window.buildAffiliateLink) ? window.buildAffiliateLink(url, '') : null;
    // ①作品URLがFANZA作品として有効 → 従来のFANZA候補（Twitter URLがあれば紐づけて保存）
    if (raw && r && r.ok) {
      var twForWork = parseTwitterUrl_(twRaw);
      var items0 = lsGet(key, '[]');
      if (items0.some(function (x) { return x.cid === r.cid; })) { msg.textContent = 'ℹ️ この作品は既に追加されています（重複追加しません）'; return; }
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
        if (twForWork.ok) it.twitterUrl = twForWork.url; // Twitter URLも一緒に保存
        items.unshift(it);
        lsSet(key, items);
        inp.value = ''; if (twInp) twInp.value = ''; msg.textContent = '✅ 追加しました';
        renderCandList(tabId);
      };
      if (window.FanzaCore && cfg.url) {
        window.FanzaCore.fetchFanzaInfo(r.cid, cfg.url, cfg.secret, url).then(function (info) {
          put(info && info.title ? info : null);
        }).catch(function () { put(null); });
      } else put(null);
      return;
    }
    // ②作品URLが無い/FANZA以外 → Twitter(X)のURLだけで追加（Twitter欄優先、無ければ作品欄に貼られたX URLも可）
    var tw = parseTwitterUrl_(twRaw) ; if (!tw.ok) tw = parseTwitterUrl_(raw);
    if (tw.ok) { addTwitterCandidate_(tabId, tw, inp, twInp, msg); return; }
    // ③どちらでもない
    msg.textContent = (raw || twRaw) ? '⚠️ FANZAの作品URL か Twitter(X)のURLを入れてください' : '⚠️ URLを入力してください';
  }
  // サークルの全作品を、指定タブ(候補/独立タブ)へまとめて追加（重複cidは除外・タブ名は不変）。
  function bulkAddCircle(tabId) {
    var src = ($('candBulkSrc').value || '').trim(), msg = $('candBulkMsg');
    if (!src) { msg.textContent = '⚠️ サークル情報を入れてください'; return; }
    msg.textContent = '⏳ サークルを特定中…';
    resolveMakerId(src, function (makerId, makerName, err) {
      if (!makerId) { msg.textContent = '⚠️ ' + err; return; }
      msg.textContent = '⏳ 作品一覧を取得中…（多いと時間がかかります）';
      fetchMakerItems(makerId, 'date', function (works, err2) {
        if (err2) { msg.textContent = '⚠️ ' + err2; return; }
        var res = appendWorks_(itemsKey(tabId), works || []);
        msg.textContent = '✅ ' + res.added + '件を追加しました' + (res.dup ? '（重複' + res.dup + '件は除外）' : '');
        $('candBulkSrc').value = '';
        renderCandList(tabId);
      }, true); // force=キャッシュ無視で最新の全件
    });
  }
  // サークルモードから: 表示中サークルの全作品を「💡候補」へ追加（重複除外・確認あり）。
  function addWorksToMain_(works, btn, circleName) {
    if (!works || !works.length) return;
    if (!window.confirm('「' + (circleName || 'このサークル') + '」の全' + works.length + '作品を「💡候補」に追加しますか？')) return;
    var res = appendWorks_(K_ITEMS, works);
    if (btn) { btn.textContent = '✅ ' + res.added + '件を候補へ' + (res.dup ? '（重複' + res.dup + '件除外）' : ''); setTimeout(function () { btn.textContent = '💡 全作品を候補に追加'; }, 3500); }
  }
  // 作品配列を保存キーへ追記（cid重複は除外）。追加数・重複数を返す。
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
    return { added: added, dup: dup };
  }
  // 🔁: このタブの各作品の価格・販売数を最新化（FANZA再取得＋販売数キャッシュ無効化）。
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
    var key = itemsKey(tabId);
    var el = $('candList');
    var all = lsGet(key, '[]');
    if (!all.length) { el.innerHTML = '<p class="hint" style="padding:4px 6px;">まだ候補がありません。上の欄に作品URLを入れて追加してください。</p>'; return; }
    var hidden = lsGet(hiddenKey(tabId), '[]'), hset = {}; hidden.forEach(function (c) { hset[c] = true; });
    var arr = sortItems(all, _sort).filter(function (it) { return (_showHidden ? hset[it.cid] : !hset[it.cid]) && (!_filterSale || isOnSale_(it)); });
    _cardIndex = {}; arr.forEach(function (it) { _cardIndex[it.cid] = it; });
    if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">' + (_showHidden ? '非表示にした作品はありません。' : '表示できる候補がありません。') + '</p>'; return; }
    var topCids = arr.slice(0, 60).map(function (it) { return it.cid; });
    var salesMiss = missingCount(topCids);
    var head = '<p class="hint" style="padding:2px 6px;">' + (_showHidden ? '🙈 非表示中 ' : '') + arr.length + '件' + (_showHidden ? '（「再表示」で戻せます）' : ' / 非表示 ' + hidden.length + '件') +
      (!_showHidden && salesMiss > 0 ? '<br>💰 販売数(実売)は上位' + salesMiss + '件がPC取得待ち。「▶今すぐ取得」を押すか、自動取得を待って🔁で反映されます(PCの電源が必要)。' : '') + '</p>';
    el.innerHTML = head + arr.map(function (it) {
      var act = _showHidden
        ? '<button type="button" class="cand-hide-btn" data-unhide="' + esc(it.cid) + '">👁 再表示</button> <button type="button" class="cand-hide-btn cand-del-btn" data-delcid="' + esc(it.cid) + '" title="削除" aria-label="削除">🗑️</button>'
        : '<button type="button" class="cand-hide-btn" data-hidecid="' + esc(it.cid) + '">🙈 非表示</button> <button type="button" class="cand-hide-btn cand-del-btn" data-delcid="' + esc(it.cid) + '" title="削除" aria-label="削除">🗑️</button>';
      return candCard(it, act);
    }).join('');
    wireCardCommon_(el);
    el.querySelectorAll('[data-hidecid]').forEach(function (b) {
      b.addEventListener('click', function () { var h = lsGet(hiddenKey(tabId), '[]'), c = b.getAttribute('data-hidecid'); if (h.indexOf(c) < 0) h.push(c); lsSet(hiddenKey(tabId), h); renderCandList(tabId); });
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
        renderCandList(tabId);
      });
    });
    // 候補作品の実売本数を取得（未取得はPC取得キューへ）。反映されたら再描画。
    fetchSalesFor(topCids, function (changed) { if (changed && _activeTab === tabId) renderCandList(tabId); });
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
      '<button id="candPcRun" type="button" class="ghost" title="PCへ「今すぐ販売数を取得」を要求(PCの電源が必要)" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">▶ 今すぐ取得</button>' +
      '<button id="candEditTab" type="button" class="ghost" title="タブ名・サークルを編集" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">✏️ 編集</button>' +
      '<button id="candShowHidden" type="button" class="ghost" style="flex:0 0 auto;width:auto;margin:0;font-size:12px;padding:6px 10px;">' + (_showHidden ? '👁 通常表示に戻す' : '🙈 非表示リストを表示') + '</button>' +
      '</div>' +
      '<label class="cand-filter-sale"><input id="candFilterSale" type="checkbox"' + (_filterSale ? ' checked' : '') + '><span>セール中の作品のみ表示</span></label>' +
      (_sort === 'rank7d' ? '<div class="hint" style="margin-top:6px;">' + esc(RANK7D_NOTE) + '</div>' : '') +
      ((_sort === 'rank' || _sort === 'rank7d') ? '<div class="hint" style="margin-top:4px;">' + esc(SALES_NOTE) + '</div>' : '') +
      '</div>' +
      '<div id="candEditForm"></div>' +
      '<div id="candMakerList"><p class="hint" style="padding:8px;">' + (force ? '🔁 全件を取り直しています…' : '⏳ サークルの作品を取得中…') + '</p></div>';
    $('candSort').addEventListener('change', function () { _sort = this.value; renderMaker(tabId); });
    $('candShowHidden').addEventListener('click', function () { _showHidden = !_showHidden; renderMaker(tabId); });
    $('candFilterSale').addEventListener('change', function () { _filterSale = this.checked; renderMaker(tabId); });
    $('candReload').addEventListener('click', function () { renderMaker(tabId, true); });
    bindPcRun_($('candPcRun'), 'candMakerList');
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
      var arr = sortItems(items, _sort).filter(function (it) { return (_showHidden ? hset[it.cid] : !hset[it.cid]) && (!_filterSale || isOnSale_(it)); });
      if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">' + (_showHidden ? '非表示にした作品はありません。' : '表示できる作品がありません。') + '</p>'; return; }
      _cardIndex = {}; arr.forEach(function (it) { _cardIndex[it.cid] = it; });
      // 実売本数(販売数)を先頭60件ぶん取得（未取得はPC取得キューへ自動登録）。反映されたら再描画。
      var topCids = arr.slice(0, 60).map(function (it) { return it.cid; });
      var salesMiss = missingCount(topCids);
      var head = '<div style="display:flex;justify-content:flex-end;padding:2px 6px 6px;">' +
        '<button id="candBulkToCand" type="button" class="ghost" style="width:auto;margin:0;font-size:12.5px;padding:6px 10px;">💡 全作品を候補に追加</button></div>' +
        '<p class="hint" style="padding:2px 6px;">' + (_showHidden ? '🙈 非表示中の作品 ' : '') + arr.length + '件' + (_showHidden ? '(「再表示」で戻せます)' : ' / 非表示 ' + hidden.length + '件・不足なら🔁リロード') +
        (!_showHidden && salesMiss > 0 ? '<br>💰 販売数(実売)は上位' + salesMiss + '件がPC取得待ち。「▶今すぐ取得」を押すか、自動取得を待って🔁で反映されます(PCの電源が必要)。' : '') + '</p>';
      el.innerHTML = head + arr.map(function (it) {
        var btn = _showHidden
          ? '<button type="button" class="cand-hide-btn" data-unhide="' + esc(it.cid) + '">👁 再表示</button>'
          : '<button type="button" class="cand-hide-btn" data-hide="' + esc(it.cid) + '">🙈 非表示</button>';
        return candCard(it, btn);
      }).join('');
      wireCardCommon_(el);
      var bulkBtn = $('candBulkToCand');
      if (bulkBtn) bulkBtn.addEventListener('click', function () { addWorksToMain_(items, bulkBtn, tab.name); });
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
    var isMaker = !!tab.makerId; // サークルタブのみ「貼り替え」欄を出す（候補タブは名前のみ編集）
    f.innerHTML = '<div class="card" style="margin:8px 0;">' +
      '<div class="field-label" style="margin-top:0;">✏️ タブを編集</div>' +
      '<label class="hint" style="display:block;margin-bottom:2px;">タブ名（長い場合は短く編集できます）</label>' +
      '<input id="candEditName" type="text" autocomplete="off" value="' + esc(tab.name) + '">' +
      (isMaker ?
        '<label class="hint" style="display:block;margin:8px 0 2px;">サークルを貼り替える（任意：ID/サークルURL/作品URL）</label>' +
        pasteRow_('<input id="candEditSrc" type="text" inputmode="url" autocomplete="off" placeholder="変更しないなら空のまま" style="flex:1;">', 'candEditSrc') : '') +
      '<div style="display:flex;gap:8px;margin-top:8px;">' +
      '<button id="candEditSave" type="button" class="primary" style="flex:1;font-size:.9rem;padding:10px;">保存</button>' +
      '<button id="candEditDel" type="button" class="ghost" style="flex:0 0 auto;width:auto;color:#c0392b;border-color:#c0392b;">タブ削除</button>' +
      '<button id="candEditCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">やめる</button>' +
      '</div><div id="candEditMsg" class="hint" style="min-height:1.3em;"></div></div>';
    wirePaste_(f);
    $('candEditCancel').addEventListener('click', function () { f.innerHTML = ''; });
    $('candEditDel').addEventListener('click', function () {
      if (!window.confirm('タブ「' + tab.name + '」を削除しますか？' + (isMaker ? '(非表示リストも消えます)' : '(このタブに貯めた候補も消えます)'))) return;
      var rest = lsGet(K_TABS, '[]').filter(function (t) { return t.id !== tab.id; });
      lsSet(K_TABS, rest);
      try { localStorage.removeItem(hiddenKey(tab.id)); } catch (e) {}
      try { localStorage.removeItem(itemsKey(tab.id)); } catch (e) {} // 候補タブの保存アイテムも破棄
      // 他タブが同じサークルを使っていなければ、PCバッチの追跡対象から外す
      if (tab.makerId && !rest.some(function (t) { return t.makerId === tab.makerId; })) trackMaker(tab.makerId, '', true);
      _activeTab = 'main'; render();
    });
    $('candEditSave').addEventListener('click', function () {
      var name = ($('candEditName').value || '').trim();
      var srcEl = $('candEditSrc');
      var src = srcEl ? (srcEl.value || '').trim() : ''; // 候補タブには貼り替え欄が無い
      var msg = $('candEditMsg');
      function applyTab(makerId, makerName) {
        var tabs = lsGet(K_TABS, '[]');
        var oldMakerId = tab.makerId;
        tabs.forEach(function (t) {
          if (t.id !== tab.id) return;
          t.name = name || makerName || t.name;
          if (makerId) { t.makerId = makerId; if (makerName) t.makerName = makerName; }
        });
        lsSet(K_TABS, tabs);
        // サークル貼り替え時: 新サークルを追跡登録し、旧サークルは他タブが使っていなければ解除
        if (makerId && makerId !== oldMakerId) {
          trackMaker(makerId, makerName);
          if (oldMakerId && !tabs.some(function (t) { return t.makerId === oldMakerId; })) trackMaker(oldMakerId, '', true);
        }
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
    var sale = isOnSale_(it);
    var priceHtml = sale
      ? '<span class="cand-list-price">' + yen(it.listPrice) + '</span> <b class="cand-sale">' + yen(it.price) + '</b> <span class="cand-off">' + it.discountPct + '%off</span>'
      : '<b>' + yen(it.price != null ? it.price : it.listPrice) + '</b>';
    var sub = [];
    if (it.author || it.makerName) sub.push('🏷 ' + esc(it.author || it.makerName));
    if (it.date) sub.push('発売 ' + esc(fmtDate(it.date)));
    if (it.addedAt) sub.push('追加 ' + esc(fmtTs(it.addedAt)));
    var ws = deriveWorkState_(it.date);
    var badgesHtml = (ws ? stateBadgeHtml_(ws) : '') + ((!it.isTwitter && it.url) ? workKindBadgeHtml_(it.url) : '') + (isAiWork_(it.genres) ? '<span class="fp-kind fp-kind-ai">AI</span>' : '');
    var genresHtml = (it.genres && it.genres.length)
      ? '<div class="fz-genres" style="margin-top:4px;">' + it.genres.slice(0, 5).map(function (g) { return '<span class="fz-genre">' + esc(g) + '</span>'; }).join('') + '</div>'
      : '';
    // 売れ行きの数値。実売本数(販売数)がPC取得済みなら実数を最優先。無ければレビュー件数(代理指標)。
    var rc = it.reviewCount;
    var avg = (it.reviewAvg != null && it.reviewAvg !== '') ? (' ★' + it.reviewAvg) : '';
    var num = function (n) { return Number(n).toLocaleString('ja-JP'); };
    var sales = salesOf(it.cid); // number=実売 / null=PC未取得 / undefined=未問い合わせ
    // 販売数は黒字・強調なし・「(実売)」表記なし。価格の下の段に置く。
    var salesHtml = '';
    if (typeof sales === 'number') {
      if (_sort === 'rank7d') {
        var sd = weekSalesDelta(it.cid, sales);
        salesHtml = (sd != null)
          ? '<div class="cand-sales">🔥 直近1週間の販売：+' + num(sd) + '本（累計 ' + num(sales) + '本）</div>'
          : '<div class="cand-sales">販売数：' + num(sales) + '本</div>';
      } else {
        salesHtml = '<div class="cand-sales">販売数：' + num(sales) + '本</div>';
      }
    } else if (_sort === 'rank7d') {
      var wd = weekReviewDelta(it.cid, rc);
      if (wd != null) salesHtml = '<div class="cand-sales">🔥 直近1週間の伸び：レビュー +' + num(wd) + '件' + (rc != null ? '（累計' + num(rc) + '件）' : '') + '</div>';
      else if (rc != null) salesHtml = '<div class="cand-sales">売れ行きの目安：レビュー ' + num(rc) + '件' + avg + '<span style="color:var(--sub);">（販売数はPC取得待ち）</span></div>';
    } else if (_sort === 'rank' && rc != null) {
      salesHtml = '<div class="cand-sales">売れ行きの目安：レビュー ' + num(rc) + '件' + avg + '</div>';
    } else if (rc != null && rc > 0) {
      salesHtml = '<div class="cand-sub">レビュー ' + num(rc) + '件' + avg + '</div>';
    }
    var hasRef = refImgHas(it.cid);
    var hasBsky = bskyImgHas(it.cid);
    var refImgs = refImgsOf_(it.cid);          // 動画生成用に保存した画像（複数可）
    var refImgSrc = refImgs[0] || '';
    return '<div class="cand-card">' +
      '<div class="cand-thumbcol">' +
        (it.thumb ? '<img class="cand-thumb cand-thumb-click" data-thumbcid="' + esc(it.cid) + '" src="' + esc(it.thumb) + '" loading="lazy" alt="タップで画像を表示">' : '<div class="cand-thumb cand-thumb-ph"></div>') +
        (refImgSrc ? '<img class="cand-refimg-thumb" data-refimgview="' + esc(it.cid) + '" src="' + esc(refImgSrc) + '" loading="lazy" alt="動画生成用の画像（タップで拡大）" title="動画生成用の画像（タップで拡大）">' : '') +
        (refImgs.length > 1 ? '<span class="cand-refimg-multi">🖼 複数あり ×' + refImgs.length + '</span>' : '') +
      '</div>' +
      '<div class="cand-info">' +
        (badgesHtml ? '<div style="margin-bottom:3px;">' + badgesHtml + '</div>' : '') +
        '<div class="cand-title">' + esc(it.title || '(無題)') + '</div>' +
        (sub.length ? '<div class="cand-sub">' + sub.join('　') + '</div>' : '') +
        genresHtml +
        ((it.price != null || it.listPrice != null) ? '<div class="cand-price">' + priceHtml + '</div>' : '') +
        salesHtml +
        '<div class="cand-actions">' +
          ((!it.isTwitter && it.url) ? '<a class="vlink vlink-work" href="' + esc(it.url) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
          (it.twitterUrl ? '<a class="vlink" href="' + esc(it.twitterUrl) + '" target="_blank" rel="noopener" style="color:#1d9bf0;">🐦 X↗</a>' : '') +
          '<button type="button" class="cand-refimg-btn' + (hasRef ? ' has-img' : '') + '" data-refimg="' + esc(it.cid) + '">🖼 投稿編集' + (hasRef ? '✓' : '') + '</button>' +
          '<button type="button" class="cand-bsky-btn' + (hasBsky ? ' has-img' : '') + '" data-bsky="' + esc(it.cid) + '" title="Bluesky投稿に添付する画像を保存">🦋' + (hasBsky ? '✓' : '') + '</button>' +
          '<span style="flex:1 1 auto;"></span>' + // 非表示/再表示/削除ボタンを右端へ寄せる
          actionHtml +
        '</div>' +
      '</div></div>';
  }

  try { window.Go5Cand = { render: render }; } catch (e) {}
  hydrateImages_(); // IDBから画像をメモリへ＋旧localStorage画像を移行（5MB枠を解放）
  // 既存タブの移行: 登録済みサークルをPCバッチの追跡対象へ（登録済みはフラグでスキップ＝通信は初回のみ）
  ensureTrackedAll();
}());
