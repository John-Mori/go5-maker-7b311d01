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
 *   ・上記のどちらにも無い行は、記録シート(GAS action=history)から**表示専用**で補う(displayItems_/
 *     mergeSheetExtras_・hist-merge-core.js)。この端末には元々存在しない行(＝別端末で投稿した分)を
 *     ☁️シート由来バッジ付きで見せるだけで、localStorageへは書き戻さない(編集/削除もこの端末からは不可)。
 * 完全クライアントサイド。APIキーはこの端末内だけに保存。(リポジトリには置かない)
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  if (!$('ytClickList')) return;

  // ★アカウント解決は必ず Go5Acct.current() を通す(core/account.js＝唯一の入口という規約)。
  //   かつては当ファイルが localStorage('current_account') を直読みし、書き込み側の bluesky.js は
  //   window.getCurrentAccount()(＝メモリ上の curAccount)を見ていた。この2つは setAccount() の
  //   localStorage 書き込みが失敗した時や別タブで切り替えた時にズレる。ズレると
  //   「書き込みは acc2 / 読み出しは acc1」となり、**宵桜艶帖(acc2)の履歴だけが表示されなくなる**。
  //   どちらのフォールバックも 'acc1' なので、月詠み(acc1)では症状が出ない＝非対称の正体(INC-112)。
  function acct() {
    try { if (window.Go5Acct) return window.Go5Acct.current(); } catch (e) {}
    try { return localStorage.getItem('current_account') || 'acc1'; } catch (e) { return 'acc1'; }
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // 作品属性。(複数可)キャラ=実在キャラの二次創作 / JK / ギャル / 異世界。キャラ無し＝オリジナル。(非表示)
  // カテゴリの正本は core/categories.js(Go5Cats)。ここは list() から {key,label,color} を都度派生させる。
  //   ★都度読み＝カテゴリを追加/並べ替え/色替えしても再描画で即反映される(Chami依頼2026-08-02)。
  function attrDefs_() {
    try { return window.Go5Cats.visible().map(function (c) { return { key: c.key, label: c.label, color: c.color }; }); }
    catch (e) { return []; }
  }
  // 題名表示のタグ省略(2026-07-13・Chami指定): タグ構成は今後も変わるため固定リスト方式を廃止し、
  //   「最初の#以降を丸ごと省略」に統一。#が一個も無い題名だけ「タグ忘れあり」を表示する。
  function stripCommonTags(t) {
    var r = String(t || '');
    var i = r.indexOf('#');
    if (i < 0) return r.trim();
    return (r.slice(0, i).trim() || r.trim()); // #開始の題名は全消えを避けて原文のまま
  }
  function missingCommonTags(t) { return String(t || '').indexOf('#') < 0; }
  // 題名から定番タグに依存せずハッシュタグを抽出する(Chami依頼2026-07-31)。固定リストを持たないので
  //   実験でタグを変えても「実際に入っているタグ」がそのまま採れる。Chami保証の形式＝
  //   「題名<半角スペース1個>#tag #tag…」。半角スペース以降の #語 を拾い、無ければ題名全体から拾う。
  function titleHashtags_(title) {
    var t = String(title || '');
    var sp = t.indexOf(' '); // 最初の半角スペース＝題名とタグの区切り
    var body = sp >= 0 ? t.slice(sp + 1) : t;
    var m = (body.match(/#[^\s#]+/g)) || (t.match(/#[^\s#]+/g)) || [];
    return m.join(' ');
  }
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
        // ★日本時間で記録する(Chami依頼2026-07-17「JSTで今後記録して」)。
        //   toISOString()はUTC=Chamiの体感と9時間ズレ、日付すら変わって「いつ消えたか」が読めない。
        //   端末のローカル時刻(=JST)で 'YYYY-MM-DD HH:MM:SS' として持つ。
        at: (function () { var d = new Date(), p = function (n) { return (n < 10 ? '0' : '') + n; };
          return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' +
                 p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds()); })(),
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
  // ★bluesky.js の histSaveFor_ からも証拠を採れるよう公開する。
  //   当初この罠は「short_hist__ への書き込みは saveArr/saveArrFor_ が唯一の出口」を前提にしていたが、
  //   実際には bluesky.js:histSaveFor_ が第3の出口として素通りしていた。**罠の外で消えていたから
  //   犯人が捕まらなかった**(=「唯一の未解決INC」が長引いた構造的な理由・INC-112)。
  try { window.Go5HistLoss = { record: recordLoss_ }; } catch (e) {}
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
  // ★データ消失バグの本丸対策(2026-08-01)。長時間走る非同期ループ(バルク計測生成等)は
  //   開始時に配列をスナップショットして走るため、その窓の中でユーザーが別項目を「編集→保存」しても
  //   ループ終了時の「スナップショット丸ごと書き戻し」が編集前の値で上書きし、巻き戻してしまう。
  //   → 保存の直前に現ストレージを読み直し、itemKey一致の1件だけ指定フィールドを更新して書き戻す。
  //   対象行が既に消えている場合は何もしない(消した行を復活させない)。
  function persistFields_(storeKey, srcItem, fields) {
    try {
      var cur = loadArr(storeKey), key = itemKey(srcItem), idx = -1;
      for (var i = 0; i < cur.length; i++) { if (itemKey(cur[i]) === key) { idx = i; break; } }
      if (idx < 0) return;
      fields.forEach(function (f) { cur[idx][f] = srcItem[f]; });
      saveArr(storeKey, cur);
    } catch (e) {}
  }
  function loadYtMap() { try { return JSON.parse(localStorage.getItem(ytMapKey()) || '{}') || {}; } catch (e) { return {}; } }
  function saveYtMap(m) { try { localStorage.setItem(ytMapKey(), JSON.stringify(m)); } catch (e) {} }
  function apiKey() { try { return (localStorage.getItem('yt_api_key') || '').trim(); } catch (e) { return ''; } }
  function itemKey(it) { return (window.HistMerge && window.HistMerge.historyItemKey) ? window.HistMerge.historyItemKey(it) : (it.manual ? it.id : (it.postUri ? ('u:' + it.postUri) : (it.shortUrl ? ('s:' + it.shortUrl) : ('v:' + (it.videoId || ''))))); }
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

  // ── シート由来・表示専用マージ(Chami報告2026-07-21：「宵桜(acc2)の履歴だけ消える」「月詠み(acc1)の
  //   再生数が出ない」の真因は、この端末にその行が元々無いこと=別端末で投稿した分だった)。
  //   GAS(action=history)は行を丸ごと返せるのに、従来は既存ローカル行への欠損補完(restoreYtFromSheet_)
  //   にしか使っておらず、ローカルに無い行は一生表示されなかった。
  //   ★表示だけをマージする。localStorage(short_hist__)へは絶対に書き戻さない
  //   (INC-112「JSON破損時[]で上書き全消し」と同じ危険を新経路に持ち込まないため＝AD-GL裁定)。
  //   allItems() 自体は不変のまま(reconcileYtToSheet_/sendSync_/pruneSheet 等の書き込み系は
  //   これまで通りローカルのみを見る＝GAS/短縮Workerへの追加書き込みは一切発生しない)。
  //   重複排除・整形は hist-merge-core.js の純粋関数(HistMerge.mergeSheetExtras)へ切り出しテスト済み。
  var _sheetExtraCache = {}; // acct -> {at, items:[表示専用アイテム(_fromSheet:true)]}
  var SHEET_EXTRA_TTL_MS = 60000;
  // ★シート履歴(記録_ch1/ch2)の生行をlocalStorageへ退避(SWR)。acct -> [生シート行]。
  //   真因(Chami報告2026-08-02②「また7/29以前が消えた・同じミス」): GASのhistory取得が一過性に
  //   失敗/未達だと _sheetExtraCache[a] が空になり、投稿履歴がローカル(直近)だけ＝7/29以前の
  //   シート由来行が“また消えた”ように見えていた。v=574は「隠す(フィルタ)」だけをfail-openにしたが、
  //   「取れなかった時に空へ倒れる」経路が残っていた。→ 取得成功時に生行を保存し、失敗/取得前は
  //   前回の生行から復元して表示する(取れない時ほど旧データを見せる=fail-open)。次の成功で最新化。
  function persistSheetRaw_(a, rows) { try { localStorage.setItem('sheet_hist_raw__' + a, JSON.stringify(Array.isArray(rows) ? rows : [])); } catch (e) {} }
  function loadSheetRaw_(a) { try { var r = JSON.parse(localStorage.getItem('sheet_hist_raw__' + a) || '[]'); return Array.isArray(r) ? r : []; } catch (e) { return []; } }
  function mergeRawVsLocal_(rows) { return (rows && rows.length && window.HistMerge && window.HistMerge.mergeSheetExtras) ? window.HistMerge.mergeSheetExtras(allItems(), rows) : []; }
  function mergeRawSheetOnly_(rows) { return (rows && rows.length && window.HistMerge && window.HistMerge.mergeSheetExtras) ? window.HistMerge.mergeSheetExtras([], rows) : []; }
  // ★ランキング専用のシート履歴キャッシュ。acct -> {at, items}。
  //   _sheetExtraCache は「今のタブのチャンネル(acct())」の分しか取らないため、ランキング(両ch合算)では
  //   非アクティブ側のチャンネルのシート由来行(旧い作品)が永久に欠ける=「片方だけランキングに出ない」非対称に
  //   なる(Chami報告2026-08-02: 月詠みは出たが宵桜が出ない)。→ ランキングは acc1/acc2 両方を明示取得する。
  var _rankSheetCache = {}; // acct -> {at, items:[_fromSheet表示アイテム]}
  // ★ランキングは1回のrenderRankでdoRenderが複数回走る(即描画→YT取得後→GAS差分後→両chシート到着後)。
  //   毎回el.innerHTMLを丸ごと組み直すと、非同期で後から入る作品サムネ/価格が都度消えて“ちらつく”
  //   (Chami報告2026-08-02「サムネが表示されたり消えたり」)。→ 生成HTMLが前回と同一なら再描画を省く。
  var _rankLastHtml = '';
  var _rankGen = 0; // renderRank の世代(Codex監査 真因2)。古い非同期描画が最新DOMを上書きしないためのトークン。
  // ★シート由来行(_fromSheet)の編集を「保持」する表示専用オーバーレイ。acct -> { videoId: patch }。
  //   真因(Chami「一瞬反映→消失」2026-07-28 再発): 保存直後の refresh() が mergeSheetExtras_→
  //   TTL切れなら即GAS再取得し、upsertがまだ届く前の“古いシート値”で _sheetExtraCache を上書き=編集が消える。
  //   楽観キャッシュの上書き(v=464)だけでは再取得に勝てないため、videoId別のpatchを毎レンダーで上塗りして
  //   「再取得しても編集が復活しない」を保証する(display専用=localStorageへは一切書かない=INC-112防壁維持)。
  //   同じ行を編集し直すと上書き。GAS反映が遅れても消えず、届けば同値なので無害。
  var _pendingSheetEdits = {};
  // ★シート由来編集をリロードを越えて保持する専用ストア(hist/verify_manualとは別キー＝INC-112防壁の対象外)。
  //   真因(#5 Chami「リロードしたら保存したのにまた消えた」2026-07-29): _pendingSheetEdits は在メモリのみで、
  //   GAS往復が届く前にリロードすると {} に戻り、_fromSheet行が古いシート値へ戻る=編集が消える。
  //   → 編集を sheet_edit_pending__<acct>(専用キー・非同期=許可リスト外で既定ローカル)へも書き、起動時に復元する。
  //   シート正本が編集を反映できたら(historyHasEdit)そのvideoIdの保持は消す(=以後はシートが権威)。
  function pendKey_(a) { return 'sheet_edit_pending__' + (a || acct()); }
  function loadPend_(a) { try { return JSON.parse(localStorage.getItem(pendKey_(a)) || '{}') || {}; } catch (e) { return {}; } }
  function savePend_(a, obj) {
    try {
      if (obj && Object.keys(obj).length) localStorage.setItem(pendKey_(a), JSON.stringify(obj));
      else localStorage.removeItem(pendKey_(a));
    } catch (e) {}
  }
  // ── 合算URL(導線1)の永続ストア(Chami依頼2026-07-31) ─────────────────────────
  //   シート由来行(_fromSheet)の合算URLはシートに列が無く、_pendingSheetEdits(反映後に破棄される
  //   保持patch)にしか乗らないため、GAS往復が届くと消える。videoId別の専用キーへ書き、displayItems_
  //   が常に上塗りする=シートが権威になっても合算(クリック加算＋投稿URL欄の合算後URL表示)を維持する。
  //   ローカル行は it.mergeUrls(履歴配列に同梱)で永続するのでこのストアは使わない。
  function mergeStoreKey_(a) { return 'merge_urls__' + (a || acct()); }
  function loadMergeStore_(a) { try { return JSON.parse(localStorage.getItem(mergeStoreKey_(a)) || '{}') || {}; } catch (e) { return {}; } }
  function saveMergeStore_(a, obj) {
    try {
      if (obj && Object.keys(obj).length) localStorage.setItem(mergeStoreKey_(a), JSON.stringify(obj));
      else localStorage.removeItem(mergeStoreKey_(a));
    } catch (e) {}
  }
  function setMergeForVideo_(a, vid, urls) {
    if (!vid) return;
    var m = loadMergeStore_(a);
    if (Array.isArray(urls) && urls.length) m[String(vid)] = urls;
    else delete m[String(vid)];
    saveMergeStore_(a, m);
  }
  // シート正本が編集を反映できたvideoIdの保持を落とす(在メモリ＋localStorage双方)。過剰保持を防ぐ自己清掃。
  //   ★workUrl/ytUrlのどちらかが非空のpatchだけ照合対象(historyHasEditはこの2つ＋workStateしか見ないため、
  //    属性/platformだけの編集を空expectedで誤って"反映済み"と判定して消さない)。
  function reconcilePend_(a, sheetItems) {
    var pm = _pendingSheetEdits[a]; if (!pm) return;
    var he = window.HistMerge && window.HistMerge.historyHasEdit; if (!he) return;
    var changed = false;
    Object.keys(pm).forEach(function (vid) {
      var patch = pm[vid] || {};
      if (!patch.workUrl && !patch.ytUrl) return; // 照合できる実体が無い=在セッションのbgSuccessに任せる
      var expected = { videoId: vid, youtubeUrl: patch.ytUrl || '', workUrl: patch.workUrl || '', workState: patch.workState || '' };
      if (he(sheetItems, expected)) { delete pm[vid]; changed = true; }
    });
    if (changed) savePend_(a, pm);
  }
  // 起動時に両チャンネルの保持を復元(リロードを越えて編集を生かす)。acctは明示指定=呼び出し時のタブに依存しない。
  ['acc1', 'acc2'].forEach(function (a) { var p = loadPend_(a); if (p && Object.keys(p).length) _pendingSheetEdits[a] = p; });
  // 短縮URLのドメインからチャンネルを判定(月詠み=5mgl.com/acc1・宵桜艶帖=yoz2.com/acc2)。
  //   短縮リンクは投稿時にチャンネル別ドメインで払い出される(bluesky.js URL_BY_ACCT)ので、
  //   postUri/背骨IDの無い手動・ドラフト由来行でも所属を確定できる唯一の権威シグナル。
  function acctByShort_(it) {
    var s = String((it && it.shortUrl) || '') + ' ' + String((it && it.workShortUrl) || '') + ' ' + String((it && it.shareUrl) || '');
    if (s.indexOf('5mgl.com') >= 0) return 'acc1';
    if (s.indexOf('yoz2.com') >= 0) return 'acc2';
    return '';
  }
  // 表示専用のチャンネルガード。所属が「別チャンネルだと確定できた」行だけを今のタブから隠す。
  //   判定不能(ownerOf_='' かつ ドメイン無し)は残す=fail-open(正当な行を誤って消さない)。
  //   ★表示だけ。localStorage/シートへは一切書かない(INC-112 防壁を維持)。
  //   狙い(Chami報告2026-07-29): 同じ題名が両チャンネルの投稿履歴に出る=正本がどちらのストアにも
  //   居る状態でも、短縮URLドメイン/投稿者DID/背骨ID接頭辞で正しい側のタブにだけ出す。
  function filterOtherChannel_(items) {
    var cur = acct();
    return items.filter(function (it) {
      if (!it) return false;
      // ★シート由来行(_fromSheet)は「そのチャンネルのシート(記録_ch1/ch2)」から channel=<cur> 指定で
      //   取得した権威データ＝この行はこのタブのチャンネルで確定している。背骨ID接頭辞(INC-73で
      //   記録_ch2 に紛れた誤 acc1- 行)や短縮ドメイン(7/20分割前の共用 5mgl.com)といった「acc1に倒れる
      //   歴史的シグナル」で誤って隠すと、宵桜(acc2)の旧い実投稿がどのタブにも出ず“消えた”ように見える
      //   (Chami報告2026-08-02・v=497の表示ガード発効=7/30以降にacc2の7/29以前が消えた症状に一致)。
      //   → シート由来行は postUri×DID台帳/↩️固定で「別chと積極的に確定」できた時だけ隠す=fail-open。
      //   (このガードが本来狙うのは「同一題名がローカル両ストアに居る」ケース＝下のローカル行側で継続)。
      if (it._fromSheet) {
        if ((it._ownerPin === 'acc1' || it._ownerPin === 'acc2') && it._ownerPin !== cur) return false;
        var R = window.Go5AccountRepair;
        if (it.postUri && R && R.ledgerFresh && R.ledgerFresh() && R.didReady && R.didReady() && R.classifyByPost) {
          var byPost = R.classifyByPost(it) || '';
          if (byPost && byPost !== cur) return false; // DIDで別chと確定した時のみ隠す
        }
        return true;
      }
      var ch = ownerOf_(it) || acctByShort_(it);
      return !ch || ch === cur; // 他chと確定した行のみ隠す。不明はそのまま出す
    });
  }
  // 【恒久・供給一本化 2026-08-03】シート由来行(_fromSheet)への上塗り(保持patch＋合算URLストア)を
  //   投稿履歴とランキングで共通化する。従来は投稿履歴(displayItems_)だけが当てており、ランキングは
  //   生シート行を直読み=shortUrl/合算URLがpatch側にしか無い作品のクリックコードが解決できず、
  //   「投稿履歴では出るクリックがランキングに出ない」非対称の温床だった(Chami報告2026-08-02【A】)。
  function applySheetOverlays_(items, a) {
    var pend = _pendingSheetEdits[a];
    if (pend) items = items.map(function (it) {
      if (!it || !it._fromSheet || !it.videoId) return it;
      var patch = pend[String(it.videoId)];
      if (!patch) return it;
      var copy = {};
      for (var p in it) if (Object.prototype.hasOwnProperty.call(it, p)) copy[p] = it[p];
      for (var q in patch) if (Object.prototype.hasOwnProperty.call(patch, q)) {
        var pv = patch[q];
        // ★空文字のpatchでシート値を消さない=編集で触っていない/未入力の欄が空でも上書きしない。
        //   (これをしないと保持patchのworkShortUrl='' 等が導線2の短縮URLを毎回空欄に戻す事故になる)
        //   カテゴリ属性はbooleanで false も有効値なので常に反映する。
        if (typeof pv === 'string' && pv === '') continue;
        copy[q] = pv;
      }
      // ★意図的クリア印が立っていたら、シートに残る誤挿入の作品短縮URLを表示上も空にする
      //   (patchのworkShortUrl='' は上の空スキップで効かないので、boolの印で確実に消す)。
      if (copy.workShortNone) { copy.workShortUrl = ''; copy.workShareUrl = ''; }
      return copy;
    });
    // 合算URL(導線1)を_fromSheet行へ上塗り(保持patchが破棄された後も維持・Chami依頼2026-07-31)。
    var mstore = loadMergeStore_(a);
    if (mstore && Object.keys(mstore).length) items = items.map(function (it) {
      if (!it || !it._fromSheet || !it.videoId) return it;
      var mu = mstore[String(it.videoId)];
      if (!Array.isArray(mu) || !mu.length) return it;
      var copy = {}; for (var p in it) if (Object.prototype.hasOwnProperty.call(it, p)) copy[p] = it[p];
      copy.mergeUrls = mu;
      return copy;
    });
    return items;
  }
  function displayItems_() {
    var local = allItems();
    var c = _sheetExtraCache[acct()];
    var items = (c && c.items && c.items.length) ? local.concat(c.items) : local;
    return filterOtherChannel_(applySheetOverlays_(items, acct()));
  }
  // GASのhistoryをマージ用に取得。未設定/失敗時は前回キャッシュ(無ければ空)を返すだけ＝ローカル表示は無傷。
  function fetchSheetExtra_(cb) {
    var a = acct(), now = Date.now(), c = _sheetExtraCache[a];
    // at < 0 = 失敗マーク(常にTTL切れ扱い→リトライ。ただしcが存在するためrender()は「読み込み中...」を解除する)
    if (c && c.at >= 0 && (now - c.at) < SHEET_EXTRA_TTL_MS) { if (cb) cb(c.items); return; }
    // ★SWR: 未取得なら退避済みの生行から即復元して表示(7/29以前を待たせず・消さず出す)。この後で最新化する。
    if (!c) { var seed = mergeRawVsLocal_(loadSheetRaw_(a)); if (seed.length) { _sheetExtraCache[a] = c = { at: 0, items: seed }; } }
    var gasUrl = gasUrl_();
    if (!gasUrl) {
      if (!c) _sheetExtraCache[a] = { at: 0, items: [] }; // GAS未設定=マージ対象なし・キャッシュを「取得済み扱い」にして「読み込み中...」を出さない
      if (cb) cb((_sheetExtraCache[a] && _sheetExtraCache[a].items) || []); return;
    }
    jsonp_(gasUrl, { action: 'history', channel: a, limit: 300 }, function (res) {
      if (!res || !res.ok || !Array.isArray(res.items)) {
        // ★失敗時は空へ倒さない=退避済みの生行を復元して「7/29以前が消える」を防ぐ(fail-open)。
        //   退避も無い場合のみ空(at=-1)にして「読み込み中...」を解除。次回リトライ可(TTL常に切れ)。
        var fb = mergeRawVsLocal_(loadSheetRaw_(a));
        var prev = (_sheetExtraCache[a] && _sheetExtraCache[a].items) || [];
        _sheetExtraCache[a] = { at: -1, items: fb.length ? fb : prev };
        if (cb) cb(_sheetExtraCache[a].items); return;
      }
      persistSheetRaw_(a, res.items); // 成功した生行を退避(次の失敗/リロードで復元できる)
      var extra = (window.HistMerge && window.HistMerge.mergeSheetExtras) ? window.HistMerge.mergeSheetExtras(allItems(), res.items) : [];
      _sheetExtraCache[a] = { at: now, items: extra };
      reconcilePend_(a, res.items); // シートが編集を反映済みなら保持を落とす(リロード後の自己清掃)
      if (cb) cb(extra);
    });
  }
  // 指定chのシート由来行(キャッシュ→無ければ退避済み生行から即席復元・通信なし)。
  function rankSheetItems_(a) {
    var c = _rankSheetCache[a];
    if (!c) c = _rankSheetCache[a] = { at: 0, items: mergeRawSheetOnly_(loadSheetRaw_(a)) };
    return c.items || [];
  }
  // 【恒久・供給一本化 2026-08-03】指定chの表示アイテム=ローカル履歴＋シート由来行＋上塗り(patch/合算URL)。
  //   投稿履歴(displayItems_)と同じ材料をチャンネル明示で返す。ランキングの収集とスナップ採録(vidCodeMap_)は
  //   必ずここを通す=「投稿履歴とランキングでデータの取り方が分裂」する構造を根絶(Chami報告2026-08-02【A】)。
  //   ローカルとシートの重複は呼び出し側が vid で排除する(ローカルが先=ローカル優先)。
  function channelItemsFor_(a) {
    var local = loadArr('short_hist__' + a).filter(function (it) { return it && !it.manualOnly; })
      .concat(loadArr('verify_manual__' + a));
    return applySheetOverlays_(local.concat(rankSheetItems_(a)), a);
  }
  // ランキング(両ch合算)用に、指定チャンネル a のシート履歴を明示取得する。
  //   fetchSheetExtra_ は acct()(今のタブ)固定なので非アクティブ側が取れない。ここは a を明示。
  //   ローカルとの重複排除はランキング側が vid で行うため、mergeSheetExtras の第1引数は空配列
  //   (シート行同士の重複だけ畳む)。GAS未設定/失敗でも表示は無傷(空配列を返すだけ)。
  function fetchSheetForRank_(a, cb) {
    var now = Date.now(), c = _rankSheetCache[a];
    if (c && c.at >= 0 && (now - c.at) < SHEET_EXTRA_TTL_MS) { if (cb) cb(c.items); return; }
    // ★SWR: 未取得なら退避済み生行から即復元(非アクティブ側chもランキングから消えない)。
    if (!c) { rankSheetItems_(a); c = _rankSheetCache[a]; }
    var gasUrl = gasUrl_();
    if (!gasUrl) { if (!c) _rankSheetCache[a] = { at: 0, items: [] }; if (cb) cb((_rankSheetCache[a] && _rankSheetCache[a].items) || []); return; }
    jsonp_(gasUrl, { action: 'history', channel: a, limit: 300 }, function (res) {
      if (!res || !res.ok || !Array.isArray(res.items)) {
        // ★失敗時は空へ倒さない=退避済み生行を復元(ランキングから旧作が消えるのを防ぐ)。
        var fb = mergeRawSheetOnly_(loadSheetRaw_(a));
        var prev = (_rankSheetCache[a] && _rankSheetCache[a].items) || [];
        _rankSheetCache[a] = { at: -1, items: fb.length ? fb : prev };
        if (cb) cb(_rankSheetCache[a].items); return;
      }
      persistSheetRaw_(a, res.items); // 成功した生行を退避(投稿履歴側と共用)
      var extra = (window.HistMerge && window.HistMerge.mergeSheetExtras) ? window.HistMerge.mergeSheetExtras([], res.items) : [];
      _rankSheetCache[a] = { at: now, items: extra };
      if (cb) cb(extra);
    });
  }
  // refresh()から毎回呼ぶ(TTLキャッシュ内は通信ゼロ)。GASレスポンス後は必ずrender()=「読み込み中...」を確実に解除する。
  function mergeSheetExtras_() {
    fetchSheetExtra_(function (extra) {
      render(); // GAS応答後に必ず再描画(「読み込み中...」→実データ or「まだ記録がありません」へ更新)
      if (!extra || !extra.length) return; // 追加行が無ければここで終了
      try { fetchData_(extra, {}, false).then(function () { render(); }); } catch (e) {}
    });
  }

  // ── PC(広い画面)向け：投稿履歴カードの列数(ユーザー選択・スマホは無効)。候補タブと同方式。 ──
  var K_HISTCOLS = 'hist_pc_cols';
  var HCOLS_MIN = 1, HCOLS_MAX = 4, HCOLS_DEF = 2; // 既定2列(候補タブと同方式・PC幅拡張に合わせ2026-07-17)。モバイルはCSSで常に1列
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
    var g = window.Go5Short;
    var base = (g && g.ourBase) ? g.ourBase(shortUrl) : '';  // 両ドメイン+旧r2のどれかに一致したベース
    if (!base || !shortUrl) return '';
    // ★base.length で切ると scheme 無しURL("5mgl.com/xxxxx")でズレる。両者から scheme を外して比較・抽出する。
    var bareBase = base.replace(/^https?:\/\//, '');
    var bareUrl = String(shortUrl).replace(/^https?:\/\//, '');
    if (bareUrl.indexOf(bareBase + '/') !== 0) return '';
    var rest = bareUrl.slice(bareBase.length + 1).split(/[/?#]/)[0];
    return /^[0-9A-Za-z]+$/.test(rest) ? rest : '';
  }
  // 投稿リンクがX(旧Twitter)か判定。(BlueskyのpostUri=at://は常にBsky確定。
  //   生URLがx.com/twitter.comならX。短縮URLしか無い場合は判別不能=既定X＝platOf_(ラジオ)の既定と一致させる。
  //   ★旧・既定Bskyだと、保存前は「ラジオ=X」なのに「表示=Bsky↗」に食い違った(Chami報告2026-07-29)。
  function isXLink_(href, it) {
    // 編集で明示指定(X/Bsky)があれば最優先。短縮URLだけの行はURLから判別できないため手動選択が正。
    if (it && it.platform === 'x') return true;
    if (it && it.platform === 'bsky') return false;
    if (it && it.postUri) return false;
    var XRE = /(?:x\.com|twitter\.com)\//i;
    if (XRE.test(String(href || ''))) return true;
    if (it && (XRE.test(String(it.postUrl || '')) || XRE.test(String(it.shareUrl || '')))) return true;
    if (it && /bsky\.app\//i.test(String((it.postUrl || '') + ' ' + (it.shareUrl || '') + ' ' + (it.shortUrl || '')))) return false;
    return true; // 判別不能=既定X(Chami:これから原則X投稿)。platOf_ と揃える
  }
  // 投稿履歴の「Bsky↗」リンク。Xリンクなら「X↗」表示＋白字黒枠(.vlink-x)へ切替。
  function postLinkHtml_(href, it) {
    if (!href) return '';
    var x = isXLink_(href, it);
    return '<a class="vlink ' + (x ? 'vlink-x' : 'vlink-bsky') + '" href="' + esc(href) + '" target="_blank" rel="noopener">' + (x ? 'X↗' : 'Bsky↗') + '</a>';
  }
  // 編集モーダルのX/Bskyラジオ用：この行の現在の投稿先。明示指定＞URL判定＞既定X(Chami:これから原則X投稿)。
  function platOf_(it) {
    if (it && it.platform === 'x') return 'x';
    if (it && it.platform === 'bsky') return 'bsky';
    if (it && it.postUri) return 'bsky';
    var s = String((it && it.postUrl) || '') + ' ' + String((it && it.shareUrl) || '') + ' ' + String((it && it.shortUrl) || '');
    if (/(?:x\.com|twitter\.com)\//i.test(s)) return 'x';
    if (/bsky\.app\//i.test(s)) return 'bsky';
    return 'x';
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
  // 管理中のセール案内URL(名前付き・アカウント別)を列挙し、各エントリの短縮コード集合を導出する。
  //   bluesky.js が短縮リンクを bsky_discount_link_cache(map: account|entryId|afId|domain → 短縮URL)へ貯める。
  //   別IIFEだが同一ページ・同一localStorageなので直接読む。名前で分けて表示するため(Chami依頼2026-07-29)。
  //   ★旧実装は saleCodes_()(JrziR＋死んだキー bsky_discount_list_link_r2＝どこからも書かれない)しか
  //   見ておらず、名前付き管理へ移行した現行のセールURL(例 夏セールの同人祭)が投稿履歴に一切出なかった=本件の根因。
  var SALE_SEED_URL = 'https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=mens/';
  function saleEntries_() {
    var acc = acct(), arr = [];
    try { var a = JSON.parse(localStorage.getItem('bsky_discount_urls__' + acc) || '[]'); if (Array.isArray(a)) arr = a; } catch (e) {}
    // 後方互換: アカウント別キーが空なら、口座分割(2026-07-20)前の旧・単一キー(bsky_discount_urls)も見る。
    //   旧運用でここへ登録された名前付きセール(例 夏セールの同人祭)が、suffix付きキーしか読まないため
    //   名前で一切出ず、投稿履歴の上が汎用「セール会場」に落ちていた穴を塞ぐ(Chami報告2026-07-29)。
    if (!arr.length) {
      try { var lg = JSON.parse(localStorage.getItem('bsky_discount_urls') || '[]'); if (Array.isArray(lg)) arr = lg; } catch (e) {}
    }
    var cache = {};
    try { var o = JSON.parse(localStorage.getItem('bsky_discount_link_cache') || '{}'); if (o && typeof o === 'object') cache = o; } catch (e) {}
    var codesByEntry = {}; // entryId → [短縮コード…](同一ch内のaf_id違いだけ合算＝名前ごとの通算)
    // ★キャッシュキーは account|entryId|afId|domain(bluesky-core.js buildDiscountCacheKey)。
    //   セール案内URLはチャンネル別ドメインで計測される(月詠み=5mgl.com/acc1・宵桜艶帖=yoz2.com/acc2)。
    //   entryId だけで束ねると別ch(別ドメイン)のクリックまで合算=「ごっちゃ」になっていた(Chami報告2026-07-29③)。
    //   → 表示中アカウント(=そのドメイン)のコードだけを集計し、ドメインごとに独立計測する。
    Object.keys(cache).forEach(function (k) {
      var seg = String(k).split('|'), kacc = seg[0] || '', eid = seg[1] || ''; if (!eid) return;
      if (kacc && kacc !== acc) return; // 別チャンネル(別ドメイン)のコードは混ぜない=独立計測
      var c = codeOf(cache[k] || ''); if (!c) return;
      (codesByEntry[eid] = codesByEntry[eid] || []).push(c);
    });
    return arr.map(function (e) {
      var codes = (codesByEntry[e.id] || []).slice();
      if (/campaign=gain/.test(String(e.url || '')) && codes.indexOf('JrziR') < 0) codes.push('JrziR'); // 既定セールページは歴史的JrziRを合算(過去分を失わない)
      var uniq = codes.filter(function (c, i) { return codes.indexOf(c) === i; });
      return { id: e.id, name: String(e.name || '(無題)'), url: String(e.url || ''), codes: uniq, at: (typeof e.at === 'number' ? e.at : 0) };
    });
  }
  // 現行のセールコードをGASへ登録(変化時のみ送信)。→ snapshotStatsが各コードを日次スナップし
  //   今日/昨日/週を名前別に出せるようにする。アカウント別に保持(両chのコードを失わない)。
  function registerSaleCodes_() {
    var base = gasUrl_(); if (!base) return;
    var codes = [];
    saleEntries_().forEach(function (e) { e.codes.forEach(function (c) { if (codes.indexOf(c) < 0) codes.push(c); }); });
    if (!codes.length) return;
    var acc = acct(), tag = acc + ':' + JSON.stringify(codes), last = '';
    try { last = localStorage.getItem('sale_codes_reg') || ''; } catch (e) {}
    if (last === tag) return; // 変化が無ければ送らない(通信を増やさない)
    jsonp_(base, { action: 'sale_reg', acc: acc, sale: JSON.stringify(codes) }, function (res) {
      // saleReg_ が応答した時だけ登録済みにする(countを返すのはsaleReg_のみ。未デプロイGASの
      //   既定分岐は{ok:true,shortUrl:''}を返すため、それを成功と誤認して再送を止めないようcountで判別)。
      if (res && res.ok && typeof res.count === 'number') { try { localStorage.setItem('sale_codes_reg', tag); } catch (e) {} }
    });
  }
  function renderSaleStats_() {
    var el = document.getElementById('saleStats'); if (!el) return;
    var entries = saleEntries_();
    try { registerSaleCodes_(); } catch (e) {}
    var allCodes = [];
    entries.forEach(function (e) { e.codes.forEach(function (c) { if (allCodes.indexOf(c) < 0) allCodes.push(c); }); });
    if (!allCodes.length) allCodes = saleCodes_(); // 後方互換(管理URL未登録の旧環境)
    function f(x) { return (x == null ? '–' : num(x)); }
    function deltasFor(codes) {
      var tc = null, yc = null, wc = null;
      codes.forEach(function (c) {
        var d = deltaCache && (deltaCache['SALE:' + c] || (c === 'JrziR' ? deltaCache.SALE : null));
        if (!d) return;
        if (d.tc != null) tc = (tc || 0) + d.tc;
        if (d.yc != null) yc = (yc || 0) + d.yc;
        if (d.wc != null) wc = (wc || 0) + d.wc;
      });
      return { tc: tc, yc: yc, wc: wc };
    }
    // 旧🏮絵文字を金色カーソル(白背景透過済み)へ置換(Chami指定2026-07-29)
    var SALE_ICO = '<img class="emico emico-sale" src="assets/icons/ic-sale-gold.png" alt="セール">';
    function fmtDay_(ms) { if (!ms) return ''; var d = new Date(ms); return d.getFullYear() + '/' + (d.getMonth() + 1) + '/' + d.getDate(); }
    function paint() {
      var lines;
      if (entries.length) {
        // 1段目=金矢印＋名前 / 2段目=記載開始日・累計/今日/昨日/週(見やすさ優先で改行・Chami指定2026-07-29)
        lines = entries.map(function (e) {
          var cum = null; e.codes.forEach(function (c) { if (c in clicksCache) cum = (cum || 0) + clicksCache[c]; });
          var dl = deltasFor(e.codes);
          var day = fmtDay_(e.at);
          var sub = (day ? '記載開始:' + day + '　' : '') +
            '累計:' + f(cum) + '　今日:' + f(dl.tc) + '　昨日:' + f(dl.yc) + '　週:' + f(dl.wc);
          return SALE_ICO + esc(e.name) + '<br><span class="sale-sub">' + sub + '</span>';
        });
      } else {
        var cum = null; allCodes.forEach(function (c) { if (c in clicksCache) cum = (cum || 0) + clicksCache[c]; });
        var d = (typeof deltaCache === 'object' && deltaCache) ? deltaCache.SALE : null;
        lines = [SALE_ICO + 'セール会場<br><span class="sale-sub">累計:' + f(cum) + '　今日:' + f(d && d.tc) + '　昨日:' + f(d && d.yc) + '　週:' + f(d && d.wc) + '</span>'];
      }
      el.innerHTML = lines.join('<br>');
    }
    // 既に一括取得済みならリクエスト0で描画。未取得のときだけ /api/list を1本(TTL内は再利用)。
    //   ＝render()のたびに /api/stats を叩いていた旧実装の無駄を除去(Cloudflare無料枠対策2026-07-16)
    if (allCodes.some(function (c) { return c in clicksCache; })) { paint(); return; }
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
  // ── 計測ヘルス(B-3・Chami承認2026-07-17) ─────────────────────────────
  // 「🏮セール会場 累計0」「YouTube→Bluesky 0なのにBluesky→FANZA 19」のように、Chamiが数字を
  // 疑うたびに調査が1回走っていた。**信頼は可視化からしか生まれない**ので、計測3経路の生死を常時出す。
  // ★P-2(1操作=Nリクエスト禁止)を守るため、**追加の通信は一切しない**。既存の fetchAllClicks_ /
  //   fetchDeltas_ / fetchVideos の**結果を記録するだけ**(観測のために叩かない)。
  var _health = { r2: null, gas: null, yt: null, gasAt: 0 }; // null=未実行 / true=OK / false=失敗
  function healthHtml_() {
    function seg(label, st, note) {
      if (st === null) return '<span style="opacity:.45;">' + label + ' —</span>';
      return st ? '<span style="opacity:.75;">' + label + ' OK' + (note ? '(' + note + ')' : '') + '</span>'
                : '<span style="color:#dc465a;font-weight:700;">' + label + ' 応答なし</span>';
    }
    var gasNote = _health.gasAt ? ('最終 ' + fmtTimeShort_(_health.gasAt)) : '';
    return '計測: ' + seg('短縮URL', _health.r2) + ' / ' + seg('記録GAS', _health.gas, gasNote) + ' / ' + seg('YouTube', _health.yt);
  }
  function fmtTimeShort_(ms) { try { var d = new Date(ms); return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); } catch (e) { return ''; } }
  function renderHealth_() { var el = document.getElementById('measHealth'); if (el) el.innerHTML = healthHtml_(); }

  var _clicksAt = 0, _clicksP = null, CLICKS_TTL_MS = 60000;
  function fetchAllClicks_(force) {
    var w = window.Go5Short;
    if (!w || !w.WORKER_URL || !w.SHARED_SECRET) return Promise.resolve(false);
    var now = new Date().getTime();
    if (!force && _clicksP && (now - _clicksAt) < CLICKS_TTL_MS) return _clicksP; // 直近取得を再利用(連打・多発を抑制)
    _clicksAt = now;
    var u = w.WORKER_URL.replace(/\/+$/, '') + '/api/list?secret=' + encodeURIComponent(w.SHARED_SECRET);
    _clicksP = fetch(u).then(function (r) { return r.json(); }).then(function (j) {
      if (!j || !j.ok || !j.links) { _health.r2 = false; renderHealth_(); return false; }
      j.links.forEach(function (l) { if (l && l.code) clicksCache[l.code] = l.clicks || 0; });
      _health.r2 = true; renderHealth_();                 // ★既存の取得結果を記録するだけ=追加通信ゼロ
      return true;
    }).catch(function () { _health.r2 = false; renderHealth_(); return false; });
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
      _health.yt = !(j && j.error); try { renderHealth_(); } catch (e) {} // 既存取得の結果を記録(追加通信ゼロ)
      return out;
    }).catch(function () { _health.yt = false; try { renderHealth_(); } catch (e) {} return { __error: '通信エラー(YouTubeに接続できませんでした)' }; }); // D2: 失敗を{}で握りつぶさない＝「成功表示なのに取れない」を防ぐ
  }

  // ── 今日/昨日/直近1週間の再生・クリック増加(GASが毎時サーバー側で記録した差分)──
  // localStorageに前回値を保持し、開いた瞬間に即表示→GAS取得で最新化。
  var deltaCache = (function () { try { return JSON.parse(localStorage.getItem('delta_cache') || '{}') || {}; } catch (e) { return {}; } })(); // vid -> {tv,yv,wv,tc,yc,wc}
  var peakCache = (function () { try { return JSON.parse(localStorage.getItem('peak_cache') || '{}') || {}; } catch (e) { return {}; } })(); // vid -> {vRate,vWin,cRate,cWin}
  var tpCache = (function () { try { return JSON.parse(localStorage.getItem('tp_cache') || '{}') || {}; } catch (e) { return {}; } })(); // vid -> {b30:{v,c,age},..} GASサーバー時点記録(公開起点・端末未起動でも記録)
  // ★負のデルタは無意味(期間内にクリック/再生が減ることは無い)。GASが短縮コード切替やaf_id変更で
  //   カウンタがリセットされた区間を跨ぐと (now − weekAgo) が負になり「週:-16」のような表示になる
  //   (Chami報告 msg1532109479103955026「累計0なのに先週-16」)。期間デルタは 0 を下限に丸める。
  //   null(記録欠損=「–」表示)は触らない=Chami仕様の「今日投稿の昨日だけ–」を壊さない。
  function sanitizeDeltas_(dc) {
    if (!dc || typeof dc !== 'object') return dc;
    Object.keys(dc).forEach(function (k) {
      var d = dc[k]; if (!d || typeof d !== 'object') return;
      ['tv', 'yv', 'wv', 'tc', 'yc', 'wc'].forEach(function (f) {
        if (typeof d[f] === 'number' && d[f] < 0) d[f] = 0;
      });
    });
    return dc;
  }
  sanitizeDeltas_(deltaCache); // 起動時にlocalStorageから読んだ旧キャッシュ内の負値も丸める
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
  function fmtDelta_(d, tsMs, hasWork, prePost) {
    // ★dが無くても「記録待ち」の文言は出さず、今日/昨日/週の枠を必ず出す(セルは–・Chami依頼2026-07-30)。
    //   サーバースナップが載れば refreshDeltas_ が数値へ差し替える。
    var pending = !d;
    if (pending) d = {};
    var CI = '<img class="emico" src="assets/icons/ic-link.png" alt="">';         // 導線1(Bsky投稿クリック)
    var WI = '<img class="emico emico-cursor" src="assets/icons/ic-cursor-pink.png" alt="">'; // 導線2(作品クリック)
    var todayPosted = postedTodayOf_(tsMs);
    // 投稿からの経過時間。「投稿したて＝日次スナップがまだ回っていない」を「記録欠損(⚠)」と区別する用(Chami依頼2026-08-03)。
    var ageMs = tsMs ? (Date.now() - Number(tsMs)) : -1;
    var freshPost = ageMs >= 0 && ageMs < 36 * 3600 * 1000; // 36時間以内=投稿したて→値が無いのは「まだ記録待ち」
    function cell(v, allowDash) {
      if (v != null) return num(v);
      // 投稿前(YouTube未公開=投稿予定)/スナップ前(記録待ち)は「記録欠損」ではなく元々データが無いだけなので ⚠ ではなく – を出す(Chami指示2026-07-28/2026-07-30)
      if (allowDash || prePost || pending) return '–';
      // 投稿したて(36h以内)でまだスナップが取れていないだけ=欠損ではないので ⚠ ではなく「未」(=未計測・毎時の自動記録で数値に変わる。Chami依頼2026-08-03)
      if (freshPost) return '<span title="投稿したてで、まだ計測記録が取れていません(毎時の自動記録で数値に変わります)。⚠は追跡開始前の期間か取得失敗を表し、これとは別です">未</span>';
      return '<span title="記録欠損: 追跡開始前の期間(この計測機能の導入前に投稿)か、その回の取得失敗。(YT APIクォータ等)以後の期間は正常に記録されます">⚠</span>';
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
      el.innerHTML = fmtDelta_(vid && deltaCache[vid], el.getAttribute('data-delta-ts'), el.getAttribute('data-delta-haswork') === '1', el.getAttribute('data-delta-prepost') === '1') || el.innerHTML;
    });
  }
  function fetchDeltas_(force, cb) {
    if (_deltaFetched && !force) { applyDeltas_(); if (cb) cb(); return; }
    var url = gasUrl_(); if (!url) { applyDeltas_(); if (cb) cb(); return; }
    jsonp_(url, { action: 'deltas' }, function (res) {
      if (res && res.ok && res.deltas) {
        deltaCache = sanitizeDeltas_(res.deltas); _deltaFetched = true; // GAS由来の負デルタも0下限へ
        try { localStorage.setItem('delta_cache', JSON.stringify(deltaCache)); } catch (e) {}
        if (res.peaks) { peakCache = res.peaks; try { localStorage.setItem('peak_cache', JSON.stringify(peakCache)); } catch (e) {} }
        if (res.timepoints) { tpCache = res.timepoints; try { localStorage.setItem('tp_cache', JSON.stringify(tpCache)); } catch (e) {} }
        _health.gas = true; _health.gasAt = new Date().getTime(); // 既存取得の結果を記録(追加通信ゼロ)
      } else { _health.gas = false; }
      try { renderHealth_(); } catch (e) {}
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
  // 【恒久・供給一本化 2026-08-03】導線1/導線2のクリック数を「投稿履歴と全く同じ計算」で1関数へ寄せる。
  //   v=579 は材料(shortUrl)の供給を履歴とランキングで揃えたが、値の"計算式"は分裂したままだった=
  //   ランキングは clicksCache[code] を直読みするだけで ①合算URL(mergeUrls)の加算 ②GAS日次デルタ
  //   (deltaCache)による累計の下限 を欠いていた。そのため「手入力の作品短縮URLでcodeOfが空/合算で
  //   割れた作品」は履歴では210出るのにランキングでは null→除外され「クリックがランキングに出ない」が
  //   残った(Chami報告2026-08-03【A再発】)。以後は履歴(render)もランキング(doRender)もこの1関数を通す。
  // 短縮URL群を code 単位で重複なく合算(Codex §6.3)。表記違い(https有無/query)でも同一codeは1回。
  //   1つでも clicksCache に在れば数値(取得済み0を含む)、全て未取得なら null(取得中/計測URLなしと区別)。
  function sumClickCodes_(urls) {
    var seen = {}, sum = 0, got = false;
    for (var i = 0; i < urls.length; i++) {
      var c = codeOf(urls[i] || '');
      if (c && !seen[c]) { seen[c] = 1; if (c in clicksCache) { sum += (clicksCache[c] || 0); got = true; } }
    }
    return got ? sum : null;
  }
  function postClicks_(it, vid) {
    var code = codeOf(it.shortUrl || '');   // 表示用の主コード(白矢印リンク)
    var wcode = codeOf(it.workShortUrl || ''); // 表示用の主コード(ピンク矢印リンク)
    // 導線1: 主short + clickUrls(異ドメインの別URL) + 合算URL群 を code 単位で重複なく合算。
    //   従来は主code値に mergeUrls を"別途"足していたため、mergeUrls に主codeが含まれると二重計上し得た。
    //   URL集合→code重複除去→1回加算 に統一(Codex T2/T3・履歴とランキング共通)。
    var clicks = sumClickCodes_([it.shortUrl].concat(it.clickUrls || []).concat(it.mergeUrls || []));
    // 導線2: 作品短縮 + workClickUrls(統合で拾った別URL)。
    var wclicks = sumClickCodes_([it.workShortUrl].concat(it.workClickUrls || []));
    // GAS日次デルタで累計の下限を張る(累計≥週)。codeOfが空(手入力の作品短縮URL等)でもGAS由来の
    //   実数があれば必ず反映=「累計0なのに週8」やランキング除外を封じる(履歴と同一のロジック)。
    var _dl = vid ? deltaCache[vid] : null;
    if (_dl) {
      var cCum = (_dl.cc != null) ? _dl.cc : Math.max(_dl.wc || 0, _dl.tc || 0, _dl.yc || 0);
      if (cCum > 0) clicks = Math.max(clicks || 0, cCum);
      var wCum = (_dl.cwc != null) ? _dl.cwc : Math.max(_dl.wwc || 0, _dl.twc || 0, _dl.ywc || 0);
      if (wCum > 0) wclicks = Math.max(wclicks || 0, wCum);
    }
    // リビルド結合＝この投稿のクリック＋リビルド前の動画のクリック(別短縮URLのため加算)。
    var clicksTotal = (it.rebuildMerged && it.rebuildBaseClicks != null) ? ((clicks != null ? clicks : 0) + it.rebuildBaseClicks) : clicks;
    return { c1: clicksTotal, c2: wclicks, code: code, wcode: wcode };
  }
  var viewsCache = {};     // videoId -> views
  var publishedCache = {}; // videoId -> publishedAt(ms)
  var titleCache = {};     // videoId -> YouTubeタイトル
  var _pubBackfillTried = {}; // シート補完でvidを補った投稿の公開日時を取りに行った印(セッション内で1回だけ・ループ防止)
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

  // 合算(導線1のみ・Chami依頼2026-07-31): X凍結→Bluesky退避などで別の短縮URLへ割れた同一作品の
  //   クリックを、この投稿へ束ねる。合算した短縮URL群のうち「最新の1本」を投稿URL欄(veditBsky)の
  //   代表へ昇格させ(＝合算後の短縮URLを投稿URL欄へ置き換えて表示)、残りはクリック加算用に保持する。
  //   ・addMergeRow_ =「合算」ボタンで足す入力欄(短縮ボタン付き)。保存すると最新の1本が投稿URL欄へ。
  //   ・addHistRow_  = 再オープン時、既に合算済み(過去)の短縮URLを読み取り専用で並べる(✕で外せる)。
  function addMergeRow_(url) {
    var list = $('veditMergeList'); if (!list) return;
    var row = document.createElement('div');
    row.className = 'vedit-merge-row vedit-bsky-row';
    var inp = document.createElement('input');
    inp.type = 'url'; inp.className = 'vedit-merge-url'; inp.setAttribute('inputmode', 'url');
    inp.autocomplete = 'off'; inp.placeholder = '合算したい短縮URL(導線1)→保存で投稿URL欄へ';
    inp.value = url || '';
    var bShort = document.createElement('button');
    bShort.type = 'button'; bShort.className = 'vedit-copy vedit-copy-fit vedit-merge-short'; bShort.textContent = '短縮';
    var bDel = document.createElement('button');
    bDel.type = 'button'; bDel.className = 'vedit-copy vedit-copy-fit vedit-merge-del'; bDel.textContent = '✕';
    bDel.title = 'この合算URLを外す';
    row.appendChild(inp); row.appendChild(bShort); row.appendChild(bDel);
    list.appendChild(row);
    // 短縮: 長いURLを自前ドメインの計測用短縮URL(codeOf解決可＝クリック加算の対象)へ差し替える。
    bShort.addEventListener('click', function () {
      var v = (inp.value || '').trim();
      if (!/^https?:\/\//.test(v)) { showModalErr_('先に合算したいURLを入れてください'); return; }
      if (typeof window.Go5MakeShort !== 'function') { showModalErr_('短縮機能が未読み込みです。🦋投稿タブを一度開いてから再度お試しください。'); return; }
      var errEl = $('veditError'); if (errEl) errEl.hidden = true;
      var orig = bShort.textContent; bShort.disabled = true; bShort.textContent = '生成中…';
      window.Go5MakeShort(v).then(function (res) {
        var short = (res && res.shortUrl) || (res && res.shareUrl) || ''; // 計測キー(自前ドメイン)を優先＝codeOf解決可
        if (!short) { showModalErr_('短縮に失敗しました。(短縮ワーカーに接続できませんでした)'); return; }
        inp.value = short;
      }).catch(function () { showModalErr_('短縮に失敗しました。'); })
        .then(function () { bShort.disabled = false; bShort.textContent = orig; });
    });
    bDel.addEventListener('click', function () { if (row.parentNode) row.parentNode.removeChild(row); });
    return inp;
  }
  function addHistRow_(url) {
    var list = $('veditMergeList'); if (!list) return;
    var v = (url || '').trim(); if (!v) return;
    var row = document.createElement('div');
    row.className = 'vedit-merge-row vedit-bsky-row vedit-merge-histrow';
    var c = codeOf(v);
    var cl = (c && (c in clicksCache)) ? clicksCache[c] : null;
    var span = document.createElement('span');
    span.className = 'vedit-merge-hist-url';
    span.setAttribute('data-url', v);
    span.innerHTML = '合算元：<code class="vgen-url">' + esc(v) + '</code>' +
      (cl != null ? ' <span class="vmerge-clicks">(クリック ' + num(cl) + ')</span>'
                  : (c ? ' <span class="vmerge-clicks" style="opacity:.6;">(取得待ち)</span>' : ' <span class="vmerge-clicks" style="opacity:.6;">(計測コード無し)</span>'));
    var bDel = document.createElement('button');
    bDel.type = 'button'; bDel.className = 'vedit-copy vedit-copy-fit vedit-merge-del'; bDel.textContent = '✕';
    bDel.title = 'この合算を外す';
    row.appendChild(span); row.appendChild(bDel);
    list.appendChild(row);
    bDel.addEventListener('click', function () { if (row.parentNode) row.parentNode.removeChild(row); });
  }
  function setMergeRows_(urls) {
    var list = $('veditMergeList'); if (!list) return;
    list.innerHTML = '';
    (Array.isArray(urls) ? urls : []).forEach(function (u) { if (u) addHistRow_(u); });
  }
  // 現在のモーダルDOMから {primary: 合算後の代表(最新の短縮URL), mergeUrls: 残り(過去)} を作る。
  //   並び＝過去(hist・読み取り専用)→現primary(投稿URL欄)→今回追加(staging)。最後(＝最新)を代表にする。
  //   保存→再オープンでも並びは同型なので代表が入れ替わらない(安定)。
  function resolveMerge_() {
    var boxEl = $('veditBsky');
    var box = (boxEl && boxEl.value || '').trim();
    var hist = [], staged = [], list = $('veditMergeList');
    if (list) {
      list.querySelectorAll('.vedit-merge-hist-url').forEach(function (el) { var v = (el.getAttribute('data-url') || '').trim(); if (v) hist.push(v); });
      list.querySelectorAll('.vedit-merge-url').forEach(function (inp) { var v = (inp.value || '').trim(); if (v) staged.push(v); });
    }
    var all = [];
    hist.concat([box]).concat(staged).forEach(function (u) { var v = (u || '').trim(); if (v && all.indexOf(v) < 0) all.push(v); });
    return { primary: all.length ? all[all.length - 1] : '', mergeUrls: all.slice(0, -1) };
  }

  function injectModal_() {
    if ($('veditOverlay')) return;
    var d = document.createElement('div');
    d.id = 'veditOverlay';
    d.className = 'vedit-overlay';
    d.hidden = true;
    d.innerHTML =
      '<div class="vedit-modal">' +
        '<button id="veditClose" type="button" class="vedit-close" aria-label="閉じる" title="閉じる">✕</button>' +
        '<p class="vedit-title" id="veditTitle">URL を編集</p>' +
        '<p class="vedit-error" id="veditError" hidden></p>' +
        '<label class="vedit-field">YouTube URL' +
          '<div class="vedit-bsky-row">' +
            '<input id="veditYt" type="url" inputmode="url" autocomplete="off" placeholder="https://youtu.be/…(省略可)">' +
            '<button id="veditYtPaste" type="button" class="vedit-copy">貼り付け</button>' +
          '</div>' +
        '</label>' +
        '<div class="vedit-plat">' +
          '<label class="vedit-plat-opt"><span>X</span><input type="radio" name="veditPlat" id="veditPlatX" value="x"></label>' +
          '<label class="vedit-plat-opt"><span>Bsky</span><input type="radio" name="veditPlat" id="veditPlatBsky" value="bsky"></label>' +
          '<span class="vedit-plat-cap">投稿URL(計測用の短縮URL)</span>' +
        '</div>' +
        '<label class="vedit-field vedit-field-plat">' +
          '<div class="vedit-bsky-row">' +
            '<input id="veditBsky" type="url" inputmode="url" autocomplete="off" placeholder="https://x.com/… または短縮URL(省略可)">' +
            '<button id="veditBskyCopy" type="button" class="vedit-copy vedit-copy-fit">コピー</button>' +
            '<button id="veditMergeAdd" type="button" class="vedit-copy vedit-copy-fit" title="X凍結→Bluesky退避などで別の短縮URLに割れた同一作品のクリックを、この投稿へ合算する(導線1のみ)">合算</button>' +
          '</div>' +
          '<div id="veditMergeList" class="vedit-merge-list"></div>' +
        '</label>' +
        '<div id="veditGenResult" class="vedit-gen-result" hidden></div>' +
        '<label class="vedit-field">作品URL(DMM/FANZAの商品ページURL)' +
          '<div class="vedit-bsky-row">' +
            '<input id="veditWork" type="url" inputmode="url" autocomplete="off" placeholder="https://www.dmm.co.jp/…(省略可)">' +
            '<button id="veditWorkCopy" type="button" class="vedit-copy vedit-copy-fit">コピー</button>' +
          '</div>' +
        '</label>' +
        '<label class="vedit-field">作品クリック計測用の短縮URL(投稿→FANZA・導線2)' +
          '<div class="vedit-bsky-row">' +
            '<input id="veditWorkShort" type="url" inputmode="url" autocomplete="off" placeholder="投稿すると自動で入ります・空なら「自動生成」で作成">' +
            '<button id="veditWorkShortGen" type="button" class="vedit-copy vedit-copy-fit">自動生成</button>' +
          '</div>' +
          '<span class="vedit-hint" style="font-size:11px;color:var(--sub);">この短縮URLのクリックが作品クリック数(ピンクの矢印)として集計されます。空だと表示されません。</span>' +
        '</label>' +
        '<div class="vedit-attrs">' +
          '<div class="vedit-attrs-title">カテゴリ(複数選択可・キャラ無し＝オリジナル)</div>' +
          attrDefs_().map(function (a) {
            return '<label class="vedit-attr"><input id="veditAttr_' + a.key + '" type="checkbox"><span class="vatt" style="color:' + esc(a.color) + ';border-color:' + esc(a.color) + ';">' + esc(a.label) + '</span></label>';
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
    $('veditClose').addEventListener('click', closeModal_); // ★右上の✕で閉じる(Chami依頼2026-07-30)
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
    // 合算: 押すたびに投稿URL欄の下へ空の合算入力欄を1つ追加する。(Chami依頼2026-07-31)
    $('veditMergeAdd').addEventListener('click', function () {
      var inp = addMergeRow_('');
      if (inp) inp.focus();
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
      attrDefs_().forEach(function (a) { var el = $('veditAttr_' + a.key); attrs[a.key] = !!(el && el.checked); });
      var wsEl = $('veditWorkState');
      var platEl = $('veditPlatBsky');
      var _mres = resolveMerge_(); // 合算後の代表(最新)を投稿URL欄へ昇格・残りはクリック加算用に保持
      cb(
        ($('veditYt').value || '').trim(),
        _mres.primary, // 投稿URL＝合算後の短縮URL(最新)
        ($('veditWork').value || '').trim(),
        attrs,
        (wsEl && wsEl.value) || '旧作',
        ($('veditWorkShort').value || '').trim(),
        (platEl && platEl.checked) ? 'bsky' : 'x', // 既定=X
        _mres.mergeUrls // 合算URL(導線1のみ・過去の短縮URL群=クリック加算)
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

  function openModal_(title, ytVal, bskyVal, workVal, attrs, workState, onSave, workShortVal, platform, mergeUrls) {
    injectModal_();
    $('veditTitle').textContent = title;
    $('veditYt').value = ytVal || '';
    $('veditBsky').value = bskyVal || '';
    setMergeRows_(mergeUrls); // 合算URL(導線1のみ)を復元
    var plat = (platform === 'bsky') ? 'bsky' : 'x'; // 既定=X(Chami:これから原則X投稿)
    if ($('veditPlatX')) $('veditPlatX').checked = (plat === 'x');
    if ($('veditPlatBsky')) $('veditPlatBsky').checked = (plat === 'bsky');
    $('veditWork').value = workVal || '';
    if ($('veditWorkShort')) $('veditWorkShort').value = workShortVal || '';
    attrs = attrs || {};
    attrDefs_().forEach(function (a) { var el = $('veditAttr_' + a.key); if (el) el.checked = !!attrs[a.key]; });
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
    var g = window.Go5Short;
    var isGo5 = !!(g && g.ourBase && bskyUrl && g.ourBase(bskyUrl));  // 両ドメイン+旧r2を自前と認識
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
    attrDefs_().forEach(function (a) { if (attrs && attrs[a.key]) item[a.key] = true; else delete item[a.key]; });
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
    if (_pendingWorkShort) { item.workShortUrl = _pendingWorkShort; item.workShareUrl = _pendingWorkShare || _pendingWorkShort; delete item.workShortNone; }
    else if (typedVal) { item.workShortUrl = typedVal; item.workShareUrl = typedVal; delete item.workShortNone; }
    else {
      // ★元々入っていた作品短縮URLを消して空で保存した=意図的な削除。印(workShortNone)を残して
      //   自動生成(autoMeasureWorkShort_)の再充填を止める。これをしないと導線2導入前の履歴に
      //   誤って入った短縮URLを消しても、作品URLから自動再生成されて復活する(Chami報告2026-07-29)。
      if (item.workShortUrl || item.workShareUrl) item.workShortNone = true;
      delete item.workShortUrl; delete item.workShareUrl;
    }
  }
  // 合算URL(導線1のみ)を item へ反映。空配列=合算なし=印を消す。
  function applyMergeUrls_(item, mergeUrls) {
    if (Array.isArray(mergeUrls) && mergeUrls.length) item.mergeUrls = mergeUrls;
    else delete item.mergeUrls;
  }
  function saveEdit_(k, it, ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal, platform, mergeUrls) {
    var plat = (platform === 'x' || platform === 'bsky') ? platform : null;
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
        if (plat) manual[i].platform = plat; // X↗/Bsky↗の手動指定(既定X)
        if (_pendingShort) { manual[i].shortUrl = _pendingShort; delete manual[i].postUrl; } // 計測キー(r2)
        if (_pendingShare) manual[i].shareUrl = _pendingShare; // 表示用(da.gd)
        applyWorkShort_(manual[i], workShortVal); // 作品クリック計測URL(導線2)
        applyMergeUrls_(manual[i], mergeUrls); // 合算URL(導線1のみ)
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
        if (plat) hist[j].platform = plat; // X↗/Bsky↗の手動指定(既定X)
        if (_pendingShort) { hist[j].shortUrl = _pendingShort; delete hist[j].postUrl; } // 計測キー(r2)
        if (_pendingShare) hist[j].shareUrl = _pendingShare; // 表示用(da.gd)
        applyWorkShort_(hist[j], workShortVal); // 作品クリック計測URL(導線2)
        applyMergeUrls_(hist[j], mergeUrls); // 合算URL(導線1のみ)
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
    if (saved) autoMeasureWorkShort_(saved, function () { saveArr(saved.manual ? manualKey() : histKey(), saved.manual ? manual : hist); pushItemToGas_(saved); });
    refresh();
  }

  // シート由来行(_fromSheet)の編集をGASへ即時upsertする。成功後にUIを更新、失敗はモーダルにエラーを出す。
  // localStorageへは書き戻さない(INC-112防壁を維持)。
  function saveEditFromSheet_(k, it, ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal, platform, mergeUrls) {
    var plat = (platform === 'x' || platform === 'bsky') ? platform : null;
    var gasUrl = '';
    try { gasUrl = (localStorage.getItem('bsky_gas_url') || '').trim(); } catch (e) {}
    if (!gasUrl) { showModalErr_('GAS URLが設定されていません。'); return; }
    if (!it.videoId) { showModalErr_('この行にはvideoIdがありません。保存できません。'); return; }
    var editCore = window.HistMerge;
    if (workUrl && (!editCore || !editCore.workCidFromUrl || !editCore.workCidFromUrl(workUrl))) {
      showModalErr_('作品URLから作品ID(cid)を読み取れません。DMM/FANZAの商品ページURLを確認してください。');
      return;
    }

    // 送信用コピーに編集内容を反映。キャッシュ(_sheetExtraCache)は成功後に更新する。
    var edited = {};
    for (var p in it) if (Object.prototype.hasOwnProperty.call(it, p)) edited[p] = it[p];
    if (ytUrl) edited.ytUrl = ytUrl; else delete edited.ytUrl;
    saveBskyToItem_(edited, bskyUrl);
    if (workUrl) edited.workUrl = workUrl; else delete edited.workUrl;
    applyAttrs_(edited, attrs);
    edited.workState = workState || '旧作';
    if (plat) edited.platform = plat; // X↗/Bsky↗の手動指定(既定X)
    if (_pendingShort) { edited.shortUrl = _pendingShort; delete edited.postUrl; }
    if (_pendingShare) edited.shareUrl = _pendingShare;
    applyWorkShort_(edited, workShortVal);
    applyMergeUrls_(edited, mergeUrls); // 合算URL(導線1のみ・クライアント表示用。GAS列は持たない)

    var payload = {
      op: 'upsert',
      channel: chForItem_(edited),
      videoId: edited.videoId,
      title: edited.title || '',
      postUri: edited.postUri || '',
      postUrl: edited.postUrl || '',
      workUrl: edited.workUrl || '',
      shortUrl: edited.shortUrl || '',
      shareUrl: edited.shareUrl || '',
      youtube_url: edited.ytUrl || '',
      work_short_url: edited.workShortUrl || '',
      work_short_clear: !!edited.workShortNone // ★意図的クリア=GAS側でセルを空に確定(putIfの空スキップを越える)
    };
    attrDefs_().forEach(function (a) { payload[a.key] = !!edited[a.key]; });
    payload.workState = edited.workState || '旧作';
    if (edited.platform === 'x' || edited.platform === 'bsky') payload.platform = edited.platform; // 投稿先(X/Bsky)列

    var curAcct = acct();
    // 合算URL(導線1)を永続ストアへ=保持patch(反映後に破棄)が消えても維持する(Chami依頼2026-07-31)
    setMergeForVideo_(curAcct, edited.videoId, Array.isArray(edited.mergeUrls) ? edited.mergeUrls : []);

    // ★Chami指示2026-07-28: 保存を押したら編集モーダルは即閉じ、UIは楽観更新。GAS反映は裏でやる。
    //   旧実装はGASへupsert→履歴再読込での確認が通るまでモーダルを閉じず(最大3回リトライ)、
    //   確認が遅い/取れないと「保存しても反映されない」ように見えていた(Chami報告2026-07-28)。
    //   シート由来行はlocalStorageへ書き戻さない(INC-112防壁)。表示専用のpatchをvideoId別に登録し、
    //   以後どのタイミングの再取得でもdisplayItems_が上塗りする=「一瞬反映→消失」の再発を封じる。
    (function registerPendingEdit_() {
      var patch = {};
      ['ytUrl', 'workUrl', 'workState', 'shortUrl', 'shareUrl', 'postUrl', 'postUri', 'workShortUrl', 'platform']
        .forEach(function (f) { patch[f] = edited[f] || ''; });
      attrDefs_().forEach(function (a) { patch[a.key] = !!edited[a.key]; });
      patch.workShortNone = !!edited.workShortNone; // ★意図的クリアの印はboolで保持=リロード跨ぎでも復活させない(#5系)
      patch.mergeUrls = Array.isArray(edited.mergeUrls) ? edited.mergeUrls : []; // 合算URL(導線1のみ・表示専用オーバレイ)
      (_pendingSheetEdits[curAcct] = _pendingSheetEdits[curAcct] || {})[String(edited.videoId)] = patch;
      savePend_(curAcct, _pendingSheetEdits[curAcct]); // ★リロードを越えて保持(#5根治)
    })();
    closeModal_();
    refresh();
    if (ytUrl) pokeSnapshotNow_();

    // ★導線2(作品クリック計測URL)に手入力された非r2リンク(作品ページURL/アフィリンク/da.gd等)を
    //   正規の自前r2短縮へ変換してシートへ再upsert=計測可能にする(Chami指示2026-08-01「正規の短縮URLに変更しといて」)。
    //   autoMeasureWorkShort_ 内で 空/既にr2/意図的クリア(workShortNone) は無変換=冪等。
    //   ※作品URLからの自動発行はしない方針(2026-07-30)は維持=空欄は空欄のまま(内部ガードでno-op)。
    //   シート由来行はlocalStorageへ書き戻さない(INC-112防壁)ので、保持patch(_pendingSheetEdits)へ反映する。
    autoMeasureWorkShort_(edited, function () {
      var pm = _pendingSheetEdits[curAcct]; var pv = pm && pm[String(edited.videoId)];
      if (pv) { pv.workShortUrl = edited.workShortUrl || ''; pv.workShareUrl = edited.workShareUrl || ''; savePend_(curAcct, pm); }
      try { pushItemToGas_(edited); } catch (e) {}
    });

    // ── ここから裏方(非ブロッキング): GASへupsert→履歴再読込で反映を確認。失敗時だけ静かに通知する。──
    var finished = false, verifyStarted = false;
    function bgFail_(message) {
      if (finished) return;
      finished = true;
      try { setStatus('⚠ ' + message, true); } catch (e) {}
    }
    function bgSuccess_(sheetItems) {
      if (finished) return;
      finished = true;
      // シート正本を読み直せたらキャッシュを権威データで上書きして再描画(楽観更新のズレを正す)。
      var c = _sheetExtraCache[curAcct];
      var merged = (window.HistMerge && window.HistMerge.mergeSheetExtras)
        ? window.HistMerge.mergeSheetExtras(allItems(), sheetItems || []) : null;
      if (c && merged) { c.items = merged; c.at = Date.now(); refresh(); }
      // シートが編集を反映できた=以後シートが権威。この行の保持を落とす(在メモリ＋localStorage)。
      try { var pm = _pendingSheetEdits[curAcct]; if (pm && pm[String(payload.videoId)]) { delete pm[String(payload.videoId)]; savePend_(curAcct, pm); } } catch (e) {}
    }
    function verifyFromSheet_() {
      if (verifyStarted || finished) return;
      verifyStarted = true;
      var tries = 0;
      function check_() {
        tries++;
        jsonp_(gasUrl, { action: 'history', channel: curAcct, limit: 300 }, function (res) {
          if (finished) return;
          if (!res || !res.ok || !Array.isArray(res.items)) {
            if (tries < 3) { setTimeout(check_, 1200 * tries); return; }
            bgFail_('スプレッドシートへの保存を確認できませんでした。通信を確認して、もう一度編集→保存してください。');
            return;
          }
          var expected = { videoId: payload.videoId, youtubeUrl: payload.youtube_url, workUrl: payload.workUrl, workState: payload.workState };
          if (window.HistMerge && window.HistMerge.historyHasEdit && window.HistMerge.historyHasEdit(res.items, expected)) {
            bgSuccess_(res.items);
            return;
          }
          if (tries < 3) { setTimeout(check_, 1200 * tries); return; }
          bgFail_('スプレッドシートへの反映を確認できませんでした。もう一度編集→保存してください。');
        });
      }
      check_();
    }
    try {
      // GASのPOST応答はCORSで本文を読めない。no-corsで確実に送信し、成否は履歴再読込で判定する。
      fetch(gasUrl, { method: 'POST', mode: 'no-cors', body: JSON.stringify(payload) })
        .then(verifyFromSheet_, verifyFromSheet_);
      setTimeout(verifyFromSheet_, 3000);
    } catch (e) {
      verifyFromSheet_();
    }
  }

  // 作品クリック計測URL(導線2)の自動確定。手入力が r2 でない(作品ページURL/アフィリンク/da.gd等)場合、
  //   アフィリンク化→r2短縮して workShortUrl を計測可能なキーに整える。既に r2 なら何もしない(冪等)。
  function autoMeasureWorkShort_(it, persist) {
    try {
      if (it && it.workShortNone) return; // ★ユーザーが意図的に消した行は自動生成で復活させない(Chami 2026-07-29)
      var go5 = window.Go5Short || {};
      function isR2(u) { return !!(go5.ourBase && go5.ourBase(u)); }  // 両ドメイン+旧r2を自前と認識
      var cur = (it && it.workShortUrl) || '';
      if (!it || !go5.ourBase || typeof window.Go5MakeShort !== 'function') return;
      // ★作品URLからの自動発行はしない(Chami依頼2026-07-30)。導線2(作品クリック計測URL)の短縮は
      //   「自動生成」ボタン(_pendingWorkShort)か投稿時のフローだけが起こす。編集保存では勝手に発行しない。
      //   ここでやるのは、既に導線2欄へ入っている非r2リンクを計測キー(r2)へ正規化することだけ。
      //   ★2026-07-29に入れた it.workUrl フォールバックが「画像だけ直して保存→短縮URLが勝手に湧く」の原因。
      //   空欄は空欄のまま残す(作品URLへフォールバックしない)。
      if (!/^https?:\/\//.test(cur) || isR2(cur)) return; // 空 / 既に自前短縮＝何もしない
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

  // 投稿完了時に、作品クリック計測URL(導線2)を作品URLから"一発で発行"する(Chami依頼2026-07-30)。
  //   ★これは comment(autoMeasureWorkShort_:1430)が許可する「投稿時のフロー」＝作品URLからの新規発行を
  //   意図的に行う経路。編集保存用の autoMeasureWorkShort_ は空欄を作品URLへフォールバックしない仕様
  //   (「画像だけ直して保存→短縮URLが勝手に湧く」対策・2026-07-29)なので、投稿完了経路がそれを呼ぶと
  //   workShortUrl が空のままシートへ載り、サブ端末で「作品クリックの短縮URLが空」になっていた(Chami再発
  //   指摘2026-08-03②)。完了時は"新規発行してよい"のでこちらを使う。既に有れば触らない(冪等)。
  function mintWorkShortAtPost_(it, persist) {
    try {
      if (!it || it.workShortNone) return;          // 意図的に消した行は復活させない
      if (it.workShortUrl) return;                  // 既に有れば触らない(冪等)
      var wurl = (it.workUrl || '').trim();
      if (!/^https?:\/\//.test(wurl)) return;       // 作品URLが無ければ発行できない
      var go5 = window.Go5Short || {};
      function isR2(u) { return !!(go5.ourBase && go5.ourBase(u)); }
      if (typeof window.Go5MakeShort !== 'function') return;
      var toShorten = wurl;
      // FANZA/DMMの作品ページURL(アフィリンクでない)なら、先にアフィリンク化してから短縮する。
      if (window.buildAffiliateLink && /(^|\.)dmm\.co\.jp|(^|\.)dlsite|fanza/.test(wurl) && !/al\.(fanza|dmm)/.test(wurl)) {
        var afId = ''; try { afId = localStorage.getItem('fanza_af_id') || ''; } catch (e) {}
        var aff = window.buildAffiliateLink(wurl, afId);
        if (aff && aff.ok && aff.link) toShorten = aff.link;
      }
      window.Go5MakeShort(toShorten).then(function (res) {
        if (!(res && res.shortUrl && isR2(res.shortUrl))) return;
        it.workShortUrl = res.shortUrl; it.workShareUrl = res.shareUrl || res.shortUrl;
        if (typeof persist === 'function') persist();
        if (acct() === chForItem_(it)) refresh(); // 作品クリック(ピンク矢印)がこの再描画で出る
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
      hashtags: titleHashtags_(it.title), // ハッシュタグ列＝題名から抽出(定番タグ依存を廃止・Chami依頼2026-07-31)。
                                          //   ドラフト投稿完了経路がハッシュタグを送っておらずAH列が空になる不整合を塞ぐ。
      youtube_url: it.ytUrl || '',   // ★YouTube動画URL列へ反映=サーバーがvidを認識→日別記録(デルタ)開始。
                                     //   これが空だとシートにvidが無く、スナップされず「記録待ち」が永久固定になる(根治)
      work_short_url: it.workShortUrl || '', // 導線2(作品クリック)の計測URL=作品クリック数の日次スナップ元(GAS 14C)
      work_short_clear: !!it.workShortNone   // ★意図的に消した=空でシートを確定(GAS:1018受信・putIfの空スキップを越える)。
                                             //   これが無いと、導線2導入前の履歴で誤挿入された短縮URLを消して保存しても
                                             //   シート側セルが残り、行が_fromSheet化/📥復元した時に「復活」した(2026-08-01・REQ-811075a64f)。
    };
    attrDefs_().forEach(function (a) { payload[a.key] = !!it[a.key]; }); // カテゴリ列：属性名を明記
    payload.workState = it.workState || '旧作'; // 作品状態列
    if (it.platform === 'x' || it.platform === 'bsky') payload.platform = it.platform; // 投稿先(X/Bsky)列
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

  // ── 過去分プレビュー取り込み(Drive参照) ──────────────────────────────────
  //   Chami依頼(REQ-0bfd8d7207 / 2回目=再発): 7/30以前など、プレビュー画像がGoogleドライブへ
  //   保存され始める前の投稿履歴について、Driveの[題名]フォルダの「題名_プレビュー.*」を探して
  //   1ページ目に取り込む。無ければ「無かった」でスキップ(Chami「ないものはなかったでOK」)。
  //   Worker側は read-only=既存物に一切触れない。usedImgSave(pKey, [preview]+既存, prev=1) で先頭挿入。
  function runDrivePreviewBackfill_(items, btn) {
    if (!window.Go5Drive || !window.Go5Drive.fetchPreview) { alert('Drive取込が未設定です。(drive_worker_url を確認してください)'); return; }
    var cand = window.Go5Cand;
    if (!cand || !cand.usedImgs || !cand.usedImgSave) { alert('画像ストア未対応の環境です。'); return; }
    var ch = acct(); // 現在表示中のチャンネル
    // 対象=題名があり、まだプレビュー(先頭prev枚)を持っていない履歴だけ。
    var targets = (items || []).filter(function (it) {
      if (!it || !it.title) return false;
      var pKey = it.videoId || itemKey(it);
      var prevN = cand.usedPrevCount ? (cand.usedPrevCount(pKey) || 0) : 0;
      return prevN === 0;
    });
    if (!targets.length) { alert('取り込む対象がありません。(このチャンネルの履歴は全てプレビュー済み、または題名が空です)'); return; }
    if (!window.confirm('このチャンネルの ' + targets.length + ' 件について、Googleドライブから過去分のプレビュー画像を探して取り込みます。よろしいですか？')) return;
    var i = 0, ok = 0, miss = 0, origLabel = btn.textContent;
    btn.disabled = true;
    function step() {
      if (i >= targets.length) {
        btn.disabled = false; btn.textContent = origLabel;
        alert('Drive取込 完了\n挿入: ' + ok + '件 / Driveに無し: ' + miss + '件 / 対象: ' + targets.length + '件');
        try { refresh(); } catch (e) {}
        return;
      }
      var it = targets[i++];
      var pKey = it.videoId || itemKey(it);
      btn.textContent = '取込中… ' + i + '/' + targets.length;
      window.Go5Drive.fetchPreview(ch, it.title).then(function (durl) {
        if (durl) {
          var used = (cand.usedImgs(pKey) || []).slice();
          cand.usedImgSave(pKey, [durl].concat(used), 1); // 先頭1枚=投稿プレビュー(prev=1)
          ok++;
        } else { miss++; }
      }).catch(function () { miss++; }).then(step);
    }
    step();
  }

  // ── render ──────────────────────────────────────────────────────────────
  function render() {
    var list = $('ytClickList');
    var rawItems = displayItems_(); // ローカル＋シート由来の表示専用マージ(書き込み系はallItems()のまま不変)
    var ymap = loadYtMap();
    if (!rawItems.length) {
      // GAS設定済みかつキャッシュ未初期化(=シート取得がまだ終わっていない)→「読み込み中...」を表示。
      // GAS未設定 / 取得失敗(at=-1) / 取得完了(at>=0) のいずれかでは通常の「まだ記録がありません」を表示。
      var _noCache = !_sheetExtraCache[acct()];
      var _emptyMsg = (_noCache && gasUrl_())
        ? '記録シートから読み込み中...'
        : 'まだ投稿の記録がありません。(投稿して短縮URLが出ると、ここに集まります)「➕ 手動で追加」からYouTube動画を直接登録もできます。表示中アカウント：' + esc(acct());
      list.innerHTML = '<p class="hint">' + _emptyMsg + '</p>';
      return;
    }
    var items = sortItems(rawItems, ymap);
    // YouTube公開前(非公開/予約公開)の動画一覧 → vidで引けるマップに(「投稿予定」バッジ表示用)
    var schedMap = {};
    try { loadYtSched_(acct()).forEach(function (y) { if (y && y.vid) schedMap[y.vid] = y; }); } catch (e) {}
    // ★見出し日時は必ず YouTube公開日時(snippet.publishedAt)にする(Chami指示2026-08-05:
    //   「投稿履歴の時刻は動画作成日時ではなくYouTube投稿時間が正」)。ローカル行にYT URLが結線されず
    //   vid が空だと §1651 の実投稿時刻(it.ts=動画作成/投稿完了時刻)へ落ち、"作成日時"が見出しに出る
    //   (宵桜艶帖・予約公開＝完了8:31／YT公開12:20 のズレで顕在化)。記録シートにある youtubeUrl を
    //   videoId/postUri/shortUrl で引いて vid を補い(表示専用・非破壊)、公開日時を取り直す。
    var _rawYt = { vid: {}, uri: {}, sh: {} };
    try {
      loadSheetRaw_(acct()).forEach(function (r) {
        var y = String((r && r.youtubeUrl) || '').trim(); if (!y) return;
        if (r.videoId) _rawYt.vid[String(r.videoId)] = y;
        if (r.postUri) _rawYt.uri[String(r.postUri)] = y;
        if (r.shortUrl) _rawYt.sh[String(r.shortUrl)] = y;
      });
    } catch (e) {}
    function sheetYtFor_(it) {
      return (it.videoId && _rawYt.vid[String(it.videoId)]) ||
             (it.postUri && _rawYt.uri[String(it.postUri)]) ||
             (it.shortUrl && _rawYt.sh[String(it.shortUrl)]) || '';
    }
    var _needPub = []; // シートから補ったが公開日時が未取得の vid（この描画の後で1回だけ取りに行く）
    // 被リビルド作品の非表示トグル。(最新の投稿カードにボタンを設置。ONで被リビルド済みを一覧から除外)
    var hideRemadeKey = 'verify_hide_remade__' + acct();
    var hideRemade = false; try { hideRemade = localStorage.getItem(hideRemadeKey) === '1'; } catch (e) {}
    var visibleItems = hideRemade ? items.filter(function (it) { return !it.remade; }) : items;
    // 非表示トグルは行の枠外(リスト最上部の独立バー)に置く＝先頭カードに重ならない。
    var hideBarHtml = '<div class="vhide-remade-bar">' +
      '<span id="saleStats" class="sale-stats" title="セール会場リンク(大幅割引セール中の同人祭ページ)のクリック数。累計はr2計測・今日/昨日/週は日次スナップショット"><img class="emico emico-sale" src="assets/icons/ic-sale-gold.png" alt=""> セール会場 …</span>' +
      // 計測ヘルス(B-3): 正常時は目立たせない。異常時だけ赤字。追加通信はしない(既存取得の結果を映すだけ)
      '<span id="measHealth" class="meas-health" title="計測3経路の生死。短縮URL=クリック数/記録GAS=今日昨日週の日別記録/YouTube=再生数。「応答なし」の時、その数字は古い値です">' + healthHtml_() + '</span>' +
      histColsCtlHtml_() + // 列数セレクタ(PCのみCSSで表示)
      '<button id="drivePrevBackfill" type="button" class="vhide-remade-btn" title="過去の投稿履歴について、Googleドライブに保存済みの「題名_プレビュー」画像を探して1ページ目に取り込みます(このチャンネル分・既にプレビューがある履歴は対象外)">🔁 Drive→過去分プレビュー取込</button>' +
      '<button id="hideRemadeBtn" type="button" class="vhide-remade-btn" title="被リビルド作品を一覧から隠す/戻す">' + (hideRemade ? '👁 被リビルドを表示' : '被リビルドを非表示') + '</button></div>';
    list.innerHTML = hideBarHtml + visibleItems.map(function (it, idx) {
      var k = itemKey(it);
      var yt = ymap[k] || it.ytUrl || '';
      var vid = ytIdOf(yt);
      // ローカル行にYT URLが結線されていない時だけ、記録シートの youtubeUrl で vid を補う(見出し日時を
      //   YouTube公開日時にするため)。公開日時が未取得なら _needPub に積んで描画後に取り直す。
      if (!vid) {
        var _syt = sheetYtFor_(it);
        if (_syt) {
          yt = _syt; vid = ytIdOf(_syt);
          if (vid && apiKey() && !(vid in publishedCache) && !_pubBackfillTried[vid]) _needPub.push(vid);
        }
      }
      // 【供給一本化 2026-08-03】導線1/導線2のクリックは postClicks_ で計算(ランキングと同一の1関数)。
      //   合算URLの加算・GAS日次デルタの累計下限・リビルド結合まで内包する(旧・この場のインライン計算を
      //   関数へ寄せた=履歴とランキングで計算式が二度と割れないようにする)。_dl は下の総再生数下限で再利用。
      var _pc = postClicks_(it, vid);
      var code = _pc.code, wcode = _pc.wcode;
      var wclicks = _pc.c2;
      var clicksTotal = _pc.c1;
      var _dl = vid ? deltaCache[vid] : null;
      // 動画で実際に使った画像は履歴単位で読む。候補タブの全画像(ref)とは分離する。
      // 旧データだけは先頭1枚を互換表示するが、2枚目以降の候補画像は絶対に投稿履歴へ混ぜない。
      var rImgCid = it.workUrl ? workCidOf_(it.workUrl) : '';
      var pKey = it.videoId || k;
      var legacyRefImgs = (rImgCid && window.Go5Cand && window.Go5Cand.refImgs) ? (window.Go5Cand.refImgs(rImgCid) || []) : [];
      var storedUsedImgs = (window.Go5Cand && window.Go5Cand.usedImgs) ? (window.Go5Cand.usedImgs(pKey) || []) : [];
      var usedImgArr = (window.HistMerge && window.HistMerge.historyUsedImages)
        ? window.HistMerge.historyUsedImages(storedUsedImgs, legacyRefImgs, !!(window.Go5Cand && window.Go5Cand.usedImgKnown && window.Go5Cand.usedImgKnown(pKey)))
        : (storedUsedImgs.length ? storedUsedImgs : legacyRefImgs.slice(0, 1));
      // ★投稿画像(編集モーダルで添付する用途'post')も履歴カードのサムネ候補に入れる。
      //   動画で使った画像/Bluesky画像が両方無い作品(投稿画像だけ添付した作品)は、モーダルにデータが在るのに
      //   カードが空表示になっていた(Chami報告2026-07-30・添付=1532357129657385031)。用途'post'の1枚目を最後の砦にする。
      var postImgArr = (window.Go5Cand && window.Go5Cand.postImgs) ? (window.Go5Cand.postImgs(pKey) || []) : [];
      var refThumb = usedImgArr[0] || (rImgCid && window.Go5Cand && window.Go5Cand.bskyImg ? window.Go5Cand.bskyImg(rImgCid) : '') || postImgArr[0] || '';
      var views = vid && (vid in viewsCache) ? viewsCache[vid] : null;
      // ★総再生数(top ▶)も導線1/導線2のクリック累計と同じく、GASの日次デルタ(今日/昨日/週)を下限に取る。
      //   YouTube再生数はAPI未取得/クォータ切れ/紐付け直後だと0や未取得のまま張り付き、下段の「今日▶120/週▶120」
      //   と食い違う(=総再生数0表示。Chami報告2026-07-30)。週デルタは all-time 累計に必ず内包されるので
      //   max(週,今日,昨日)を下限に置けば「累計 ≥ 週」を守りつつ、取得済みの実累計が大きければそちらを活かす。
      if (_dl) {
        var vCum = (_dl.cv != null) ? _dl.cv : Math.max(_dl.wv || 0, _dl.tv || 0, _dl.yv || 0);
        if (vCum > 0) views = Math.max(views || 0, vCum);
      }
      var pub = vid && (vid in publishedCache) ? publishedCache[vid] : null;
      var sched = (pub == null) && vid && schedMap[vid]; // 公開済みが観測されたら予約表示はしない
      // ★予約公開(sched)/カレンダー予定(plannedAt)の「予定時刻」が既に過ぎていたら、YouTube公開が
      //   まだ観測できていなくても実際には投稿済み＝その予定時刻から計測を始める(Chami依頼2026-08-05
      //   「ドラフトのまま投稿してるのに投稿予定になる。この場合も18:30から計測スタートにして」)。
      //   schedMap.publishAtは取得時に未来だった値だけを持つ(§2643)＝リロードせずに時刻が過ぎると
      //   「投稿予定」に張り付き、日別デルタも– のままだった。予定時刻(publishAt優先→plannedAt)を実効の
      //   投稿時刻として、過ぎていれば投稿済み表示＋計測開始に切り替える。予定時刻が未来なら従来どおり投稿予定。
      var plannedMs = it.plannedAt ? (Date.parse(String(it.plannedAt).replace(' ', 'T')) || NaN) : NaN;
      var schedMs = (sched && sched.publishAt) ? Number(sched.publishAt) : plannedMs; // 予定時刻(予約公開 or カレンダー予定)
      var schedPassed = !isNaN(schedMs) && schedMs <= Date.now(); // 予定時刻を過ぎた=実際には投稿済み
      var stillScheduled = (!!sched || !!it.plannedAt) && !schedPassed; // 予定時刻がまだ=本当に投稿予定
      var prePostFlag = !!(sched && !schedPassed); // 計測窓の抑止は「本当にまだ投稿前」の時だけ
      var deltaTs = it.ts || (schedPassed ? schedMs : 0); // 実投稿時刻が無い予定過ぎ投稿は予定時刻を計測起点にする
      // YouTube動画が紐付いていない投稿(Bluesky単体投稿等)は、YouTube公開日時が原理的に存在しない。
      //   sendSync_()と同じ考え方(実投稿時刻(ts)を正とする)でit.tsにフォールバックする＝
      //   「投稿日時不明」のまま放置しない。(シート復元直後のvid無し投稿で顕在化)
      // カレンダー公開枠の予定時刻(予約投稿)。YouTube側のpublishAtが観測される前に「投稿予定 時刻」を出す下限。
      var plannedHtml = (pub == null && it.plannedAt && stillScheduled)
        ? ('<b>' + fmtPostDate(it.plannedAt) + '</b> <span class="vtag vtag-scheduled">投稿予定</span>') : '';
      var dateHtml = (sched && stillScheduled)
        ? ((sched.publishAt ? '<b>' + fmtPostDate(sched.publishAt) + '</b> ' : '') + '<span class="vtag vtag-scheduled">投稿予定</span>')
        : (pub != null
          ? '<b>' + fmtPostDate(pub) + '</b>'
          : (plannedHtml
            ? plannedHtml
            // 予定時刻を過ぎている(schedPassed)=実際には投稿済み。予定時刻を投稿時刻として太字表示。
            : (schedPassed ? '<b class="vdate-tsonly">' + fmtPostDate(schedMs) + '</b>'
              // 予約公開の予定時刻を過ぎてもYouTube側の公開日時が観測できない時、vidが在るというだけで「…」に張り付いていた
              //   (宵桜艶帖の1件・Chami報告2026-08-05)。上の§1637の設計意図どおり実投稿時刻(ts)を先に正とし、tsも無い時だけ「…」を出す。
              : (it.ts ? '<b class="vdate-tsonly">' + fmtPostDate(it.ts) + '</b>'
                : (vid ? '<b class="vdate-pending">…</b>' : '<b class="vdate-unknown">投稿日時不明</b>')))));
      var rawTitle = (vid && titleCache[vid]) || it.title || (it.manual ? '(手動追加)' : '(無題)');
      var dispTitle = esc(stripCommonTags(rawTitle));
      var tagWarn = !it.manual && vid && (vid in titleCache) && missingCommonTags(rawTitle);
      var titleHtml = tagWarn
        ? '<span style="color:#dc465a;font-weight:700;">' + dispTitle + ' ⚠タグ忘れあり</span>'
        : dispTitle;
      var bskyHref = it.shareUrl || it.shortUrl || it.postUrl || ''; // 表示リンクは共有(da.gd)優先。計測は下のcode(=r2)で行う
      // 属性バッジ(作品名の下に改行して表示。作品状態は価格行の左に別途表示)
      var tagsHtml = attrDefs_().map(function (a) { return it[a.key] ? '<span class="vtag" style="color:' + esc(a.color) + ';border-color:' + esc(a.color) + ';font-weight:700;">' + esc(a.label) + '</span>' : ''; }).join('');
      // 作り直し系バッジ：rebuild=この動画自体がリビルド版 / remade=この投稿は被リビルド(=リビルド版に取って代わられた)
      if (it.rebuild) tagsHtml += '<span class="vtag vtag-rebuild">🔁リビルド版</span>';
      if (it.remade) tagsHtml += '<span class="vtag vtag-remade">🔁被リビルド</span>';
      // ★この端末のローカル履歴には無く、記録シートから補った行。編集・削除はGAS経由で正本へ反映する。
      if (it._fromSheet) tagsHtml += '<span class="vtag vtag-sheet" title="この端末にはこの記録が無く、記録シートの内容を表示して補っています(編集・削除は記録シートへ反映)">☁️シート由来</span>';
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
          ((wcode || it.workShortUrl) ? '<span title="作品リンククリック数(投稿→FANZA・導線2)。計測URLを入れると投稿前でも0で表示。数値は短縮URL(r2)確定後に集計"><img class="emico emico-cursor" src="assets/icons/ic-cursor-pink.png" alt="作品クリック"> ' + (wclicks != null ? num(wclicks) : (wcode ? '…' : '0')) + '</span>' : '') +
          '<span class="vrow-links">' + // 🛠️編集/Bsky↗/YouTube↗/作品↗ を1グループに＝編集もBskyと同じ段に表示・作品↗だけ改行される事故を防ぐ
            '<button class="vedit-btn" type="button" data-k="' + esc(k) + '">🛠️編集</button>' +
            postLinkHtml_(bskyHref, it) +
            (yt ? '<a class="vlink vlink-yt" href="' + esc(yt) + '" target="_blank" rel="noopener">YouTube↗</a>' : '') +
            (it.workUrl ? '<a class="vlink vlink-work" href="' + esc(it.workUrl) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
            // セール会場(導線3): この投稿に添えたセール案内会場を名前つきで表示(Chami依頼DEF-a57e596842「どの会場を貼ったか出す所がない」)。
            //   投稿時に histAdd が saleName/saleUrl を刻む=以後の投稿で出る。過去投稿は未保存のため出ない。
            (it.saleUrl ? '<a class="vlink vlink-sale" href="' + esc(it.saleUrl) + '" target="_blank" rel="noopener" title="この投稿に添えたセール会場(導線3)">🏮' + esc(it.saleName || 'セール会場') + '↗</a>' : '') +
          '</span>' +
        '</div>' +
        '</div>' + // .vrow-body
        ((it.workUrl || refThumb) ? '<div class="vrow-thumbcol">' +
          (it.workUrl ? '<img class="vrow-thumb" data-fanza-thumb-url="' + esc(it.workUrl) + '" alt="作品サムネ(タップで詳細)" title="タップで作品詳細" loading="lazy" style="display:none;">' : '') +
          (refThumb ? '<img class="vrow-refimg" data-refcid="' + esc(rImgCid) + '" data-usedkey="' + esc(pKey) + '" src="' + esc(refThumb) + '" alt="動画で使った画像(タップで拡大)" title="タップで拡大。Bluesky投稿画像と違えば左右フリックで両方表示" loading="lazy">' : '') +
        '</div>' : '') +
        // footは本文列(vrow-body)の外＝カード全幅の独立行。これで🗑がカードの一番右(画像の真下)まで届く
        '<div class="vrow-foot">' +
          '<span class="vrow-delta"' + (vid ? ' data-delta-vid="' + esc(vid) + '" data-delta-ts="' + (deltaTs || 0) + '"' + ((wcode || it.workShortUrl) ? ' data-delta-haswork="1"' : '') + (prePostFlag ? ' data-delta-prepost="1"' : '') : '') + ' title="日別の増分。(30分毎のサーバー記録から)⚠=記録欠損。(追跡開始前/取得失敗)–は今日投稿の昨日/投稿前/スナップ前">' + (vid ? fmtDelta_(deltaCache[vid], deltaTs, !!(wcode || it.workShortUrl), prePostFlag) : '<span style="opacity:.55;">今日 ▶– 🖱–　(YT未連携=日別記録なし)</span>') + '</span>' +
          '<div class="vrow-actcol">' +
            (!it.remade && it.videoId ? '<button class="vrebuild-from" type="button" data-rbvid="' + esc(it.videoId) + '" title="この投稿をリビルド元にして動画作成タブへ(同一作品ならBluesky投稿を引き継ぎ)">🔁 リビルド作成</button>' : '') +
            ((!it._fromSheet || it.videoId) ? '<button class="vremake' + (it.remade ? ' on' : '') + '" type="button" data-k="' + esc(k) + '" title="この投稿に被リビルドの印を付ける(削除ではなく記録として残す)">' + (it.remade ? '↩ 被リビルド取消' : '🔁 被リビルドへ') + '</button>' : '') +
          '</div>' +
          '<button class="vdel" type="button" data-k="' + esc(k) + '" title="この記録を消去">🗑</button>' +
        '</div>' +
        '</div>';
    }).join('');
    // シートから vid を補ったが公開日時が未取得の投稿を、描画後に1回だけ取りに行く(見出しを YouTube公開日時へ)。
    //   通常のrefresh()はallItems(ローカル)しか照会しないため、結線が切れた行はここでしか公開日時を拾えない。
    //   取得できたら再描画で §1646(pub)が §1651(it.ts=作成日時)に勝つ。まだ非公開(予約公開中)なら空応答＝
    //   _pubBackfillTried で二度打ちを止める(公開後のリロード/更新で拾い直す)。
    if (_needPub.length && apiKey()) {
      var _pb = _needPub.filter(function (v, i, a) { return a.indexOf(v) === i; }).slice(0, 50);
      _pb.forEach(function (v) { _pubBackfillTried[v] = 1; });
      try {
        fetchVideos(_pb).then(function (m) {
          var got = false;
          Object.keys(m || {}).forEach(function (id) {
            if (id.indexOf('__') === 0) return; var rec = m[id] || {};
            if (rec.views != null) viewsCache[id] = rec.views;
            if (rec.published != null) { publishedCache[id] = rec.published; got = true; }
            if (rec.title) titleCache[id] = rec.title;
          });
          if (got) { try { ytMetaPersist(m); } catch (e) {} render(); }
        }).catch(function () {});
      } catch (e) {}
    }
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

    // 過去分プレビュー取り込み(Drive参照)。このチャンネルの、まだプレビューが無い履歴だけが対象。
    var backfillBtn = $('drivePrevBackfill');
    if (backfillBtn) backfillBtn.addEventListener('click', function () { runDrivePreviewBackfill_(visibleItems, backfillBtn); });

    // サムネ → 作品詳細モーダル
    list.querySelectorAll('.vrow-thumb').forEach(function (im) {
      im.addEventListener('click', function () { openFanzaModal_(im.getAttribute('data-fanza-thumb-url')); });
    });

    // 動画で使った画像 → 拡大ズーム。候補タブのref画像は読まず、履歴単位のusedだけを表示する。
    //   旧履歴でused未保存の場合も、カードに表示済みの先頭1枚だけを使うため候補画像が後ろへ混ざらない。
    list.querySelectorAll('.vrow-refimg').forEach(function (im) {
      im.addEventListener('click', function () {
        var cid = im.getAttribute('data-refcid');
        var usedKey = im.getAttribute('data-usedkey');
        var imgs = (usedKey && window.Go5Cand && window.Go5Cand.usedImgs) ? (window.Go5Cand.usedImgs(usedKey) || []).slice() : [];
        // 動画で使った画像が無い作品は投稿画像(用途'post')を開く＝サムネがpostImgArr[0]由来のケース。
        var fromPost = false;
        if (!imgs.length && usedKey && window.Go5Cand && window.Go5Cand.postImgs) { imgs = (window.Go5Cand.postImgs(usedKey) || []).slice(); fromPost = imgs.length > 0; }
        if (!imgs.length && im.getAttribute('src')) imgs = [im.getAttribute('src')];
        var b = (cid && window.Go5Cand && window.Go5Cand.bskyImg) ? window.Go5Cand.bskyImg(cid) : '';
        // 先頭prevN枚は「投稿プレビュー画像」、それ以降は動画で使った画像(Chami依頼2026-07-30)。投稿画像由来なら全ページ「投稿画像」。
        var prevN = (usedKey && window.Go5Cand && window.Go5Cand.usedPrevCount) ? (window.Go5Cand.usedPrevCount(usedKey) || 0) : 0;
        var caps = imgs.map(function (_c, i) { return fromPost ? '投稿画像' : (i < prevN ? '動画投稿プレビュー' : '動画生成で使用した画像'); });
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
        var rawItems = displayItems_(), ymap = loadYtMap();
        var it = null;
        for (var i = 0; i < rawItems.length; i++) { if (itemKey(rawItems[i]) === k) { it = rawItems[i]; break; } }
        if (!it) return;
        var ytCur = ymap[k] || it.ytUrl || '';
        // 合算済み(mergeUrls有・shortUrlが自前ドメイン)=合算後の代表(自前短縮)を投稿URL欄へ置き換えて表示(Chami依頼2026-07-31)
        var _g = window.Go5Short;
        var bskyCur = (it.mergeUrls && it.mergeUrls.length && it.shortUrl && _g && _g.ourBase && _g.ourBase(it.shortUrl))
          ? it.shortUrl
          : (it.shareUrl || it.shortUrl || it.postUrl || ''); // 通常は短い計測URL(da.gd)を優先表示
        var workCur = it.workUrl || '';
        var workShortCur = it.workShareUrl || it.workShortUrl || ''; // 作品クリック計測URL(導線2)の現値
        var attrCur = {}; attrDefs_().forEach(function (a) { attrCur[a.key] = !!it[a.key]; });
        _curSrcUrl = it.postUrl || it.shortUrl || bskyCur || ''; // 生成の元＝この投稿の元URL
        if (it._fromSheet) {
          openModal_('URL を編集', ytCur, bskyCur, workCur, attrCur, it.workState || '旧作', function (ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal, platform, mergeUrls) {
            saveEditFromSheet_(k, it, ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal, platform, mergeUrls);
          }, workShortCur, platOf_(it), it.mergeUrls);
          // シート由来行(別端末で作成)は「動画で使った画像」が欠けるので、ここでも後付け添付できるようにする。
          // 画像はvideoId単位の別ストア(write-through)＝localStorageの履歴配列には書き戻さない(INC-112防壁は無関係)。
          addPostImagesToModal_(k, it, 'used');
        } else {
          openModal_('URL を編集', ytCur, bskyCur, workCur, attrCur, it.workState || '旧作', function (ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal, platform, mergeUrls) {
            closeModal_();
            saveEdit_(k, it, ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal, platform, mergeUrls);
          }, workShortCur, platOf_(it), it.mergeUrls);
          addMoveButtonsToModal_(k, it); // 「→ 別アカウントへ移動」を差し込む
          addRebuildMergeButtonToModal_(k, it); // 「🔁 リビルド結合」を保存の上に差し込む
          addPostImagesToModal_(k, it); // 「投稿画像を添付(複数可)」を差し込む
        }
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
    if (target) {
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
      return;
    }
    // ★この端末のローカルには無く、記録シートから表示だけ補った行(_fromSheet)。
    //   ローカル配列には存在しないので上のfilterでは消えない＝ごみ箱を押しても何も起きなかった
    //   (Chami報告2026-07-23「ごみ箱が表示されないものがある」)。シート側をGAS action=delete で
    //   直接消し、表示キャッシュからも同じ行を除いて即座に一覧から消す。
    var sheetTarget = null, extraCache = _sheetExtraCache[acct()];
    ((extraCache && extraCache.items) || []).forEach(function (it) { if (itemKey(it) === k) sheetTarget = it; });
    if (!sheetTarget) { clearMark(); return; }
    var sTitle = sheetTarget.title || '(無題・シート由来)';
    if (!window.confirm('「' + sTitle + '」を本当に消去しますか？\n(この端末には元データが無いため、記録シート側を直接削除します。取り消せません)')) { clearMark(); return; }
    var gasUrl = gasUrl_();
    if (!gasUrl) { clearMark(); window.alert('記録用URL(GAS)が未設定のため削除できません。'); return; }
    jsonp_(gasUrl, { action: 'delete', channel: acct(), videoId: sheetTarget.videoId || '', postUri: sheetTarget.postUri || '', short: sheetTarget.shortUrl || '' }, function (res) {
      if (!res || !res.ok || !(Number(res.deleted) > 0)) { clearMark(); window.alert('削除対象を記録シートで特定できませんでした。再読み込み後にもう一度お試しください。'); return; }
      if (extraCache && extraCache.items) extraCache.items = extraCache.items.filter(function (it) { return itemKey(it) !== k; });
      refresh();
    });
  }

  // 作り直し印のトグル。(削除はしない)ONで「この動画を消して作り直した」印を付け、記録シートにも反映。
  function toggleRemade(k) {
    // 対象が手動追加(verify_manual)か投稿履歴(short_hist)かを判定して、その配列内のフラグを反転。
    var manual = loadManual(), hist = loadHist();
    var inManual = manual.some(function (x) { return itemKey(x) === k; });
    var inHist = hist.some(function (x) { return itemKey(x) === k; });
    if (inManual || inHist) {
      var arrKey = inManual ? manualKey() : histKey();
      var arr = inManual ? manual : hist;
      var target = null, next = false;
      arr.forEach(function (x) { if (itemKey(x) === k) { x.remade = !x.remade; target = x; next = !!x.remade; } });
      if (!target) return;
      saveArr(arrKey, arr);
      // 記録シート(GAS)にも反映：videoId 行の「作り直し」列を 作り直し済/解除 に。テストIDと未設定は送らない。
      pushRemadeToGas_(target.videoId || '', next);
      refresh();
      return;
    }
    // ★シート由来行(_fromSheet)：ローカルに実体が無いのでGAS(videoId)へ反映し、表示は保持patchで即反転する。
    //   (Chami依頼2026-07-30「両chでほとんどが被リビルドボタンが消えた」＝ローカル履歴が消えてシート由来に
    //    なった行にも従来通り被リビルドを効かせる。シートはremade列を返さないため保持patchで状態を維持する。)
    var a = acct(), c = _sheetExtraCache[a], sheetTarget = null;
    ((c && c.items) || []).forEach(function (x) { if (itemKey(x) === k) sheetTarget = x; });
    if (!sheetTarget || !sheetTarget.videoId) return;
    var vid = String(sheetTarget.videoId);
    var pm = (_pendingSheetEdits[a] = _pendingSheetEdits[a] || {});
    var patch = pm[vid] || {};
    var cur = (patch.remade != null) ? patch.remade : !!sheetTarget.remade;
    var nextR = !cur;
    patch.remade = nextR; pm[vid] = patch;
    savePend_(a, pm); // リロードを越えて保持(シートが権威のremade列を返さないため保持で維持)
    pushRemadeToGas_(vid, nextR, a);
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
    // ★シート由来行(ローカル履歴が消えた端末)もリビルド元に選べるようにdisplayItems_を使う(Chami依頼2026-07-30)。
    return displayItems_()
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
    // ★ローカルに実体が無い(シート由来)動画をリビルド元にした場合も、被リビルドをGAS＋保持patchへ反映。
    var pm = (_pendingSheetEdits[a] = _pendingSheetEdits[a] || {});
    var patch = pm[String(videoId)] || {}; patch.remade = true; pm[String(videoId)] = patch;
    savePend_(a, pm);
    pushRemadeToGas_(videoId, true, a);
    if (a === acct()) refresh();
  }
  // ── 投稿完了(ドラフトの投稿モード)から1件を投稿履歴へ記録する。account指定で正しいアカウント側へ書く。──
  //   ①「投稿完了を押しても投稿履歴に載らない」の対処。ここに載れば、既存の updateYtScheduled_ が
  //   予約公開(公開前)の動画を yt_scheduled__ へ拾い、scheduler.js が予約タブへ「公開待ち」表示する(②は自動達成)。
  //   同じ動画(videoId)or同じ計測URL(shortUrl)が既にあれば重複追加しない。表示中アカウントなら即反映。
  function addCompletedPost_(opts) {
    opts = opts || {};
    var acc = opts.account || acct();
    var ytUrl = (opts.ytUrl || '').trim();
    var shortUrl = (opts.shortUrl || '').trim();
    if (!ytUrl && !shortUrl) return false; // 動画URLも計測URLも無ければ履歴に載せる意味がない
    var vid = ytUrl ? ytIdOf(ytUrl) : '';
    var manual = loadArrFor_('verify_manual', acc);
    var hist = loadArrFor_('short_hist', acc);
    var ymap = loadYtMapFor_(acc);
    var dupe = manual.concat(hist).some(function (it) {
      var y = ymap[itemKey(it)] || it.ytUrl || '';
      if (vid && ytIdOf(y) === vid) return true;
      if (shortUrl && it.shortUrl === shortUrl) return true;
      return false;
    });
    if (dupe) { if (acc === acct()) refresh(); return false; }
    var id = 'm:' + new Date().getTime();
    var entry = { manual: true, id: id, ts: opts.ts || new Date().getTime() };
    if (ytUrl) entry.ytUrl = ytUrl;
    if (opts.title) entry.title = String(opts.title).replace(/\n+/g, ' ').trim();
    if (opts.workUrl) entry.workUrl = opts.workUrl;
    if (shortUrl) entry.shortUrl = shortUrl;
    if (opts.shareUrl) entry.shareUrl = opts.shareUrl;
    // post_id(=背骨ID)は idgen形式 `acc-YYYYMMDD-HHMM-rand` を正本にする。以前はここで opts.videoId が
    //   空だと YouTube動画ID(vid)を videoId＝post_id へ流用しており、シートの post_id 列に YouTube ID が
    //   そのまま入ってしまっていた(Chami指摘2026-07-31・ドラフト投稿モードで videoId 未伝搬の行が該当)。
    //   YouTube ID は entry.ytUrl / ymap に別途保持していて再生数計測はそちらで効くので、post_id には使わない。
    //   videoId が来ていればそれ(ドラフトの背骨ID)、無ければ idgen で正規IDを発番＝「今まで通り」の形式へ戻す。
    if (opts.videoId) entry.videoId = opts.videoId;
    else if (window.IdGen && window.IdGen.makeVideoId) entry.videoId = window.IdGen.makeVideoId(acc, new Date(), {});
    entry.workState = opts.workState || '旧作';
    // カレンダー公開枠の予定時刻(予約投稿)。YouTube APIのpublishAtが返る前でも「投稿予定 時刻」を出せる。
    if (opts.scheduledAt) entry.plannedAt = opts.scheduledAt;
    // ジャンル(カテゴリ)のチェックを引き継ぐ＝投稿完了で履歴にジャンルが渡らない穴を塞ぐ(Chami依頼2026-07-30)。
    if (opts.attrs) attrDefs_().forEach(function (a) { if (opts.attrs[a.key]) entry[a.key] = true; });
    manual.push(entry);
    saveArrFor_('verify_manual', acc, manual);
    if (ytUrl) { ymap[id] = ytUrl; saveYtMapFor_(acc, ymap); }
    // 作品クリック計測URL(導線2)を作品URLから自動発行＝編集→保存を待たずに一発で埋める(Chami依頼2026-07-30)。
    //   ★投稿完了は"新規発行してよい"経路なので mintWorkShortAtPost_ を使う。autoMeasureWorkShort_(編集保存用)は
    //   空欄を作品URLへフォールバックしない仕様のため、ここで呼ぶと workShortUrl が空のままシート/サブ端末へ
    //   載っていた(Chami再発②2026-08-03)。
    if (entry.workUrl && !entry.workShortUrl) {
      try {
        mintWorkShortAtPost_(entry, function () {
          saveArrFor_('verify_manual', acc, loadArrFor_('verify_manual', acc).map(function (x) { return x.id === id ? entry : x; }));
          pushItemToGas_(entry);
        });
      } catch (e) {}
    }
    if (acc === acct()) { try { pokeSnapshotNow_(); } catch (e) {} refresh(); }
    return true;
  }
  // ── カレンダー枠との紐づけ用(③④・Chami 2026-08-06)：指定日(JST)に投稿された現アカウントの履歴を返す。──
  //   投稿時刻の解決は投稿履歴カード(§1665〜)と同じ順序＝YouTube公開日時→予約/カレンダー予定→実投稿時刻(ts)。
  //   カレンダーiframeはこの解決を持たないので、本体側で解決してから postMessage で渡す(integration.js)。
  function effPostMs_(it, ymap, schedMap) {
    var vid = ytIdOf((ymap && ymap[itemKey(it)]) || it.ytUrl || '');
    var pub = vid && (vid in publishedCache) ? publishedCache[vid] : null;
    if (pub != null) return Number(pub);
    var sched = vid && schedMap[vid];
    var plannedMs = it.plannedAt ? (Date.parse(String(it.plannedAt).replace(' ', 'T')) || NaN) : NaN;
    var schedMs = (sched && sched.publishAt) ? Number(sched.publishAt) : plannedMs;
    if (!isNaN(schedMs)) return schedMs;
    if (it.ts) return Number(it.ts);
    return NaN;
  }
  function postsForDay_(dateStr) {
    if (!dateStr) return [];
    ensureIds();
    var ymap = loadYtMap();
    var schedMap = {};
    try { loadYtSched_(acct()).forEach(function (y) { if (y && y.vid) schedMap[y.vid] = y; }); } catch (e) {}
    var out = [];
    displayItems_().forEach(function (it) {
      var ms = effPostMs_(it, ymap, schedMap);
      if (isNaN(ms)) return;
      var dObj = new Date(ms);                     // JST端末前提(getHours等は端末ローカル=Chamiの体感と一致)
      var y = dObj.getFullYear(), mo = ('0' + (dObj.getMonth() + 1)).slice(-2), da = ('0' + dObj.getDate()).slice(-2);
      if ((y + '-' + mo + '-' + da) !== dateStr) return;
      var vid = ytIdOf(ymap[itemKey(it)] || it.ytUrl || '');
      var title = (vid && titleCache[vid]) || it.title || (it.manual ? '(手動追加)' : '(無題)');
      out.push({
        id: it.videoId || itemKey(it),
        videoId: it.videoId || '',
        title: stripCommonTags(title),
        timeMs: ms,
        hhmm: ('0' + dObj.getHours()).slice(-2) + ':' + ('0' + dObj.getMinutes()).slice(-2),
        url: it.shareUrl || it.shortUrl || it.postUrl || it.ytUrl || ''
      });
    });
    out.sort(function (a, b) { return a.timeMs - b.timeMs; });
    return out;
  }
  try { window.Go5History = { listForRebuildPicker: listForRebuildPicker_, markRebuilt: markRebuilt_, addCompletedPost: addCompletedPost_, postsForDay: postsForDay_ }; } catch (e) {}

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
  function addPostImagesToModal_(k, it, defaultUse) {
    var ov = document.getElementById('veditOverlay'); if (!ov) return;
    var modal = ov.querySelector('.vedit-modal'); if (!modal) return;
    var old = modal.querySelector('.vedit-postimg'); if (old) old.parentNode.removeChild(old);
    var api = window.Go5Cand || {};
    if (!api.postImgs || !api.postImgSave || !api.usedImgs || !api.usedImgSave) return; // 画像ストア未対応環境では出さない
    var pKey = it.videoId || k;
    var cid = it.workUrl ? workCidOf_(it.workUrl) : '';
    // 用途(保存先)。usedストア(履歴単位)の先頭prev枚が「動画投稿プレビュー画像」、それ以降が「動画で使った画像」。
    //   ★プレビューと使用画像は1レコードを頭割りで共有する(prev=先頭何枚がプレビューか)。用途を分けて別々に編集でき、
    //   過去の投稿履歴(prev未設定)でもプレビュー枠から追加できる(Chami依頼2026-07-30)。Bluesky添付だけは作品cid単位。
    var USES = [{ v: 'prev', label: '動画投稿プレビュー', multi: true }, { v: 'post', label: '投稿画像', multi: true }, { v: 'used', label: '動画で使った画像', multi: false }];
    if (cid) USES.push({ v: 'bsky', label: 'Bluesky投稿画像', multi: false });
    // usedストアの現在の全画像(表示と同じ合成)と、先頭プレビュー枚数。
    function usedAll_() {
      var saved = (api.usedImgs(pKey) || []).slice();
      var legacy = (cid && api.refImgs) ? (api.refImgs(cid) || []) : [];
      return (window.HistMerge && window.HistMerge.historyUsedImages)
        ? window.HistMerge.historyUsedImages(saved, legacy, !!(api.usedImgKnown && api.usedImgKnown(pKey)))
        : (saved.length ? saved : legacy.slice(0, 1));
    }
    function prevN_() { return (api.usedPrevCount ? (api.usedPrevCount(pKey) || 0) : 0); }
    // 初期の用途。プレビュー画像を持つ動画はプレビュー枠を最初に開く。シート由来行は「動画で使った画像」を指定して開く。
    var use = (defaultUse && USES.some(function (u) { return u.v === defaultUse; })) ? defaultUse
      : (prevN_() > 0 ? 'prev' : 'post');
    function useDef_() { for (var i = 0; i < USES.length; i++) { if (USES[i].v === use) return USES[i]; } return USES[0]; }
    function load_() {
      if (use === 'prev') { return usedAll_().slice(0, prevN_()); }        // 先頭プレビュー枚
      if (use === 'used') { return usedAll_().slice(prevN_()); }           // プレビュー以降＝実際に動画へ使った画像
      if (use === 'bsky') { var b = api.bskyImg ? api.bskyImg(cid) : ''; return b ? [b] : []; }
      return (api.postImgs(pKey) || []).slice();
    }
    function store_(arr) {
      if (use === 'prev') { var restU = usedAll_().slice(prevN_()); return api.usedImgSave(pKey, arr.concat(restU), arr.length); }   // 新プレビュー＋既存の使用画像・prev=新プレビュー枚数
      if (use === 'used') { var pv = usedAll_().slice(0, prevN_()); return api.usedImgSave(pKey, pv.concat(arr), pv.length); }        // 既存プレビューを保持したまま使用画像だけ差し替え
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
        '<button id="veditImgPaste" type="button" class="vedit-copy vedit-postimg-btn">貼り付け</button>' +
        '<label class="vedit-copy vedit-postimg-btn" style="cursor:pointer;margin:0;">＋ 選ぶ<input type="file" accept="image/*" multiple hidden></label>' +
      '</div>' +
      '<div class="vedit-postimg-grid"></div>' +
      '<div class="vedit-postimg-msg hint" style="min-height:0;margin:2px 0 0;"></div>';
    var actions = modal.querySelector('.vedit-actions');
    if (actions) modal.insertBefore(wrap, actions); else modal.appendChild(wrap);
    var grid = wrap.querySelector('.vedit-postimg-grid');
    var fileInp = wrap.querySelector('input[type=file]');
    var useSel = wrap.querySelector('#veditImgUse');
    useSel.value = use; // 初期用途を反映(シート由来行は「動画で使った画像」)
    var msg = wrap.querySelector('.vedit-postimg-msg');
    function persist() { store_(imgs); try { render(); } catch (e) {} } // 即保存＋カード再描画(画像変更なのでrender=クリック再取得を伴わない)
    function draw() {
      grid.innerHTML = '';
      if (!imgs.length) { grid.innerHTML = '<div class="hint" style="padding:6px 2px;">まだありません。「貼り付け」か「＋ 選ぶ」で追加してください。</div>'; return; }
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
    openModal_('YouTube動画を追加', '', '', autoWorkUrl, {}, '旧作', function (ytUrl, bskyUrl, workUrl, attrs, workState, workShortVal, platform, mergeUrls) {
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
      if (platform === 'x' || platform === 'bsky') entry.platform = platform; // X↗/Bsky↗表示の手動指定(既定X)
      if (Array.isArray(mergeUrls) && mergeUrls.length) entry.mergeUrls = mergeUrls; // 合算URL(導線1のみ)
      saveArr(manualKey(), loadManual().concat([entry]));
      var m = loadYtMap(); m[id] = ytUrl; saveYtMap(m);
      pokeSnapshotNow_(); // 手動追加でもYT URL紐付け当日に日別記録のベースラインを作る(④)
      refresh();
    });
  }

  // クリック数(開封数)・YouTube視聴回数/投稿日時/題名をAPIから取得しキャッシュへ。Promiseを返す。
  function fetchData_(items, ymap, force) { // force=true(手動🔄更新)のときだけTTLを無視して取り直す
    // 導線1(shortUrl=YT→投稿)と導線2(workShortUrl=投稿→FANZA)の両計測コードをまとめて照会
    var mergeCodes = [];
    items.forEach(function (it) { if (Array.isArray(it.mergeUrls)) it.mergeUrls.forEach(function (u) { var c = codeOf(u || ''); if (c) mergeCodes.push(c); }); });
    var codes = items.map(function (it) { return codeOf(it.shortUrl || ''); })
      .concat(items.map(function (it) { return codeOf(it.workShortUrl || ''); }))
      .concat(mergeCodes)
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
  // ── 点検(自己修復)と再生数/クリック取得の間引き ───────────────────────────
  //   Chami要望2026-07-29「投稿履歴が毎回色々読み込んで遅い。毎回読むべきものと不要なものを分けて、
  //   点検は裏で何日かに一回でいい」。所有権サニタイズ/シート後追い/取り残しYT再接続は表示を正すための
  //   冪等な自己修復で、タブを開くたびに走らせる必要はない。→ まずキャッシュから即描画し、点検はTTLで間引く。
  //   手動🔄(announce)は必ず全部走らせる。再生数/クリックはキャッシュ表示は常に即・自動再取得だけ間引く。
  var HIST_MAINT_TTL_MS = 6 * 3600 * 1000;   // 点検の最短間隔(6時間)。手動🔄は即時
  var HIST_METRICS_TTL_MS = 30 * 60 * 1000;  // 再生数/クリックの自動再取得の最短間隔(30分)。表示自体はキャッシュから即時
  function tsGet_(k) { try { return parseInt(localStorage.getItem(k) || '0', 10) || 0; } catch (e) { return 0; } }
  function tsSet_(k, v) { try { localStorage.setItem(k, String(v)); } catch (e) {} }
  function maintDue_() { return (Date.now() - tsGet_('hist_maint_at')) > HIST_MAINT_TTL_MS; }
  function metricsDue_() { return (Date.now() - tsGet_('hist_metrics_at')) > HIST_METRICS_TTL_MS; }

  function refresh(announce) {
    // ★まずキャッシュから即描画。点検・通信でタブ表示を待たせない(Chami「表示が遅い」対策)。
    render();
    // 点検(自己修復)は 手動🔄 か TTL到来時だけ・描画の後に走らせる。冪等なので裏で回して問題ない。
    //   ★サニタイズは ensureIds より前(偽の背骨ID接頭辞を刻む前に所属を確定する)——この順序は崩さない。
    var fixed = false;
    if (announce || maintDue_()) {
      try { fixed = sanitizeOwnership_(); } catch (e) {} // 誤アカウント混入を正へ帰還
      try { flushSheetMovePending_(); } catch (e) {} // 前回失敗したシート行移動を自動再送(T2)
      try { ensureIds(); } catch (e) {} // IDが無いアイテムへ背骨IDを付与(サニタイズ後)
      try { reconnectStrandedYt_(); } catch (e) {} // 取り残されたYT URLマップを正しいアカウントへ自己再接続(冪等)
      try { reconcileYtToSheet_(); } catch (e) {} // 端末のYT URLをシートへ後追い反映(冪等・台帳ガード)
      tsSet_('hist_maint_at', Date.now());
      if (fixed) render(); // 点検で移動が発生した時だけ再描画
      // DID台帳がまだ未解決なら、解決後にもう一度サニタイズ(冪等)。点検時のみ通信する。
      (function () {
        var R = window.Go5AccountRepair;
        if (R && R.ensureDids && !(R.ledgerFresh && R.ledgerFresh())) {
          R.ensureDids(function () { var more = sanitizeOwnership_(); if (more) { render(); notifySanitized_(more); } });
        }
      })();
    }
    try { mergeSheetExtras_(); } catch (e) {} // シート由来行の表示補完(60秒TTL・SWR・書き込みなし)
    var note = sanitizeNoteHtml_(fixed); // 更新完了メッセージに付記(サニタイズ通知が上書きで消えない)
    // 再生数/クリックはキャッシュが既に描画済み。自動更新は30分間引き(手動🔄は即・強制)。
    if (!announce && !metricsDue_()) {
      setStatus((apiKey() ? '' : '※YouTube再生数・投稿日時は⚙️詳細設定でAPIキーを設定し、各行にYouTube URLを入れると表示されます') + note, !!note);
      if (fixed) wireSanUndo_();
      return Promise.resolve(false);
    }
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
      tsSet_('hist_metrics_at', Date.now()); // 自動再取得の間引き基準(次の30分は再通信しない)
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
      attrDefs_().forEach(function (a) { rec[a.key] = !!it[a.key]; }); // カテゴリ属性
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
    // ★両ドメイン+旧r2を自前と認識(旧: workerUrl 1個だけ判定だと、もう片方のチャンネルの
    //   短縮URL(yoz2.com等)が永久に「未生成」扱いになり、タブを開くたびフルバルク再生成が走って
    //   その窓で編集が巻き戻る原因になっていた・2026-08-01)。autoMeasureWorkShort_:1288と同じ基準。
    function isR2(u) { return !!(go5.ourBase ? go5.ourBase(u) : (u && u.indexOf(workerUrl + '/') === 0)); }
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
        // ★ここでの「スナップショット丸ごと書き戻し」は廃止。成功分は下の逐次保存(persistFields_)で
        //   既に1件ずつ現ストレージへ反映済み。丸ごと保存はこの窓で入った手動編集を巻き戻すだけで害しかない(2026-08-01)。
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
            // ★逐次保存は「1件マージ」で(丸ごと保存だと並行中の手動編集を巻き戻す・2026-08-01)。
            persistFields_(it.manual ? manualKey() : histKey(), it, ['shortUrl', 'shareUrl']);
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
      function isR2(u) { return !!(go5.ourBase ? go5.ourBase(u) : (u && u.indexOf(w + '/') === 0)); } // 両ドメイン+旧r2(2026-08-01)
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
  // ytPruneSheet: D2-a で無効化(hidden属性付与・配線削除)。本体pruneSheet_()は残置(C-003)
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
      // at はJSTの 'YYYY-MM-DD HH:MM:SS'(v=354以降)。旧UTC(ISO)の記録も読めるようTだけ均す。
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
  // ★すぐ表示(Chami依頼2026-07-29「リロードで毎回全部読み込み直して遅い/毎回要る物と要らない物を分けて」):
  //   リロード直後はまず localStorage の永続キャッシュ(yt_meta_cache=題名/再生数/日付・clicks_cache=クリック数)
  //   から即描画し、シート由来行だけ先に取りに行く。重い再取得(YouTube再生数・クリックの再フェッチ/自動生成/
  //   各種復元)は下の 2500ms 便に残す=初回表示を2.5秒待たせない。render/merge は冪等なので下の refresh() と二重でも無害。
  function paintCachedNow_() {
    var pv = $('pageVerify'); if (!pv || pv.hidden) return;
    try { render(); } catch (e) {}           // 在メモリの永続キャッシュから即描画(通信0)
    try { mergeSheetExtras_(); } catch (e) {} // シート由来行だけ先に取得(TTL内なら通信0)。応答後に自身がrender()
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', paintCachedNow_);
  else paintCachedNow_();
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
  function setFanzaEls(fanzaUrl, title, root) {
    var man = fanzaManualOf_(fanzaUrl);
    if (man && man.title) title = man.title; // 手動入力の作品名が最優先
    var ok = title && !isBadFanzaTitle(title);
    // rootを渡すとその要素配下だけを走査する(1行分)。既定=document(全行・再描画後の反映用)。
    //   ★root無しの全体走査を件数分呼ぶとO(N²)＝件数の多いチャンネルで表示が激遅(Chami報告2026-07-30 月詠み)。
    (root || document).querySelectorAll('[data-fanza-url]').forEach(function (el) {
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
             ' <span class="fp-sale">' + yen_(p.price) + '</span>' +
             ' <span class="fp-off">' + p.discountPct + '%off</span>';
    }
    return '現定価:<span class="fp-cur">' + yen_(p.price) + '</span>';
  }
  // 投稿時(当時)価格のHTML。全体を作品名と同じ淡色で表示。%offは現在と同様に枠で囲む。
  function fmtSnapPriceHtml(p) {
    if (!p || p.price == null) return '';
    if (p.listPrice != null && p.discountPct > 0 && p.listPrice > p.price) {
      return '定価:<span class="fp-snap-list">' + yen_(p.listPrice) + '</span> ' + yen_(p.price) + ' <span class="fp-snap-off">' + p.discountPct + '%off</span>';
    }
    return '定価:' + yen_(p.price);
  }
  // data-fanza-snap-url が一致する当時価格の要素へ反映。★既に当時価格が出ている要素は上書きしない
  //   (現在価格で真の投稿時価格を潰さない)。空スロットにだけ埋める=過去投稿の空欄を救済する用途に使える。
  function setFanzaSnapEls(fanzaUrl, html) {
    if (!html) return; // 空HTMLで既存表示を消さない
    document.querySelectorAll('[data-fanza-snap-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-snap-url') !== fanzaUrl) return;
      if ((el.innerHTML || '').trim()) return; // 既に表示済み(真の当時価格)は保護
      el.innerHTML = html;
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
    // ★ローカル配列に無い行(☁️シート由来など)は d1/d2 が立たないが、空の当時価格スロットには
    //   表示だけ反映する。setFanzaSnapEls は非空を上書きしない=真の当時価格は保護される。(Chami依頼2026-07-30)
    setFanzaSnapEls(workUrl, fmtSnapPriceHtml(snap));
  }
  // data-fanza-author-url が一致する要素へサークル名(作者名)を反映。手動入力が最優先。
  function setFanzaAuthorEls(fanzaUrl, author, root) {
    var man = fanzaManualOf_(fanzaUrl);
    if (man && man.author) author = man.author;
    // サークル名の前にサークルマーク(候補タブと同じグレーの人物シルエット)を付ける。(Chami依頼2026-07-14「全部のタブに」)
    var ico = (typeof window.Go5CircleIcon === 'string') ? window.Go5CircleIcon : '';
    (root || document).querySelectorAll('[data-fanza-author-url]').forEach(function (el) {
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
      // 投稿時価格(当時)が空の作品は手動価格を当時価格として埋める。API未収録・価格取得前に投稿した作品の救済＝
      //   「投稿時の価格が表示されない作品がある」の主因(自動キャッシュに価格が無いと snap が永久に空だった)。
      //   setFanzaSnapEls/backfillSnap_ は非空スロット(真の当時価格)を保護するので既存の当時価格は上書きしない。
      var pm = mergeManualPrice_(u, null);
      if (pm && pm.price != null) { setFanzaSnapEls(u, fmtSnapPriceHtml(pm)); backfillSnap_(u, pm); }
    });
  }

  // data-fanza-thumb-url が一致するサムネ<img>へ画像を設定して表示。
  // src＝メイン画像。(モーダルと同じ・存在確認済みの大きい方)altSrc＝読込失敗時の代替。両方ダメなら非表示。
  function setFanzaThumbEls(fanzaUrl, src, altSrc, root) {
    if (!src && altSrc) { src = altSrc; altSrc = ''; }
    if (!src) return;
    (root || document).querySelectorAll('img[data-fanza-thumb-url]').forEach(function (el) {
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
            '<label class="vedit-field" style="flex:1;">セール(円・無ければ空)<input id="fzePrice" type="text" inputmode="numeric" autocomplete="off" placeholder="924"></label>' +
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
  function setFanzaPriceEls(fanzaUrl, priceInfo, root) {
    priceInfo = mergeManualPrice_(fanzaUrl, priceInfo);
    var html = fmtFanzaPriceHtml(priceInfo);
    (root || document).querySelectorAll('[data-fanza-price-url]').forEach(function (el) {
      if (el.getAttribute('data-fanza-price-url') !== fanzaUrl) return;
      if (html) { el.innerHTML = html; el.style.display = ''; }
      else { el.innerHTML = ''; el.style.display = 'none'; }
    });
    // 発売日→現在の作品状態。投稿時より「新しい」ときだけ引き上げる。(格下げはしない)
    //   例: 投稿時=旧作/準新作 でも 現在=新作 なら 新作 に合わせる。(準新作も同様)両アカウント共通ロジック。
    var apiState = priceInfo && deriveWorkState_(priceInfo.releaseDate);
    if (apiState) {
      var cr = wsRank_(apiState);
      (root || document).querySelectorAll('[data-fanza-state-url]').forEach(function (el) {
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
      // ★この行だけを更新範囲にする=件数分の全体走査(O(N²))を避ける。(月詠みで表示が激遅・Chami 2026-07-30)
      //   行が見つからない環境(ランキング等)はdocumentへフォールバック。
      var row = (nameEl.closest && nameEl.closest('.vrow')) || document;
      if (cached) {
        var age = now - (cached.fetchedAt || 0);
        var freshFull = cached.title && !isBadFanzaTitle(cached.title) && age < DAY && cached.priceInfo && ('releaseDate' in cached.priceInfo) && cached.media && cached.sv === FZ_SV;
        var freshPartial = cached.partial && cached.media && cached.sv === FZ_SV && age < DAY;
        // ★当時スナップの固定条件は「価格が新鮮か」だけで判定する(freshFullは releaseDate/media も要求するため、
        //   価格はあるのに発売日や画像が欠けた作品は snap が永久に空＝「投稿時価格が出ない作品がある」の主因)。
        //   ここは age<DAY・sv一致・price有りに限る＝古い価格を投稿時価格にしない担保は保つ。(Chami報告2026-07-30)
        var freshPrice = cached.priceInfo && cached.priceInfo.price != null && cached.sv === FZ_SV && age < DAY;
        // ★stale-while-revalidate：古い/旧スキーマのキャッシュでも「まず即表示」して待たせない。
        //   新鮮ならここで確定。古ければ表示は残したまま下のjobsに積んで裏で静かに最新化する。
        if (cached.title && !isBadFanzaTitle(cached.title)) {
          setFanzaEls(url, cached.title, row); setFanzaAuthorEls(url, cached.author || '', row);
          if (cached.priceInfo) { setFanzaPriceEls(url, cached.priceInfo, row); var _sp = mergeManualPrice_(url, cached.priceInfo); setFanzaSnapEls(url, fmtSnapPriceHtml(_sp)); if (freshPrice) backfillSnap_(url, _sp); } // 当時価格の"永続固定"は新鮮な価格のときだけ(古い価格を投稿時価格に保存しない・freshPrice=price有り+sv一致+age<DAY)。ただし空スロットの"表示"はキャッシュ価格でも即埋める(過去投稿の空欄救済・非空は保護・Chami依頼2026-07-30)
          if (cached.media) setFanzaThumbEls(url, cached.media.thumb || cached.media.thumbSmall, cached.media.thumbSmall, row);
          displayed = true;
          if (freshFull) return;
        } else if (cached.partial && cached.media) {
          // 画像のみの部分情報(API未収録作品)：サムネ＋手動入力の作品名/価格を表示
          setFanzaEls(url, '', row); setFanzaPriceEls(url, null, row); setFanzaAuthorEls(url, cached.author || '', row);
          setFanzaThumbEls(url, cached.media.thumb || cached.media.thumbSmall, cached.media.thumbSmall, row);
          displayed = true;
          if (freshPartial) return;
        } else if (!cached.title && !cached.partial && age < NEG) {
          setFanzaEls(url, '', row); setFanzaPriceEls(url, null, row); setFanzaAuthorEls(url, '', row); return; // 直近「未取得」→再取得しない(手動入力があれば表示)
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
  var _rankMetric = (function () { try { return localStorage.getItem('rank_metric') || ''; } catch (e) { return ''; } })(); // v/c1/c2(空=旧rank_modeから移行)
  var _rankWin = (function () { try { return localStorage.getItem('rank_window') || ''; } catch (e) { return ''; } })();    // total/peak/b30…b4320
  // 投稿(YouTube公開)からの経過時間バケットごとに再生数スナップショットを自動記録。
  //   ※アプリが再生数を取得した時にだけ観測できる＝そのバケットの許容窓内に開いた投稿だけ記録される。
  //   各バケットは「基準時刻〜基準+許容(基準の50%)」で初観測した再生数を固定。過去投稿は対象外＝未記録。
  var SNAP_BUCKETS = [
    { key: 'b30', min: 30, label: '30分' },
    { key: 'b60', min: 60, label: '1時間' },
    { key: 'b120', min: 120, label: '2時間' },
    { key: 'b360', min: 360, label: '6時間' },
    { key: 'b720', min: 720, label: '12時間' },
    { key: 'b1440', min: 1440, label: '24時間' },
    { key: 'b2880', min: 2880, label: '48時間' },
    { key: 'b4320', min: 4320, label: '72時間' }
  ];
  // バケットごとの許容窓(分)。旧 max(15, min*0.5) は60分窓に90分まで許し「60分計測が78分」を生んでいた(Chami 2026-08-02)。
  //   基準の15%かつ最大30分に締める= b60は[60,69](78を弾く)、12h/48hのようなGAS未対応の大窓は最大30分(数%)で残す=空にしない。(2026-08-03)
  function snapTol_(b) { return Math.min(b.min * 0.15, 30); }
  var snapCache = (function () { try { return JSON.parse(localStorage.getItem('view_snaps') || '{}') || {}; } catch (e) { return {}; } })(); // vid -> {b30:{v,c,w,ageMin},...}  v=再生数 c=導線1クリック w=導線2クリック(公開からの経過時点)
  function snapPersist_() { try { localStorage.setItem('view_snaps', JSON.stringify(snapCache)); } catch (e) {} }
  // 旧・緩い許容窓で採った「目標を大きく超える」観測(例: 60分窓に78分)は、Chami裁定2(2026-08-02)で
  //   「破棄せず"参考値"として残す」。よって削除はしない=以後 snapTol_ で新規生成だけを抑え、既存記録は保持する。
  //   目標+許容窓を超える記録かどうかは表示側で判定し「参考」と明示する(snapIsRef_ / ランキング行の"·参考")。
  //   ※v=604は起動時に一掃していた(snapPrune_)。裁定2でその一掃を撤去=残す方針へ変更(v=606)。
  function snapIsRef_(bucketMin, ageMin) { return ageMin != null && bucketMin != null && ageMin > bucketMin + Math.min(bucketMin * 0.15, 30); }
  // vid → {code:導線1短縮コード, wcode:導線2短縮コード}。バケット観測時にクリックも一緒に固定するための索引。
  function vidCodeMap_() {
    var m = {};
    try {
      allItems().forEach(function (it) {
        var yt = it.ytUrl || ''; var vid = ytIdOf(yt); if (!vid) return;
        if (!m[vid]) m[vid] = { code: codeOf(it.shortUrl || ''), wcode: codeOf(it.workShortUrl || '') };
        else { if (!m[vid].code) m[vid].code = codeOf(it.shortUrl || ''); if (!m[vid].wcode) m[vid].wcode = codeOf(it.workShortUrl || ''); }
      });
    } catch (e) {}
    return m;
  }
  function captureSnaps_() {
    var now = new Date().getTime(), changed = false;
    var cm = vidCodeMap_();
    Object.keys(viewsCache).forEach(function (vid) {
      var pub = publishedCache[vid];
      if (!pub || viewsCache[vid] == null) return;
      var ageMin = (now - pub) / 60000;
      var rec = snapCache[vid] || {};
      var cc = cm[vid] || {};
      var c1 = (cc.code && cc.code in clicksCache) ? clicksCache[cc.code] : null;   // 導線1クリック(白矢印)
      var c2 = (cc.wcode && cc.wcode in clicksCache) ? clicksCache[cc.wcode] : null; // 導線2クリック(ピンク矢印)
      SNAP_BUCKETS.forEach(function (b) {
        var tol = snapTol_(b);
        var inWin = ageMin >= b.min && ageMin <= b.min + tol;
        if (!inWin) return;
        var cur = rec[b.key];
        // 再生数は初観測で固定。クリックはその時点でまだ未取得(null)なら、同じ窓内の後続観測で埋める(値が出るまで待つ)。
        if (!cur) { rec[b.key] = { v: viewsCache[vid], c: c1, w: c2, ageMin: Math.round(ageMin) }; changed = true; }
        else {
          if (cur.c == null && c1 != null) { cur.c = c1; changed = true; }
          if (cur.w == null && c2 != null) { cur.w = c2; changed = true; }
        }
      });
      if (Object.keys(rec).length) snapCache[vid] = rec;
    });
    if (changed) snapPersist_();
  }
  function fmtAge_(min) { return min == null ? '' : (min < 90 ? min + '分後' : (Math.round(min / 6) / 10) + 'h後'); }
  // バケット値を「目標分に最も近い側(ローカル/GAS)」で1組選ぶ(Chami「60分計測なのに78分になる」2026-08-02)。
  //   rank-core が未読込の時だけ従来のローカル優先へフォールバック。
  function pickBucketRec_(snap, gtp, targetMin) {
    if (window.Go5RankCore && window.Go5RankCore.pickBucketRec) return window.Go5RankCore.pickBucketRec(snap, gtp, targetMin);
    return {
      v: (snap && snap.v != null) ? snap.v : (gtp && gtp.v != null ? gtp.v : null),
      c: (snap && snap.c != null) ? snap.c : (gtp && gtp.c != null ? gtp.c : null),
      w: (snap && snap.w != null) ? snap.w : null,
      age: (snap && snap.ageMin != null) ? snap.ageMin : (gtp && gtp.age != null ? gtp.age : null)
    };
  }

  // ── ランキングタブ(両アカウント合算・3モード切替)──────────────────────────────
  function renderRank() {
    var el = $('pageRank');
    if (!el) return;
    var myGen = ++_rankGen; // この描画系列の世代。以後の非同期callbackはこれが最新の時だけDOMをcommitする。

    // ★両チャンネルのシート履歴(記録_ch1/ch2)を確実に取得してからランキングに反映する。
    //   投稿履歴(displayItems_)はシート由来行を合算するのにランキングはlocalStorage直読みのみ＝
    //   データの取り方が分裂していた(Chami報告2026-08-02・③非対称)。ローカル履歴がほぼ空でシート頼みの
    //   チャンネルは、この分裂で「投稿履歴には出るがランキングには出ない」旧い作品が生じる。
    //   ★さらに _sheetExtraCache は acct()(今のタブ)固定のため、非アクティブ側のchはランキングにも永久欠落
    //   していた(月詠みは出たが宵桜が出ない)。→ acc1/acc2 両方を fetchSheetForRank_ で明示取得する。
    //   TTL内の同期コールでは at が変わらない→再描画しない=ループ防止。
    (function ensureRankSheets_() {
      ['acc1', 'acc2'].forEach(function (a0) {
        var before = (_rankSheetCache[a0] && _rankSheetCache[a0].at) || 0;
        fetchSheetForRank_(a0, function () {
          var nowAt = (_rankSheetCache[a0] && _rankSheetCache[a0].at) || 0;
          if (nowAt !== before && $('pageRank') && !$('pageRank').hidden) renderRank();
        });
      });
    })();

    // 両アカウントからアイテムとYouTube URLを収集
    var combined = [];
    ['acc1', 'acc2'].forEach(function (a) {
      var ymap;
      try { ymap = JSON.parse(localStorage.getItem('verify_yt__' + a) || '{}') || {}; } catch (e) { ymap = {}; }
      // 【恒久・供給一本化 2026-08-03】投稿履歴(displayItems_)とランキングの材料を channelItemsFor_ で1本化。
      //   従来ここは生シート行を直読みし、保持patch/合算URLストア(mstore)の上塗りを当てていなかった=
      //   shortUrl がpatch側にしか無い作品はクリックコード(code)が解決できず、metricVal==null で除外され
      //   「投稿履歴では210クリック出るのにランキングに出ない」非対称になっていた(Chami報告2026-08-02【A】)。
      //   channelItemsFor_ はローカル履歴＋シート由来行に applySheetOverlays_ を当てて返す=履歴と同じ材料。
      //   ローカルとシートの重複は後段の vid 重複排除(seen)で吸収(ローカルが先＝ローカル優先)。
      var items = channelItemsFor_(a);
      items.forEach(function (it) {
        if (it.remade) return; // 被リビルド(リビルド版に置き換え済み)はランキングに出さない＝新しい方だけ載る
        var k = itemKey(it);
        var yt = ymap[k] || it.ytUrl || '';
        var vid = ytIdOf(yt);
        if (!vid) return;
        combined.push({ it: it, vid: vid, yt: yt, acct: a });
      });
    });

    // 【恒久・field-level統合 2026-08-03】同一vidを"1行選んで残り捨て"ではなく field ごとに合成する
    //   (Codex監査 真因1)。ローカル行の shortUrl が空でも、shortUrl を持つシート行の値を補完し、
    //   計測URLは clickUrls/workClickUrls に集合で保持=postClicks_ が重複なく合算する。
    //   rank-core.js 未読込時は従来の先勝ち排除へフォールバック(表示は無傷)。
    var _attrKeys = attrDefs_().map(function (a) { return a.key; });
    var uniq = (window.Go5RankCore && window.Go5RankCore.mergeByVid)
      ? window.Go5RankCore.mergeByVid(combined, _attrKeys)
      : (function () { var seen = {}; return combined.filter(function (x) { if (seen[x.vid]) return false; seen[x.vid] = true; return true; }); })();

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

    // 2軸のランキング(Chami指示2026-08-02)。①指標＝再生数/白矢印(導線1)/ピンク矢印(導線2)を上段ボタンで切替。
    //   ②窓＝総合/ピーク/30分/1時間/2時間/6時間/12時間/24時間/48時間/72時間 を下段で切替。窓は「YouTube公開時刻」起点。
    var LINK_IC = '<img class="emico" src="assets/icons/ic-link.png" alt="">';
    var CUR_IC = '<img class="emico emico-cursor" src="assets/icons/ic-cursor-pink.png" alt="">';
    var RANK_METRICS = [
      { key: 'v', label: '▶ 再生数' },
      { key: 'c1', label: LINK_IC + ' クリック数' },   // 絵文字はそのまま＋「クリック数」(Chami指示2026-08-02)
      { key: 'c2', label: CUR_IC + ' クリック数' }
    ];
    var RANK_WINS = [
      { key: 'total', label: '総合' },
      { key: 'peak', label: 'ピーク' }
    ].concat(SNAP_BUCKETS.map(function (b) { return { key: b.key, label: b.label }; })); // 30分/1時間/2時間/6時間/12時間/24時間/48時間/72時間
    // 旧・単一モード(rank_mode)からの移行。views→(v,総合) clicks→(c1,総合) pv→(v,ピーク) pc→(c1,ピーク) bXXX→(v,窓)。
    (function migrate_() {
      if (_rankMetric || _rankWin) return; // 既に新形式が入っていれば触らない
      var m = _rankMode || 'views';
      if (m === 'early') m = 'b120';
      if (m === 'wviews') m = 'views';
      if (m === 'views') { _rankMetric = 'v'; _rankWin = 'total'; }
      else if (m === 'clicks') { _rankMetric = 'c1'; _rankWin = 'total'; }
      else if (m === 'pv') { _rankMetric = 'v'; _rankWin = 'peak'; }
      else if (m === 'pc') { _rankMetric = 'c1'; _rankWin = 'peak'; }
      else if (m.charAt(0) === 'b') { _rankMetric = 'v'; _rankWin = m; }
      else { _rankMetric = 'v'; _rankWin = 'total'; }
    })();
    // 12時間バケット新設で窓集合が変わっても、未知キーは総合へ戻す。
    if (!RANK_WINS.some(function (w) { return w.key === _rankWin; })) _rankWin = 'total';
    if (!RANK_METRICS.some(function (m) { return m.key === _rankMetric; })) _rankMetric = 'v';

    function doRender(_async) {
      // 非同期(_async=true)経由の描画は、より新しいrenderRankが走っていたら破棄=古い一部一覧で
      //   全件DOMを上書きしない(Codex監査 真因2)。ユーザー操作/即時キャッシュ描画は最新DOM上でのみ
      //   発火するため素通し。
      if (_async && myGen !== _rankGen) return;
      captureSnaps_();
      // ★作品サムネのちらつき対策: 取得済み(キャッシュ済み)のFANZA画像URLをHTMLへ直接焼き込む。
      //   従来は img を display:none で出し fillFanzaNames が後から src を差す方式だったため、
      //   再生数/クリック数が届くたびの再描画で img が作り直され、サムネが一瞬消えて“ちらついて”いた
      //   (Chami報告2026-08-02①)。キャッシュ済みなら src をHTMLに入れておけば再描画でも消えない。
      var _fzCache = {}; try { _fzCache = fanzaNameCacheLoad() || {}; } catch (e) {}
      var isBucket = _rankWin.charAt(0) === 'b';
      var isPeak = _rankWin === 'peak';
      var bucketDef = isBucket ? SNAP_BUCKETS.filter(function (b) { return b.key === _rankWin; })[0] : null;
      var c2PeakUnsupported = isPeak && _rankMetric === 'c2'; // 導線2(ピンク矢印)のピークはGAS未対応=データ無し
      var pk0 = peakCache || {};
      var rows = uniq.map(function (x) {
        var it = x.it;
        // 【供給一本化 2026-08-03】クリック値は投稿履歴と同一の postClicks_ で計算(合算URL/GAS日次
        //   デルタ/リビルドを内包)。従来はここで clicksCache[code] を直読みするだけで、履歴が加算する
        //   合算URL・GASデルタ下限を欠き「履歴では出るクリックがランキングに出ない」が残っていた【A再発】。
        var _pc = postClicks_(it, x.vid);
        var code = _pc.code, wcode = _pc.wcode;
        var snap = (isBucket && snapCache[x.vid]) ? snapCache[x.vid][_rankWin] : null;
        var gtp = (isBucket && tpCache[x.vid]) ? tpCache[x.vid][_rankWin] : null; // GASサーバー時点記録(過去分・端末未起動でも記録。再生数と導線1のみ・12h/48h/導線2は非対応)
        var bkr = (isBucket && bucketDef) ? pickBucketRec_(snap, gtp, bucketDef.min) : null; // 目標分に近い側を1組で採用(78分ズレの根治)
        var pk = pk0[x.vid] || {};
        var cats = attrDefs_().map(function (a) { return it[a.key] ? '<span class="vtag" style="color:' + esc(a.color) + ';border-color:' + esc(a.color) + ';font-weight:700;">' + esc(a.label) + '</span>' : ''; }).join('');
        return {
          vid: x.vid, yt: x.yt, acct: x.acct,
          title: titleCache[x.vid] || it.title || (it.manual ? '(手動追加)' : '(無題)'),
          views: (x.vid in viewsCache) ? viewsCache[x.vid] : null,
          clicks: _pc.c1, // 導線1総合(投稿履歴と同一計算=合算URL/GAS日次デルタ/リビルドを内包・供給一本化2026-08-03)
          wclicks: _pc.c2, // 導線2総合(ピンク矢印・同上)
          code: code, wcode: wcode,
          snapV: bkr ? bkr.v : null, snapC: bkr ? bkr.c : null, snapW: bkr ? bkr.w : null, snapAge: bkr ? bkr.age : null,
          peakV: pk.vRate != null ? pk.vRate : null, peakVWin: pk.vWin || '',
          peakC: pk.cRate != null ? pk.cRate : null, peakCWin: pk.cWin || '',
          ts: it.ts || (publishedCache[x.vid] || 0),
          bskyHref: it.shareUrl || it.shortUrl || it.postUrl || '',
          bskyIsX: isXLink_(it.shareUrl || it.shortUrl || it.postUrl || '', it),
          workUrl: it.workUrl || '', workState: it.workState || '旧作', cats: cats
        };
      });
      // 指標(v/c1/c2)×窓(total/peak/bXX)でソート対象の値を決める。
      function metricVal(r) {
        if (_rankWin === 'total') return _rankMetric === 'v' ? r.views : (_rankMetric === 'c1' ? r.clicks : r.wclicks);
        if (isPeak) return _rankMetric === 'v' ? r.peakV : (_rankMetric === 'c1' ? r.peakC : null); // 導線2ピークは未対応
        // バケット窓: 公開からの経過時点で固定した各指標
        return _rankMetric === 'v' ? r.snapV : (_rankMetric === 'c1' ? r.snapC : r.snapW);
      }
      // 【恒久 2026-08-03・Codex監査 真因3】「総合」は再生数だけでなく白/ピンク矢印も値なし行を残す。
      //   silent drop は「作品が存在しない」と「未集計(URL無し/取得失敗)」を同じ"消える"に潰し障害を
      //   長期化させていた。総合では全件残し、未集計理由は各指標欄の「…」(取得中/失敗)「–」(計測URL無し)
      //   で示す。ピーク/各時間窓は本質的に未記録が多いので従来どおり値なしを除外する。
      var isBaseList = (_rankWin === 'total');
      if (!isBaseList) rows = rows.filter(function (r) { return metricVal(r) != null; });
      var _numCnt = isBaseList && _rankMetric !== 'v' ? rows.filter(function (r) { return metricVal(r) != null; }).length : 0;
      rows.sort(function (a, b) {
        var av = metricVal(a), bv = metricVal(b);
        if (av == null && bv == null) return (b.views || 0) - (a.views || 0);
        if (av == null) return 1; if (bv == null) return -1;
        return bv - av;
      });
      var metricName = _rankMetric === 'v' ? '再生数' : (_rankMetric === 'c1' ? '白矢印クリック(導線1)' : 'ピンク矢印クリック(導線2)');
      var metricRow = '<div class="rank-tabs rank-tabs-metric">' + RANK_METRICS.map(function (m) {
        return '<button class="rank-tab rank-metric-tab' + (m.key === _rankMetric ? ' active' : '') + '" data-metric="' + m.key + '" type="button">' + m.label + '</button>';
      }).join('') + '</div>';
      var winRow = '<div class="rank-tabs rank-tabs-win">' + RANK_WINS.map(function (w) {
        return '<button class="rank-tab rank-win-tab' + (w.key === _rankWin ? ' active' : '') + '" data-win="' + w.key + '" type="button">' + w.label + '</button>';
      }).join('') + '</div>';
      var tabsHtml = metricRow + winRow;
      var noteHtml = c2PeakUnsupported
        ? '<div class="rank-note">ピンク矢印(導線2)のピークはまだ集計していません(GAS側の対応待ち)。総合や各時間(30分〜72時間)の窓は表示できます。</div>'
        : (isBucket
          ? '<div class="rank-note">' + metricName + 'の「公開から約' + bucketDef.label + '」ランキング。YouTube公開時刻を起点に自動記録(この機能導入後の投稿が対象・未記録は非表示)。「(◯後)」は実記録時刻。<b>·参考</b>付き=目標時刻を大きく外れた旧記録の参考値(そのまま残しています)。</div>'
          : (isPeak
            ? '<div class="rank-note">' + metricName + 'の最大瞬間風速ランキング(1時間あたりの伸びが最大の区間。GAS自動記録・未記録は非表示)。</div>'
            : '<div class="rank-note">' + metricName + 'の総合ランキング。' + (_rankMetric === 'v' ? '' : ('対象' + rows.length + '本 / 数値取得' + _numCnt + '本(未取得は末尾に「…」取得中/失敗・「–」計測URL無しで表示)')) + '</div>'));
      var emptyHtml = rows.length ? '' : '<p class="hint" style="padding:10px 14px;">このランキングに表示できる記録がまだありません。</p>';
      var listHtml = '<div class="rank-list">' +
        rows.map(function (r, i) {
          var rank = i + 1;
          var topCls = rank <= 3 ? ' rank-top' + rank : '';
          var dispTitle = esc(stripCommonTags(r.title));
          // 右端の画像列: 作品サムネ(タップで作品詳細=サンプル一覧) + 動画生成に使った保存画像(タップで拡大)
          var rcid = '';
          try { if (r.workUrl && window.buildAffiliateLink) { var _nu = window.normalizeWorkUrl ? window.normalizeWorkUrl(r.workUrl) : r.workUrl; var _rr = _nu ? window.buildAffiliateLink(_nu, '') : null; if (_rr && _rr.ok) rcid = _rr.cid; } } catch (e) {}
          var refSrc = '';
          try { if (rcid && window.Go5Cand && window.Go5Cand.refImgs) { var _ri = window.Go5Cand.refImgs(rcid); refSrc = (_ri && _ri[0]) || ''; } } catch (e) {}
          var thumbSrc = '';
          try { var _fz = r.workUrl ? _fzCache[r.workUrl] : null; if (_fz && _fz.media) thumbSrc = _fz.media.thumb || _fz.media.thumbSmall || ''; } catch (e) {}
          var thumbColHtml = (r.workUrl || refSrc)
            ? '<div class="rank-thumbcol">' +
                (r.workUrl ? '<img class="rank-thumb" data-fanza-thumb-url="' + esc(r.workUrl) + '" alt="作品サムネ(タップで詳細)" title="タップで作品詳細(サンプル画像)" loading="lazy"' + (thumbSrc ? ' src="' + esc(thumbSrc) + '"' : ' style="display:none;"') + '>' : '') +
                (refSrc ? '<img class="rank-refimg" data-rank-refimg="' + esc(rcid) + '" src="' + esc(refSrc) + '" alt="動画で使った画像(タップで拡大)" title="動画で使った画像(タップで拡大)" loading="lazy">' : '') +
              '</div>'
            : '';
          var dateStr = fmtTsFull(r.ts);
          var acctLabel = ACCT_NAME[r.acct] || r.acct;
          // 指標スパン。総合3種(▶再生/白矢印/ピンク矢印)は常に併記。窓(バケット/ピーク)は主指標だけ先頭に強調。
          var hlTotal = _rankWin === 'total';
          var PLAY_IC = '<span class="rank-play">▶</span>'; // ▶再生数アイコン=白＋黒フチ（Chami依頼2026-08-02）
          var METRIC_IC = _rankMetric === 'v' ? PLAY_IC : (_rankMetric === 'c1' ? LINK_IC : CUR_IC);
          var mViews = '<span class="' + (hlTotal && _rankMetric === 'v' ? 'rank-main' : '') + '" title="YouTube再生数">' + PLAY_IC + ' ' + (r.views != null ? num(r.views) : (apiKey() ? '…' : '–')) + '</span>';
          var mClicks = '<span class="' + (hlTotal && _rankMetric === 'c1' ? 'rank-main' : '') + '" title="白矢印クリック(導線1)">' + LINK_IC + ' ' + (r.clicks != null ? num(r.clicks) : (r.code ? '…' : '–')) + '</span>';
          var mWork = '<span class="' + (hlTotal && _rankMetric === 'c2' ? 'rank-main' : '') + '" title="ピンク矢印クリック(導線2)">' + CUR_IC + ' ' + (r.wclicks != null ? num(r.wclicks) : (r.wcode ? '…' : '–')) + '</span>';
          var snapVal = _rankMetric === 'v' ? r.snapV : (_rankMetric === 'c1' ? r.snapC : r.snapW);
          // 目標時刻を大きく外れた記録(旧・緩い許容窓)は"参考値"(Chami裁定2・2026-08-02)。行にも「参考」を明示。
          var snapRef = isBucket && bucketDef && snapIsRef_(bucketDef.min, r.snapAge);
          var mBucket = (isBucket && snapVal != null) ? '<span class="rank-main' + (snapRef ? ' rank-ref' : '') + '" title="公開から約' + bucketDef.label + 'の' + metricName + (snapRef ? '（参考値:記録時刻が目標から外れた旧記録です）' : '') + '">⏱ ' + METRIC_IC + ' ' + num(snapVal) + '<span class="rank-sub">(' + fmtAge_(r.snapAge) + (snapRef ? ' ·参考' : '') + ')</span></span>' : '';
          var peakVal = _rankMetric === 'v' ? r.peakV : (_rankMetric === 'c1' ? r.peakC : null);
          var peakWin = _rankMetric === 'v' ? r.peakVWin : r.peakCWin;
          var mPeak = (isPeak && peakVal != null) ? '<span class="rank-main" title="最大瞬間風速">🌀 ' + METRIC_IC + ' ' + num(peakVal) + '/時<span class="rank-sub">(' + esc(peakWin || '') + ')</span></span>' : '';
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
                mPeak + mBucket + mViews + mClicks + mWork +
                (r.bskyHref ? '<a class="vlink ' + (r.bskyIsX ? 'vlink-x' : 'vlink-bsky') + '" href="' + esc(r.bskyHref) + '" target="_blank" rel="noopener">' + (r.bskyIsX ? 'X↗' : 'Bsky↗') + '</a>' : '') +
                (r.yt ? '<a class="vlink vlink-yt" href="' + esc(r.yt) + '" target="_blank" rel="noopener">YouTube↗</a>' : '') +
                (r.workUrl ? '<a class="vlink vlink-work" href="' + esc(r.workUrl) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
              '</div>' +
            '</div>' +
            thumbColHtml +
          '</div>';
        }).join('') +
      '</div>';
      var fullHtml = tabsHtml + noteHtml + emptyHtml + listHtml;
      // 同一内容の再描画はスキップ=非同期で入るサムネ/価格を消さない(ちらつき防止)。
      //   ただしリストがまだDOMに無い(初回/プレースホルダ状態)なら必ず描く。
      if (fullHtml === _rankLastHtml && el.querySelector('.rank-list')) return;
      _rankLastHtml = fullHtml;
      el.innerHTML = fullHtml;
      // サブタブ配線(上段=指標 v/c1/c2・下段=窓 total/peak/bXX)
      el.querySelectorAll('.rank-tab').forEach(function (b) {
        b.addEventListener('click', function () {
          var mk = b.getAttribute('data-metric'), wk = b.getAttribute('data-win');
          if (mk) { _rankMetric = mk; try { localStorage.setItem('rank_metric', _rankMetric); } catch (e) {} }
          if (wk) { _rankWin = wk; try { localStorage.setItem('rank_window', _rankWin); } catch (e) {} }
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

    // 再生数・クリック数を取得してから描画。
    // ★総合(再生数)は「YouTubeの"現在の"総再生数」なので、キャッシュ済みでも毎回取り直す。
    //   旧実装は missing(=一度も取得していない動画)だけ取っていたため、過去に一度でも取得した動画は
    //   起動時に yt_meta_cache から読んだ"古い再生数"で固定され、その後いくら伸びてもランキングに
    //   反映されなかった(=「直近しか反映されない/もっと再生されてる過去分が反映されない」Chami指摘
    //   2026-08-02)。対策: 一覧の全動画IDを毎回 videos.list で最新化する(50件/回=無料枠は十分)。
    //   まずキャッシュで即描画→取得後に最新値へ差し替える(初回表示を待たせない)。
    var allV = uniq.map(function (x) { return x.vid; }).filter(function (v, i, a) { return v && a.indexOf(v) === i; });
    var hadCache = allV.some(function (v) { return v in viewsCache; });
    if (hadCache) { try { doRender(); } catch (e) {} } // 既存キャッシュで即表示(通信0)。取得後に下で最新化。
    else { _rankLastHtml = ''; el.innerHTML = '<p style="color:var(--sub);font-size:13px;padding:8px 14px;">再生数・クリック数を取得中…</p>'; }
    var jobs = [];
    for (var i = 0; i < allV.length; i += 50) {
      (function (b) {
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
      })(allV.slice(i, i + 50));
    }
    jobs.push(fetchAllClicks_()); // 全コードのクリック数も最新化(TTL内なら通信0=連打抑制)。導線1/導線2とも
    Promise.all(jobs).then(function () { clicksPersist_(); doRender(true); });
    // ピーク/差分(GAS)を取得したら再描画。(ピーク2モードに反映)
    fetchDeltas_(false, function () { doRender(true); });
  }
  try { window.YtRank = { renderRank: renderRank }; } catch (e) {}
  // 短縮URL→現在のクリック数。(bluesky.jsのリビルド引き継ぎが「リビルド前スナップショット」取得に使う)
  try { window.Go5Clicks = { of: function (shortUrl) { var c = codeOf(shortUrl || ''); return (c && (c in clicksCache)) ? clicksCache[c] : null; } }; } catch (e) {}
})();
