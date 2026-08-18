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
  function usableCandidatePrefetch_(cached) {
    return !!(cached && cached.done && cached.info && cached.info.title && !cached.errored);
  }

  // モーダル本体は再利用のためDOMに残す。祖先overlayが hidden なら「開いている」と扱わない。
  // documentに依存しない形にして、回帰テストからも判定規則を固定できるようにする。
  function modalIsOpen_(modal) {
    if (!modal) return false;
    var overlay = null;
    try { overlay = modal.closest ? modal.closest('.fz-overlay') : modal.parentNode; } catch (e) {}
    return !(overlay && overlay.hidden);
  }

  // ★動画生成用画像スロットの状態判定(純関数=Nodeテストで真値表を固定できる)。DOM/ストレージに触らない。
  //   has=保存画像が1枚以上あるか / worked=コメントかメモがあるか(=動画を作った痕跡→画像が在るべき) /
  //   idbOk=IDB使用可 / refLoaded=このcidをIDBから実際に読んだか(===true) / inMem=_imgMem.refにこのcidの実体があるか /
  //   candidateHydrated=一括展開が完了したか。戻り値=images/loading/checking/missing/none。
  //   ★⚠(missing)は per-cid の陽性確認(refLoaded===true か inMem)でのみ返す=一括展開の完了(candidateHydrated)だけでは
  //     「無い」と断定しない。同期/別タブで後から届く画像を「消えた」と誤表示しないため(C-041=一度の観測を状態の代理に
  //     するな。Chami 2026-08-15「画像あるはずなのよ、消えてるってこと」)。checking の作品は端末内を能動確認して確定する。
  function refSlotDecide_(has, worked, idbOk, refLoaded, inMem, candidateHydrated) {
    if (has) return 'images';
    if (!worked) return 'none';                       // コメント/メモも無い=触っていない作品は空欄のまま
    if (!idbOk || refLoaded === true || inMem === true) return 'missing'; // 実際に読んだ結果0枚=正当な「画像なし」
    if (!candidateHydrated) return 'loading';         // まだ一括展開の途中=読込中(まだ何も断定しない)
    return 'checking';                                // 展開は済んだがこのcidは未確認=端末内を能動確認してから判定
  }

  // Node(テスト)からは純関数 buildPostedIndex_ だけを取り出す。DOM/localStorage を触る本体は実行しない。
  //   関数宣言は巻き上げられるので、本体の定義位置より前でも参照できる(tests/test_posted_index.js)。
  if (typeof module !== 'undefined' && module.exports && typeof document === 'undefined') {
    module.exports = { buildPostedIndex_: buildPostedIndex_, usableCandidatePrefetch_: usableCandidatePrefetch_, modalIsOpen_: modalIsOpen_, candTextOf_: candTextOf_, candTextSave_: candTextSave_, candTextNonEmpty_: candTextNonEmpty_, refSlotDecide_: refSlotDecide_, shouldShowIdbHint_: shouldShowIdbHint_ };
    return;
  }
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function lsGet(k, def) { try { return JSON.parse(localStorage.getItem(k) || def); } catch (e) { return JSON.parse(def); } }
  function lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} reqSyncFor_(k); }
  // 同期対象の候補キーが変わったら即時同期を要求。(デバウンス＋最小間隔はGo5Sync側で吸収)
  //   キャッシュ系(cand_sales/cand_mk2 等)では発火させない＝no-op同期の無駄打ちを避ける。
  function reqSync_() { try { if (window.Go5Sync && window.Go5Sync.requestSync) window.Go5Sync.requestSync(); } catch (e) {} }
  function reqSyncFor_(k) { if (/^cand_(items|tabs)(__|$)/.test(k) || /^cand_hidden__/.test(k) || k === 'cand_hide_posted') reqSync_(); if (/^cand_(items|tabs)(__|$)/.test(k)) schedulePoolSync_(); }
  // 継続改善制度の行動ログ。(意味のある操作のみ・失敗は無害)
  function klog_(action, objType, objId, meta) { try { if (window.Go5Kaizen) window.Go5Kaizen.log('candidates', action, objType, objId, meta); } catch (e) {} }
  function workerCfg() {
    var u = '', s = '';
    try { u = (localStorage.getItem('fanza_worker_url') || '').trim(); s = (localStorage.getItem('fanza_shared_secret') || '').trim(); } catch (e) {}
    return { url: u.replace(/\/+$/, ''), secret: s };
  }
  // 候補プールD1同期の「最後の結果」を端末に残す観測点。console.warnはChamiのスマホで読めないため、
  //   📚全候補ヘッダに人が読める形で出す(どの分岐で止まったかを実機で1発観測=v=647/648が同型リトライで
  //   直らなかったのを断ち切る・十王星南の実測要請2026-08-05)。端末ローカル(storage-keys未登録=非同期しない)。
  function poolSyncNote_(msg) { try { localStorage.setItem('cand_pool_sync_note', fmtTs(new Date().getTime()) + ' ' + msg); } catch (e) {} }
  function poolSyncNoteRead_() { try { return localStorage.getItem('cand_pool_sync_note') || ''; } catch (e) { return ''; } }
  function yen(n) { return (n != null && !isNaN(n)) ? '¥' + Number(n).toLocaleString('ja-JP') : '—'; }
  function fmtDate(s) { return String(s || '').slice(0, 10); }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  // 発売日→作品状態。判定は core/movie-attrs-core.js に一本化(2026-08-13・C-038)。core未ロード時は同ロジックで代替。
  function deriveWorkState_(dateStr) {
    if (window.Go5MovieAttrsCore && window.Go5MovieAttrsCore.deriveWorkState) return window.Go5MovieAttrsCore.deriveWorkState(dateStr);
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
  function isInfoTarget_(it) {
    return !!(it && it.cid && !it.isTwitter && !/^tw_/i.test(String(it.cid)));
  }
  // DMM同人の販売数ページをPCで取得できるcidだけを販売数キューへ送る。
  // Books・SNSを同人URLへ誤送信すると「取得待ち」が永久に残るため、入口で分離する。
  function isSalesTarget_(it) {
    return isInfoTarget_(it) && /^d_[0-9A-Za-z]+$/i.test(String(it.cid));
  }
  function salesTargetCids_(items) {
    return (items || []).filter(isSalesTarget_).map(function (it) { return it.cid; });
  }
  // 全角英字→半角(ＡＩ→AI)。FANZAのタグ表記ゆれで /AI/ が素通りするのを防ぐ。
  function toHalfWidth_(s) { return String(s == null ? '' : s).replace(/[Ａ-Ｚａ-ｚ]/g, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xFEE0); }); }
  // AI作品の判定。★判定式は core/movie-attrs-core.js(Go5MovieAttrsCore.aiHint)が唯一の正本＝候補バッジも
  //   動画作成タブのAIチェックも同一規則で判定し、「バッジはAI・でもチェックは入らない」の食い違いを封じる。
  //   同人AIは genre/floor に「AI」が載らない作品があるため worker明示フラグ ai を最優先で見る。
  //   フラグが無ければ genre/floor を /AI/ 走査(全角ＡＩも半角化)でベストエフォート判定(core内で同処理)。
  function isAiWork_(genres, floor, ai) {
    if (window.Go5MovieAttrsCore) return window.Go5MovieAttrsCore.aiHint({ genres: genres, floor: floor, ai: ai });
    if (ai) return true;
    return (genres || []).concat(floor ? [String(floor)] : []).some(function (g) { return /AI/i.test(toHalfWidth_(g)); });
  }

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
  var PCCOLS_MIN = 1, PCCOLS_MAX = 5, PCCOLS_DEF = 4; // 既定4列(Chami依頼2026-08-15)
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

  // ── 候補一覧のページ分け(1ページの表示数で分割・Chami依頼2026-08-15) ──
  //   スマホで候補が数百件になると、全カードの作品サムネ＋動画生成用画像を一度に描く→iOS Safariが
  //   画像デコードを間引いて「サムネや追加画像が表示されない」状態になる。1ページ分だけ描くことで
  //   同時描画点数を抑える(=Chami「画像や作品サムネが表示されない」の主因への対策も兼ねる)。
  var K_PAGESIZE = 'cand_page_size';
  var PAGESIZE_DEF = 30, PAGESIZE_OPTS = [20, 30, 50, 100];
  function candPageSize_() { var n = parseInt(lsGet(K_PAGESIZE, String(PAGESIZE_DEF)), 10); return (PAGESIZE_OPTS.indexOf(n) >= 0) ? n : PAGESIZE_DEF; }
  function candPageSizeHtml_() {
    var cur = candPageSize_(), opts = PAGESIZE_OPTS.map(function (n) { return '<option value="' + n + '"' + (n === cur ? ' selected' : '') + '>' + n + '件</option>'; }).join('');
    return '<div class="cand-pagesize-ctl"><label class="hint" style="margin:0;white-space:nowrap;">1ページの表示数</label><select id="candPageSizeSel">' + opts + '</select></div>';
  }
  // ページ番号の窓(先頭・末尾・現在±1を残し、間は … で省略)。0=省略記号のしるし。
  function pageWindow_(page, pages) {
    var want = [1, page - 1, page, page + 1, pages], res = [];
    want.sort(function (a, b) { return a - b; });
    want.forEach(function (n) { if (n < 1 || n > pages) return; if (res.length && n === res[res.length - 1]) return; res.push(n); });
    var out = [];
    for (var i = 0; i < res.length; i++) { if (i > 0 && res[i] - res[i - 1] > 1) out.push(0); out.push(res[i]); }
    return out;
  }
  function candPagerHtml_(page, pages, total, startI, count) {
    if (pages <= 1) return '';
    var b = '<button type="button" class="cand-page-btn" data-candpage="' + (page - 1) + '"' + (page <= 1 ? ' disabled' : '') + '>‹ 前</button>';
    pageWindow_(page, pages).forEach(function (n) {
      if (n === 0) { b += '<span class="cand-page-ellip">…</span>'; return; }
      b += '<button type="button" class="cand-page-btn' + (n === page ? ' active' : '') + '" data-candpage="' + n + '">' + n + '</button>';
    });
    b += '<button type="button" class="cand-page-btn" data-candpage="' + (page + 1) + '"' + (page >= pages ? ' disabled' : '') + '>次 ›</button>';
    var from = total ? startI + 1 : 0, to = startI + count;
    return '<div class="cand-pager">' + b + '</div><div class="cand-pager-info hint">' + from + '–' + to + '件 / 全' + total + '件(' + page + '/' + pages + 'ページ)</div>';
  }

  // ── 保存キー ──
  var K_ITEMS = 'cand_items';   // 候補リスト(共通): [{url,cid,title,author,thumb,listPrice,price,discountPct,addedAt}]
  var K_TABS = 'cand_tabs';    // サークルタブ: [{id,name,makerId,makerName}]
  // 組込タブ(buzz/main/all)の表示名だけの上書き。{buzz,main,all}。絵文字は固定・テキストのみ差し替え。
  //   端末ローカル(storage-keys 未登録=既定で非同期)。直接 localStorage を使い schedulePoolSync_(cand_tabs監視)を誤発火させない。
  var K_TABLABELS = 'cand_tab_labels';
  var BUILTIN_TAB_DEFAULTS = { buzz: 'バズ', main: '手動追加', all: '全候補' }; // ★main の既定は「手動追加」(Chami依頼)
  var BUILTIN_TAB_EMOJI = { buzz: '🦋', main: '💡', all: '📚' };
  function builtinTabLabels_() { try { return JSON.parse(localStorage.getItem(K_TABLABELS) || '{}') || {}; } catch (e) { return {}; } }
  // 組込タブの表示ラベル(テキストのみ)。上書きが無ければ既定を返す。_activeTab 値や分岐には一切関与しない=表示専用。
  function builtinTabLabel_(id) {
    var v = builtinTabLabels_()[id];
    if (typeof v === 'string' && v.trim()) return v.trim();
    return BUILTIN_TAB_DEFAULTS[id] || id;
  }
  // 組込タブの表示ラベルを保存。空 or 既定と同じなら上書きを外す(=既定に戻す)。schedulePoolSync_ 誤発火回避で直接 setItem。
  function setBuiltinTabLabel_(id, name) {
    var over = builtinTabLabels_();
    name = (name || '').trim();
    if (name && name !== (BUILTIN_TAB_DEFAULTS[id] || id)) over[id] = name; else delete over[id];
    try { localStorage.setItem(K_TABLABELS, JSON.stringify(over)); } catch (e) {}
  }
  // 組込タブ(バズ/手動追加/全候補)の表示名だけを変更する小フォーム。改名専用=削除・サークル・全候補除外は無し
  //   (サークル/独立タブ用 showEditTabForm とは別物)。containerId の要素へ差し込み、保存で render() し直す。
  function showEditBuiltinTabForm_(id, containerId) {
    var f = $(containerId || 'candEditForm');
    if (!f) return;
    var emoji = BUILTIN_TAB_EMOJI[id] || '';
    f.innerHTML = '<div class="card" style="margin:8px 0;">' +
      '<div class="field-label" style="margin-top:0;">✏️ タブ名を変更</div>' +
      '<label class="hint" style="display:block;margin-bottom:2px;">' + esc(emoji) + ' のタブ名(絵文字はそのまま・文字だけ変わります)</label>' +
      '<input id="candBiName" type="text" autocomplete="off" value="' + esc(builtinTabLabel_(id)) + '">' +
      '<div class="hint" style="margin-top:6px;">空にして保存すると既定(' + esc(BUILTIN_TAB_DEFAULTS[id] || id) + ')に戻ります。</div>' +
      '<div style="display:flex;gap:8px;margin-top:8px;">' +
      '<button id="candBiSave" type="button" class="primary" style="flex:1;font-size:.9rem;padding:10px;">保存</button>' +
      '<button id="candBiCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;">やめる</button>' +
      '</div></div>';
    $('candBiCancel').addEventListener('click', function () { f.innerHTML = ''; });
    $('candBiSave').addEventListener('click', function () { setBuiltinTabLabel_(id, $('candBiName').value || ''); f.innerHTML = ''; render(); });
  }
  // 組込タブの「✏️ 名前」ボタン(id=candEditBuiltin)を配線。フォームは candEditForm へ出す。
  function wireBuiltinRename_(id) {
    var b = $('candEditBuiltin');
    if (b) b.addEventListener('click', function () { showEditBuiltinTabForm_(id, 'candEditForm'); });
  }
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
  var _workSearchByTab = {};
  var _memoSearchByTab = {}; // メモ/コメント検索の入力をタブ別に保持(Chami依頼2026-08-11)
  var _candPageByTab = {};   // 候補一覧の現在ページをタブ別に保持(ページ分け・Chami依頼2026-08-15)
  var DUPLICATE_WORK_NOTICE = '同じ作品が既に追加されているので統合';
  // 重複追加は分かりにくいinline通知ではなくダイアログで明示する(Chami指定2026-07-24)。
  //   重複した時「だけ」出す。今回入力していたメモがあれば改行して2行目に表示する。
  //   ★ブラウザ標準のalertではなくアプリ内モーダルで出す(Chami再指定2026-07-26)。標準alertは
  //     iPhoneでドメイン名が出て安っぽく、アプリの配色にも合わないため。既存のfz-overlay方式に揃える。
  //   閉じたら、既に登録済みだった該当作品カードへ即座に移動する(スクロールではなくパッと移動)。
  var _dupOverlay = null;
  function showDuplicateDialog_(memoText, cid) {
    var memo = (memoText || '').trim();
    var ov = _dupOverlay;
    if (!ov) {
      ov = document.createElement('div'); ov.className = 'fz-overlay dup-overlay'; ov.hidden = true;
      ov.innerHTML = '<div class="fz-modal dup-modal">' +
        '<div class="dup-title">⚠️ <span id="dupTitleText"></span></div>' +
        '<div id="dupMemo" class="dup-memo"></div>' +
        '<button id="dupOk" type="button" class="primary dup-ok">OK</button>' +
        '</div>';
      document.body.appendChild(ov);
      _dupOverlay = ov;
    }
    ov.querySelector('#dupTitleText').textContent = DUPLICATE_WORK_NOTICE;
    var memoEl = ov.querySelector('#dupMemo');
    memoEl.textContent = memo;      // メモは改行して2行目に表示(textContent＝HTML混入なし)
    memoEl.hidden = !memo;
    function close() {
      ov.hidden = true;
      document.removeEventListener('keydown', onKey);
      if (cid) jumpToCandCard_(cid);
    }
    function onKey(e) { if (e.key === 'Escape' || e.key === 'Enter') { e.preventDefault(); close(); } }
    var ok = ov.querySelector('#dupOk');
    ok.onclick = close;                                        // onclickで毎回上書き＝リスナー多重登録を防ぐ
    ov.onclick = function (e) { if (e.target === ov) close(); }; // 背景タップでも閉じる
    document.addEventListener('keydown', onKey);
    ov.hidden = false;
    try { ok.focus({ preventScroll: true }); } catch (e) {}
  }
  // 指定cidの候補カードへ瞬時に移動して一時ハイライト。(behavior:'auto'＝スクロールアニメ無しで即座に表示)
  //   モーダルを閉じた直後は再描画が走ることがあるため、少し待ってから探す。見つからなければ何もしない。
  function jumpToCandCard_(cid) {
    var tries = 0;
    (function seek() {
      var anchor = document.querySelector('[data-refimg="' + (window.CSS && CSS.escape ? CSS.escape(cid) : cid) + '"]');
      var card = anchor;
      while (card && !(card.classList && card.classList.contains('cand-card'))) card = card.parentNode;
      if (!card) { if (++tries < 10) { setTimeout(seek, 80); } return; }
      try { card.scrollIntoView({ behavior: 'auto', block: 'center' }); } catch (e) {}
      card.classList.add('cand-card-flash');
      setTimeout(function () { card.classList.remove('cand-card-flash'); }, 2000);
    })();
  }
  // 絞り込み：現在価格が _priceMax 円以下の作品のみ表示(0=無効)。localStorageで永続。
  var _priceMax = (function () { try { var n = parseInt(localStorage.getItem('cand_price_max') || '0', 10); return (n > 0) ? n : 0; } catch (e) { return 0; } })();
  // アカウント別「投稿済みを非表示」トグル。(両方同時ONで、いずれかで投稿済みの作品を隠せる)localStorageで永続。
  var _hidePosted = (function () { try { return JSON.parse(localStorage.getItem('cand_hide_posted') || '{}') || {}; } catch (e) { return {}; } })();
  function saveHidePosted_() { try { localStorage.setItem('cand_hide_posted', JSON.stringify(_hidePosted)); } catch (e) {} }
  // ★「このchでは投稿していない」ユーザー宣言の恒久オーバーライド。({acc:{cid:ts}})
  //   投稿履歴レコードを消すだけだと、シート再マージ/DID矯正の移動/リビルド等がyt-clicks側で
  //   short_hist__/verify_manual__ を再投入して pill が復活する(「手動で外しても復元される」の真因)。
  //   復元経路を全部塞ぐ代わりに、ユーザーの宣言を durable に持ち、pill判定で常に尊重する(Chami依頼2026-07-30)。
  var _postedOff = (function () { try { var m = JSON.parse(localStorage.getItem('cand_posted_off') || '{}'); return (m && typeof m === 'object') ? m : {}; } catch (e) { return {}; } })();
  function savePostedOff_() { try { localStorage.setItem('cand_posted_off', JSON.stringify(_postedOff)); } catch (e) {} }
  // この作品(取りうる全cidキー)は、このアカウントで「投稿していない」と宣言済みか。
  function isPostedOff_(keys, account) {
    var m = _postedOff[account]; if (!m) return false;
    for (var i = 0; i < (keys || []).length; i++) { if (m[keys[i]] != null) return true; }
    return false;
  }
  // 宣言を立てる/解除する。cid＝ヒットした照合キー(pillのdata-posted-cidと一致)。
  function setPostedOff_(cid, account, on) {
    if (!cid || !account) return;
    if (!_postedOff[account]) _postedOff[account] = {};
    if (on) _postedOff[account][String(cid)] = new Date().getTime();
    else delete _postedOff[account][String(cid)];
    savePostedOff_();
  }
  // ★「このchで投稿済み」ユーザー宣言の恒久オーバーライド(setPostedOff_ の対称)。({acc:{cid:ts}})
  //   用途= 実際は投稿したのに ✔ が付かない場合の手動救済(Chami依頼 REQ-428b755f51「投稿済みなのに✅が
  //   入ってない場合の対処法が現在ない」)。シート権威索引(S1)にも記録が無い偽陰性の逃げ道＝端末ローカルに宣言を
  //   durable に持ち、pill判定で常に投稿済み扱いにする。※オフ宣言が同時にあればオフを優先(下の postedMatchForCand_)。
  var _postedOn = (function () { try { var m = JSON.parse(localStorage.getItem('cand_posted_on') || '{}'); return (m && typeof m === 'object') ? m : {}; } catch (e) { return {}; } })();
  function savePostedOn_() { try { localStorage.setItem('cand_posted_on', JSON.stringify(_postedOn)); } catch (e) {} }
  function isPostedOn_(keys, account) {
    var m = _postedOn[account]; if (!m) return false;
    for (var i = 0; i < (keys || []).length; i++) { if (m[keys[i]] != null) return true; }
    return false;
  }
  function postedOnTs_(keys, account) {
    var m = _postedOn[account]; if (!m) return 0;
    for (var i = 0; i < (keys || []).length; i++) { if (m[keys[i]] != null) return m[keys[i]]; }
    return 0;
  }
  function setPostedOn_(cid, account, on) {
    if (!cid || !account) return;
    if (!_postedOn[account]) _postedOn[account] = {};
    if (on) _postedOn[account][String(cid)] = new Date().getTime();
    else delete _postedOn[account][String(cid)];
    savePostedOn_();
  }
  function isHiddenByPosted_(it) {
    if (!it) return false;
    if (_hidePosted.acc1 && postedMatchForCand_(it, 'acc1')) return true;
    if (_hidePosted.acc2 && postedMatchForCand_(it, 'acc2')) return true;
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
  var K_SALES = 'cand_sales';       // {cid:{n:(number|null), unavailable?:true, at}}
  var K_SALESSNAP = 'cand_salessnap'; // {cid:[{at,n}]}  週次差分用
  var SALES_TTL = 24 * 3600 * 1000, SALES_MISS_TTL = 15 * 60 * 1000;
  function salesCache() { return lsGet(K_SALES, '{}'); }
  function salesOf(cid) { // number=実売 / null=PC待ち / 'unavailable'=取得不可 / undefined=キャッシュ切れ
    var c = salesCache()[cid]; if (!c) return undefined;
    var ttl = (c.unavailable || c.n != null) ? SALES_TTL : SALES_MISS_TTL;
    if (new Date().getTime() - c.at >= ttl) return undefined;
    return c.unavailable ? 'unavailable' : c.n;
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
    cids = (cids || []).filter(function (cid) { return /^d_[0-9A-Za-z]+$/i.test(String(cid || '')); });
    var cache = salesCache(), need = [], now = new Date().getTime();
    cids.forEach(function (cid) {
      var c = cache[cid], ttl = (c && (c.unavailable || c.n != null)) ? SALES_TTL : SALES_MISS_TTL;
      if (!c || (now - c.at) >= ttl) need.push(cid);
    });
    need = need.filter(function (v, i, a) { return a.indexOf(v) === i; });
    if (!need.length) { cb(false, missingCount(cids)); return; }
    var cfg = workerCfg(); if (!cfg.url) { cb(false, 0); return; }
    var chunks = []; for (var i = 0; i < need.length; i += 30) chunks.push(need.slice(i, i + 30));
    var pending = chunks.length, nextChunk = 0, changed = false;
    function doneOne_() {
      pending--;
      if (pending === 0) cb(changed, missingCount(cids));
      else runNext_();
    }
    function runNext_() {
      if (nextChunk >= chunks.length) return;
      var ch = chunks[nextChunk++];
      fetch(cfg.url + '/api/fanza-sales', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret }, body: JSON.stringify({ cids: ch }) })
        .then(function (r) { return r.json(); }).then(function (d) {
          if (d && d.ok) {
            var c = salesCache(), t = new Date().getTime(), s = d.sales || {};
            var unavailable = {};
            (d.unavailable || []).concat(d.unsupported || []).forEach(function (cid) { unavailable[cid] = true; });
            ch.forEach(function (cid) {
              var prev = c[cid], next;
              if (s[cid] != null) next = { n: s[cid], at: t };
              else if (unavailable[cid]) next = { n: null, unavailable: true, at: t };
              else next = { n: null, at: t };
              if (next.n != null || next.unavailable || (prev && (!!prev.unavailable !== !!next.unavailable))) changed = true;
              c[cid] = next;
            });
            lsSet(K_SALES, c); recordSalesSnapshots(s);
          }
          doneOne_();
        }).catch(doneOne_);
    }
    for (var worker = 0; worker < Math.min(3, chunks.length); worker++) runNext_();
  }
  function missingCount(cids) {
    var n = 0;
    (cids || []).forEach(function (cid) { var v = salesOf(cid); if (v === null || v === undefined) n++; });
    return n;
  }
  // 指定cidの販売数キャッシュを無効化。(🔁リロードで最新を取り直すため)
  function invalidateSales_(cids) { var c = salesCache(); (cids || []).forEach(function (cid) { delete c[cid]; }); lsSet(K_SALES, c); }

  // ── 候補の「タイトル/発売日 未取得」を自動でバックフィル ──
  //   追加した直後、FANZA workerがその時たまたま部分情報(画像のみ)しか返せなかった作品は
  //   title/date が空のまま残り、作品状態(新作/準新作/旧作)バッジも出ない。販売数(fetchSalesFor)と
  //   同じパターンで、表示のたびに未取得ぶんを控えめに再取得し、取れたら候補データへ書き戻す。
  var K_INFOMISS = 'cand_infomiss'; // {cid:{at,n}} 直近の再取得試行時刻と試行回数(無駄打ち防止＋追加直後は素早く追う)
  var INFOMISS_RETRY_TTL = 20 * 60 * 1000; // 落ち着いた後の再試行間隔(20分に1回)
  var INFOMISS_FAST_TTL  = 25 * 1000;      // 追加直後の未取得は素早く再取得(25秒に1回)
  var INFOMISS_FAST_TRIES = 6;             // 素早い再取得はこの回数まで(以後は20分間隔へ落として無駄打ちを防ぐ)
  // 旧形式(数値=試行時刻のみ)との後方互換で {at,n} に正規化する。
  function missRec_(miss, cid) {
    var r = miss[cid];
    if (r == null) return null;
    if (typeof r === 'number') return { at: r, n: 1 };
    return { at: r.at || 0, n: r.n || 0 };
  }
  function needsInfoBackfill_(it) {
    return isInfoTarget_(it) && (
      !it.title || it.title === '(タイトル未取得)' || !it.date || it.reviewCount == null ||
      // ★「情報は取れたがサムネだけ空」も追う(Chami 2026-08-17「候補で画像読み込まない時多すぎ」・Fable5診断C)。
      //   核(title/date)とgenre/floorが揃った thumb 欠けは infoBackfillTtl_ で24hに1回=fast追跡には乗らない
      //   ので無限再取得にはならない。取得成功で it.thumb が埋まれば対象から外れる。
      !it.thumb ||
      // ★AI判定に使う genre/floor が未取得の既存候補も追う=genre/floor を保存するようになる前に
      //   追加された作品は title/価格が揃っていてもタグが空のまま=AIバッジが出ない(Chami 2026-08-12
      //   「追加済みの候補に判定が入るようにして」)。floor は取得成功で doujin なら「同人」等が必ず入る
      //   ため、一度取れれば下の条件は false になり追跡は止まる(無限再取得にはならない)。
      (!(it.genres && it.genres.length) && !it.floor)
    );
  }
  function coreInfoMissing_(it) {
    return !it || !it.title || it.title === '(タイトル未取得)' || !it.date;
  }
  function infoBackfillTtl_(it, rec) {
    // タイトル等が揃い、レビュー数だけ薄い時は1日1回で十分。
    // ★核(タイトル/発売日)が欠けている間は、回数で20分間隔へ落とさず一定間隔で追い続ける
    //   (諦めない・Chami 2026-08-04「引き続き取得するようにして諦めないで」)。実際に叩くのは
    //   候補タブを見ている間の再描画時だけ(scheduleInfoTick_)なので、離席中はworkerを叩かない。
    if (!coreInfoMissing_(it)) {
      // 核(タイトル/発売日)は揃っているが genre/floor が未取得＝AI判定に要る＝素早く1回取りに行く。
      //   取得成功で floor が埋まり needsInfoBackfill_ の対象から外れる＝無限再取得にはならない。
      if (!(it.genres && it.genres.length) && !it.floor) return INFOMISS_FAST_TTL;
      return 24 * 3600 * 1000;
    }
    return INFOMISS_FAST_TTL;
  }
  // 核(タイトル/発売日)がまだ欠けている候補が残っているか(=タブを見ている間に自動で追う対象)。
  //   ★回数上限(INFOMISS_FAST_TRIES)では止めない=情報が揃うか、タブを離れるまで追い続ける(諦めない)。
  function hasFastPendingInfo_(items) {
    return (items || []).some(function (it) {
      // 核(タイトル/発売日)未取得に加え、genre/floor 未取得(AI判定用)もタブ表示中は素早く追う。
      //   review数だけ薄い候補は従来どおり fast 対象外(24hに1回)のまま。
      return needsInfoBackfill_(it) && (coreInfoMissing_(it) || (!(it.genres && it.genres.length) && !it.floor));
    });
  }
  function backfillMissingInfo_(key, items, cb) {
    if (!window.FanzaCore) { cb(false); return; }
    var cfg = workerCfg(); if (!cfg.url) { cb(false); return; }
    var miss = lsGet(K_INFOMISS, '{}'), now = new Date().getTime();
    var targets = items.filter(function (it) {
      if (!needsInfoBackfill_(it)) return false;
      var rec = missRec_(miss, it.cid); return !rec || (now - rec.at) >= infoBackfillTtl_(it, rec);
    }).slice(0, 12); // 一度に叩きすぎない(無駄打ち防止・worker保護)
    if (!targets.length) { cb(false); return; }
    var pending = targets.length, updates = {}; // cid -> 取得できた差分フィールド
    targets.forEach(function (it) {
      var prev = missRec_(miss, it.cid);
      miss[it.cid] = { at: now, n: (prev ? prev.n : 0) + 1 };
      // 一時失敗(タイムアウト/5xx=retryable)は追加時と同じく1回だけ即リトライしてから諦める(スマホ回線の単発失敗で20分待たせない)。
      var once = function () { return window.FanzaCore.fetchFanzaInfo(it.cid, cfg.url, cfg.secret, it.url); };
      once().then(function (info) {
        if (info && info.title) return info;
        if (info && info.retryable) return once();
        return info;
      }).then(function (info) {
        if (info && info.title) {
          updates[it.cid] = {
            title: info.title, author: info.author || undefined,
            date: info.releaseDate || undefined, listPrice: info.listPrice, price: info.price,
            discountPct: info.discountPct || undefined, genres: (info.genres && info.genres.length) ? info.genres : undefined,
            floor: info.floor || undefined, service: info.service || undefined,
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
        Object.keys(u).forEach(function (f) {
          if (u[f] !== undefined && JSON.stringify(it[f]) !== JSON.stringify(u[f])) { it[f] = u[f]; changed = true; }
        });
      });
      if (changed) lsSet(key, cur);
      cb(changed);
    }
  }

  // 追加直後の未取得タイトルを、タブ表示中に自動で追いかける自己再予約タイマー。
  //   素早い再取得フェーズ(n<INFOMISS_FAST_TRIES)の未取得が残る間だけ、TTLより少し長い間隔で
  //   1回だけ再描画を予約する。再描画が backfill を回し、まだ残れば scheduleInfoTick_ が再度予約する
  //   ＝取れきる/回数上限/タブ離脱 のいずれかで自然に止まる(無限ループ・多重予約なし)。
  var _infoTickTimer = null;
  function scheduleInfoTick_(tabId, items) {
    if (_infoTickTimer) return;                // 二重予約しない
    if (!hasFastPendingInfo_(items)) return;   // 追う対象が無ければ止める
    _infoTickTimer = setTimeout(function () {
      _infoTickTimer = null;
      if (_activeTab === tabId) renderCandList(tabId); // 再描画→backfill→(まだ残れば)再予約
    }, INFOMISS_FAST_TTL + 3000);              // TTLより少し長く=再描画時に必ず再取得が解禁される
  }

  // 「ユーザーが見に来た」瞬間(タブへ戻る/アプリ再前面化)に、素早い再取得フェーズ(25秒×6回)を
  //   使い切って20分間隔へ落ちてしまった核未取得の候補を、もう一度素早く追う状態へ戻す。
  //   ★試行回数(n)だけ0に戻し、直近試行時刻(at)は残す＝直後の連続再描画では叩かず、25秒経てば
  //   backfillが解禁され、hasFastPendingInfo_→scheduleInfoTick_の自動追跡も再開する。
  //   取れきる/回数上限/タブ離脱で再び自然に落ち着く(無限ポーリングにならない)。
  function kickInfoBackfill_() {
    try {
      var key = itemsKey(_activeTab), items = lsGet(key, '[]');
      var miss = lsGet(K_INFOMISS, '{}'), changed = false;
      items.forEach(function (it) {
        if (!needsInfoBackfill_(it) || !coreInfoMissing_(it)) return;
        var rec = missRec_(miss, it.cid);
        if (rec && rec.n >= INFOMISS_FAST_TRIES) { miss[it.cid] = { at: rec.at, n: 0 }; changed = true; }
      });
      if (changed) lsSet(K_INFOMISS, miss);
    } catch (e) {}
  }

  // 壁で未判定のまま aiChecked が付かない候補のハンマリング防止(cid→最終試行ms・10分TTL)。
  var _aiTried = {}, AI_TRY_TTL_MS = 10 * 60 * 1000;
  // 同人候補のAI生成判定を「一度だけ」確定する。★AIはジャンルタグにも floor 名にも載らず、FANZAの
  //   必須開示文(作品説明の「AI生成」)にしか出ない作品がある(実測 d_748630)。worker に checkAi を渡して
  //   ページ由来のAIフラグを取りに行き、it.ai を立てる。1候補につき一度きり(it.aiChecked)＝取れなくても
  //   「確認済み」にして二度は叩かない(DMMへの無駄打ち・無限ポーリングを防ぐ)。タブ表示中のみ・12件ずつ。
  //   ★既存候補(=追加済み)にも判定が後から届く(Chami 2026-08-12「追加されてる候補に判定が入るように」)。
  function aiRecheck_(key, items, cb) {
    if (!window.FanzaCore) { cb(false); return; }
    var cfg = workerCfg(); if (!cfg.url) { cb(false); return; }
    var now = Date.now();
    // ★未検証(壁でworkerが読めず aiChecked が付かない)候補は次回リロードで再挑戦できるよう it.aiChecked を立てない。
    //   ただし毎描画で叩き続けると壁作品にハンマリングするため、_aiTried で10分間は同cidを再叩きしない。
    var targets = (items || []).filter(function (it) {
      return isSalesTarget_(it) && it.title && it.title !== '(タイトル未取得)' && !it.ai && !it.aiChecked
        && (!_aiTried[it.cid] || (now - _aiTried[it.cid]) >= AI_TRY_TTL_MS);
    }).slice(0, 12);
    if (!targets.length) { cb(false); return; }
    var pending = targets.length, updates = {};
    targets.forEach(function (it) {
      _aiTried[it.cid] = now;
      window.FanzaCore.fetchFanzaInfo(it.cid, cfg.url, cfg.secret, it.url, { checkAi: true }).then(function (info) {
        // verified=判定が確定した時だけ(AI開示ヒット or 検証済みfalse)。壁で未判定(!ai && !aiChecked)は凍結しない。
        if (info && info.title) updates[it.cid] = { ai: !!info.ai, verified: !!(info.ai || info.aiChecked) };
        if (--pending === 0) finish();
      }).catch(function () { if (--pending === 0) finish(); });
    });
    // 書き戻しは現在のlocalStorage配列に対して差分だけ当てる(他の変更を巻き戻さない・backfillと同じ考え方)。
    function finish() {
      var cids = Object.keys(updates); if (!cids.length) { cb(false); return; }
      var cur = lsGet(key, '[]'), changed = false;
      cur.forEach(function (it) {
        if (!it || it.cid == null || !(it.cid in updates)) return;
        if (updates[it.cid].ai && !it.ai) { it.ai = true; changed = true; }
        if (updates[it.cid].verified && !it.aiChecked) { it.aiChecked = true; changed = true; } // 検証済みの時だけ確定(未確認は次回リトライ可)
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
  var _imgMem = { ref: {}, bsky: {}, post: {}, used: {} };
  var _idbOk = !!(window.Go5Idb && window.Go5Idb.available());
  // ★IDB→メモリへの展開(hydrateImages_)は非同期。完了前は _imgMem が空なので refImgOf() が
  //   「実際にはIDBに在るのに null」を返す=モーダルのpendingが全項目空で作られ、そのまま保存すると
  //   refImgSaveのempty判定に入り【画像もコメントも削除】されていた。(Chami報告2026-07-17
  //   「動画生成へ進むと候補用画像とコメントが候補から消える・作り直せない」の真因。画像が多い/重い
  //   ほど展開が遅く、間欠的に発火する。commit 2a16fceが直したのは別件=書込完了待ちで、この競合は
  //   残っていたためChamiの「多分治ってない」は正しかった)
  //   → 展開の完了フラグと待ち合わせを持ち、(1)未展開のうちは破壊的な空保存を拒否 (2)モーダルは
  //     展開を待ってから開く、の二段で防ぐ。
  var _hydrated = false;                          // ref/bsky/post/used の全種類が展開済み
  var _candidateHydrated = false;                 // 候補ページに必要な ref/bsky が展開済み
  var _hydrateWaiters = [];
  var _refLoaded = Object.create(null);           // 全体展開前でも作品単位で安全に読めたcid
  var _refLoadJobs = Object.create(null);
  var _candidateHydrateInFlight = false;
  var _candidateHydrateRetryTimer = null;
  var _candidateHydrateFailures = 0;
  var _hydrateFailSince = 0;                        // 現在の失敗連鎖の開始時刻。案内バーは「持続」を確かめてから出す(誤発火防止)。
  var _syncRehydrateRetryTimer = null;
  var _histHydrateFailures = 0;                    // 投稿履歴画像(post:/used:)の展開失敗回数
  var _histHydrateRetryTimer = null;              // 同・張り直し予約(同時に1本だけ)
  // 展開成功/回復のたびに失敗連鎖をゼロへ戻す(件数と開始時刻を対で戻す=案内バーの持続ゲートが正しく効く)。
  function resetCandidateHydrateFailures_() { _candidateHydrateFailures = 0; _hydrateFailSince = 0; }
  // ★「閉じて開き直せ」案内バーを出してよいかの唯一の判定(純関数=tests/test_idb_hint_gate.js で検証)。
  //   短い接続死では出さず、5回以上連続で失敗し かつ 連鎖が60秒以上続いた(=回復せず本当にプロセス単位で
  //   死んでいる)時だけ true。sinceMs=連鎖開始時刻(0=連鎖なし)。Chami報告2026-08-18「案内がめちゃくちゃ出る」対策。
  //   ★60000(=60秒)は関数内リテラルで持つ。Node(テスト)では上の module.exports で早期returnするため、
  //   var の代入行(このブロックより後)は実行されず undefined になる=定数を外の var に置くと壊れる。
  function shouldShowIdbHint_(failures, sinceMs, nowMs) {
    return failures > 4 && !!sinceMs && (nowMs - sinceMs) >= 60000; // 60秒=持続死のしきい
  }
  function markCandidateHydrated_() {
    if (_candidateHydrated) return;
    _candidateHydrated = true;
    _hydrateWaiters.splice(0).forEach(function (f) { try { f(); } catch (e) {} });
    try { document.dispatchEvent(new CustomEvent('go5-candidate-images-hydrated')); } catch (e) {}
  }
  function markHydrated_() {
    markCandidateHydrated_();
    if (_hydrated) return;
    _hydrated = true;
    // ★画像がメモリに載った合図を全ページへ発火する。投稿履歴/ランキング(yt-clicks.js)は起動直後に一度だけ
    //   Go5Cand.usedImgs()を同期で読んで「動画で使った画像」を描くが、その時点でハイドレート未了だと空になり、
    //   タブをもう一度タップするまで画像が出なかった(Chami「動画に使った画像が表示されない・すぐ表示して」
    //   2026-08-11 / DEF-de2408cb00と同型)。ハイドレート完了をイベントで知らせ、履歴側が自動で描き直す。
    try { document.dispatchEvent(new CustomEvent('go5-images-hydrated')); } catch (e) {}
  }
  function whenImagesReady_(cb) {                 // 候補用(ref/bsky)が展開済みなら即時、未了なら完了時に呼ぶ
    if (_candidateHydrated || !_idbOk) { cb(); return; }
    var done = false, fire = function () { if (done) return; done = true; cb(); };
    _hydrateWaiters.push(fire);
    setTimeout(fire, 3000);                       // 保険(追加処理側は未完了なら保存せず案内する)
  }
  function refImgKey(cid) { return 'cand_refimg__' + cid; }   // localStorage互換キー(フォールバック/移行用)
  function bskyImgKey(cid) { return 'cand_bskyimg__' + cid; }
  function idbKey(kind, cid) { return kind + ':' + cid; }     // IDBキー 'ref:<cid>' / 'bsky:<cid>'
  function idbFail_(e) { try { console.warn('[go5 idb] 画像保存に失敗(メモリには保持)', e); } catch (_) {} }

  // ── 候補テキストの正本 cand_text(同期LS単一マップ)──────────────────────────────────
  // ★INC-127→129→132 の恒久対策(断定1)。コメント・メモ・X URL・URL2 は従来 IDB(_imgMem.ref)に
  //   持っていたが、IDB→メモリ展開(hydrateImages_)が非同期のため「ハイドレート完了前に描画されて空に見える」
  //   構造が残っていた(ページ移動/再読込で直る=描画時に読めていないだけ)。テキストは容量が小さいので、
  //   localStorage の単一マップ cand_text = { "<cid>": {comment,memo,twitterUrl,twitterUrl2,urls2,at} } を
  //   正本へ昇格＝同期read/writeで初回描画から必ず読める。画像(imgs)は容量的にLS不可なので従来のIDB経路のまま。
  //   同期は core/sync.js が cand_text を cid 単位フィールドマージで扱う(whole-key LWWにしない=別端末の消失防止)。
  function candTextKey_() { return 'cand_text'; }             // hoisted=Node(テスト)から順序非依存で参照可
  var _candTextCache = { raw: null, map: {} };                // LS文字列が同一なら再parseしない軽量キャッシュ
  function candTextMap_() {
    var raw; try { raw = localStorage.getItem(candTextKey_()) || ''; } catch (e) { raw = ''; }
    if (_candTextCache && raw === _candTextCache.raw) return _candTextCache.map;
    var m = {};
    try { var p = JSON.parse(raw || '{}'); if (p && typeof p === 'object' && !Array.isArray(p)) m = p; } catch (e) {}
    _candTextCache = { raw: raw, map: m };
    return m;
  }
  function candTextOf_(cid) {                                 // 1件を同期で返す(無ければ null)
    var m = candTextMap_(), v = m[String(cid)];
    return (v && typeof v === 'object' && !Array.isArray(v)) ? v : null;
  }
  function candTextNonEmpty_(r) { return !!(r && (r.comment || r.memo || r.twitterUrl || r.twitterUrl2 || (r.urls2 && r.urls2.length))); }
  // read-modify-write。空項目は空として保存(=正当な全消しを許す)。全項目が空なら該当cidを削除。
  // at 明示可(移行バックフィルは元recのatを保つ=古い値が新しいatで同期の勝者になるのを防ぐ)。戻り値=真の成否。
  function candTextWrite_(cid, data, at) {
    cid = String(cid || ''); if (!cid) return false;
    var map;
    try { map = JSON.parse(localStorage.getItem(candTextKey_()) || '{}'); if (!map || typeof map !== 'object' || Array.isArray(map)) map = {}; } catch (e) { map = {}; }
    var comment = (data && data.comment) || '';
    var memo = (data && data.memo) || '';
    var twitterUrl = (data && data.twitterUrl) || '';
    var urls2 = [];
    if (data) {
      if (Array.isArray(data.urls2)) urls2 = data.urls2.map(function (s) { return String(s || '').trim(); }).filter(Boolean);
      else if (data.twitterUrl2) urls2 = [String(data.twitterUrl2).trim()].filter(Boolean);
    }
    var allEmpty = !comment && !memo && !twitterUrl && !urls2.length;
    if (allEmpty) {
      if (!Object.prototype.hasOwnProperty.call(map, cid)) return true; // 既に無い=何もしない(成功扱い)
      delete map[cid];
    } else {
      map[cid] = { comment: comment, memo: memo, twitterUrl: twitterUrl, twitterUrl2: urls2[0] || '', urls2: urls2, at: at || new Date().getTime() };
    }
    try {
      localStorage.setItem(candTextKey_(), JSON.stringify(map));
      _candTextCache = { raw: null, map: {} }; // 次回読みで再parse(自分の書きでキャッシュ無効化)
      reqSync_();                              // 永続保存できた内容だけを同期へ送る
      return true;
    } catch (e) { return false; } // 容量超過など
  }
  function candTextSave_(cid, data) { return candTextWrite_(cid, data, new Date().getTime()); }
  // 移行バックフィル(冪等・空で非空を上書きしない): _imgMem.ref(旧正本)のテキストを cand_text へフィールド単位で埋め戻す。
  //   cand_text 側が既に非空ならそれを優先。何も足せなければ書かない(同期の無駄打ち防止)。at は元recのatを保つ。
  function backfillCandText_(cid, rec) {
    if (!rec || typeof rec !== 'object') return false;
    cid = String(cid || ''); if (!cid) return false;
    var cur = candTextOf_(cid) || {};
    var recUrls2 = Array.isArray(rec.urls2) ? rec.urls2.filter(Boolean) : (rec.twitterUrl2 ? [String(rec.twitterUrl2).trim()].filter(Boolean) : []);
    var curUrls2 = Array.isArray(cur.urls2) ? cur.urls2.filter(Boolean) : (cur.twitterUrl2 ? [String(cur.twitterUrl2).trim()].filter(Boolean) : []);
    var next = {
      comment: cur.comment || rec.comment || '',
      memo: cur.memo || rec.memo || '',
      twitterUrl: cur.twitterUrl || rec.twitterUrl || '',
      urls2: curUrls2.length ? curUrls2 : recUrls2
    };
    var same = next.comment === (cur.comment || '') && next.memo === (cur.memo || '')
      && next.twitterUrl === (cur.twitterUrl || '') && next.urls2.join('\n') === curUrls2.join('\n');
    if (same) return false; // cand_text に既に反映済み=何も足さない
    if (!(next.comment || next.memo || next.twitterUrl || next.urls2.length)) return false; // 全空は書かない
    var at = Math.max(Number(cur.at) || 0, Number(rec.at) || 0) || new Date().getTime();
    return candTextWrite_(cid, next, at);
  }
  var _candTextBackfilled = false;
  function backfillAllCandText_() {                          // ハイドレート完了時に一度だけ全cidを埋め戻す
    if (_candTextBackfilled) return; _candTextBackfilled = true;
    try { Object.keys(_imgMem.ref).forEach(function (cid) { backfillCandText_(cid, _imgMem.ref[cid]); }); } catch (e) {}
  }

  function mergeImageEntries_(all) {
    function putLatest_(bucket, key, val) {
      var cur = bucket[key];
      // 全体cursorが走っている間に投稿編集で保存した新しいメモリ値を、古い読取結果で巻き戻さない。
      if (!cur || !cur.at || !val || !val.at || Number(val.at) >= Number(cur.at)) bucket[key] = val;
    }
    Object.keys(all || {}).forEach(function (k) {
      var v = all[k];
      if (k.indexOf('ref:') === 0) { putLatest_(_imgMem.ref, k.slice(4), v); _refLoaded[k.slice(4)] = true; backfillCandText_(k.slice(4), _imgMem.ref[k.slice(4)]); }
      else if (k.indexOf('bsky:') === 0) putLatest_(_imgMem.bsky, k.slice(5), v);
      else if (k.indexOf('post:') === 0) putLatest_(_imgMem.post, k.slice(5), v);
      else if (k.indexOf('used:') === 0) putLatest_(_imgMem.used, k.slice(5), v);
    });
  }  function readImageEntries_(prefixes) {
    // 新APIはIDBKeyRangeで必要な画像だけ読む。旧キャッシュ時だけ従来の全件走査へフォールバック。
    if (window.Go5Idb.entriesByPrefixes) return window.Go5Idb.entriesByPrefixes(prefixes);
    return window.Go5Idb.entries();
  }
  function legacyRefOf_(cid) {
    try { return JSON.parse(localStorage.getItem(refImgKey(cid)) || 'null'); } catch (e) { return null; }
  }

  // 全体ハイドレートを待たず、押された作品1件だけを直接復元する。
  // 候補画像が多い/iOSが低メモリでも「投稿編集」の入口を全体走査から切り離す。
  function ensureRefLoaded_(cid) {
    cid = String(cid || '');
    // 全体ハイドレート完了は「このcidも読めた」証明ではない。同期などで完了後にIDBへ入った
    // 作品はメモリに無いことがあるため、cid単位の既知フラグ/実体が無ければ直接getする。
    if (!cid || !_idbOk || _refLoaded[cid] || Object.prototype.hasOwnProperty.call(_imgMem.ref, cid)) {
      if (cid && Object.prototype.hasOwnProperty.call(_imgMem.ref, cid)) _refLoaded[cid] = true;
      return Promise.resolve(true);
    }
    if (_refLoadJobs[cid]) return _refLoadJobs[cid];
    var readP = (typeof window.Go5Idb.getResult === 'function')
      ? window.Go5Idb.getResult(idbKey('ref', cid))
      : window.Go5Idb.get(idbKey('ref', cid)).then(function (value) {
          return { ok: true, value: value };
        }, function (error) {
          return { ok: false, value: null, error: error };
        });
    var job = readP.then(function (result) {
      if (!result || !result.ok) {
        idbFail_(result && result.error ? result.error : new Error('idb-read-failed'));
        var old = legacyRefOf_(cid);
        if (isR2Marker_(old)) { resolveR2IntoMem_(cid, old); return false; } // マーカーはR2から実体化(メモリ/IDBへ生で入れない)
        if (old) { _imgMem.ref[cid] = old; _refLoaded[cid] = true; return true; }
        return false; // 読取失敗を「存在しない」と誤認せず、空の上書きを許可しない
      }
      var rec = result.value;
      if (rec) {
        _imgMem.ref[cid] = rec;
        backfillCandText_(cid, rec); // 直読1件も同期LSへ昇格
      } else {
        // 旧localStorage形式が残っている端末は、この1件も移行完了前に安全に拾う。
        var legacy = legacyRefOf_(cid);
        if (isR2Marker_(legacy)) {
          resolveR2IntoMem_(cid, legacy); // マーカーはR2から実体化=生のマーカーをIDB/同期へ流さない
        } else if (legacy) {
          _imgMem.ref[cid] = legacy;
          window.Go5Idb.set(idbKey('ref', cid), legacy).then(function () {
            try { localStorage.removeItem(refImgKey(cid)); } catch (e) {}
          }).catch(idbFail_);
        }
      }
      _refLoaded[cid] = true; // 読取成功時だけ「存在しない」ことも確認済みにする
      return true;
    }).catch(function (e) {
      idbFail_(e); return false;
    });
    _refLoadJobs[cid] = job.then(function (ok) { delete _refLoadJobs[cid]; return ok; }, function () { delete _refLoadJobs[cid]; return false; });
    return _refLoadJobs[cid];
  }
  function refImgOf(cid) {
    // 画像(imgs)はIDB/_imgMem由来、テキストは同期LSの正本 cand_text 由来を第一とする(ハイドレート未了でも読める)。
    // ★_idbOk が真でも _imgMem が空なら localStorage 退避(cand_refimg__<cid>)も読む。iOS SafariでIDBが
    //   間欠的に接続死する端末では、保存は v=791 の fail-open で LS へ退避して成功していても、表示側は
    //   hydrateImages_/migrateLocalImages_ が「IDB読みの成功」に依存するため、IDB読みが落ち続ける端末では
    //   LS退避画像が一生メモリへ載らず「保存できたのに何度リロードしても画像が出ない」が残っていた
    //   (Chami 2026-08-14①)。ここでLSも読めば、IDBが死んでいても同期で画像が出る=非破壊の追加読み。
    var base = (_idbOk ? (_imgMem.ref[cid] || null) : null) || legacyRefOf_(cid) || null;
    // LSがR2マーカー(base64を持たない枚数印)なら、実体をR2から取り寄せてメモリへ載せる(裏で・冪等)。
    //   表示側にはマーカーの内部(__r2n)を渡さず、テキストだけ持つ空画像レコードとして扱う=解決後の再描画で画像が出る。
    if (isR2Marker_(base)) { resolveR2IntoMem_(cid, base); base = { comment: base.comment, memo: base.memo, twitterUrl: base.twitterUrl, twitterUrl2: base.twitterUrl2, urls2: base.urls2, at: base.at }; }
    var txt = candTextOf_(cid);
    if (!base && !txt) return null;
    if (!txt) return base; // 移行前の端末=IDB/旧LSの値をそのまま(cand_textはハイドレート後にbackfillされる)
    var b = base || {};
    return {
      imgs: b.imgs, img: b.img, at: b.at,
      comment: txt.comment || '', memo: txt.memo || '',
      twitterUrl: txt.twitterUrl || '', twitterUrl2: txt.twitterUrl2 || '', urls2: txt.urls2 || []
    };
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
    return !!(has || r.comment || r.memo || r.twitterUrl || r.twitterUrl2 || (r.urls2 && r.urls2.length));
  }

  // ── R2 退避フォールバック(2026-08-15・C-038 恒久対策/Fable5根本解析)──────────────────────
  //   真因: v=791 は「IDB書込失敗→画像base64をlocalStorage(cand_refimg__)へ退避」で fail-open したが、
  //   iOS Safari の LS は1オリジン約5MB固定で、テキスト正本 cand_text と同じ枠を食い合う。IDBが慢性的に
  //   間欠死する端末では退避が積もる一方(掃除役 migrateLocalImages_ はIDB復帰時しか消せない)＝5MB枯渇→
  //   candTextSave_ すら QuotaExceeded で落ち「保存できませんでした」が毎回・決定的に出ていた。退避画像は
  //   周期同期(isSyncIdbKey=IDBのみ読む)にもLS同期(cand_はlegacyNoSync)にも乗らず出口ゼロだった。
  //   → 退避先を LS(base64) から R2(論理名アドレス putBlobR2At=sha256hex(名前)がキー)へ移し、LSには
  //   ハッシュを持たず枚数マーカー {__r2n} だけ置く=cand_text の容量を奪わない。読み側は go5ref:<cid>:<idx>
  //   から取り寄せてメモリへ実体化する。★不変条件: _imgMem.ref と IDB ref: には常に dataURL だけを入れる
  //   (マーカーは決してメモリ/IDB/同期へ漏らさない=解決してから載せる)。R2不可(オフライン等)の時だけ従来の
  //   base64 LS退避へ落ちる(双方向fail-open)。
  var R2_REF_PREFIX = 'go5ref:';
  function r2RefName_(cid, idx) { return R2_REF_PREFIX + String(cid) + ':' + idx; }
  function r2Ready_() {
    try { return !!(window.Go5Sync && window.Go5Sync.configured && window.Go5Sync.configured() && window.Go5Sync.putBlobR2At && window.Go5Sync.fetchBlobR2At); } catch (e) { return false; }
  }
  function isR2Marker_(rec) {
    return !!(rec && typeof rec === 'object' && !Array.isArray(rec) && rec.__r2n > 0 &&
      !(Array.isArray(rec.imgs) && rec.imgs.some(Boolean)) && !rec.img);
  }
  function dataUrlToBlob_(u) {
    try {
      var m = /^data:([^;,]*?)(;base64)?,([\s\S]*)$/.exec(String(u || '')); if (!m) return null;
      var mime = m[1] || 'image/jpeg', isB64 = !!m[2], data = m[3], bytes;
      if (isB64) { var bin = atob(data); bytes = new Uint8Array(bin.length); for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i); }
      else { var dec = decodeURIComponent(data); bytes = new Uint8Array(dec.length); for (var j = 0; j < dec.length; j++) bytes[j] = dec.charCodeAt(j); }
      return new Blob([bytes], { type: mime });
    } catch (e) { return null; }
  }
  function blobToDataUrl_(blob) {
    return new Promise(function (resolve) {
      try { var fr = new FileReader(); fr.onload = function () { resolve(fr.result); }; fr.onerror = function () { resolve(null); }; fr.readAsDataURL(blob); } catch (e) { resolve(null); }
    });
  }
  // imgs(dataURL配列) を go5ref:<cid>:<idx> で R2 へ。全枚成功で true、1枚でも失敗で false(=部分退避で縮小しない)。
  function pushRefToR2_(cid, imgs) {
    if (!r2Ready_() || !imgs || !imgs.length) return Promise.resolve(false);
    return imgs.reduce(function (p, u, i) {
      return p.then(function (okAll) {
        if (!okAll) return false;
        var blob = dataUrlToBlob_(u); if (!blob) return false;
        return window.Go5Sync.putBlobR2At(r2RefName_(cid, i), blob).then(function (key) { return !!key; }, function () { return false; });
      });
    }, Promise.resolve(true)).catch(function () { return false; });
  }
  // go5ref:<cid>:0..n-1 → dataURL配列。全枚取れたら配列、1枚でも欠けたら null(消えたと誤判定せずマーカーを残す)。
  function resolveRefFromR2_(cid, n) {
    if (!r2Ready_() || !(n > 0)) return Promise.resolve(null);
    var idxs = []; for (var i = 0; i < n; i++) idxs.push(i);
    var out = [];
    return idxs.reduce(function (p, i) {
      return p.then(function () {
        if (out === null) return;
        return window.Go5Sync.fetchBlobR2At(r2RefName_(cid, i)).then(function (blob) {
          if (!blob) { out = null; return; }
          return blobToDataUrl_(blob).then(function (u) { if (!u) out = null; else if (out) out.push(u); });
        }, function () { out = null; });
      });
    }, Promise.resolve()).then(function () { return out; }).catch(function () { return null; });
  }
  var _r2ResolveJobs = {};
  // マーカー(テキスト等のメタ)+ R2から取れた imgs から、メモリ/表示が期待する ref レコードを組む。
  //   ★resolveR2IntoMem_ と resolveRefImgsAwaited_ の2経路で同じ形を作る=リテラル二重化(片方だけ直すと割れる)を避けて共用。
  function refRecordFromMarker_(marker, imgs) {
    marker = marker || {};
    return {
      imgs: imgs, img: (imgs && imgs[0]) || '', comment: marker.comment || '', memo: marker.memo || '',
      twitterUrl: marker.twitterUrl || '', twitterUrl2: marker.twitterUrl2 || '', urls2: marker.urls2 || [], at: marker.at || 0
    };
  }
  // LSのR2マーカーをR2から実体化して _imgMem.ref[cid] へ dataURL で載せる。冪等(多重発射・既に実体あり=no-op)。
  function resolveR2IntoMem_(cid, marker) {
    cid = String(cid || '');
    if (!cid || _r2ResolveJobs[cid] || Object.prototype.hasOwnProperty.call(_imgMem.ref, cid)) return;
    if (!isR2Marker_(marker)) return;
    _r2ResolveJobs[cid] = true;
    resolveRefFromR2_(cid, marker.__r2n).then(function (imgs) {
      delete _r2ResolveJobs[cid];
      if (!imgs || !imgs.length) return; // 取れなければマーカーのまま=次回再試行(「無い」と断定しない)
      _imgMem.ref[cid] = refRecordFromMarker_(marker, imgs);
      _refLoaded[cid] = true;
      try {
        var page = document.getElementById('pageCand');
        var btn = page && liveRefButton_(page, cid);
        var card = btn && (btn.closest ? btn.closest('.cand-card') : null);
        if (card) updateCardRefThumb_(card, cid);
      } catch (e) {}
    }, function () { delete _r2ResolveJobs[cid]; });
  }
  // 候補→動画作成の写真ハンドオフ用: 画像を「待って」取り出す。メモリ/LSに実体があれば即返し、無くて
  //   R2退避マーカーだけがある時は resolveRefFromR2_ を await してから返す。★resolveR2IntoMem_ は裏で
  //   メモリへ載せるだけ=呼び側は await できず、遷移直後の consume_ が空を掴んで写真ガードで止まる
  //   =「ドラフトに遷移しない(acc2=候補起点)」の芯(Chami報告2026-08-16・Fable5診断④-1)。ここは明示的に待つ。
  //   マーカーが無い作品は従来と完全に同じ(refImgsOf_ の結果をそのまま返す)=非破壊の追加経路。
  function resolveRefImgsAwaited_(cid) {
    cid = String(cid || '');
    var have = refImgsOf_(cid);
    if (have && have.length) return Promise.resolve(have);
    var raw = legacyRefOf_(cid);
    if (isR2Marker_(raw) && r2Ready_()) {
      return resolveRefFromR2_(cid, raw.__r2n).then(function (imgs) {
        if (imgs && imgs.length) {
          if (!Object.prototype.hasOwnProperty.call(_imgMem.ref, cid)) { _imgMem.ref[cid] = refRecordFromMarker_(raw, imgs); _refLoaded[cid] = true; }
          return imgs;
        }
        return refImgsOf_(cid); // 取れなければ現状(空でもマーカーは残す=「無い」と断定しない)
      }, function () { return refImgsOf_(cid); });
    }
    return Promise.resolve(have || []);
  }
  // 起動時の解毒: LSに積もった base64 退避(v=791の毒)をR2へ逃がして枚数マーカーへ縮小し、cand_textと
  //   食い合う5MBを解放する。既にマーカーの物はR2から実体をメモリへ載せる。★confirm-before-shrink=
  //   R2 PUT成功を確認してからLSを縮める(唯一のコピーを先に消さない)。IDBが生きていれば migrateLocalImages_ が
  //   先にIDBへ移す=ここは「IDB間欠死の端末で退避がLSに積もり続ける」経路にだけ効く(冪等)。
  function hydrateR2Refs_() {
    if (!r2Ready_()) return;
    var keys = [];
    try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (k && k.indexOf('cand_refimg__') === 0) keys.push(k); } } catch (e) {}
    keys.forEach(function (k) {
      var cid = k.slice('cand_refimg__'.length);
      var val; try { val = JSON.parse(localStorage.getItem(k) || 'null'); } catch (e) { val = null; }
      if (!val) return;
      if (isR2Marker_(val)) { resolveR2IntoMem_(cid, val); return; }
      var imgs = Array.isArray(val.imgs) ? val.imgs.filter(Boolean) : (val.img ? [val.img] : []);
      if (!imgs.length) return;
      pushRefToR2_(cid, imgs).then(function (ok) {
        if (!ok) return; // R2不可=そのまま(migrateがIDBへ移す機会を待つ)
        var marker = { __r2n: imgs.length, comment: val.comment || '', memo: val.memo || '', twitterUrl: val.twitterUrl || '', twitterUrl2: val.twitterUrl2 || '', urls2: val.urls2 || [], at: val.at || 0 };
        try { if (localStorage.getItem(k) != null) { localStorage.setItem(k, JSON.stringify(marker)); klog_('ref_image_detox_r2', 'work', cid, { n: imgs.length }); } } catch (e) {}
      });
    });
  }

  function refImgSave(cid, data) {
    cid = String(cid || ''); if (!cid) return false;
    // data.imgs(配列・新)または data.img(単発・旧)を受け付け、{imgs, img:先頭} で保存。(img は旧読み手互換用)
    var imgs = data ? (Array.isArray(data.imgs) ? data.imgs.filter(Boolean) : (data.img ? [data.img] : [])) : [];
    // 2つ目以降のURLは配列 urls2 を正とし、旧 twitterUrl2(単発)からも取り込む(後方互換)。
    var urls2 = [];
    if (data) {
      if (Array.isArray(data.urls2)) urls2 = data.urls2.map(function (s) { return String(s || '').trim(); }).filter(Boolean);
      else if (data.twitterUrl2) urls2 = [String(data.twitterUrl2).trim()].filter(Boolean);
    }
    var empty = !data || (!imgs.length && !data.comment && !data.memo && !data.twitterUrl && !urls2.length);
    // ★展開前(_imgMemが空)の「空データ=削除」は、読めていないだけの既存データを消す事故になる。
    //   未展開のうちは破壊的な空保存を拒否する。(明示削除はUIから展開後に行われるので実害なし)
    if (empty && _idbOk && !_candidateHydrated && !_refLoaded[cid]) { try { console.warn('[go5 cand] 画像展開前の空保存を拒否(既存データ保護)', cid); } catch (e) {} return false; }
    // ★テキストは同期LSの正本 cand_text へ先に確定保存(戻り値=真の成否)。IDB書込の成否・ハイドレート状態に依存せず、
    //   次の描画で必ずコメント/メモ/X URLが読める。ここを通る=空でも正当な削除(展開後)なので cand_text も更新する。
    var textSaved = candTextSave_(cid, { comment: data && data.comment, memo: data && data.memo, twitterUrl: data && data.twitterUrl, twitterUrl2: urls2[0] || (data && data.twitterUrl2) || '', urls2: urls2 });
    if (!textSaved) return false; // LS容量超過等を成功扱いにしない。モーダルは開いたまま再操作できる。

    // IDB/旧LSは画像専用。テキストも旧版との後方互換用に同梱するが、画像ゼロならレコード自体を削除して cand_text だけ残す。
    var rec = imgs.length ? {
      imgs: imgs, img: imgs[0] || '', comment: (data && data.comment) || '', memo: (data && data.memo) || '',
      twitterUrl: (data && data.twitterUrl) || '', twitterUrl2: urls2[0] || '', urls2: urls2, at: new Date().getTime()
    } : null;

    // ★画像が変わっていない保存は、cand_text 確定時点でUI上の保存完了とする。画像なし/メモ等だけの編集で
    //   IndexedDB を待つ必要はない。iOS Safari のIDBタイムアウト(内部8秒×再接続1回)へ入り「保存中…」が
    //   長時間続く真因を切り離す。旧IDBレコードのテキストが再移行されないよう、既存レコードだけは裏で更新/掃除する。
    var prev = _idbOk ? (_imgMem.ref[cid] || null) : legacyRefOf_(cid);
    var prevImgs = prev ? (Array.isArray(prev.imgs) ? prev.imgs.filter(Boolean) : (prev.img ? [prev.img] : [])) : [];
    var imageChanged = prevImgs.length !== imgs.length;
    if (!imageChanged) {
      for (var ii = 0; ii < imgs.length; ii++) { if (prevImgs[ii] !== imgs[ii]) { imageChanged = true; break; } }
    }
    if (!imageChanged) {
      _refLoaded[cid] = true;
      if (_idbOk && prev) {
        if (rec) _imgMem.ref[cid] = rec; else delete _imgMem.ref[cid];
        try {
          var mirrorWrite = rec ? window.Go5Idb.set(idbKey('ref', cid), rec) : window.Go5Idb.del(idbKey('ref', cid));
          Promise.resolve(mirrorWrite).then(function () { reqSync_(); }, idbFail_);
        } catch (e) { idbFail_(e); }
      } else if (!_idbOk && prev) {
        try {
          if (rec) localStorage.setItem(refImgKey(cid), JSON.stringify(rec)); else localStorage.removeItem(refImgKey(cid));
        } catch (e) { idbFail_(e); }
      }
      return true;
    }
    if (_idbOk) {
      var hadPrev = Object.prototype.hasOwnProperty.call(_imgMem.ref, cid);
      prev = _imgMem.ref[cid];
      if (rec) _imgMem.ref[cid] = rec; else delete _imgMem.ref[cid];
      var write = rec ? window.Go5Idb.set(idbKey('ref', cid), rec) : window.Go5Idb.del(idbKey('ref', cid));
      return write.then(function () {
        _refLoaded[cid] = true;
        reqSync_(); // 永続保存が成功した内容だけを同期へ送る
        if (rec) klog_('ref_image_saved', 'work', cid, { imgs: imgs.length });
        return true;
      }, function (e) {
        idbFail_(e);
        // ★IDB書込が落ちても、テキスト(コメント/URL)は既に cand_text へ確定保存済み。画像は「まずR2へ退避し、
        //   LSにはハッシュを持たない枚数マーカー {__r2n} だけ置く」=cand_text と食い合う5MBを奪わない
        //   (v=791の base64 LS退避が5MBを枯らして"毎回保存できませんでした"を起こしていた真因の恒久対策・
        //   Fable5根本解析2026-08-15/C-038)。R2成功で成功扱いにしてモーダルを閉じさせる。
        //   R2不可(オフライン/未設定)の時だけ従来どおり base64 をLSへ退避(双方向fail-open)。
        //   両方落ちた時だけ本当の失敗として false(モーダル保持・再操作可)。メモリ(_imgMem.ref[cid])は
        //   既に新しい画像/削除済み=表示は無傷。削除(rec=null)はR2を触らずマーカー/退避を消すだけ。
        if (!rec) {
          try { localStorage.removeItem(refImgKey(cid)); _refLoaded[cid] = true; reqSync_(); return true; }
          catch (e2) { if (hadPrev) _imgMem.ref[cid] = prev; else delete _imgMem.ref[cid]; return false; }
        }
        return pushRefToR2_(cid, imgs).then(function (r2ok) {
          if (r2ok) {
            var marker = { __r2n: imgs.length, comment: rec.comment, memo: rec.memo, twitterUrl: rec.twitterUrl, twitterUrl2: rec.twitterUrl2, urls2: rec.urls2, at: rec.at };
            try { localStorage.setItem(refImgKey(cid), JSON.stringify(marker)); _refLoaded[cid] = true; reqSync_(); klog_('ref_image_saved_r2', 'work', cid, { imgs: imgs.length }); return true; } catch (e3) {}
          }
          // R2に載らなかった=従来の base64 LS退避へ(img複製は落として足跡を半減=P1-3)。
          try {
            var recLs = { imgs: imgs, comment: rec.comment, memo: rec.memo, twitterUrl: rec.twitterUrl, twitterUrl2: rec.twitterUrl2, urls2: rec.urls2, at: rec.at };
            localStorage.setItem(refImgKey(cid), JSON.stringify(recLs));
            _refLoaded[cid] = true; reqSync_(); return true;
          } catch (e2) {
            if (hadPrev) _imgMem.ref[cid] = prev; else delete _imgMem.ref[cid];
            klog_('ref_image_save_failed', 'work', cid, { cause: (e2 && e2.name) || 'quota', r2: r2ok ? 1 : 0, imgs: imgs.length });
            return false;
          }
        });
      });
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
    if (!img && _idbOk && !_candidateHydrated) { try { console.warn('[go5 cand] 画像展開前の空保存を拒否(既存データ保護)', cid); } catch (e) {} return false; } // refImgSaveと同じ理由
    var rec = img ? { img: img, at: new Date().getTime() } : null;
    if (_idbOk) {
      var hadPrev = Object.prototype.hasOwnProperty.call(_imgMem.bsky, cid);
      var prev = _imgMem.bsky[cid];
      if (rec) _imgMem.bsky[cid] = rec; else delete _imgMem.bsky[cid];
      var write = rec ? window.Go5Idb.set(idbKey('bsky', cid), rec) : window.Go5Idb.del(idbKey('bsky', cid));
      return write.then(function () {
        reqSync_();
        return true;
      }, function (e) {
        if (hadPrev) _imgMem.bsky[cid] = prev; else delete _imgMem.bsky[cid];
        idbFail_(e);
        return false;
      });
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

  // ── 動画で実際に使った画像(履歴アイテム単位＝videoId/itemKey)──
  // 候補タブの ref は「候補として保存した全画像」。投稿履歴から同じ ref を読むと未採用画像まで混ざるため、
  // 実際に動画へ渡した画像だけを used として別保存する。
  function usedImgsOf_(key) {
    if (!key) return [];
    var r = _idbOk ? _imgMem.used[key] : (function () { try { return JSON.parse(localStorage.getItem('hist_usedimg__' + key) || 'null'); } catch (e) { return null; } })();
    return (r && Array.isArray(r.imgs)) ? r.imgs.filter(Boolean) : [];
  }
  function usedImgKnown_(key) {
    if (!key) return false;
    if (_idbOk) return Object.prototype.hasOwnProperty.call(_imgMem.used, key);
    try { return localStorage.getItem('hist_usedimg__' + key) != null; } catch (e) { return false; }
  }
  // 先頭何枚が「投稿プレビュー画像」か。(投稿履歴の拡大表示で見出しを分ける・Chami依頼2026-07-30)
  function usedPrevCount_(key) {
    if (!key) return 0;
    var r = _idbOk ? _imgMem.used[key] : (function () { try { return JSON.parse(localStorage.getItem('hist_usedimg__' + key) || 'null'); } catch (e) { return null; } })();
    return (r && r.prev) ? (r.prev | 0) : 0;
  }
  function usedImgSave_(key, imgs, prevCount) {
    if (!key) return false;
    imgs = (imgs || []).filter(Boolean);
    if (!imgs.length && _idbOk && !_hydrated) { try { console.warn('[go5 cand] 画像展開前の空保存を拒否(既存データ保護)', key); } catch (e) {} return false; }
    // 空配列もレコードとして残す。「未移行」ではなく「使用画像を明示的に削除した」と区別し、
    // 旧候補画像の先頭が互換表示で復活するのを防ぐ。
    // prevCount=先頭何枚が「投稿プレビュー画像」か。投稿履歴の拡大表示で見出しを分けるのに使う(Chami依頼2026-07-30)。
    var rec = { imgs: imgs, at: new Date().getTime() };
    if (prevCount != null) rec.prev = prevCount | 0;
    if (_idbOk) {
      _imgMem.used[key] = rec;
      window.Go5Idb.set(idbKey('used', key), rec).catch(idbFail_);
      return true;
    }
    try {
      localStorage.setItem('hist_usedimg__' + key, JSON.stringify(rec));
      return true;
    } catch (e) { return false; }
  }

  // 起動時：候補ページに必要なref/bskyだけを最優先で展開する。
  // 従来のentries()全件走査は同じDB内のドラフト動画Blobまで値として復元し、iPhoneで画像表示と
  // 投稿編集の両方を長時間止めていた。候補用が描けた後、統合ページだけpost/usedを裏で読む。
  function hydrateHistoryImages_() {
    if (_hydrated) return;
    readImageEntries_(['post:', 'used:']).then(function (all) {
      _histHydrateFailures = 0;
      mergeImageEntries_(all);
      markHydrated_();  // go5-images-hydrated を発火→StockLists/ランキング(yt-clicks.js)が自動で描き直す
    }).catch(function (e) {
      _histHydrateFailures++;
      try { console.warn('[go5 idb] 投稿履歴画像の展開を再試行します', e); } catch (_) {}
      // ★一発で諦めない(旧: 1.2秒後に1回だけ→以後 markHydrated_ が呼ばれず go5-images-hydrated が
      //   永久に不発=StockLists のプレビューが空のまま固定されていた・Chami報告2026-08-16「更新では直らない」)。
      //   scheduleCandidateHydrateRetry_ と同型の無限バックオフ(上限15秒)で、IDBが後から回復したら追いつく。
      if (!_hydrated && !_histHydrateRetryTimer) {
        var delay = Math.min(15000, 1000 * Math.pow(2, Math.min(4, Math.max(0, _histHydrateFailures - 1))));
        _histHydrateRetryTimer = setTimeout(function () {
          _histHydrateRetryTimer = null;
          hydrateHistoryImages_();
        }, delay);
      }
    });
  }
  function scheduleCandidateHydrateRetry_() {
    if (!_idbOk || _candidateHydrated || _candidateHydrateRetryTimer) return;
    var delay = Math.min(15000, 1000 * Math.pow(2, Math.min(4, Math.max(0, _candidateHydrateFailures - 1))));
    _candidateHydrateRetryTimer = setTimeout(function () {
      _candidateHydrateRetryTimer = null;
      hydrateImages_();
    }, delay);
  }
  function hydrateImages_() {
    if (!_idbOk || _candidateHydrated || _candidateHydrateInFlight) return;
    _candidateHydrateInFlight = true;
    readImageEntries_(['ref:', 'bsky:']).then(function (all) {
      mergeImageEntries_(all);
      return migrateLocalImages_();
    }).then(function () {
      try { hydrateR2Refs_(); } catch (e) {} // IDBへ移せなかった退避画像をR2へ逃がして解毒(冪等)
      _candidateHydrateInFlight = false;
      resetCandidateHydrateFailures_();
      hideIdbRecoveryHint_();   // 展開できた=「失敗案内」はもう嘘。回復イベント頼みにせず直接消す
      markCandidateHydrated_(); // 候補画像・コメントの空保存拒否をここで解除
      bgRender_();              // サムネ・コメント・✓バッジをすぐ反映
      if (!window.__go5CandidateStandalone) hydrateHistoryImages_();
    }).catch(function (e) {
      _candidateHydrateInFlight = false;
      _candidateHydrateFailures++;
      if (_candidateHydrateFailures === 1) _hydrateFailSince = Date.now(); // 連鎖の起点を刻む
      // 一時的なSafariの接続死を「IDB非対応」と確定して空表示へ落とさない。張り直しを継続する。
      try { console.warn('[go5 idb] 候補画像の展開を再試行します', e); } catch (_) {}
      // ★案内バーは「持続死」だけに絞る(誤発火の恒久対策・Chami報告2026-08-18「案内がめちゃくちゃ出る」)。
      //   旧: 5回連続失敗(≒15秒)で即表示 → iOSのタブ退避/一時的メモリ圧など数秒で回復する接続死でも
      //   「閉じて開き直せ(再読込では直らない)」という強い案内が頻発していた。今は go5-idb-recovered で
      //   自動的に画像を読み直せる(閉じ直し不要)ため、この案内は「回復せず一定時間(60秒)以上続く=本当に
      //   WebKitのプロセス単位のIDB死」の時だけ1回出す。回復すれば resetCandidateHydrateFailures_ で連鎖が
      //   切れ、以後は出ない。genuine死は失敗し続けるので60秒後に必ず出る=案内の意味は失わない。
      if (shouldShowIdbHint_(_candidateHydrateFailures, _hydrateFailSince, Date.now())) showIdbRecoveryHint_();
      scheduleCandidateHydrateRetry_();
    });
  }
  // ★IDBがプロセス単位で死んでいる時の最終防衛(アプリでは治せない=ユーザーに正しい手順を伝える)。
  //   リロードでは直らず、タブ/PWAを閉じて開き直すとプロセスごと破棄されて直る。アプリ配色(ティール
  //   #2bb3c0 / ダーク #0e1422・半角括弧・紫禁止)。回復(go5-idb-recovered)で自動的に消える。
  var _idbHintEl = null;
  function showIdbRecoveryHint_() {
    if (_idbHintEl) return;
    try {
      if (!document.body) return;
      var bar = document.createElement('div');
      bar.id = 'idbRecoveryHint';
      bar.style.cssText = 'position:fixed;left:8px;right:8px;bottom:8px;z-index:99999;background:#0e1422;color:#e8eef7;border:1px solid #2bb3c0;border-radius:10px;padding:10px 12px;font-size:13px;line-height:1.5;box-shadow:0 4px 16px rgba(0,0,0,.4);';
      var x = document.createElement('button');
      x.type = 'button';
      x.textContent = '×';
      x.setAttribute('aria-label', '閉じる');
      x.style.cssText = 'float:right;background:transparent;border:0;color:#2bb3c0;font-size:16px;line-height:1;cursor:pointer;margin-left:8px;';
      x.addEventListener('click', function () { hideIdbRecoveryHint_(); });
      var msg = document.createElement('span');
      msg.textContent = '画像の読み込みに失敗しています。このページを一度閉じて開き直すと直ります(再読み込みでは直りません)。';
      bar.appendChild(x);
      bar.appendChild(msg);
      document.body.appendChild(bar);
      _idbHintEl = bar;
    } catch (e) {}
  }
  function hideIdbRecoveryHint_() {
    try { if (_idbHintEl && _idbHintEl.parentNode) _idbHintEl.parentNode.removeChild(_idbHintEl); } catch (e) {}
    _idbHintEl = null;
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
      // R2マーカーはIDB/同期へ生で流さない=R2から実体化してメモリへ載せ、LSにはマーカーを残す(冪等)。
      if (isRef && isR2Marker_(val)) { resolveR2IntoMem_(cid, val); return Promise.resolve(); }
      if (isRef) _imgMem.ref[cid] = val; else _imgMem.bsky[cid] = val;
      return window.Go5Idb.set(idbKey(isRef ? 'ref' : 'bsky', cid), val)
        .then(function () { try { localStorage.removeItem(k); } catch (e) {} })
        .catch(idbFail_); // 失敗時はlocalStorageに残す(次回再試行)
    });
    return Promise.all(jobs);
  }
  // ★候補を入力中は「背景由来の全再描画」で pageCand を組み直さない=打ちかけの入力が消えるのを根治。
  //   (Chami 2026-08-11「候補に入れてる途中でリロードが入るからもうアカン」)。真因はページ遷移ではなく、
  //   60秒オートsync(core/sync.js)の go5-synced→render() と 画像ハイドレート完了時の render() が、
  //   追加フォーム(candUrl/candTwitter/candMemo=addFormHtml_)ごとリストを作り直していたこと=リロードに見えた。
  //   入力中(フォーカス中/打ちかけの文字あり/追加モーダル表示中)は再描画を保留し、追加確定やタブ再入場の
  //   通常render()で反映する(新着サムネは少し遅れて出るだけ=非破壊)。render()冒頭で保留フラグは必ず解除。
  var _bgRerenderPending = false;
  function _entryInProgress_() {
    try {
      // ★.add-modal は初回作成後ずっとDOMに残り、閉じる時は祖先 .fz-overlay を hidden にするだけ。
      //   存在だけで判定すると、一度でも「追加」を開いた後は永久に入力中扱いとなり、同期/IDB展開後の
      //   再描画が止まる。その結果「画像が出ず、ページを移動し直すと出る」になっていた。
      //   開いているoverlayだけを入力中とみなす。閉じたモーダル内に残ったURL/メモも判定対象外。
      var addModal = document.querySelector('.add-modal');
      if (modalIsOpen_(addModal)) return true;
    } catch (e) {}
    return false;
  }
  // 背景(オートsync・画像ハイドレート)由来の再描画。候補タブ表示中のみ・入力中は保留。
  var _bgRetryTimer = null;
  function bgRender_() {
    try {
      var pc = document.getElementById('pageCand');
      if (!pc || pc.hidden) return;
      if (_entryInProgress_()) {
        // ★入力中は打ちかけを消さないよう保留するが、そのまま放置すると「もう一度💡候補を叩くまで
        //   画像が出ない」状態が残る(item8/DEF-de2408cb00と同型)。入力が終わったら自動で追いつくよう
        //   軽いポーリングで再試行を予約する=手でタブを叩き直さなくても画像が出る。self-clearなので誤発火しない。
        _bgRerenderPending = true;
        if (!_bgRetryTimer) {
          _bgRetryTimer = setInterval(function () {
            if (!_entryInProgress_()) {
              try { clearInterval(_bgRetryTimer); } catch (e) {}
              _bgRetryTimer = null;
              if (_bgRerenderPending) { try { bgRender_(); } catch (e) {} }
            }
          }, 1200);
        }
        return;
      }
      if (_bgRetryTimer) { try { clearInterval(_bgRetryTimer); } catch (e) {} _bgRetryTimer = null; }
      render();
    } catch (e) {}
  }
  // ★同期で「後から届いた画像」をメモリへ取り込んで再描画する。(サブ端末の一発表示・Chami再発2026-08-06)
  //   真因: 画像は起動時に一度だけ hydrateImages_ で _imgMem へ載る。サブ端末で後から sync-worker が
  //   R2→IDB へ画像を書き戻しても、candidates.js の _imgMem は更新されず画面も再描画されないため、
  //   「アクセス時は空・もう一度タブを開くと出る」状態になっていた(item9/DEF-de2408cb00 と同型)。
  //   go5-synced の detail.pulledImg(実際に取り込んだ画像件数)>0 の時だけ IDB を読み直して描画する
  //   =画像が来ていない同期(タブ復帰の空振り等)では再描画しない=無条件反応の白フラッシュを避ける。
  function reHydrateFromSync_() {
    if (!_idbOk || !window.Go5Idb || !window.Go5Idb.available()) return;
    // 同期で増えた画像だけの4名前空間を再読込。stock動画Blob等は候補描画へ持ち込まない。
    var prefixes = window.__go5CandidateStandalone ? ['ref:', 'bsky:'] : ['ref:', 'bsky:', 'post:', 'used:'];
    readImageEntries_(prefixes).then(function (all) {
      mergeImageEntries_(all);
      resetCandidateHydrateFailures_();
      if (!_candidateHydrated) markCandidateHydrated_();
      bgRender_();   // 入力中は保留(打ちかけの候補入力を消さない)
    }).catch(function (e) {
      try { console.warn('[go5 idb] 同期画像の再読込を再試行します', e); } catch (_) {}
      if (!_syncRehydrateRetryTimer) {
        _syncRehydrateRetryTimer = setTimeout(function () {
          _syncRehydrateRetryTimer = null;
          reHydrateFromSync_();
        }, 1500);
      }
    });
  }
  try { document.addEventListener('go5-synced', function (e) {
    var d = e && e.detail || {};
    if (d.pulledCand) bgRender_();
    if (d.pulledImg) reHydrateFromSync_();
  }); } catch (e) {}
  // ★画像がIDBからメモリへ載った合図(markHydrated_ が発火)でも候補ページを描き直す。hydrateImages_ の
  //   直接呼び(bgRender_)に加えた独立経路=各イベントlistenerは独立実行なので、他ページのlistenerが投げても・
  //   初回renderとの順序がズレても確実に追いつく(item8/DEF-de2408cb00と同型・Chami 2026-08-11「出た。OK」で再現確認)。
  //   bgRender_ が「候補タブ表示中・入力中は保留」を守るので非破壊。
  try { document.addEventListener('go5-images-hydrated', function () { bgRender_(); }); } catch (e) {}
  // ★IDBが無言死(iOS Safariのメモリ圧・バックグラウンド化)から回復した合図で、未展開の画像を今すぐ読み直す。
  //   従来は起動時の一発ハイドレートに依存し、IDBが後から回復しても「閉じて開き直す」まで空表示のままだった
  //   (Chami報告2026-08-16「更新では直らない・閉じて開くと出る」)。回復案内バーも消す。
  try { document.addEventListener('go5-idb-recovered', function () {
    if (!_idbOk) return;
    try {
      resetCandidateHydrateFailures_();
      _histHydrateFailures = 0;
      if (!_candidateHydrated) hydrateImages_();
      if (!_hydrated && !window.__go5CandidateStandalone) hydrateHistoryImages_();
      bgRender_();
    } catch (e) {}
    hideIdbRecoveryHint_();
  }); } catch (e) {}
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
  //   ★認識を高める(Chami 2026-08-15「画像はコピーしてるのに"画像がない"と出る」):
  //     ①全ClipboardItem・全typeを走査(先頭item/先頭typeだけで諦めない) ②type一致は大小文字を無視
  //     ③getTypeが1候補で失敗しても次の候補へ(在るのに取り出せず"画像なし"にしない)
  //     ④画像typeが無い時は「何かはコピーされていたか」を見て理由を出し分ける
  //       =iOSでWeb上の画像を長押しコピーするとURL/テキストになり画像bytesが入らない典型を言い当てる。
  function pasteImageFromClipboard_(cb) {
    if (!(navigator.clipboard && navigator.clipboard.read)) { cb(null, 'この端末では画像の貼り付けに未対応です(「画像を選ぶ」をお使いください)'); return; }
    navigator.clipboard.read().then(function (items) {
      items = items || [];
      var cands = [], sawAnyType = false;
      for (var i = 0; i < items.length; i++) {
        var types = items[i].types || [];
        for (var j = 0; j < types.length; j++) {
          sawAnyType = true;
          if (/image\//i.test(types[j])) cands.push({ item: items[i], type: types[j] });
        }
      }
      if (!cands.length) {
        cb(null, sawAnyType
          ? 'コピーされていたのは画像ではなくリンク/文字でした。画像そのものを長押しして「写真をコピー」するか、「画像を選ぶ」からお選びください'
          : 'クリップボードに画像がありません(先に画像をコピーしてください)');
        return;
      }
      var k = 0;
      (function tryNext() {
        if (k >= cands.length) { cb(null, 'クリップボードの画像を取り出せませんでした(「画像を選ぶ」をお使いください)'); return; }
        var c = cands[k++];
        c.item.getType(c.type).then(function (blob) { fileToScaledDataUrl(blob, cb); }).catch(tryNext);
      })();
    }).catch(function () { cb(null, 'クリップボードを読み取れませんでした(表示される「ペースト」をタップして許可してください)'); });
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
      // ★PCはスワイプできないので左右の矢印で切替(スマホはスワイプも従来通り効く)。2枚以上の時だけ表示。
      '<button class="fz-zoom-nav prev" type="button" aria-label="前へ" hidden>‹</button>' +
      '<button class="fz-zoom-nav next" type="button" aria-label="次へ" hidden>›</button>' +
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
    // ★PC用の切替：左右矢印ボタン＋キーボード(←→で移動・Escで閉じる)。スマホのスワイプは上で維持。
    z.querySelector('.fz-zoom-nav.prev').addEventListener('click', function (e) { e.stopPropagation(); zoomGo_(-1); });
    z.querySelector('.fz-zoom-nav.next').addEventListener('click', function (e) { e.stopPropagation(); zoomGo_(1); });
    document.addEventListener('keydown', function (e) {
      if (!_zoom || _zoom.hidden) return;
      if (e.key === 'ArrowRight') { e.preventDefault(); zoomGo_(1); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); zoomGo_(-1); }
      else if (e.key === 'Escape') { _zoom.hidden = true; }
    });
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
    var multi = _zoomList.length > 1; // ★2枚以上の時だけ左右矢印を出す(PCの切替手段)
    var np = z.querySelector('.fz-zoom-nav.prev'), nn = z.querySelector('.fz-zoom-nav.next');
    if (np) np.hidden = !multi; if (nn) nn.hidden = !multi;
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
      Promise.resolve(refImgSave(cid, { imgs: imgs, comment: cur.comment, memo: cur.memo, twitterUrl: cur.twitterUrl, twitterUrl2: cur.twitterUrl2 })).then(function (ok) {
        if (!ok) { done(null, '画像を保存できませんでした。もう一度お試しください'); return; }
        try { if (_activeTab) render(); } catch (e) {}
        done(imgs.slice(), null);
      }).catch(function () {
        done(null, '画像を保存できませんでした。もう一度お試しください');
      });
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
  // 指定URLから候補と同じcidを1つ求める小ヘルパ。(明示cidが無い履歴/候補の突き合わせ用)
  function cidFromUrl_(u) {
    if (!u || !window.buildAffiliateLink) return '';
    var url = window.normalizeWorkUrl ? window.normalizeWorkUrl(u) : u;
    var r = url ? window.buildAffiliateLink(url, '') : null;
    return (r && r.ok && r.cid) ? r.cid : '';
  }
  // ★履歴アイテムが取りうる cid キーを「全部」返す(明示cid＋workCid＋workUrl再計算)。
  //   候補側の cid はadd時に保存された固定値、履歴側は毎回workUrlから再計算——cid規則が変わった作品
  //   (FANZA Books .com: 旧=数字ID / 新=content_id)で両者が食い違い、投稿済みなのにpillが光らない
  //   (＝未投稿表示)不具合の根治。索引を「片側1キー」から「両側の全キーの和集合」にする。(Chami依頼2026-07-30)
  function cidKeysOfHistItem_(it) {
    if (!it) return [];
    var out = [], seen = {};
    function push(c) { c = String(c || ''); if (c && !seen[c]) { seen[c] = 1; out.push(c); } }
    push(it.cid); push(it.workCid); push(cidFromUrl_(it.workUrl || ''));
    return out;
  }
  // ★候補アイテムが取りうる cid キーを全部返す(保存cid＋url再計算cid)。履歴側と同じ和集合照合に使う。
  function candCidsOf_(it) {
    if (!it) return [];
    var out = [], seen = {};
    function push(c) { c = String(c || ''); if (c && !seen[c]) { seen[c] = 1; out.push(c); } }
    push(it.cid); push(cidFromUrl_(it.url || ''));
    return out;
  }
  // ★投稿済み判定の索引を合成する純関数(3層)。tests/test_posted_index.js が require する(module.exports両対応)。
  //   引数: authorityItems=GASシート由来の権威アイテム配列([{c,w,v,t}] or 空/未取得null)、
  //         localItems=端末ローカル履歴アイテム配列(短縮URL履歴+手動追加)、account='acc1'|'acc2'、
  //         offMap=このaccountの「投稿していない」宣言({cid:ts})、fetchedAt=権威キャッシュのfetchedAt(ms)、
  //         cidFromUrl=作品URL→cidの再計算関数(ブラウザは cidFromUrl_ を渡す。無ければ再計算しない)。
  //   戻り: { cid: item }。item は「ローカル実体があればそれ、無ければ権威の薄いアイテム(t/tsだけ持つ)」。
  //   設計書_投稿済み判定の権威ソース化_2026-07-31 S1。
  function buildPostedIndex_(authorityItems, localItems, account, offMap, fetchedAt, cidFromUrl) {
    var map = {};
    var off = offMap || {};
    var fa = fetchedAt || 0;
    var toUrlCid = (typeof cidFromUrl === 'function') ? cidFromUrl : function () { return ''; };
    // ローカルアイテムが取りうる cid キー(明示cid + workCid + workUrl再計算)。cidKeysOfHistItem_ と同一。
    function localKeys(it) {
      if (!it) return [];
      var o = [], seen = {};
      function push(c) { c = String(c || ''); if (c && !seen[c]) { seen[c] = 1; o.push(c); } }
      push(it.cid); push(it.workCid); push(toUrlCid(it.workUrl || ''));
      return o;
    }
    // 権威アイテムが取りうる cid キー(明示c + wを再計算)。
    function authKeys(a) {
      if (!a) return [];
      var o = [], seen = {};
      function push(c) { c = String(c || ''); if (c && !seen[c]) { seen[c] = 1; o.push(c); } }
      push(a.c); push(toUrlCid(a.w || ''));
      return o;
    }
    // ローカルアイテムを索引へ。所有ガード(videoId prefix / account欄)は fail-open(prefix/account無しは数える)。
    function addLocal(it, requireFresh) {
      var owner = String((it && it.videoId) || '').match(/^(acc[12])-/);
      if (owner && owner[1] !== account) return; // 背骨IDが別ch=このchでは数えない
      var explicitAcct = String((it && it.account) || '');
      if ((explicitAcct === 'acc1' || explicitAcct === 'acc2') && explicitAcct !== account) return; // account欄が別ch
      if (requireFresh) {
        // 権威が生きている時は無印(所有スタンプ無し)を数えない(fail-closed)。
        //   採用条件: ①ts>fetchedAt(直近投稿=権威に未反映でも即載せる) ②所有スタンプ陽性一致(account一致 or videoId prefix一致)。
        var fresh = (it && it.ts && it.ts > fa);
        var ownedByAcct = (explicitAcct === account);
        var ownedByPrefix = !!(owner && owner[1] === account);
        if (!fresh && !ownedByAcct && !ownedByPrefix) return;
      }
      var keys = localKeys(it);
      for (var ki = 0; ki < keys.length; ki++) { if (!map[keys[ki]]) map[keys[ki]] = it; }
    }
    var loc = localItems || [];
    var hasAuthority = !!(authorityItems && authorityItems.length);
    if (hasAuthority) {
      // 権威層: シート由来の各行を索引化(薄いアイテム。t を ms へパースして ts に持たせ postedTsOf_ が日付を出せるようにする)。
      for (var i = 0; i < authorityItems.length; i++) {
        var a = authorityItems[i]; if (!a) continue;
        var tms = 0; if (a.t) { var p = Date.parse(a.t); if (p) tms = p; }
        var thin = { cid: String(a.c || ''), workUrl: String(a.w || ''), videoId: String(a.v || ''), t: String(a.t || ''), ts: tms, account: account, _authority: true };
        var aks = authKeys(a);
        for (var ai = 0; ai < aks.length; ai++) { if (!map[aks[ai]]) map[aks[ai]] = thin; }
      }
      // ローカル新鮮層: ts>fetchedAt または所有スタンプ陽性のみ(無印は fail-closed)。ローカル実体は権威の薄いアイテムに勝つ。
      for (var j = 0; j < loc.length; j++) addLocal(loc[j], true);
    } else {
      // レガシー層(権威未取得): 現行 postedIndexFor_ と同じ fail-open 挙動。
      for (var k = 0; k < loc.length; k++) addLocal(loc[k], false);
    }
    // 「このchでは投稿していない」宣言のキーは索引から除外(postedMatchForCand_ 側の isPostedOff_ と二重でも害はない)。
    for (var key in map) { if (map.hasOwnProperty(key) && off[key] != null) delete map[key]; }
    return map;
  }
  // 権威キャッシュ(GASシート由来)を読む。{fetchedAt, acc1, acc2} or null。
  function postedAuthorityCache_() {
    try { var v = JSON.parse(localStorage.getItem('posted_sheet_v1') || 'null'); return (v && typeof v === 'object') ? v : null; } catch (e) { return null; }
  }
  // GAS action=posted_cids を叩いて権威キャッシュを更新する(10分TTL・stale-while-revalidate)。
  //   bsky_gas_url 未設定/通信失敗は静かに何もしない＝ローカル判定へ完全フォールバック(可用性優先)。
  var _postedAuthorityInflight = false;
  function fetchPostedAuthority_() {
    if (_postedAuthorityInflight) return;
    var url = '';
    try { url = localStorage.getItem('bsky_gas_url') || ''; } catch (e) { url = ''; }
    if (!url) return; // 未設定＝フォールバック(何もしない)
    var cache = postedAuthorityCache_();
    if (cache && cache.fetchedAt && (Date.now() - cache.fetchedAt) < 600000) return; // 10分TTL(多重取得を防ぐ)
    if (typeof window === 'undefined' || !window.Go5Util || typeof window.Go5Util.jsonp !== 'function') return;
    _postedAuthorityInflight = true;
    window.Go5Util.jsonp(url, { action: 'posted_cids', channel: 'both' }, function (data) {
      _postedAuthorityInflight = false;
      if (!data || data.ok !== true) return; // 失敗はキャッシュ据え置き(フォールバック)
      try {
        localStorage.setItem('posted_sheet_v1', JSON.stringify({ fetchedAt: Date.now(), acc1: data.acc1 || [], acc2: data.acc2 || [] }));
      } catch (e) { return; }
      invalidatePostedIndex_();
      try { if (_activeTab === 'main') render(); else if (typeof renderMaker === 'function') renderMaker(_activeTab); } catch (e) {}
    });
  }
  // チャンネルの cid→item 索引を(必要なら作り直して)返す。権威は posted_sheet_v1 キャッシュから読む。
  function postedIndexFor_(account) {
    if (typeof window.Go5PostedItems !== 'function') return {};
    var items = window.Go5PostedItems(account) || [];
    var cache = postedAuthorityCache_();
    var authorityItems = cache ? (account === 'acc2' ? cache.acc2 : cache.acc1) : null;
    var fetchedAt = (cache && cache.fetchedAt) || 0;
    // sig にキャッシュの fetchedAt を混ぜる＝権威が更新されたら索引を作り直す。
    var sig = items.length + ':' + ((items[0] && items[0].ts) || '') + ':' + ((items[items.length - 1] && items[items.length - 1].ts) || '') +
      ':a' + ((authorityItems && authorityItems.length) || 0) + ':' + fetchedAt;
    var cached = _postedIdxCache[account];
    if (cached && cached.sig === sig) return cached.map;
    var map = buildPostedIndex_(authorityItems, items, account, _postedOff[account] || {}, fetchedAt, cidFromUrl_);
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
      var kept = arr.filter(function (x) { return cidKeysOfHistItem_(x).indexOf(cid) < 0; });
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
  // ★候補アイテムを、取りうる全cidキーで投稿履歴と和集合照合。{item, key}(ヒットしたキー)or null。
  //   key は履歴側のキーでもある(索引が両側の和集合)ので、pillのdata-posted-cidに使えば削除照合も一致する。
  function postedMatchForCand_(it, account) {
    var ks = candCidsOf_(it);
    // ★ユーザーが「このchでは投稿していない」と宣言済みなら、履歴に記録が残っていても未投稿扱い。
    //   (シート再マージ等で記録が復活しても pill は光らせない＝手動オフが効き続ける)
    if (isPostedOff_(ks, account)) return null;
    var idx = postedIndexFor_(account);
    for (var i = 0; i < ks.length; i++) { if (idx[ks[i]]) return { item: idx[ks[i]], key: ks[i] }; }
    // ★手動「投稿済み」宣言の救済(索引にもシートにも記録が無い偽陰性)。薄い item を合成して ✔ を光らせる。
    if (isPostedOn_(ks, account)) {
      var onTs = postedOnTs_(ks, account);
      return { item: { cid: ks[0], workUrl: (it && it.url) || '', ts: onTs, account: account, _manualOn: true, title: (it && it.title) || '' }, key: ks[0] };
    }
    return null;
  }
  // バッジ行に並べるチャンネル表記。投稿済み＝ボタン化(クリックで投稿詳細)＋テーマ色。未投稿＝ボタン化せず淡色表記。
  function acctBadgesHtml_(it) {
    return _ACCTS.map(function (a) {
      var m = postedMatchForCand_(it, a[0]);
      if (m) {
        return '<span class="cand-acct-pill cand-acct-' + a[0] + ' posted" role="button" tabindex="0" ' +
          'data-posted-acct="' + a[0] + '" data-posted-cid="' + esc(m.key) + '" title="' + esc(a[1]) + 'で投稿済み(タップで投稿内容)">' +
          esc(a[1]) + ' <b>✔</b></span>';
      }
      // 未投稿pill。タップで「実は投稿済み」を手動宣言できる(✔が付かない偽陰性の救済・data-poston-*)。
      var onCid = (candCidsOf_(it) || [])[0] || '';
      return '<span class="cand-acct-pill cand-acct-' + a[0] + ' notposted" role="button" tabindex="0" ' +
        'data-poston-acct="' + a[0] + '" data-poston-cid="' + esc(onCid) + '" title="' + esc(a[1]) + '(未投稿・タップで手動で投稿済みにできる)">' + esc(a[1]) + '</span>';
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
  function postedDatesHtml_(cand) {
    return _ACCTS.map(function (a) {
      var m = postedMatchForCand_(cand, a[0]);
      var it = m && m.item;
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
    var it = postedItemForCid_(cid, account);
    // 手動「投稿済み」宣言だけで✔が付いている作品は索引に実体が無い＝薄いitemを合成して開ける(🚫で取り消せる)。
    if (!it && isPostedOn_([cid], account)) it = { cid: cid, ts: postedOnTs_([cid], account), _manualOn: true, title: '' };
    if (!it) return;
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
      // ①恒久オーバーライドを先に立てる＝以後シート再マージ等で記録が戻っても pill は光らない(復元対策)。
      setPostedOn_(cid, account, false); // 手動「投稿済み」宣言を取り消す(誤タップの逃げ道)
      setPostedOff_(cid, account, true);
      // ②実レコードも外す(ランキング/投稿履歴タブからも消す＝従来動作)。
      removePostedForAcct_(cid, account);
      invalidatePostedIndex_();
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
    // 未投稿pill：タップで「実は投稿済み」を手動宣言(✔が付かない偽陰性の救済)。
    root.querySelectorAll('[data-poston-acct]').forEach(function (b) {
      var handler = function (e) {
        e.stopPropagation();
        var a = b.getAttribute('data-poston-acct'), c = b.getAttribute('data-poston-cid');
        var lbl = (a === 'acc2') ? '宵桜艶帖' : '月詠み';
        if (!c) { alert('この作品はcidが解決できないため手動指定できません。'); return; }
        if (!window.confirm('この作品を「' + lbl + '」で投稿済みにします。\n(実際に投稿したのに✔が付かない時の手動救済です。誤って押した場合は、付いた✔をタップ→🚫で取り消せます)\nよろしいですか？')) return;
        setPostedOn_(c, a, true);
        invalidatePostedIndex_();
        try { render(); } catch (err) {} // 候補一覧を再描画＝✔が付く
      };
      b.addEventListener('click', handler);
      b.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(e); } });
    });
  }

  // ── X/Bluesky/その他URLの種別判定＆カードのリンク札(Chami依頼2026-08-09: X以外も表示・非SNSは Web)──
  function urlKind_(u) { u = String(u || ''); if (/bsky\.app\//.test(u)) return 'b'; if (/(?:x\.com|twitter\.com)\//.test(u)) return 'x'; return 'web'; }
  function candUrlLink_(su, n) {
    var k = urlKind_(su);
    var color = k === 'b' ? '#1185fe' : (k === 'x' ? '#1d9bf0' : '#2bb3c0');
    var base = k === 'b' ? 'Bsky' : (k === 'x' ? 'X' : 'Web'); // ★BlueskyはB→Bsky(Chami依頼2026-08-11・Bだけだと分かりにくい)
    // vlink-sns=X/Bsky札は誤タップ防止で左右に少し余白＋タップ域を広げる(Chami依頼2026-08-11「横のリンクやボタンと少し幅を開けて」)。
    var cls = 'vlink' + ((k === 'b' || k === 'x') ? ' vlink-sns' : '');
    return '<a class="' + cls + '" href="' + esc(su) + '" target="_blank" rel="noopener" style="color:' + color + ';">' + base + (n ? String(n) : '') + '↗</a>';
  }
  // refimgレコードの「2つ目以降のURL」を配列で返す(旧 twitterUrl2 単発から移行・後方互換)。
  function refUrls2_(rec) { if (!rec) return []; if (Array.isArray(rec.urls2)) return rec.urls2.filter(Boolean); return rec.twitterUrl2 ? [rec.twitterUrl2] : []; }

  // ── 投稿画像モーダル(複数画像＋メモを保存)──
  var _refOverlay = null;
  var _refOpenSeq = 0; // モーダルを開くたびに増える通し番号(遅い非同期処理が古いpendingへ書き込むのを防ぐ)
  function closeRefOverlay_() {
    _refOpenSeq++;
    if (_refOverlay) _refOverlay.hidden = true;
  }
  function ensureRefOverlay_() {
    if (_refOverlay && _refOverlay.isConnected) return _refOverlay;
    var ov = document.createElement('div'); ov.className = 'fz-overlay'; ov.hidden = true;
    ov.innerHTML = '<div class="fz-modal refimg-modal"><button class="fz-close" type="button" aria-label="閉じる">✕</button><div class="fz-body"></div></div>';
    document.body.appendChild(ov);
    ov.addEventListener('click', function (e) { if (e.target === ov) closeRefOverlay_(); });
    ov.querySelector('.fz-close').addEventListener('click', closeRefOverlay_);
    _refOverlay = ov;
    return ov;
  }
  function showRefLoadState_(ov, it, failed, onSaved) {
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      '<div class="fz-title refimg-title" style="padding-right:36px;">' + esc(it.title || it.cid) + '</div>' +
      '<div class="hint" aria-live="polite" style="padding:22px 8px;text-align:center;">' +
        (failed ? '⚠️ 保存済みデータを読み込めませんでした。通信状態を確認して、もう一度お試しください。' : '⏳ 保存済みの画像・コメントを読み込み中…') +
      '</div>' +
      (failed ? '<div style="text-align:center;"><button type="button" class="ghost refimg-load-retry">もう一度読み込む</button></div>' : '');
    if (failed) {
      var retry = body.querySelector('.refimg-load-retry');
      if (retry) retry.addEventListener('click', function () { openRefImgModal_(it, onSaved); });
    }
    ov.hidden = false; // クリックした瞬間から反応を見せる。透明な待ち時間を作らない。
  }
  function openRefImgModal_(it, onSaved, refReady) {
    if (!it) return;
    var ov = ensureRefOverlay_();
    // 全体の候補画像展開が遅くても、押された作品のrefレコード1件だけを直接読む。
    // 読み取り確認前に空モーダルを作って保存可能にすると既存画像を消し得るため、読込中UIを先に出す。
    var cid = String(it.cid || '');
    // 全体走査が終わった後に同期・別ページから追加された画像もあるため、この作品を実際に
    // 読んだかだけで判定する。全体完了だけで空モーダルを開くと、遷移時の保存で画像を消し得る。
    var known = _refLoaded[cid] || Object.prototype.hasOwnProperty.call(_imgMem.ref, cid);
    if (_idbOk && !known && !refReady) {
      var loadSeq = ++_refOpenSeq;
      showRefLoadState_(ov, it, false, onSaved);
      var slowTimer = setTimeout(function () {
        if (loadSeq === _refOpenSeq && !ov.hidden) showRefLoadState_(ov, it, false, onSaved);
      }, 4000);
      ensureRefLoaded_(cid).then(function (ok) {
        clearTimeout(slowTimer);
        if (loadSeq !== _refOpenSeq) return; // 閉じた/別作品を開いた後なら古い結果を出さない
        if (!ok) { showRefLoadState_(ov, it, true, onSaved); return; }
        // 直接読めた1件は全体ハイドレートを待たずカード側にも即時反映する。
        try {
          var page = document.getElementById('pageCand'), live = page && liveRefButton_(page, cid);
          if (live) updateCardRefThumb_(live.closest ? live.closest('.cand-card') : null, cid);
        } catch (e) {}
        openRefImgModal_(it, onSaved, true);
      });
      return;
    }
    var mySeq = ++_refOpenSeq;
    var cur = refImgOf(it.cid) || {};
    var curImgs = Array.isArray(cur.imgs) ? cur.imgs.filter(Boolean) : (cur.img ? [cur.img] : []);
    // pending.imgs=保存候補の画像列(複数可・37ページ級の連続貼り付けOK)・idx=表示中(「動画生成へ」で採用される1枚)
    // X/Bluesky URL は refimg 側に無ければ候補アイテム側(it.twitterUrl=カードのXリンクの出所)からフォールバック
    //   。(カードにXリンクが出ているのにモーダルの欄が空になる不一致を防ぐ)
    var pending = { imgs: curImgs.slice(), idx: 0, comment: cur.comment || '', twitterUrl: cur.twitterUrl || it.twitterUrl || '', memo: cur.memo || '', urls2: refUrls2_(cur).slice() };
    // 「動画生成へ」は遷移ボタンでもある。画像を触っていないのに保存画像列を書き直さない。
    // 明示的な追加・並べ替え・削除があった時だけ画像IDBを更新する。
    var imagesDirty = false;
    var isTw = !!(it.isTwitter || it.twitterUrl); // Twitterのみ候補(埋め込みポストURLあり)
    // 作品URLのプレフィル：候補が実際に作品URLを持つ(!isTwitter かつ it.url がDMM/book等)なら、
    //   twitterUrl の有無に関わらずそのまま欄に表示。(＝カードの「作品↗」と同じ判定)X起点(it.url=ポストURL)は空。
    var workUrlPrefill = (!it.isTwitter && it.url) ? it.url : '';
    var body = ov.querySelector('.fz-body');
    body.innerHTML =
      '<div class="fz-title refimg-title" style="background:none;color:#fff;padding:0 36px 0 0;margin:0 0 6px;font-weight:700;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">' + esc(it.title || it.cid) + '</div>' +
      // ★動画生成へは右端から離す(padding-right)＝右上の✕との誤タップ防止(Chami依頼2026-08-09)
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;padding-right:40px;">' +
        '<span class="hint" style="margin:0;flex:1;">動画生成用の画像</span>' +
        '<button id="refImgToMovie" type="button" class="primary" style="width:auto;margin:0;flex:0 0 auto;font-size:13px;padding:7px 14px;display:inline-flex;align-items:center;justify-content:center;text-align:center;line-height:1;">動画生成へ</button>' +
      '</div>' +
      '<div id="refImgPreview" class="cand-refimg-preview"></div>' +
      '<div class="cand-img-btnrow">' +
        '<label class="ghost cand-refimg-pick">画像を選ぶ<input id="refImgFile" type="file" accept="image/*" multiple style="display:none;"></label>' +
        '<button id="refImgPaste" type="button" class="ghost" style="background:#fffef9;color:#111;border-color:#d8d2bf;">画像を貼り付け</button>' +
        '<button id="refImgClear" type="button" class="ghost cand-img-clear" style="background:#fffef9;color:#111;border-color:#d8d2bf;">消す</button>' +
      '</div>' +
      // メモ欄は「メモ追加」ボタンで生成(既存メモがあれば開いた時に自動表示)。コメントが無い時にカードへ水色で表示。
      '<div id="refImgMemoWrap"></div>' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">コメント</label>' +
      '<input id="refImgComment" type="text" class="cand-refimg-line" autocomplete="off" placeholder="コメント">' +
      '<label class="hint" style="display:block;margin:10px 0 2px;">X / Bluesky URL</label>' +
      '<div style="display:flex;gap:6px;align-items:stretch;">' +
        '<input id="refImgTwitter" size="1" type="text" inputmode="url" class="cand-refimg-line" autocomplete="off" placeholder="https://x.com/… " style="flex:1;min-width:0;">' +
        '<button type="button" class="ghost paste-btn" data-paste="refImgTwitter" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
      '</div>' +
      // 2つ目以降のURL(カードに X2↗ / B2↗ / Web2↗ で表示)。下の「URL追加」ボタンで欄が増える(1モーダル完結)。
      '<div id="refImgUrls2Wrap"></div>' +
      '<label class="hint" style="display:block;margin:10px 0 2px;font-size:11px;white-space:nowrap;">アフィリンク付き作品URLを貼ると、正式な作品URLに自動変換</label>' +
      '<div style="display:flex;gap:6px;align-items:stretch;">' +
        '<input id="refImgWorkUrl" size="1" type="text" inputmode="url" class="cand-refimg-line" autocomplete="off" placeholder="作品URLを貼り付け" value="' + esc(workUrlPrefill) + '" style="flex:1;min-width:0;">' +
        '<button type="button" class="ghost paste-btn" data-paste="refImgWorkUrl" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
      '</div>' +
      // 保存を小さくし、空いた枠にメモ追加・URL追加ボタン(押下でそれぞれの欄を生成)。狭ければ折り返す(Chami依頼2026-08-09)。
      '<div style="display:flex;gap:8px;margin-top:10px;align-items:stretch;flex-wrap:wrap;">' +
        '<button id="refImgSave" type="button" class="primary" style="flex:1 1 auto;padding:9px 16px;">保存</button>' +
        '<button id="refMemoAdd" type="button" class="ghost" style="flex:0 0 auto;width:auto;padding:6px 9px;font-size:12px;white-space:normal;line-height:1.15;text-align:center;">メモ<br>追加</button>' +
        '<button id="refUrlAdd" type="button" class="ghost" style="flex:0 0 auto;width:auto;padding:6px 9px;font-size:12px;white-space:normal;line-height:1.15;text-align:center;">URL<br>追加</button>' +
        '<button id="refImgCancel" type="button" class="ghost" style="flex:0 0 auto;width:auto;padding:9px 12px;">閉じる</button>' +
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
        // ★1行固定・絵文字なし(Chami依頼2026-08-09)。長い時ははみ出さず省略。
        '<div class="hint" style="text-align:center;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11px;">' +
          (n > 1 ? (pending.idx + 1) + '/' + n + '(スワイプで切替/表示中の画像が動画生成で使用)' : '画像 1枚') +
        '</div>';
      previewEl.querySelector('img').addEventListener('click', function () {
        openImgZoom_(pending.imgs.slice(), pending.idx, {
          onReorder: function (i) {
            if (i <= 0 || i >= pending.imgs.length) return pending.imgs.slice();
            var img = pending.imgs.splice(i, 1)[0]; pending.imgs.unshift(img); pending.idx = 0; imagesDirty = true; drawPreview(); // 旧1枚目は2枚目へずれる(保存で確定)
            return pending.imgs.slice();
          },
          onPasteAdd: function (done) {
            pasteImageFromClipboard_(function (durl, err) {
              if (err || !durl) { done(null, err || '画像がコピーされていません'); return; }
              pending.imgs.unshift(durl); pending.idx = 0; imagesDirty = true; drawPreview(); // 先頭＝1ページ目(保存で確定)
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
    // メモ欄は「メモ追加」ボタンで生成する単一欄。既存メモがあれば開いた時に自動表示。✕で欄ごと消せる。
    var memoWrap = body.querySelector('#refImgMemoWrap');
    function collectMemo_() {
      var el = body.querySelector('#refImgMemoInline');
      return el ? (el.value || '') : (pending.memo || '');
    }
    function addMemoBox_(val) {
      var el = body.querySelector('#refImgMemoInline');
      if (el) { el.focus(); return; } // 既にあれば増やさずフォーカス(メモは1欄)
      memoWrap.innerHTML =
        '<label class="hint" style="display:block;margin:8px 0 2px;">メモ</label>' +
        '<div class="refimg-url2-row" style="margin-top:0;">' +
          '<input id="refImgMemoInline" size="1" type="text" class="cand-refimg-line" autocomplete="off" placeholder="メモ(コメントが無い時にカードへ水色で表示)" style="flex:1;min-width:0;">' +
          '<button type="button" class="cand-url2-del" title="メモ欄を消す">✕</button>' +
        '</div>';
      memoWrap.querySelector('input').value = val || '';
      memoWrap.querySelector('.cand-url2-del').addEventListener('click', function () { pending.memo = ''; memoWrap.innerHTML = ''; });
    }
    if (pending.memo) addMemoBox_(pending.memo);
    body.querySelector('#refMemoAdd').addEventListener('click', function () { addMemoBox_(''); });
    // 2つ目以降のURL欄を pending.urls2 から描く。「URL追加」で空欄を1つ足す。各欄に貼り付け＋✕(欄を消す)。
    var urls2Wrap = body.querySelector('#refImgUrls2Wrap');
    function collectUrls2_() {
      var out = [];
      urls2Wrap.querySelectorAll('input.refimg-url2-input').forEach(function (el) { var v = (el.value || '').trim(); if (v) out.push(v); });
      return out;
    }
    var _url2Seq = 0;
    function addUrl2Row_(val) {
      var id = 'refImgUrl2_' + (_url2Seq++);
      var row = document.createElement('div');
      row.className = 'refimg-url2-row';
      row.innerHTML =
        '<input id="' + id + '" size="1" type="text" inputmode="url" class="cand-refimg-line refimg-url2-input" autocomplete="off" placeholder="2つ目以降のX/Bluesky/その他URL" style="flex:1;min-width:0;">' +
        '<button type="button" class="ghost paste-btn" data-paste="' + id + '" style="margin:0;color:#fff;font-size:12px;padding:0 12px;white-space:nowrap;flex:0 0 auto;width:auto;">貼り付け</button>' +
        '<button type="button" class="cand-url2-del" title="このURL欄を消す">✕</button>';
      urls2Wrap.appendChild(row);
      row.querySelector('input').value = val || '';
      row.querySelector('.cand-url2-del').addEventListener('click', function () { if (row.parentNode) row.parentNode.removeChild(row); });
      wirePaste_(body);
    }
    (pending.urls2 || []).forEach(function (u) { addUrl2Row_(u); });
    body.querySelector('#refUrlAdd').addEventListener('click', function () { addUrl2Row_(''); });
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
          if (added) { pending.imgs = batch.concat(pending.imgs); pending.idx = 0; imagesDirty = true; } // ★追加画像を先頭(1枚目)へ(標準)
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
        pending.imgs.unshift(durl); pending.idx = 0; imagesDirty = true; drawPreview(); // ★追加画像を先頭(1枚目)へ(置換せず追加・複数枚OK)
        body.querySelector('#refImgMsg').textContent = '貼り付けました。(1枚目に追加・計' + pending.imgs.length + '枚)続けて貼り付けできます(保存で確定)';
      });
    });
    body.querySelector('#refImgClear').addEventListener('click', function () {
      var n = pending.imgs.length;
      if (!n) { drawPreview(); return; }
      if (!window.confirm(n > 1 ? ('表示中の画像(' + (pending.idx + 1) + '/' + n + ')を削除しますか？') : '本当に画像を削除しますか？')) return;
      pending.imgs.splice(pending.idx, 1);
      imagesDirty = true;
      if (pending.idx >= pending.imgs.length) pending.idx = Math.max(0, pending.imgs.length - 1);
      drawPreview();
      body.querySelector('#refImgMsg').textContent = '画像を削除しました(保存で確定・残り' + pending.imgs.length + '枚)';
    });
    // メモ・2つ目以降URLを(生成済みなら)欄から pending へ取り込む(1モーダル完結・Chami依頼2026-08-09)。
    function syncPcMemoInline_() {
      pending.memo = collectMemo_();
      pending.urls2 = collectUrls2_();
    }
    // 動画生成へ：このモーダルの作品データを動画作成タブへ引き継いで移動する。
    body.querySelector('#refImgToMovie').addEventListener('click', function () {
      pending.comment = body.querySelector('#refImgComment').value || '';
      pending.twitterUrl = (body.querySelector('#refImgTwitter').value || '').trim();
      syncPcMemoInline_();
      var workVal = (body.querySelector('#refImgWorkUrl') && body.querySelector('#refImgWorkUrl').value || '').trim();
      if (!workVal && !it.isTwitter && it.url) workVal = it.url; // 欄が空でも候補が作品URLを持つなら使う(動画側へ確実に反映)
      var workUrl = workVal ? (window.normalizeWorkUrl ? window.normalizeWorkUrl(workVal) : workVal) : '';
      var toMovieBtn = this;
      if (toMovieBtn.disabled) return;
      toMovieBtn.disabled = true;
      body.querySelector('#refImgMsg').textContent = '保存中…';
      // ★遷移はIDB保存の成否に依存させない。動画作成タブへ渡すデータは、この場のメモリ(it/pending)から
      //   直接運ぶ(transferToMovie_)ため、候補の永続保存が失敗しても遷移は必ず続行する。
      //   v=764(e24bb57)で保存失敗時に `if(!ok) return` で遷移を止めたところ、iOS SafariのIDB書込が
      //   無言失敗すると refImgSave が false を返し「押しても動画作成タブに移動しない」再発になった
      //   (Chami実機報告2026-08-13・恒久対策C-038=遷移と保存を切り離す)。
      var go_ = function () {
        var selectedIndex = pending.idx;
        transferToMovie_(it, pending.imgs[selectedIndex] || '', pending.comment, workUrl, {
          cid: it.cid || '', index: selectedIndex
        }); // ★表示中の画像を採用。容量超過時はcid+順番からIDBへ取り直せるようにする
        if (onSaved) onSaved();
        closeRefOverlay_();
      };
      // 画像未編集なら、小さい文字正本(cand_text)だけを保存する。候補画像IDBを再保存しないため、
      // メモリ未反映・iOS遷移中断があっても「動画生成へ」が保存画像を消す操作にならない。
      var saveForMove = imagesDirty
        ? Promise.resolve(refImgSave(it.cid, pending))
        : Promise.resolve(candTextSave_(it.cid, pending));
      saveForMove.then(function (ok) {
        // 保存失敗はログにだけ残し、遷移は止めない(渡すデータはメモリ側=無傷)。
        if (!ok) { try { console.warn('[go5 cand] 動画生成へ: 候補の永続保存に失敗したが遷移は続行', it.cid); } catch (e) {} }
        go_();
      }).catch(function () {
        try { console.warn('[go5 cand] 動画生成へ: 保存で例外。遷移は続行', it.cid); } catch (e) {}
        try { go_(); } catch (e) { toMovieBtn.disabled = false; body.querySelector('#refImgMsg').textContent = '移動できませんでした。もう一度お試しください'; }
      });
    });
    body.querySelector('#refImgCancel').addEventListener('click', closeRefOverlay_);
    body.querySelector('#refImgSave').addEventListener('click', function () {
      var saveBtn = this;
      if (saveBtn.disabled) return;
      var saveMsg = body.querySelector('#refImgMsg');
      function showSaveFailure_(custom) {
        saveMsg.textContent = custom || (pending.imgs.length
          ? '画像をこの端末へ保存できませんでした。入力は残っています。もう一度お試しください'
          : 'この端末へ保存できませんでした。入力は残っています。もう一度お試しください');
      }
      // ★候補保存も共通の単一終端権威へ接続。成功/失敗/時間切れ/遅着の最初の1件だけを採用し、
      //   どの経路でもボタンを必ず再操作可能へ戻す。候補とドラフトで別々の番犬を持たない。
      var saveOp = window.Go5OperationGate && window.Go5OperationGate.armButton
        ? window.Go5OperationGate.armButton(saveBtn, {
            pendingLabel: saveBtn.textContent,
            successLabel: saveBtn.textContent,
            timeoutLabel: saveBtn.textContent,
            timeoutMs: 20000,
            onSettle: function (ok, reason) {
              if (!ok && reason === 'timeout') showSaveFailure_('保存処理が時間内に完了しませんでした。入力は残っています。もう一度お試しください');
            }
          })
        : null;
      if (!saveOp) {
        showSaveFailure_('保存制御の読込に失敗しました。ページを再読込してもう一度お試しください');
        return;
      }
      pending.comment = body.querySelector('#refImgComment').value || '';
      pending.twitterUrl = (body.querySelector('#refImgTwitter').value || '').trim();
      syncPcMemoInline_();
      var workRaw = (body.querySelector('#refImgWorkUrl') && body.querySelector('#refImgWorkUrl').value || '').trim();
      // 作品URL欄が空、またはプレフィル値から変更が無ければ何もしない。(無駄なAPI呼び出し/意図しないaddedAtリセットを防止)
      if (workRaw && workRaw !== workUrlPrefill) {
        saveMsg.textContent = isTw ? '作品候補に変換中…' : '作品URLを更新中…';
        try {
          applyWorkUrl_(it, workRaw, pending, function (ok, err) {
            if (!saveOp.finish(ok)) return; // 時間切れ後の遅着結果で画面を閉じない
            if (!ok) { showSaveFailure_(err || '変換できません'); return; }
            saveMsg.textContent = isTw ? '作品候補に変換しました' : '作品URLを更新しました';
            if (onSaved) onSaved();
            if (_activeTab) render();
            setTimeout(function () { if (mySeq === _refOpenSeq) closeRefOverlay_(); }, 700);
          });
        } catch (e) {
          if (saveOp.fail()) showSaveFailure_('作品URLを更新できませんでした。入力は残っています。もう一度お試しください');
        }
        return;
      }
      saveMsg.textContent = '保存中…';
      var saveResult;
      try {
        saveResult = refImgSave(it.cid, pending);
      } catch (e) {
        if (saveOp.fail()) showSaveFailure_();
        return;
      }
      Promise.resolve(saveResult).then(function (ok) {
        if (!saveOp.finish(ok)) return; // 時間切れ後の遅着結果で画面を閉じない
        if (!ok) { showSaveFailure_(); return; }
        saveMsg.textContent = '保存しました';
        if (onSaved) onSaved();
        setTimeout(function () { if (mySeq === _refOpenSeq) closeRefOverlay_(); }, 600);
      }, function () {
        if (saveOp.fail()) showSaveFailure_();
      });
    });    wirePaste_(body);
    ov.hidden = false;
  }

  // (メモ＋X/Bluesky URL の小モーダル openMemoUrlModal_ は廃止=投稿編集モーダル本体に統合・Chami依頼2026-08-09)
  // 動画作成タブへ切替え、候補の作品データ(前景画像/作者/コメント/作品URL)を各入力欄へ埋め込む。
  //   ※drafts.js の applyDraft_ と同じ手法：#author/#top/#movieWorkUrl を値+イベントで設定、
  //     前景画像は data-URL→File にして window.Go5SetForegroundFile() で #photo に反映。
  function transferToMovie_(it, imgDataUrl, comment, workUrl, imageRef) {
    // 候補専用ページ(KouhoLists.html)には動画作成タブのDOMが無い=そこから「動画を作る」を押したら、
    //   選択内容を sessionStorage で持ち越して index.html へ遷移し、あちらで同じ流し込みを再実行する
    //   (同一オリジン・同一タブなので sessionStorage は遷移後も残る。クラウド同期もしない)。
    if (!document.getElementById('author')) {
      var imageCid = (imageRef && imageRef.cid) || it.cid || '';
      var imageIndex = imageRef && Number.isFinite(Number(imageRef.index)) ? Math.max(0, Number(imageRef.index)) : 0;
      var carry = { it: it, imgDataUrl: imgDataUrl || '', comment: comment || '', workUrl: workUrl || '', imageCid: imageCid, imageIndex: imageIndex };
      try {
        sessionStorage.setItem('cand_to_movie_pending', JSON.stringify(carry));
      } catch (e) {
        // data URLがsessionStorageの容量を超えても、軽い参照情報を残して遷移先でIDBから同じ画像を復元する。
        carry.imgDataUrl = '';
        try { sessionStorage.removeItem('cand_to_movie_pending'); } catch (e1) {}
        try { sessionStorage.setItem('cand_to_movie_pending', JSON.stringify(carry)); } catch (e2) {}
      }
      try { location.href = 'index.html'; } catch (e) {}
      return;
    }
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
    // 作品名も渡す：総集編はジャンルタグに載らず作品名にだけ「総集編」と入る作品が多いため、
    //   ジャンルが空でも作品名に「総集編」があれば総集編カテゴリへ即チェック(Chami依頼2026-08-06)。
    if (window.Go5MovieAttrs && ((it.genres && it.genres.length) || it.title || it.floor || it.ai)) window.Go5MovieAttrs.applyGenres(it.genres || [], it.cid || '', it.title || '', it.floor || '', it.service || '', !!it.ai);
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
    // 候補を開いた時点で前作品の画像を破棄する(新画像の変換失敗時にも旧画像を誤表示しないため)。
    var imageApplySeq = null;
    if (window.Go5ClearForeground) imageApplySeq = window.Go5ClearForeground();
    // ★破棄したあと再適用が失敗すると fgImg=null のまま残り、make() が「写真未選択」ガードで無反応に見える沈黙に
    //   落ちる=「動画が生成されない」の芯(Chami報告2026-08-16・恒久対策C-038)。失敗経路は以下の3つ:
    //   ①持ち越しに画像が無い(sessionStorage容量超過→IDBからも復元不可・iOSのIDB無言死) ②fetch/decode失敗。
    //   どの経路でも黙って終えず、status に理由を出して写真の入れ直しへ導く(REQ-e145da61c0「無理なら手動で入れる」)。
    //   写真欄は動画作成タブ上部=直後の landAtMovieTop_ が最上部へ運ぶので、ここではスクロールしない。
    var candPhotoFail_ = function (reason) {
      var st = document.getElementById('status');
      if (st) st.textContent = '⚠ 候補の写真を読み込めませんでした(' + reason + ')。上の写真欄から選び直してから作成してください。';
    };
    if (imgDataUrl && window.Go5SetForegroundFile) {
      fetch(imgDataUrl).then(function (r) { return r.blob(); }).then(function (blob) {
        window.Go5SetForegroundFile(new File([blob], 'candidate.jpg', { type: blob.type || 'image/jpeg' }), imageApplySeq);
      }).catch(function (e) {
        try { console.warn('[go5 cand] 候補画像を動画作成へ変換できませんでした', e); } catch (e2) {}
        candPhotoFail_('取得に失敗');
      });
    } else {
      candPhotoFail_('画像が持ち越されていません');
    }
    // 作品データを流し込んだら、動画タブの「上部」に着地させる(Chami依頼2026-07-29：
    //   投稿編集→動画生成で最下段の作成ボタンへ強制スクロールしていたのをやめ、上から順に確認できるように)。
    //   作成ボタンは光らせておく＝下までスクロールすれば残り1タップと分かる(行動量支援は維持)。
    landAtMovieTop_();
  }
  // 動画タブの先頭へスクロール＋作成ボタン(#makeBtn)を一時ハイライト(スクロールはしない)。
  function landAtMovieTop_() {
    setTimeout(function () {
      try { window.scrollTo({ top: 0, behavior: 'auto' }); } catch (e) { try { window.scrollTo(0, 0); } catch (e2) {} }
      var mk = document.getElementById('makeBtn');
      if (mk) {
        mk.classList.add('cta-ready-pulse');
        setTimeout(function () { mk.classList.remove('cta-ready-pulse'); }, 2400);
      }
    }, 260); // タブ切替の描画が終わってから
  }
  // 保存直後に、その候補カードのサムネ＋コメント/メモを即時反映。(一覧を全再描画せず＝スクロール位置を保つ)
  //   ★コメント/メモは candCard と同一構造(cand-comment-row / cand-manage-row)で組み直し fitOneLineTexts_ で
  //     1行化する＝「保存直後に改行、リロードで直る」不整合を解消。(INC)
  function updateCardRefThumb_(cardEl, cid) {
    if (!cardEl) return;
    var col = cardEl.querySelector('.cand-thumbcol');
    if (col) {
      // ★スロットは候補カードと同じ refSlotHtml_ で全枚数(0枚時は状態札)を組み直す。判定は refSlotState_ に集約。
      //   タップ拡大は pageCand 委任(data-refimgview)が拾うためノード個別のリスナーは不要。
      var slot = col.querySelector('.cand-refimgs');
      if (!slot) {
        slot = document.createElement('div');
        slot.className = 'cand-refimgs';
        slot.setAttribute('data-refslot', cid);
        col.appendChild(slot);
      }
      slot.innerHTML = refSlotHtml_(cid);
      // 旧構造(スロット外に直接置いた単体サムネ/バッジ/折り返しコメント)の名残を掃除(:scopeは使わず親で判定)
      [].slice.call(col.querySelectorAll('.cand-refimg-thumb, .cand-refimg-multi, .cand-refimg-comment')).forEach(function (n) {
        if (n.parentNode === col) col.removeChild(n); // slot内の正規サムネは親がslotなので残す
      });
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
      // ★コメント・メモ両方ある時は、メモをコメントの上の行に独立表示(render()の主描画と同じ並び)。
      if (cmt && memo) {
        var mAboveRow = document.createElement('div'); mAboveRow.className = 'cand-comment-row cand-memo-above';
        var mAboveSpan = document.createElement('span'); mAboveSpan.className = 'cand-manage-memo'; mAboveSpan.textContent = memo;
        mAboveRow.appendChild(mAboveSpan); cardEl.appendChild(mAboveRow);
      }
      if (cmt) {
        var crow = document.createElement('div'); crow.className = 'cand-comment-row';
        var cspan = document.createElement('span'); cspan.className = 'cand-manage-comment'; cspan.textContent = cmt;
        crow.appendChild(cspan); cardEl.appendChild(crow);
      }
      var mrow = document.createElement('div'); mrow.className = 'cand-manage-row';
      if (memo && !cmt) { var mspan = document.createElement('span'); mspan.className = 'cand-manage-memo'; mspan.textContent = memo; mrow.appendChild(mspan); }
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
    // 新cidへの永続保存を確認するまで候補本体を書き換えず、旧cidも消さない。
    var refPayload = {
      imgs: Array.isArray(refData.imgs) ? refData.imgs : (refData.img ? [refData.img] : []),
      comment: refData.comment || '',
      memo: refData.memo || '',
      twitterUrl: refData.twitterUrl || oldItem.twitterUrl || '',
      urls2: Array.isArray(refData.urls2) ? refData.urls2 : (refData.twitterUrl2 ? [refData.twitterUrl2] : [])
    };
    var bimg = (bskyImgOf(oldCid) || {}).img;
    Promise.all([
      Promise.resolve(refImgSave(r.cid, refPayload)),
      bimg ? Promise.resolve(bskyImgSave(r.cid, bimg)) : Promise.resolve(true)
    ]).then(function (saved) {
      if (!saved[0] || !saved[1]) {
        cb(false, '画像・URL情報を保存できませんでした。もう一度お試しください');
        return;
      }
      // 新しいコピーが確定してから旧キーを掃除する。掃除失敗は重複が残るだけで、唯一のコピーは失わない。
      if (oldCid !== r.cid) {
        Promise.resolve(refImgSave(oldCid, null)).catch(function () {});
        Promise.resolve(bskyImgSave(oldCid, null)).catch(function () {});
      }
      var liveItems = lsGet(key, '[]');
      var newItem = Object.assign({}, oldItem, {
        url: url,
        cid: r.cid,
        isTwitter: false,
        twitterUrl: refPayload.twitterUrl,
        title: '(タイトル未取得)',
        addedAt: oldItem.addedAt || new Date().getTime()
      });
      var idx = -1; liveItems.forEach(function (x, i) { if (x.cid === oldCid) idx = i; });
      if (idx >= 0) liveItems[idx] = newItem; else liveItems.unshift(newItem);
      lsSet(key, liveItems);
      var cfg = workerCfg();
      var finish = function (info) {
        var arr = lsGet(key, '[]');
        arr.forEach(function (x) {
          if (x.cid !== r.cid || !info || !info.title) return;
          x.title = info.title; x.author = info.author || ''; x.thumb = info.thumb || info.thumbSmall || '';
          x.listPrice = info.listPrice; x.price = info.price; x.discountPct = info.discountPct || 0;
          x.date = info.releaseDate || ''; x.genres = info.genres || [];
          x.floor = info.floor || ''; x.service = info.service || '';
          x.reviewCount = info.reviewCount; x.reviewAvg = info.reviewAvg;
          if (info.samples && info.samples.length) x.samples = info.samples;
        });
        lsSet(key, arr); recordReviewSnapshots(arr); cb(true);
      };
      if (window.FanzaCore && cfg.url) window.FanzaCore.fetchFanzaInfo(r.cid, cfg.url, cfg.secret, url).then(function (info) { finish(info && info.title ? info : null); }).catch(function () { finish(null); });
      else finish(null);
    }).catch(function () {
      cb(false, '画像・URL情報を保存できませんでした。もう一度お試しください');
    });
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
      var btn = this;
      if (btn.disabled) return;
      btn.disabled = true;
      body.querySelector('#bskyImgMsg').textContent = '保存中…';
      Promise.resolve(bskyImgSave(it.cid, pending.img)).then(function (ok) {
        if (!ok) {
          btn.disabled = false;
          body.querySelector('#bskyImgMsg').textContent = '⚠️ 保存できませんでした。もう一度お試しください';
          return;
        }
        body.querySelector('#bskyImgMsg').textContent = '✅ 保存しました';
        if (onSaved) onSaved();
        setTimeout(function () { ov.hidden = true; }, 600);
      }).catch(function () {
        btn.disabled = false;
        body.querySelector('#bskyImgMsg').textContent = '⚠️ 保存できませんでした。もう一度お試しください';
      });
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
  // カード一覧は同期・画像展開・作品情報取得でinnerHTMLが差し替わる。
  // pageCand(不変の親)でクリックを受けるイベント委譲にし、差し替え直後の新しいボタンも必ず動かす。
  function dataTarget_(node, attr, root) {
    var cur = node;
    while (cur && cur !== root) {
      try { if (cur.nodeType === 1 && cur.hasAttribute && cur.hasAttribute(attr)) return cur; } catch (e) {}
      cur = cur.parentNode;
    }
    return null;
  }
  // 通常は描画時の索引を使う。非同期描画の境界だけ索引が入れ替わっていても、保存済み候補から復元する。
  function durableItemByCid_(cid) {
    var hit = itemByCid_(cid);
    if (hit) return hit;
    var groups = [lsGet(itemsKey(_activeTab), '[]')];
    if (_activeTab !== 'main') groups.push(lsGet(K_ITEMS, '[]'));
    var tabs = lsGet(K_TABS, '[]');
    tabs.forEach(function (t) { if (!isMakerTab_(t)) groups.push(lsGet(itemsKey(t.id), '[]')); });
    for (var gi = 0; gi < groups.length; gi++) {
      for (var ii = 0; ii < groups[gi].length; ii++) {
        if (groups[gi][ii] && String(groups[gi][ii].cid) === String(cid)) return groups[gi][ii];
      }
    }
    return null;
  }
  function liveRefButton_(page, cid) {
    var found = null;
    page.querySelectorAll('[data-refimg]').forEach(function (b) {
      if (!found && String(b.getAttribute('data-refimg')) === String(cid)) found = b;
    });
    return found;
  }
  function ensureCardDelegation_(page) {
    if (!page || page._go5CardDelegated) return;
    page._go5CardDelegated = true;
    page.addEventListener('click', function (e) {
      var refBtn = dataTarget_(e.target, 'data-refimg', page);
      if (refBtn) {
        e.preventDefault();
        var cid = refBtn.getAttribute('data-refimg');
        var it = durableItemByCid_(cid);
        if (!it) {
          // 索引の切替境界なら同期描画で索引を作り直し、このクリック内でそのまま開く。
          render();
          it = durableItemByCid_(cid);
        }
        if (!it) return;
        openRefImgModal_(it, function () {
          var live = liveRefButton_(page, cid);
          if (!live) return;
          var has = refImgHas(cid);
          live.classList.toggle('has-img', has);
          live.textContent = '投稿編集';
          updateCardRefThumb_(live.closest ? live.closest('.cand-card') : null, cid);
        });
        return;
      }
      var refView = dataTarget_(e.target, 'data-refimgview', page);
      if (refView) {
        var rc = refView.getAttribute('data-refimgview'), imgs = refImgsOf_(rc);
        var start = parseInt(refView.getAttribute('data-refidx'), 10); // タップした画像から開く(全枚数表示に対応)
        if (!(start >= 0 && start < imgs.length)) start = 0;
        if (imgs.length) openImgZoom_(imgs, start, { onReorder: function (i) { return reorderRefImgToFirst_(rc, i); }, onPasteAdd: function (done) { pasteAddRefImgToFirst_(rc, done); } });
        return;
      }
      // ★サムネ再取得プレースホルダ(下の error ハンドラが差し込む札)のタップ=作品情報ごと取り直す。
      //   既存の per-card 配線(wireCardCommon_)は描画時のノードにしか付かないため、動的差替え分は委任で拾う。
      var reload = dataTarget_(e.target, 'data-reloadinfo', page);
      if (reload) { var rcid = reload.getAttribute('data-reloadinfo'); if (rcid) reloadWorkInfo_(rcid, reload); return; }
      var thumb = dataTarget_(e.target, 'data-thumbcid', page);
      if (thumb) openThumbModal_(durableItemByCid_(thumb.getAttribute('data-thumbcid')));
    });
    // ★候補サムネ(FANZA CDN)/Buzzサムネは onerror が無く、一過性のネット断・iOSのlazy-load中断・省データで
    //   壊れ画像のまま固着していた(reconcile_ がノードを署名一致で使い回す=同一セッション中はもう再要求されない
    //   =「候補で画像読み込まない時多すぎ」の主犯・Fable5診断案1/A・B・2026-08-17)。error はバブルしないので
    //   capture で1本拾い、同一URLを数回だけ静かに再要求→上限でタップ再取得の札へ差し替える(必ず何か出す)。
    page.addEventListener('error', function (e) {
      var img = e.target;
      if (!img || img.tagName !== 'IMG' || !img.classList) return;
      if (!(img.classList.contains('cand-thumb') || img.classList.contains('buzz-thumb') || img.classList.contains('cand-refimg-thumb'))) return;
      if (img.classList.contains('cand-thumb-ph')) return;
      var url = img.getAttribute('src') || '';
      if (!/^https?:\/\//.test(url)) return; // dataURL/相対(=手元の生成用画像等)は対象外。外部CDN URLだけ再取得する。
      var n = parseInt(img.getAttribute('data-imgretry') || '0', 10) || 0;
      if (n < 2) {
        img.setAttribute('data-imgretry', String(n + 1));
        setTimeout(function () {
          if (!img.isConnected) return;                         // 既に外れたノードは触らない
          if (img.complete && img.naturalWidth > 0) return;     // その後ロードに成功していれば何もしない
          var u = img.getAttribute('src') || url;
          img.removeAttribute('src'); img.setAttribute('src', u); // 同一URLを空→再設定で再ロードを促す(クエリを足さない=CDNキャッシュを割らない)
        }, n === 0 ? 1200 : 4000);
      } else {
        // 上限到達=作品情報ごと取り直せるタップ札へ差し替える(cand-thumb のみ。buzz/refは静かに枠のまま)。
        var cid = img.getAttribute('data-thumbcid') || '';
        if (cid && img.parentNode) {
          var ph = document.createElement('div');
          ph.className = 'cand-thumb cand-thumb-ph cand-thumb-reload';
          ph.setAttribute('data-reloadinfo', cid);
          ph.setAttribute('title', 'タップで画像を再取得');
          ph.textContent = '🔁';
          img.parentNode.replaceChild(ph, img);
        }
      }
    }, true);
  }
  // カード共通の配線：サムネのタップで画像モーダル／🖼投稿画像ボタン。
  function wireCardCommon_(el) {
    wireAcctRow_(el); // カード右上のチャンネル切替＋投稿済み表示
    fitOneLineTexts_(el); // コメント/メモを1行に収める(可変フォント)
    el.querySelectorAll('[data-reloadinfo]').forEach(function (b) {
      b.addEventListener('click', function () {
        var cid = b.getAttribute('data-reloadinfo'); if (!cid) return;
        reloadWorkInfo_(cid, b);
      });
    });
  }
  // 1作品だけ作品情報(タイトル・サムネ・作者・価格・発売日・レビュー等)をworkerから取り直して候補データへ書き戻す。
  //   「情報は取れたがサムネだけ空」のような部分取得を、作品ごとに手動で埋め直すための導線(Chami依頼2026-07-29)。
  //   一時失敗(タイムアウト/5xx=retryable)は1回だけ即リトライしてから諦める(追加時・backfillと同じ作法)。
  function reloadWorkInfo_(cid, btn) {
    var it = itemByCid_(cid); if (!it) return;
    if (!window.FanzaCore) { if (btn) { btn.textContent = '⚠️ 取得不可'; } return; }
    var cfg = workerCfg(); if (!cfg.url) { if (btn) { btn.textContent = '⚠️ worker未設定'; } return; }
    if (btn && btn.disabled) return;
    var label = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.textContent = '⏳ 取得中…'; }
    var once = function () { return window.FanzaCore.fetchFanzaInfo(cid, cfg.url, cfg.secret, it.url); };
    once().then(function (info) {
      if (info && info.title) return info;
      if (info && info.retryable) return once();
      return info;
    }).then(function (info) {
      if (!(info && info.title)) { if (btn) { btn.disabled = false; btn.textContent = '⚠️ 失敗'; setTimeout(function () { btn.innerHTML = label; }, 2200); } return; }
      // ★書き戻しは現在のlocalStorage配列を読み直してcidで当てる(古い参照itemsを上書きしない・backfillと同じ考え方)。
      var key = itemsKey(_activeTab), arr = lsGet(key, '[]'), changed = false;
      arr.forEach(function (x) {
        if (!x || x.cid !== cid) return;
        x.title = info.title; x.author = info.author || ''; x.thumb = info.thumb || info.thumbSmall || '';
        x.listPrice = info.listPrice; x.price = info.price; x.discountPct = info.discountPct || 0;
        x.date = info.releaseDate || ''; x.genres = info.genres || [];
        x.floor = info.floor || ''; x.service = info.service || ''; // AI判定用(floor名でしか分からない作品を候補→作成へ運ぶ)
        x.reviewCount = info.reviewCount; x.reviewAvg = info.reviewAvg;
        if (info.samples && info.samples.length) x.samples = info.samples;
        changed = true;
      });
      if (changed) { lsSet(key, arr); recordReviewSnapshots(arr); }
      // 取り直せたら未取得フェーズの記録も掃除(再取得の追跡対象から外す)。
      try { var miss = lsGet(K_INFOMISS, '{}'); if (miss[cid] != null) { delete miss[cid]; lsSet(K_INFOMISS, miss); } } catch (e) {}
      repaintCand_(_activeTab); // サムネ含め即反映(リロード不要)。差分更新=他カードの画像はチラつかせない
    }).catch(function () { if (btn) { btn.disabled = false; btn.textContent = '⚠️ 失敗'; setTimeout(function () { btn.innerHTML = label; }, 2200); } });
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
      '<input id="candPriceMax" type="number" inputmode="numeric" min="0" step="100" placeholder="円以下" value="' + (_priceMax ? _priceMax : '') + '" style="width:88px;"></label>';
      // 外側の「円以下」ラベルは廃止。テキストボックスの placeholder="円以下" に記載があるため重複(Chami 2026-08-11)。
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

  // 選んだサブタブ(候補タブ内のバズ/手動追加/全候補/サークル)を横スクロール帯の中央へ寄せる。
  //   上位のメインタブ(affiliate.js centerTab_)と同じ考え方=scrollIntoView は祖先ごと動いて
  //   画面が飛ぶため使わず、.cand-tabs の scrollLeft だけを動かす(Chami依頼 2026-08-08)。
  function centerActiveSubTab_() {
    try {
      var page = $('pageCand'); if (!page) return;
      var bar = page.querySelector('.cand-tabs'); if (!bar) return;
      var b = bar.querySelector('.cand-tab.active'); if (!b) return;
      if (bar.scrollWidth <= bar.clientWidth) return; // 全部収まっていれば動かさない(PC等)
      var barRect = bar.getBoundingClientRect();
      var bRect = b.getBoundingClientRect();
      var delta = (bRect.left - barRect.left) + b.offsetWidth / 2 - bar.clientWidth / 2;
      bar.scrollLeft += delta;
    } catch (e) {}
  }

  // ── DOM ──
  function render() {
    var page = $('pageCand');
    if (!page) return;
    ensureCardDelegation_(page); // page自体は再描画で交換されないため、カード差し替え後も操作を受け続ける
    _bgRerenderPending = false; // どの経路の描画でも保留は解消(追加確定・タブ再入場で最新へ追いつく)
    kickInfoBackfill_(); // タブへ戻ってきた時=未取得タイトルの追跡を素早いフェーズへ戻す(この後の描画でbackfillが回る)
    var tabs = lsGet(K_TABS, '[]');
    var tabBtns = '<button class="cand-tab cand-tab-buzz' + (_activeTab === 'buzz' ? ' active' : '') + '" data-ct="buzz" type="button">🦋 ' + esc(builtinTabLabel_('buzz')) + '</button>' +
      '<button class="cand-tab' + (_activeTab === 'main' ? ' active' : '') + '" data-ct="main" type="button">💡 ' + esc(builtinTabLabel_('main')) + '</button>' +
      '<button class="cand-tab' + (_activeTab === 'all' ? ' active' : '') + '" data-ct="all" type="button">📚 ' + esc(builtinTabLabel_('all')) + '</button>' +
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
    // 選択中のサブタブを帯の中央へ(クリック/アクセス時ともここを通る)。画像・フォントで幅が後から
    //   変わるので、初回レイアウト後(rAF)に寄せ直す(Chami依頼 2026-08-08)。
    if (window.requestAnimationFrame) window.requestAnimationFrame(centerActiveSubTab_); else centerActiveSubTab_();
  }
  // 候補アイテムの保存先: メインは cand_items、独立タブは各タブ固有キー。(表示を共有しない)
  function itemsKey(tabId) { return (!tabId || tabId === 'main') ? K_ITEMS : 'cand_items__' + tabId; }

  // 全候補cid集合をD1へ同期(部門が「全候補だけ」を読めるように)。変化時のみPOST=無駄打ち防止。
  //   送るのは除外タブ反映後の"キュレート集合"(価格/セール絞込は表示専用なので含めない)。
  function syncCandidatePool_(cids) {
    try {
      var cfg = workerCfg();
      if (!cfg || !cfg.url || !cfg.secret) { var miss = []; if (!cfg || !cfg.url) miss.push('URL'); if (!cfg || !cfg.secret) miss.push('シークレット'); poolSyncNote_('設定なし(' + miss.join('/') + '欠)＝同期せず'); return; } // worker未設定なら同期しない(表示は動く)
      // 引数は cid の配列(旧)でも {cid,source} の配列(新)でも可。初出勝ちで重複排除。
      //   source='main'(手動追加💡)/'circle'(サークル)/'list'(独立タブ)。部門が WHERE source='main' で手動追加だけを再スライスできる(2026-08-09)。
      var uniq = []; var seen = {};
      (cids || []).forEach(function (e) {
        var c = (e && typeof e === 'object') ? e.cid : e;
        var src = (e && typeof e === 'object') ? (e.source || null) : null;
        if (c && !seen[c]) { seen[c] = true; uniq.push({ cid: String(c), source: src }); }
      });
      // hashにsourceも含める=出所の付け替えが起きたら12h未満でも送り直す。
      var hash = uniq.map(function (u) { return u.cid + '~' + (u.source || ''); }).sort().join(',');
      var last = '', lastAt = 0;
      try { last = localStorage.getItem('cand_pool_hash') || ''; lastAt = parseInt(localStorage.getItem('cand_pool_hash_at') || '0', 10) || 0; } catch (e) {}
      // 前回と同じ集合でも、最後に成功したPOSTから12hを超えたら送り直す。=D1の updated_at を「生存信号」に
      //   する。以前は hash 一致で無音returnしていたため、初回に小集合(d_754842の1件)が入ると以後どのリロード
      //   でも send をスキップし、D1が1件に永久に張り付いた(商品候補選定部門の実測・updated_at 6日凍結)。
      //   cand_pool_hash_at は端末ローカル(storage-keys 未登録=既定で非同期)＝端末ごとの生存タイマー。
      var STALE_MS = 12 * 3600 * 1000;
      if (hash === last && lastAt && (new Date().getTime() - lastAt) < STALE_MS) { poolSyncNote_('スキップ:新鮮 ' + uniq.length + '件(前回送信から12h未満)'); return; } // 集合同一かつ新鮮＝送らない
      poolSyncNote_('送信中… ' + uniq.length + '件');
      var bodyStr = JSON.stringify({ cids: uniq });
      // ★iOS Safari はタブが裏に回ると in-flight fetch を中断し then/catch が一度も発火しない
      //   (Chami がスクショのためアプリ切替する導線で「送信中…」のまま固まりD1未更新・星南の実機実測
      //    2026-08-05・レスポンスが返らない=接続が生きていない)。keepalive でバックグラウンド化・
      //   ページ破棄後もブラウザがリクエストを送り切る。keepalive は本文64KB制限があるため、超える
      //   大集合(数千件)では付けない=その時は通常fetch(前面にいる間に完了する運用)。
      var fetchOpts = {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret },
        body: bodyStr
      };
      var _sz = 0; try { _sz = (new Blob([bodyStr])).size; } catch (e) { _sz = bodyStr.length; }
      if (_sz < 60000) fetchOpts.keepalive = true;
      fetch(cfg.url + '/api/candidate-pool', fetchOpts).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
        if (j && j.ok) { poolSyncNote_('送信OK ' + uniq.length + '件'); try { localStorage.setItem('cand_pool_hash', hash); localStorage.setItem('cand_pool_hash_at', String(new Date().getTime())); } catch (e) {} }
        else { poolSyncNote_('送信NG(ok=false/HTTPエラー) ' + uniq.length + '件'); try { console.warn('[candidate-pool] 同期POSTが失敗(ok=false)'); } catch (e) {} }
      }).catch(function () { poolSyncNote_('通信エラー(次回再送) ' + uniq.length + '件'); try { console.warn('[candidate-pool] 同期POSTが通信エラー(次回再送)'); } catch (e) {} });
    } catch (e) {}
  }

  var _poolSyncTimer = null;
  // 保存済み候補(main + 独立タブ + サークル(maker)タブ)の cid を D1 へ同期。起動時・追加・削除時に呼ぶ。
  //   ★サークルタブの作品も含める(2026-08-05 修正)。以前は「API非同期取得が要る」を理由に除外し、
  //   📚全候補タブを手で開いた時(renderAll_)しかサークル分がD1へ行かなかった。POSTは総入れ替え(fanza-worker)
  //   なので、この自動経路が main だけの小集合を送るたびにD1をサークル抜きへ削り戻していた=Chamiの候補が
  //   大半サークルタブだと D1 が d_754842 の1件に張り付く(商品候補選定部門の実測)。renderAll_ と同じ集合を
  //   送ることで cand_pool_hash の食い違いによる削り合いも消える。サークル作品は fetchMakerItemsMulti が
  //   キャッシュ(cand_mk2__)を使う(force=false)ので通常は通信なしで乗る(キャッシュ切れ時のみAPI)。
  function schedulePoolSync_() {
    if (_poolSyncTimer) clearTimeout(_poolSyncTimer);
    _poolSyncTimer = setTimeout(function () {
      _poolSyncTimer = null;
      var tabs = lsGet(K_TABS, '[]');
      var seen = {}, cids = [], makerIds = [];
      // ★cid が未解決の候補(URL追加後にcid抽出前 / Books .com 旧数字ID↔新content_id 食い違い)も
      //   その場で url から cid を解決して同期に乗せる。cidFromUrl_ は同期(通信なし・buildAffiliateLink)。
      // ★source: main(手動追加💡=K_ITEMS)を最初に走査=初出勝ちで手動追加の帰属を保つ(2026-08-09)。
      function pushCid_(it, src) {
        var c = (it && it.cid) ? String(it.cid) : cidFromUrl_((it && it.url) || '');
        if (c && !seen[c]) { seen[c] = true; cids.push({ cid: c, source: src }); }
      }
      (lsGet(K_ITEMS, '[]') || []).forEach(function (it) { pushCid_(it, 'main'); });
      tabs.forEach(function (t) {
        if (t.excludeFromAll) return;
        if (isMakerTab_(t)) { makerIdsOf(t).forEach(function (id) { if (makerIds.indexOf(id) < 0) makerIds.push(id); }); return; }
        (lsGet('cand_items__' + t.id, '[]') || []).forEach(function (it) { pushCid_(it, 'list'); });
      });
      function done_() { syncCandidatePool_(cids); }
      var K_MK_OK = 'cand_maker_cids_ok'; // 前回"取得成功"したサークルcid集合(端末ローカル・全滅時の代替に使う)
      // サークル分は cid のみを集めればよい(並びは同期に無関係)。キャッシュ優先=force省略。
      //   ★全滅(err && !items)でも done_() は必ず呼ぶ。以前は 2098 で return し done_()=POST自体が
      //     一度も発火しなかった(main分すら送られずD1が7/30から凍結・商品候補選定部門の実測・星南が行特定)。
      //   ★削り戻し防止は「集合を縮めない」で担保する=全滅時は前回成功したサークルcidを端末から復元して
      //     cidsへ足す(集合が main だけに縮まない)＝削り戻さず、かつPOSTは発火させる。
      if (makerIds.length) fetchMakerItemsMulti(makerIds, _sort, function (items, err) {
        if (err && !items) {
          var saved = [];
          try { saved = (localStorage.getItem(K_MK_OK) || '').split(',').filter(Boolean); } catch (e) {}
          saved.forEach(function (c) { if (c && !seen[c]) { seen[c] = true; cids.push({ cid: c, source: 'circle' }); } });
          done_(); // 前回成功したサークル分を保って発火(縮めない・削り戻さない)
          return;
        }
        var mkCids = [];
        (items || []).forEach(function (it) {
          var c = (it && it.cid) ? String(it.cid) : cidFromUrl_((it && it.url) || '');
          if (c) { mkCids.push(c); if (!seen[c]) { seen[c] = true; cids.push({ cid: c, source: 'circle' }); } }
        });
        try { localStorage.setItem(K_MK_OK, mkCids.join(',')); } catch (e) {} // 成功時だけ更新
        done_();
      });
      else done_();
    }, 500);
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
        '<button id="candEditBuiltin" type="button" class="ghost" title="タブ名を変更" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">✏️ 名前</button>' +
      '</div>' +
      // アカウント別「投稿済みを非表示」トグル。(全候補でも isHiddenByPosted_ を尊重=L2103)
      candHidePostedRowHtml_() +
      '<div style="display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap;">' +
        '<label class="cand-filter-sale" style="margin:0;"><input id="candFilterSale" type="checkbox"' + (_filterSale ? ' checked' : '') + '><span>セール中のみ</span></label>' +
        priceFilterHtml_() +
        candColsCtlHtml_() +
      '</div>' +
      '<div class="hint" style="margin-top:6px;">💡候補・独立タブ・全サークルタブの作品をまとめて表示します。タブの✏️編集で「全候補に含まない」にしたタブは除外(各部門もこの一覧の作品だけを読みます)。</div>' +
      '<div class="hint" style="margin-top:2px;opacity:.7;">🔎D1同期の最後: ' + esc(poolSyncNoteRead_() || '(まだ実行なし)') + '</div>' +
      '</div>' +
      '<div id="candEditForm"></div>' +
      '<div id="candList"><p class="hint" style="padding:8px;">⏳ 全候補を集約中…</p></div>';
    $('candSort').addEventListener('change', function () { _sort = this.value; renderAll_(); });
    $('candFilterSale').addEventListener('change', function () { _filterSale = this.checked; renderAll_(); });
    wirePriceFilter_(function () { renderAll_(); });
    wireCandColsCtl_();
    wireHidePostedButtons_(function () { renderAll_(); });
    wireBuiltinRename_('all');

    // 保存アイテム(main + 独立listタブ・除外でない)を集約し、サークルidを収集。
    // ★srcByCid: cidの出所を初出勝ちで記録(main→list→circle)。D1同期のsource付与に使う(2026-08-09)。
    var seen = {}, stored = [], srcByCid = {};
    function addItems(a, src) { (a || []).forEach(function (it) { if (it && it.cid != null && !seen[it.cid]) { seen[it.cid] = true; stored.push(it); srcByCid[it.cid] = src; } }); }
    addItems(lsGet(K_ITEMS, '[]'), 'main'); // 💡候補(main)は常に含む
    var makerIds = [];
    tabs.forEach(function (t) {
      if (t.excludeFromAll) return; // このタブを全候補に含まない
      if (isMakerTab_(t)) makerIdsOf(t).forEach(function (id) { if (makerIds.indexOf(id) < 0) makerIds.push(id); });
      else addItems(lsGet('cand_items__' + t.id, '[]'), 'list'); // 独立した候補リストタブ
    });

    function finish(makerItems) {
      var el = $('candList');
      if (!el || _activeTab !== 'all') return; // 集約中にタブが変わっていたら破棄
      var all = stored.slice();
      (makerItems || []).forEach(function (it) { if (it && it.cid != null && !seen[it.cid]) { seen[it.cid] = true; all.push(it); srcByCid[it.cid] = 'circle'; } });
      // 部門ブリッジ: 除外反映後の全候補cid(表示フィルタ前=キュレート集合)をD1へ同期。source付き=部門が手動追加だけを再スライスできる。
      syncCandidatePool_(all.map(function (it) { return { cid: it.cid, source: srcByCid[it.cid] || null }; }));
      var arr = sortItems(all, _sort).filter(function (it) {
        if (_filterSale && !isOnSale_(it)) return false;
        if (!passPrice_(it)) return false;
        if (isHiddenByPosted_(it)) return false; // アカウント別「投稿済みを非表示」は全候補でも尊重
        return true;
      });
      _cardIndex = {}; arr.forEach(function (it) { _cardIndex[it.cid] = it; });
      if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">表示できる作品がありません。(💡候補やサークルタブに作品を追加してください)</p>'; return; }
      var salesCids = salesTargetCids_(arr);
      el.innerHTML = '<p class="hint" style="padding:2px 6px;">📚 全候補 ' + arr.length + '件</p>' +
        arr.map(function (it) { return candCard(it, ''); }).join('');
      wireCardCommon_(el);
      fetchSalesFor(salesCids, function (changed) { if (changed && _activeTab === 'all') renderAll_(); });
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
      pasteRow_('<input id="candTabSrc" size="1" type="text" inputmode="url" placeholder="空欄なら「ただの候補タブ」になります" autocomplete="off" style="flex:1;min-width:0;">', 'candTabSrc') +
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
      '<button id="candEditBuiltin" type="button" class="ghost" title="タブ名を変更" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 10px;">✏️ 名前</button>' +
      '<button id="buzzReload" type="button" class="ghost" title="最新を取り直す" style="flex:0 0 auto;width:auto;margin:0;font-size:15px;padding:6px 10px;">🔁</button>' +
      '</div>' +
      '<div class="hint" style="margin-top:6px;">フォローしている人の直近' + BUZZ_RECENT_DAYS + '日の投稿を、<b>反応の多い順</b>に並べます。' +
      'Blueskyは表示回数(インプレッション)を公開していないため、<b>エンゲージメント(❤️いいね+🔁リポスト+💬返信+❝引用)</b>が唯一の勢いの指標です。</div>' +
      '</div>';
    if (!accs.length) {
      body.innerHTML = head + '<div id="candEditForm"></div>' + '<div class="card"><div class="hint">⚠️ Blueskyのハンドルが未設定です。🦋投稿タブの⚙設定でハンドル(@…)を保存すると、そのアカウントのフォローが対象になります。</div></div>';
      wireBuzzReload_();
      wireBuiltinRename_('buzz');
      return;
    }
    var namesLabel = accs.map(function (o) { return '@' + (o.handle || o.did.slice(0, 14) + '…'); }).join(' / ');
    body.innerHTML = head + '<div id="candEditForm"></div>' +
      '<div class="hint" style="margin:6px 2px;">対象アカウント：' + esc(namesLabel) + '</div>' +
      '<div id="buzzList"><div class="card"><div class="hint">⏳ フォローと投稿を集計中…(初回・更新直後は少し時間がかかります)</div></div></div>';
    wireBuzzReload_();
    wireBuiltinRename_('buzz');
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
      '<div style="margin-top:6px;">' + pasteRow_('<input id="candUrl" size="1" type="text" inputmode="url" class="cand-refimg-line" placeholder="https://…(作品URL or アフィリンク)" autocomplete="off" style="flex:1;min-width:0;">', 'candUrl') + '</div>' +
      '<label class="hint" style="display:block;margin:8px 0 2px;">X / Bluesky の投稿URL(任意)— <b>これだけでも追加できます</b></label>' +
      '<div>' + pasteRow_('<input id="candTwitter" size="1" type="text" inputmode="url" class="cand-refimg-line" placeholder="https://x.com/…/status/… か https://bsky.app/profile/…/post/…" autocomplete="off" style="flex:1;min-width:0;">', 'candTwitter') + '</div>' +
      '<label class="hint" style="display:block;margin:10px 0 2px;">動画生成用の画像(任意・最大4枚)— ボタンを押すとコピー中の画像が左から入ります</label>' +
      '<div class="cand-add-imgrow">' + slots + '</div>' +
      '<div style="margin-top:6px;display:flex;">' +
        '<label class="ghost cand-refimg-pick" style="width:auto;flex:0 0 auto;margin:0;">画像を選ぶ<input id="candAddImgFile" type="file" accept="image/*" multiple style="display:none;"></label>' +
      '</div>' +
      // ボタン幅は固定せず内容(テキスト)に追従。(width:max-content)続行ボタンは小さめ＝メモ欄を広く。
      '<div style="display:flex;gap:8px;margin-top:8px;align-items:stretch;">' +
        '<input id="candMemo" size="1" type="text" class="cand-refimg-line" placeholder="メモ(任意・候補のメモに保存)" autocomplete="off" style="flex:1;min-width:0;">' +
        '<button id="candAdd" type="button" class="primary" style="margin:0;font-size:.78rem;padding:8px 10px;width:max-content;flex:0 0 auto;white-space:nowrap;">' + (isMain ? '候補に追加 / 続行' : 'このタブに追加 / 続行') + '</button>' +
      '</div>' +
      '<div id="candMsg" class="hint" style="min-height:1.3em;"></div>' +
      '<div style="border-top:1px solid var(--line);margin:10px 0 0;padding-top:10px;">' +
        '<div class="hint">サークルの作品をまとめて' + (isMain ? '候補' : 'このタブ') + 'に追加できます。<br>(サークルID / サークルURL / 作品URLのどれか)</div>' +
        '<div style="margin-top:6px;">' + pasteRow_('<input id="candBulkSrc" size="1" type="text" inputmode="url" class="cand-refimg-line" placeholder="サークルID / サークルURL / 作品URL" autocomplete="off" style="flex:1;min-width:0;">', 'candBulkSrc') + '</div>' +
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
  var _candAddNotice = '';
  var _candAddNoticeTimer = null;
  var _candAddHydrationPending = false;
  var _prefetchCache = {}; // { cid: { done: bool, info: obj|null, errored: bool } }
  var _prefetchTimer = null;
  function showCandAddNotice_(msgEl, text) {
    if (msgEl) msgEl.textContent = text || '';
    _candAddNotice = text || '';
    var pageMsg = $('candPageMsg');
    if (pageMsg) {
      pageMsg.textContent = _candAddNotice;
      pageMsg.hidden = !_candAddNotice;
    }
    if (_candAddNoticeTimer) clearTimeout(_candAddNoticeTimer);
    if (_candAddNotice) {
      _candAddNoticeTimer = setTimeout(function () {
        _candAddNotice = '';
        var el = $('candPageMsg');
        if (el) { el.textContent = ''; el.hidden = true; }
      }, 8000);
    }
  }
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
  function attachAddImgs_(cid, keepForm) {
    var imgs = _addModalImgs.filter(Boolean);
    var memoEl = $('candMemo');
    var memo = (memoEl && memoEl.value || '').trim(); // メモ欄に入力があれば候補のメモへ保存
    if (!cid) return;
    if (imgs.length || memo) {
      var cur = refImgOf(cid) || {};
      refImgSave(cid, { imgs: imgs.length ? imgs : (cur.imgs || []), comment: cur.comment || '', memo: memo || cur.memo || '', twitterUrl: cur.twitterUrl || '', twitterUrl2: cur.twitterUrl2 || '' });
    }
    if (!keepForm) {
      if (memoEl) memoEl.value = ''; // 追加後はメモ欄をクリア(続ける時に持ち越さない)
      _addModalImgs = [];
      renderAddSlots_();
    }
  }
  // iOS Safariでは入力欄にフォーカス(=ソフトキーボード表示)がある状態でボタンを押すと、
  //   最初のタップがキーボードを閉じる動作に消費され click が発火せず「一度押しても反応しない=
  //   二度押しが要る」状態になる(Chami 2026-08-04・候補追加の「追加して閉じる」で発生)。
  //   → touchend で拾えば初回タップで発火する(スクロール中の誤爆は移動量で弾き、preventDefaultで
  //   後続のゴーストclickを抑止=二重実行しない)。デスクトップは touch が無いので click 経路で動く。
  function onTap_(el, fn) {
    if (!el) return;
    var lock = false, sx = 0, sy = 0, moved = false;
    function run(e) { if (lock) return; lock = true; setTimeout(function () { lock = false; }, 500); fn(e); }
    el.addEventListener('touchstart', function (e) {
      var t = e.touches && e.touches[0]; sx = t ? t.clientX : 0; sy = t ? t.clientY : 0; moved = false;
    }, { passive: true });
    el.addEventListener('touchmove', function (e) {
      var t = e.touches && e.touches[0];
      if (t && (Math.abs(t.clientX - sx) > 10 || Math.abs(t.clientY - sy) > 10)) moved = true;
    }, { passive: true });
    el.addEventListener('touchend', function (e) { if (moved) return; e.preventDefault(); run(e); }, { passive: false });
    el.addEventListener('click', run);
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
    onTap_($('candAdd'), function () { addCandidate(tabId); }); // 追加して続ける(開いたまま)
    onTap_($('candAddClose'), function () { ov.hidden = true; addCandidate(tabId); }); // 追加して閉じる(即閉→バックグラウンド処理・iOSの二度押しを解消)
    onTap_($('candBulkAdd'), function () { bulkAddCircle(tabId); });
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
    // fix③: URL欄へのペースト/入力と同時にFANZA情報の先読みを開始(ボタン押下時は既に取得済みになる)
    clearTimeout(_prefetchTimer); _prefetchTimer = null;
    var urlInp = $('candUrl');
    if (urlInp) urlInp.addEventListener('input', function () {
      clearTimeout(_prefetchTimer);
      var raw = urlInp.value.trim();
      var urlN = window.normalizeWorkUrl ? window.normalizeWorkUrl(raw) : raw;
      var rPre = (raw && urlN && window.buildAffiliateLink) ? window.buildAffiliateLink(urlN, '') : null;
      if (!rPre || !rPre.ok) return;
      if (_prefetchCache[rPre.cid] && _prefetchCache[rPre.cid].done) return; // 取得済み
      var cfg2 = workerCfg();
      if (!window.FanzaCore || !cfg2.url) return;
      var cidPre = rPre.cid, urlPre = urlN;
      _prefetchTimer = setTimeout(function () {
        // ★入れた瞬間(入力が落ち着いたら)にアフィリンクを素の作品URLへ無効化=見た目にも反映する
        //   (Chami 2026-08-04・al.fanza.co.jp/?lurl=… や計測パラメータ付きを素URLへ)。素URLと同じなら触らない。
        var rawNow = urlInp.value.trim();
        var urlNow = window.normalizeWorkUrl ? window.normalizeWorkUrl(rawNow) : rawNow;
        if (urlNow && urlNow !== rawNow) { urlInp.value = urlNow; }
        if (_prefetchCache[cidPre]) return; // 取得中または完了
        _prefetchCache[cidPre] = { done: false };
        var pm = $('candMsg'); if (pm) pm.textContent = '⏳ 作品情報を先読み中…';
        var fOnce = function () { return window.FanzaCore.fetchFanzaInfo(cidPre, cfg2.url, cfg2.secret, urlPre); };
        fOnce().then(function (info) {
          if (info && info.title) {
            _prefetchCache[cidPre] = { done: true, info: info, errored: false };
            var m = $('candMsg'); if (m) m.textContent = '✅ 作品情報を取得済み — 追加ボタンで確定';
          } else if (info && info.retryable) {
            fOnce().then(function (info2) {
              var ok2 = !!(info2 && info2.title);
              _prefetchCache[cidPre] = { done: true, info: ok2 ? info2 : null, errored: !ok2 };
              var m = $('candMsg'); if (m) m.textContent = ok2 ? '✅ 作品情報を取得済み — 追加ボタンで確定' : '⚠️ 作品情報の取得に失敗(追加ボタンで再試行)';
            }).catch(function () {
              _prefetchCache[cidPre] = { done: true, info: null, errored: true };
              var m = $('candMsg'); if (m) m.textContent = '⚠️ 作品情報の取得に失敗(追加ボタンで再試行)';
            });
          } else {
            _prefetchCache[cidPre] = { done: true, info: null, errored: true };
            var m = $('candMsg'); if (m) m.textContent = '⚠️ 作品情報の取得に失敗(追加ボタンで再試行)';
          }
        }).catch(function () {
          _prefetchCache[cidPre] = { done: true, info: null, errored: true };
          var m = $('candMsg'); if (m) m.textContent = '⚠️ 作品情報の取得に失敗(追加ボタンで再試行)';
        });
      }, 300);
    });
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
      (isMain
        ? '<button id="candEditBuiltin" type="button" class="ghost" title="タブ名を変更" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">✏️ 名前</button>'
        : '<button id="candEditTab" type="button" class="ghost" title="タブ名を変更・タブを削除" style="flex:0 0 auto;width:auto;margin:0;font-size:13px;padding:6px 11px;">✏️ 編集</button>') +
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
       '<div id="candPageMsg" class="hint" role="status" aria-live="polite"' + (_candAddNotice ? '' : ' hidden') + ' style="margin-top:7px;color:var(--accent);font-weight:700;">' + esc(_candAddNotice) + '</div>' +
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
    if (isMain) {
      wireBuiltinRename_('main'); // 組込タブ(手動追加)の改名。candEditForm へフォームを出す。
    } else {
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
    if (items.some(function (x) { return x.twitterUrl === tw.url || x.cid === tw.cid; })) {
      showCandAddNotice_(msg, 'ℹ️ 同じ投稿がすでに候補にあるため、1件にまとめたままです');
      if (onDone) onDone();
      return;
    }
    var isB = tw.kind === 'bsky';
    var title = isB ? (tw.user ? ('🦋 @' + tw.user + ' のポスト') : '🦋 Blueskyのポスト')
                    : (tw.user ? ('X @' + tw.user + ' のポスト') : 'X X(Twitter)のポスト');
    items.unshift({ url: tw.url, cid: tw.cid, twitterUrl: tw.url, isTwitter: true, title: title, addedAt: new Date().getTime() });
    lsSet(key, items);
    attachAddImgs_(tw.cid); // 追加モーダルの画像スロットも一緒に保存(動画生成用)
    if (inp) inp.value = ''; if (twInp) twInp.value = '';
    showCandAddNotice_(msg, isB ? '✅ Blueskyの投稿URLを候補に登録しました' : '✅ Twitter(X)のURLを候補に登録しました');
    renderCandList(tabId);
    if (onDone) onDone(); // 「追加して閉じる」＝追加完了後にモーダルを閉じる
  }
  function addCandidate(tabId, onDone) {
    tabId = tabId || 'main';
    var key = itemsKey(tabId);
    var inp = $('candUrl'), twInp = $('candTwitter'), msg = $('candMsg');
    // 候補の画像・メモはIndexedDBから非同期で展開される。重複作品への追記も既存内容との
    // マージなので、展開前の空メモリを正として上書きしないよう読込み完了後に開始する。
    if (_idbOk && !_candidateHydrated) {
      if (msg) msg.textContent = '⏳ 保存済みの候補データを確認中…';
      if (_candAddHydrationPending) return; // 連打で待機処理を増やさない
      _candAddHydrationPending = true;
      whenImagesReady_(function () {
        _candAddHydrationPending = false;
        if (!_candidateHydrated) {
          if (msg) msg.textContent = '⚠️ 保存済みデータの確認に時間がかかっています。少し待って、もう一度押してください';
          return; // 未展開のままマージすると既存画像・メモを失うため進めない
        }
        addCandidate(tabId, onDone);
      });
      return;
    }
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
        // ★作品URLの埋め戻し: 既存候補が作品URLを失っている(過去の同期union不具合/X起点追加でurl未設定)
        //   場合、正しいURLで再追加したら埋め戻す。従来は合流でtwitter/画像/メモしか触らず url は永久に
        //   空のまま=「候補に追加しても作品URLが消える(入らない)」の根(症状4)。
        if (url && !existItem.url) { existItem.url = url; mergedAny = true; }
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
          renderCandList(tabId);
          showDuplicateDialog_(newMemo, r.cid);
          if (onDone) onDone();
        } else {
          showDuplicateDialog_(newMemo, r.cid);
          if (onDone) onDone();
        }
        return;
      }
      if (msg) msg.textContent = '⏳ 作品情報を取得中…';
      var cfg = workerCfg();
      // errored=trueなら取得失敗(placeholder登録)。この場合は入力欄を消さない(Chami指定2026-07-24：
      // 「取得できなかった場合にURLを消して登録しない」のを避ける＝欄を残し、登録済みも分かるようにする)。
      var put = function (info, errored) {
        var items = lsGet(key, '[]');
        // 取得開始時に入れた「取得中」プレースホルダ(この追加が入れたもの)を探して、その場で中身を埋める。
        //   ★一覧から消さない=「追加して閉じる」で閉じた後、取得が長引いても「取得中です」が並び続ける(Chami 2026-08-05)。
        var idx = -1;
        for (var ri = 0; ri < items.length; ri++) { if (items[ri] && items[ri].cid === r.cid && items[ri]._fetching) { idx = ri; break; } }
        if (idx < 0) {
          // プレースホルダが無い(プリフェッチ即確定 or 取得中に別端末同期で本物が先に入った)。
          //   後者＝重複なので、作品URLを埋め戻して重複ダイアログ(従来動作)。
          var exist = null;
          for (var rj = 0; rj < items.length; rj++) { if (items[rj] && items[rj].cid === r.cid) { exist = items[rj]; break; } }
          if (exist) {
            if (url && !exist.url) { exist.url = url; lsSet(key, items); }
            var memoElRace = $('candMemo');
            showDuplicateDialog_(memoElRace && memoElRace.value, r.cid);
            if (onDone) onDone();
            return;
          }
        }
        var it;
        if (idx >= 0) { it = items[idx]; } // プレースホルダをその場更新(addedAt保持=並び順不変)
        else { it = { cid: r.cid, addedAt: new Date().getTime() }; items.unshift(it); }
        it.url = url;
        it.title = (info && info.title) || '(タイトル未取得)';
        it.author = (info && info.author) || '';
        it.thumb = (info && (info.thumb || info.thumbSmall)) || '';
        it.listPrice = info ? info.listPrice : null; it.price = info ? info.price : null;
        it.discountPct = info ? (info.discountPct || 0) : 0;
        it.date = (info && info.releaseDate) || '';
        it.genres = (info && info.genres) || [];
        it.floor = (info && info.floor) || ''; it.service = (info && info.service) || ''; // AI判定用
        it.reviewCount = info ? info.reviewCount : null;
        it.reviewAvg = info ? info.reviewAvg : null;
        if (info && info.samples && info.samples.length) it.samples = info.samples; // 詳細モーダル用
        if (twForWork.ok) it.twitterUrl = twForWork.url; // X / Bluesky の投稿URLも一緒に保存
        delete it._fetching; // 取得完了(または失敗確定)＝プレースホルダ状態を解除
        lsSet(key, items);
        attachAddImgs_(r.cid, errored); // errored=true → keepForm: URLとメモを消さず再試行を許す
        if (errored) {
          // URLは消さない(登録はできたが情報取得は失敗＝自動バックフィルで後から埋まる)。
          showCandAddNotice_(msg, '⚠️ 作品情報の取得に失敗しましたが、URLは登録済みです(自動で再取得します)');
        } else {
          inp.value = ''; if (twInp) twInp.value = ''; showCandAddNotice_(msg, '✅ 候補に登録しました');
        }
        renderCandList(tabId);
        if (onDone) onDone(); // 「追加して閉じる」＝追加完了後にモーダルを閉じる
      };
      // プリフェッチ済みキャッシュがあれば即確定(fetchをスキップして体感速度を上げる)
      if (_prefetchCache[r.cid] && _prefetchCache[r.cid].done) {
        var cached = _prefetchCache[r.cid]; delete _prefetchCache[r.cid];
        if (usableCandidatePrefetch_(cached)) {
          put(cached.info, false); return;
        }
      }
      // ★ここから非同期取得。取得を待たずに「取得中」プレースホルダを一覧の先頭へ入れておく=
      //   「追加して閉じる」で閉じた後、取得に時間がかかっても一覧から消えず「⏳ 取得中です…」を出し続ける
      //   (以前は put() が取得完了まで一覧へ入れず、遅いと一覧から消えてリロードで復活＝ヒヤッとする・Chami 2026-08-05)。
      (function () {
        var items = lsGet(key, '[]');
        for (var pi = 0; pi < items.length; pi++) { if (items[pi] && items[pi].cid === r.cid) return; } // 既にあれば二重に入れない
        var ph = { url: url, cid: r.cid, title: '(タイトル未取得)', addedAt: new Date().getTime(), _fetching: true };
        if (twForWork.ok) ph.twitterUrl = twForWork.url;
        items.unshift(ph);
        lsSet(key, items);
        renderCandList(tabId);
      })();
      // 一時的な失敗(タイムアウト/サーバー5xx等・retryable)は1回だけ即リトライしてから諦める。
      //   そもそも取得エラーになる頻度を減らす狙い(Chami指定2026-07-24)。
      var fetchOnce = function () { return window.FanzaCore.fetchFanzaInfo(r.cid, cfg.url, cfg.secret, url); };
      if (window.FanzaCore && cfg.url) {
        fetchOnce().then(function (info) {
          if (info && info.title) { put(info, false); return; }
          if (info && info.retryable) {
            return fetchOnce().then(function (info2) { put(info2 && info2.title ? info2 : null, !(info2 && info2.title)); });
          }
          put(null, true);
        }).catch(function () { put(null, true); });
      } else put(null, true);
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
      items.push({ url: w.url, cid: w.cid, title: w.title, author: w.makerName || w.author || '', thumb: w.thumb || '', listPrice: w.listPrice, price: w.price, discountPct: w.discountPct || 0, date: w.date || '', genres: w.genres || [], floor: w.floor || '', service: w.service || '', reviewCount: w.reviewCount, reviewAvg: w.reviewAvg, addedAt: new Date().getTime() });
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
    var targets = items.filter(isInfoTarget_);
    var cids = salesTargetCids_(items);
    var msgEl = $('candMsg');
    var cfg = workerCfg();
    var done = function () { lsSet(key, items); recordReviewSnapshots(items); if (msgEl) msgEl.textContent = ''; invalidateSales_(cids); renderCandList(tabId); };
    if (!window.FanzaCore || !cfg.url) { done(); return; }
    if (msgEl) msgEl.textContent = '⏳ 価格・情報を更新中…';
    if (!targets.length) { done(); return; }
    var pending = targets.length;
    targets.forEach(function (it) {
      window.FanzaCore.fetchFanzaInfo(it.cid, cfg.url, cfg.secret, it.url, { checkAi: true }).then(function (info) {
        if (info && info.title) {
          it.title = info.title; if (info.author) it.author = info.author;
          it.listPrice = info.listPrice; it.price = info.price; it.discountPct = info.discountPct || 0;
          if (info.releaseDate) it.date = info.releaseDate;
          if (info.genres && info.genres.length) it.genres = info.genres;
          if (info.floor) it.floor = info.floor; if (info.service) it.service = info.service; // AI判定用(floor名でしか分からない作品)
          if (info.ai) it.ai = true;
          if (info.ai || info.aiChecked) it.aiChecked = true; // 🔁でも検証済み(AI開示ヒット or 確定false)の時だけ確定。壁で未判定なら次回リトライ可のまま
          if (info.thumb || info.thumbSmall) it.thumb = info.thumb || info.thumbSmall;
          if (info.samples && info.samples.length) it.samples = info.samples;
          if (info.reviewCount != null) it.reviewCount = info.reviewCount;
          if (info.reviewAvg != null) it.reviewAvg = info.reviewAvg;
        }
        if (--pending === 0) done();
      }).catch(function () { if (--pending === 0) done(); });
    });
  }
  function normalizeWorkSearch_(value) {
    var text = String(value || '');
    try { text = text.normalize('NFKC'); } catch (e) {}
    return text.toLowerCase();
  }
  function workSearchText_(it) {
    return normalizeWorkSearch_([
      it && it.title,
      it && (it.author || it.makerName),
      it && it.cid
    ].filter(Boolean).join(' '));
  }
  // メモ/コメント検索の照合テキスト(実データ由来)。cand_text(同期LSの正本)から読むので
  //   ページ分けで画面に出ていない作品も横断して検索できる=全ページ検索。DOMに依存しない。
  function candMemoText_(it) {
    if (!it || !it.cid) return '';
    var r = refImgOf(it.cid) || {};
    return normalizeWorkSearch_(((r.comment || '') + ' ' + (r.memo || '')).trim());
  }
  function workSearchHtml_(tabId) {
    return '<div class="cand-work-search" style="padding:2px 6px 10px;">' +
      '<label for="candWorkSearch" class="hint" style="display:block;margin-bottom:4px;">作品検索(部分一致)</label>' +
      '<div style="display:flex;gap:6px;align-items:center;">' +
      '<input id="candWorkSearch" size="1" type="search" value="' + esc(_workSearchByTab[tabId] || '') + '" placeholder="作品名・サークル名・作品ID" aria-label="作品検索(部分一致)" autocomplete="off" style="flex:1 1 auto;min-width:0;height:31.5px;box-sizing:border-box;margin:0;font-size:16px;">' +
      '<button id="candWorkSearchClear" type="button" class="ghost" style="flex:0 0 auto;width:auto;margin:0;padding:7px 10px;">クリア</button>' +
      '</div>' +
      // メモ/コメント検索(部分一致)=作品検索の下に同形で並べる(Chami依頼2026-08-11)。両欄はAND(両方に一致した作品だけ表示)。
      '<label for="candMemoSearch" class="hint" style="display:block;margin:8px 0 4px;">メモ/コメント検索(部分一致)</label>' +
      '<div style="display:flex;gap:6px;align-items:center;">' +
      '<input id="candMemoSearch" size="1" type="search" value="' + esc(_memoSearchByTab[tabId] || '') + '" placeholder="メモ・コメントの中身" aria-label="メモ/コメント検索(部分一致)" autocomplete="off" style="flex:1 1 auto;min-width:0;height:31.5px;box-sizing:border-box;margin:0;font-size:16px;">' +
      '<button id="candMemoSearchClear" type="button" class="ghost" style="flex:0 0 auto;width:auto;margin:0;padding:7px 10px;">クリア</button>' +
      '</div><div id="candWorkSearchResult" class="hint" aria-live="polite" style="min-height:1.4em;margin-top:3px;"></div></div>';
  }
  function wireWorkSearch_(root, tabId) {
    var input = root && root.querySelector('#candWorkSearch');
    if (!input) return;
    var memoInput = root.querySelector('#candMemoSearch');
    var clear = root.querySelector('#candWorkSearchClear');
    var memoClear = root.querySelector('#candMemoSearchClear');
    var result = root.querySelector('#candWorkSearchResult');
    var apply = function () {
      var query = normalizeWorkSearch_(input.value);
      var mQuery = normalizeWorkSearch_(memoInput ? memoInput.value : '');
      _workSearchByTab[tabId] = input.value || '';
      _memoSearchByTab[tabId] = memoInput ? (memoInput.value || '') : '';
      var shown = 0, total = 0;
      root.querySelectorAll('.cand-card[data-work-search]').forEach(function (card) {
        total++;
        var okWork = !query || (card.getAttribute('data-work-search') || '').indexOf(query) >= 0;
        // メモ/コメントは遅延読み込み(IDB/backfill)で描画されるため、初回bake時の data-memo-search が
        //   空のまま残ることがある(→検索が一切ヒットしない・Chami 2026-08-15)。表示中の実テキストを
        //   正本にして「見えているメモは必ず検索できる」に直す。span無し(メモ無し)なら属性へフォールバック。
        var okMemo = true;
        if (mQuery) {
          var live = '';
          card.querySelectorAll('.cand-manage-comment, .cand-manage-memo').forEach(function (s) { live += ' ' + (s.textContent || ''); });
          var memoText = live.trim() ? normalizeWorkSearch_(live) : (card.getAttribute('data-memo-search') || '');
          okMemo = memoText.indexOf(mQuery) >= 0;
        }
        var matches = okWork && okMemo;
        card.style.display = matches ? '' : 'none';
        if (matches) shown++;
      });
      if (result) result.textContent = (query || mQuery) ? shown + '件表示 / ' + total + '件中' : '';
    };
    input.addEventListener('input', apply);
    if (memoInput) memoInput.addEventListener('input', apply);
    if (clear) clear.addEventListener('click', function () {
      input.value = '';
      apply();
      // ★preventScroll: クリアを押しただけで画面が動かないようにする(Chami指定2026-07-26)。
      //   font-size:16px と併せて、iOSのフォーカス時オートズームも起きない。
      try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); }
    });
    if (memoClear) memoClear.addEventListener('click', function () {
      if (memoInput) memoInput.value = '';
      apply();
      try { if (memoInput) memoInput.focus({ preventScroll: true }); } catch (e) { if (memoInput) memoInput.focus(); }
    });
    apply();
  }
  // 文字列の軽量ハッシュ(djb2)。カードの「署名」=描画に効く全内容から作り、前回と同じならDOMを作り直さない。
  function hashStr_(s) {
    var h = 5381; s = String(s);
    for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return h.toString(36);
  }
  // 現在タブの軽量再描画(外枠は壊さずカード群だけを差分更新)への参照。★非同期の取得完了・自動追跡から
  //   これを呼べば、変化の無いカード(=画像)を作り直さない=チラつかない(Chami依頼2026-08-15
  //   「画像とサムネのチラつきが激しすぎる」の恒久対策)。C-038。
  var _candRepaint_ = null, _candRepaintTab_ = null;
  function repaintCand_(tabId) {
    if (_candRepaint_ && _candRepaintTab_ === tabId && document.getElementById('candCardList')) _candRepaint_();
    else renderCandList(tabId);
  }
  function renderCandList(tabId) {
    tabId = tabId || 'main';
    invalidatePostedIndex_(); // 投稿済み判定の索引を作り直す(前回描画以降の新規投稿を確実に反映)
    fetchPostedAuthority_(); // 投稿済み判定の権威索引(GASシート)を裏で更新(10分TTL・失敗時はローカル判定へフォールバック)
    var key = itemsKey(tabId);
    var el = $('candList');
    var all = lsGet(key, '[]');
    if (!all.length) { el.innerHTML = '<p class="hint" style="padding:4px 6px;">まだ候補がありません。上の欄に作品URLを入れて追加してください。</p>'; return; }
    var hidden = lsGet(hiddenKey(tabId), '[]'), hset = {}; hidden.forEach(function (c) { hset[c] = true; });
    var filt_ = function (it) {
      if (!(_showHidden ? hset[it.cid] : !hset[it.cid])) return false;
      if (_filterSale && !isOnSale_(it)) return false;
      if (!passPrice_(it)) return false;
      if (!_showHidden && isHiddenByPosted_(it)) return false; // アカウント別「投稿済みを非表示」
      return true;
    };
    var arr = sortItems(all, _sort).filter(filt_);
    _cardIndex = {}; arr.forEach(function (it) { _cardIndex[it.cid] = it; });
    if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">' + (_showHidden ? '非表示にした作品はありません。' : '表示できる候補がありません。') + '</p>'; el._go5CandState = null; return; }
    var actOf_ = function (cid) {
      return _showHidden
        ? '<button type="button" class="cand-hide-btn" data-unhide="' + esc(cid) + '">👁 再表示</button> <button type="button" class="cand-hide-btn cand-del-btn" data-delcid="' + esc(cid) + '" title="削除" aria-label="削除">🗑️</button>'
        : '<button type="button" class="cand-hide-btn" data-hidecid="' + esc(cid) + '">非表示</button> <button type="button" class="cand-hide-btn cand-del-btn" data-delcid="' + esc(cid) + '" title="削除" aria-label="削除">🗑️</button>';
    };
    // 1枚のカードだけを配線する(＝差分更新で「新しく作った」カードにのみ呼ぶ=二重配線しない)。
    //   サムネ/生成画像のタップは pageCand への委任(ensureCardDelegation_)で拾うため、ここでは扱わない。
    var wireOneCard_ = function (node) {
      wireCardCommon_(node); // 🔁作品情報ボタン・チャンネル切替行・コメント/メモの1行フィット
      node.querySelectorAll('[data-hidecid]').forEach(function (b) {
        b.addEventListener('click', function () { if (!window.confirm('非表示にしますか？')) return; var h = lsGet(hiddenKey(tabId), '[]'), c = b.getAttribute('data-hidecid'); if (h.indexOf(c) < 0) h.push(c); lsSet(hiddenKey(tabId), h); el._go5CandState = null; renderCandList(tabId); });
      });
      node.querySelectorAll('[data-unhide]').forEach(function (b) {
        b.addEventListener('click', function () { var c = b.getAttribute('data-unhide'); lsSet(hiddenKey(tabId), lsGet(hiddenKey(tabId), '[]').filter(function (x) { return x !== c; })); el._go5CandState = null; renderCandList(tabId); });
      });
      node.querySelectorAll('[data-delcid]').forEach(function (b) {
        b.addEventListener('click', function () {
          var c = b.getAttribute('data-delcid'), items2 = lsGet(key, '[]');
          var it = items2.filter(function (x) { return x.cid === c; })[0];
          if (!it || !window.confirm('「' + (it.title || c) + '」をこのタブから削除しますか？')) return;
          lsSet(key, items2.filter(function (x) { return x.cid !== c; }));
          tombstoneCid_(tabId, c); // ★削除を墓標に記録＝同期で他端末にも伝播し復活を防ぐ(INC 2026-07-15)
          el._go5CandState = null; renderCandList(tabId);
        });
      });
    };
    // ★カード群を cid＋署名で差分更新する=前回と同じ内容のカードは既存DOMを使い回し、画像/サムネの
    //   <img> を作り直さない(=再デコードによるチラつきが起きない)。変化したカードだけ作り直す。
    var reconcile_ = function (listEl, slice) {
      var byCid = {};
      Array.prototype.forEach.call(listEl.children, function (n) { var c = n.getAttribute && n.getAttribute('data-cid'); if (c) byCid[c] = n; });
      var used = {}, fresh = [];
      slice.forEach(function (it, idx) {
        var html = candCard(it, actOf_(it.cid)), sig = hashStr_(html), cur = byCid[it.cid], node;
        if (cur && cur.getAttribute('data-sig') === sig) { node = cur; } // 内容不変=そのまま使い回す(画像は再デコードされない)
        else {
          var tmp = document.createElement('div'); tmp.innerHTML = html; node = tmp.firstElementChild;
          node.setAttribute('data-cid', it.cid); node.setAttribute('data-sig', sig); fresh.push(node);
        }
        used[it.cid] = true;
        if (listEl.children[idx] !== node) listEl.insertBefore(node, listEl.children[idx] || null);
      });
      Array.prototype.slice.call(listEl.children).forEach(function (n) { var c = n.getAttribute && n.getAttribute('data-cid'); if (!c || !used[c]) listEl.removeChild(n); });
      fresh.forEach(wireOneCard_); // 新規カードだけ配線(DOM挿入後=レイアウト確定後なので1行フィット計測も効く)
    };
    // 現在ページ(＋検索・ページ数)ぶんだけを描く。検索はDOM非表示でなく実データで絞り込む=全ページ横断。
    var paintPage_ = function () {
      var wrap = document.getElementById('candPageWrap'); if (!wrap) return;
      if (!document.getElementById('candCardList')) wrap.innerHTML = '<div id="candPageHead"></div><div id="candCardList"></div><div id="candPageFoot"></div>';
      var headEl = document.getElementById('candPageHead'), listEl = document.getElementById('candCardList'), footEl = document.getElementById('candPageFoot');
      // ★非同期取得(タイトル/販売数/AI判定)が後から届いても最新で描くため、都度LSを読み直して絞り込む。
      var fresh2 = lsGet(key, '[]'), hs2 = {}; lsGet(hiddenKey(tabId), '[]').forEach(function (c) { hs2[c] = true; });
      var arr2 = sortItems(fresh2, _sort).filter(function (it) {
        if (!(_showHidden ? hs2[it.cid] : !hs2[it.cid])) return false;
        if (_filterSale && !isOnSale_(it)) return false;
        if (!passPrice_(it)) return false;
        if (!_showHidden && isHiddenByPosted_(it)) return false;
        return true;
      });
      _cardIndex = {}; arr2.forEach(function (it) { _cardIndex[it.cid] = it; });
      var qi = document.getElementById('candWorkSearch'), mi = document.getElementById('candMemoSearch');
      var q = normalizeWorkSearch_(qi ? qi.value : ''), mq = normalizeWorkSearch_(mi ? mi.value : '');
      var view = arr2.filter(function (it) {
        var okW = !q || workSearchText_(it).indexOf(q) >= 0;
        var okM = !mq || candMemoText_(it).indexOf(mq) >= 0;
        return okW && okM;
      });
      var size = candPageSize_();
      var pages = Math.max(1, Math.ceil(view.length / size));
      var page = _candPageByTab[tabId] || 1; if (page > pages) page = pages; if (page < 1) page = 1;
      _candPageByTab[tabId] = page;
      var startI = (page - 1) * size, slice = view.slice(startI, startI + size);
      var pager = candPagerHtml_(page, pages, view.length, startI, slice.length);
      var resultLine = (q || mq) ? '<div class="hint" style="padding:2px 6px;">' + view.length + '件が条件に一致</div>' : '';
      headEl.innerHTML = resultLine + pager;      // ページャは画像を含まない=作り直しても軽い/チラつかない
      footEl.innerHTML = (pages > 1 ? pager : '');
      if (!slice.length) listEl.innerHTML = '<p class="hint" style="padding:8px;">条件に一致する候補がありません。</p>';
      else reconcile_(listEl, slice);             // カードは差分更新(使い回し)=チラつかない
      var resEl = document.getElementById('candWorkSearchResult');
      if (resEl) resEl.textContent = (q || mq) ? view.length + '件表示 / ' + arr2.length + '件中' : '';
      [headEl, footEl].forEach(function (z) {
        z.querySelectorAll('[data-candpage]').forEach(function (b) {
          b.addEventListener('click', function () {
            var p = parseInt(b.getAttribute('data-candpage'), 10); if (!p || p < 1 || p > pages) return;
            _candPageByTab[tabId] = p; paintPage_();
            try { var sb = document.getElementById('candWorkSearch'); if (sb) sb.scrollIntoView({ block: 'start' }); } catch (e) {}
          });
        });
      });
    };
    _candRepaint_ = paintPage_; _candRepaintTab_ = tabId;
    // ★外枠(件数見出し・検索欄・表示数セレクタ・ページ入れ物)は、並び順/絞り込み/表示数が変わらない限り
    //   作り直さない=検索フォーカスもカードのDOMも保つ。並び順や非表示切替など見出しが変わる操作の時だけ組み直す。
    var stateSig = tabId + '|' + _sort + '|' + (_showHidden ? 1 : 0) + '|' + (_filterSale ? 1 : 0) + '|' + _priceMax;
    var shellReady = (el._go5CandState === stateSig && document.getElementById('candCardList'));
    if (!shellReady) {
      var salesMiss = missingCount(salesTargetCids_(arr));
      var head = '<p class="hint" style="padding:2px 6px;">' + (_showHidden ? '🙈 非表示中 ' : '') + arr.length + '件' + (_showHidden ? '(「再表示」で戻せます)' : ' / 非表示 ' + hidden.length + '件') +
        (!_showHidden && salesMiss > 0 ? '<br>💰 販売数(実売)は' + salesMiss + '件がPC取得待ち。「▶今すぐ取得」を押すか、自動取得を待って🔁で反映されます。(PCの電源が必要)' : '') + '</p>';
      el.innerHTML = head + workSearchHtml_(tabId) + candPageSizeHtml_() + '<div id="candPageWrap"></div>';
      el._go5CandState = stateSig;
      // 検索欄の配線(このタブはページ分けのため実データで絞り込む=wireWorkSearch_ のDOM非表示は使わない)。
      var searchInput = el.querySelector('#candWorkSearch'), memoInput = el.querySelector('#candMemoSearch');
      var onSearch_ = function () {
        _workSearchByTab[tabId] = searchInput ? (searchInput.value || '') : '';
        _memoSearchByTab[tabId] = memoInput ? (memoInput.value || '') : '';
        _candPageByTab[tabId] = 1; // 条件が変わったら1ページ目へ
        paintPage_();
      };
      if (searchInput) searchInput.addEventListener('input', onSearch_);
      if (memoInput) memoInput.addEventListener('input', onSearch_);
      var swClear = el.querySelector('#candWorkSearchClear'), smClear = el.querySelector('#candMemoSearchClear');
      if (swClear) swClear.addEventListener('click', function () { if (searchInput) searchInput.value = ''; onSearch_(); try { if (searchInput) searchInput.focus({ preventScroll: true }); } catch (e) { if (searchInput) searchInput.focus(); } });
      if (smClear) smClear.addEventListener('click', function () { if (memoInput) memoInput.value = ''; onSearch_(); try { if (memoInput) memoInput.focus({ preventScroll: true }); } catch (e) { if (memoInput) memoInput.focus(); } });
      var sizeSel = el.querySelector('#candPageSizeSel');
      if (sizeSel) sizeSel.addEventListener('change', function () { var n = parseInt(this.value, 10) || PAGESIZE_DEF; lsSet(K_PAGESIZE, n); _candPageByTab[tabId] = 1; paintPage_(); });
    }
    paintPage_();
    var salesCids = salesTargetCids_(arr);
    // 以下の非同期取得は、届いたら repaintCand_ で「カードの差分更新だけ」する=外枠も不変カードも壊さない=チラつかない。
    fetchSalesFor(salesCids, function (changed) { if (changed && _activeTab === tabId) repaintCand_(tabId); });
    backfillMissingInfo_(key, arr, function (changed) { if (changed && _activeTab === tabId) repaintCand_(tabId); });
    aiRecheck_(key, arr, function (changed) { if (changed && _activeTab === tabId) repaintCand_(tabId); });
    // 追加直後の未取得は、タブを開いている間だけ自動で追いかける(scheduleInfoTick_→renderCandListだが
    //   外枠は使い回されカードは差分更新のためチラつかない。backfillの再実行もこの経路で継続する)。
    scheduleInfoTick_(tabId, arr);
  }

  // ── サークルタブ ──
  function renderMaker(tabId, force) {
    invalidatePostedIndex_(); // 投稿済み判定の索引を作り直す(前回描画以降の新規投稿を確実に反映)
    fetchPostedAuthority_(); // 投稿済み判定の権威索引(GASシート)を裏で更新(10分TTL・失敗時はローカル判定へフォールバック)
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
        if (!_showHidden && isHiddenByPosted_(it)) return false; // アカウント別「投稿済みを非表示」
        return true;
      });
      if (!arr.length) { el.innerHTML = '<p class="hint" style="padding:8px;">' + (_showHidden ? '非表示にした作品はありません。' : '表示できる作品がありません。') + '</p>'; return; }
      _cardIndex = {}; arr.forEach(function (it) { _cardIndex[it.cid] = it; });
      // 実売本数(販売数)を対象作品ぶん取得。(未取得はPC取得キューへ自動登録)反映されたら再描画。
      var salesCids = salesTargetCids_(arr);
      var salesMiss = missingCount(salesCids);
      var head = throttleNote + '<div style="display:flex;justify-content:flex-end;padding:2px 6px 6px;">' +
        '<button id="candBulkToCand" type="button" class="ghost" style="width:auto;margin:0;font-size:12.5px;padding:6px 10px;">💡 全作品を候補に追加</button></div>' +
        '<p class="hint" style="padding:2px 6px;">' + (_showHidden ? '🙈 非表示中の作品 ' : '') + arr.length + '件' + (makerIds.length > 1 ? '(' + makerIds.length + 'サークル)' : '') + (_showHidden ? '(「再表示」で戻せます)' : ' / 非表示 ' + hidden.length + '件・不足なら🔁リロード') +
        (!_showHidden && salesMiss > 0 ? '<br>💰 販売数(実売)は' + salesMiss + '件がPC取得待ち。「▶今すぐ取得」を押すか、自動取得を待って🔁で反映されます。(PCの電源が必要)' : '') + '</p>';
      el.innerHTML = head + workSearchHtml_(tabId) + arr.map(function (it) {
        var btn = _showHidden
          ? '<button type="button" class="cand-hide-btn" data-unhide="' + esc(it.cid) + '">👁 再表示</button>'
          : '<button type="button" class="cand-hide-btn" data-hide="' + esc(it.cid) + '">非表示</button>';
        return candCard(it, btn);
      }).join('');
      wireWorkSearch_(el, tabId);
      wireCardCommon_(el);
      var bulkBtn = $('candBulkToCand');
      if (bulkBtn) bulkBtn.addEventListener('click', function () { addWorksToMain_(items, bulkBtn, tab.name); });
      if (!_showHidden && !force) fetchSalesFor(salesCids, function (changed) { if (changed && _activeTab === tabId) renderMaker(tabId); });
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
        pasteRow_('<input id="candEditSrc" size="1" type="text" inputmode="url" autocomplete="off" placeholder="追加したいサークルを入れて「＋ 追加」" style="flex:1;min-width:0;">', 'candEditSrc') +
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

  // このcidの動画生成用画像スロットの状態を1箇所で判定する(candCard/updateCardRefThumb_で式が割れないよう集約)。
  //   'images'=保存画像あり / 'loading'=一括展開がまだ(⏳) / 'checking'=展開済みだがこのcidだけ未確認(🔍・端末内を能動確認) /
  //   'missing'=この端末で確認済みだが0枚(⚠) / 'none'=痕跡も無い(空欄)。
  //   ★⚠(missing)は per-cid の陽性確認(_refLoaded[cid]===true か _imgMem.ref に実体)でのみ出す。一括展開の完了フラグ
  //     (_candidateHydrated)だけで「無い」と断定しない=同期/別タブで後から届く画像を「消えた」と誤表示しない
  //     (C-041=一度の観測を状態の代理にするな。Chami 2026-08-15「画像あるはずなのよ、消えてるってこと」)。
  function refSlotState_(cid) {
    var has = refImgsOf_(cid).length > 0;
    // R2マーカー(base64を持たず実体はR2)なら「画像あり・取り寄せ中」=⏳ loading にし、⚠(消えた)と誤表示しない。
    if (!has && !Object.prototype.hasOwnProperty.call(_imgMem.ref, cid)) {
      var lg = legacyRefOf_(cid);
      if (isR2Marker_(lg)) { resolveR2IntoMem_(cid, lg); return 'loading'; }
    }
    var rr = refImgOf(cid);
    var worked = !!(rr && (rr.comment || rr.memo));
    var inMem = Object.prototype.hasOwnProperty.call(_imgMem.ref, cid);
    return refSlotDecide_(has, worked, _idbOk, _refLoaded[cid] === true, inMem, _candidateHydrated);
  }
  // 展開済みだがこのcidだけ未確認の作品を、端末内(IDB/旧LS)から能動的に取り寄せて確定する。
  //   成功したら(画像が在れば表示・端末内に無ければ「確認済み0枚=⚠」へ)そのカードだけ差分更新=全再描画しない。
  //   読取失敗(IDB接続死等)は「無い」と断定せず確認中のまま裏の再試行(reHydrateFromSync_)へ委ねる。
  //   ★ok===false時は再描画しない=render→probe→render の環が閉じ、無限ループを作らない。多重発射は
  //     _refLoadJobs(ensureRefLoaded_が冪等)＋_refLoaded で二重ガード。
  function ensureRefProbe_(cid) {
    if (!_idbOk || _refLoaded[cid] || Object.prototype.hasOwnProperty.call(_imgMem.ref, cid) || _refLoadJobs[cid]) return;
    ensureRefLoaded_(cid).then(function (ok) {
      if (!ok) return;
      try {
        var page = document.getElementById('pageCand');
        var btn = page && liveRefButton_(page, cid);
        var card = btn && (btn.closest ? btn.closest('.cand-card') : null);
        if (card) updateCardRefThumb_(card, cid);
      } catch (e) {}
    });
  }
  // 動画生成用画像スロットのHTML。★表示は先頭1枚だけ・全幅で大きく出す(2列グリッドの全枚表示は見にくい=元の見せ方へ戻す・
  //   Chami 2026-08-15「画像表示の方法は見にくいので元に戻して」)。全枚数はサムネをタップ→ズームで左右送りして見られる
  //   (openImgZoom_ が data-refidx から開き全枚を順に表示)。複数ある時は枠をアンバー(.multi)で明示する。
  //   0枚の時は空欄にせず状態札で「まだ読込前(⏳)」「端末内を確認中(🔍)」「確認済みで画像なし(⚠)」を区別する
  //   =Chami「消えてるのか表示されてないのか分からん」への対策(こちらは維持)。
  function refSlotHtml_(cid) {
    var imgs = refImgsOf_(cid);
    if (imgs.length) {
      var multi = imgs.length > 1;
      var cap = multi ? ('動画生成用の画像(全' + imgs.length + '枚・タップで拡大)') : '動画生成用の画像(タップで拡大)';
      return '<img class="cand-refimg-thumb' + (multi ? ' multi' : '') + '" data-refimgview="' + esc(cid) + '" data-refidx="0" src="' + esc(imgs[0]) + '" loading="lazy" alt="' + esc(cap) + '" title="' + esc(cap) + '">';
    }
    var state = refSlotState_(cid);
    if (state === 'loading') return '<div class="cand-refimg-ph cand-refimg-loading" title="動画生成用の画像を読み込み中です">⏳ 画像読込中…</div>';
    if (state === 'checking') { ensureRefProbe_(cid); return '<div class="cand-refimg-ph cand-refimg-checking" title="この作品の動画生成用画像を端末内から確認しています">🔍 画像を確認中…</div>'; }
    if (state === 'missing') return '<div class="cand-refimg-ph cand-refimg-missing" data-refimg="' + esc(cid) + '" title="この端末に動画生成用の画像が見つかりません(タップで投稿編集から確認・再登録)">⚠ 画像なし</div>';
    return '';
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
    var badgesHtml = (ws ? stateBadgeHtml_(ws) : '') + ((!it.isTwitter && it.url) ? workKindBadgeHtml_(it.url) : '') + (isAiWork_(it.genres, it.floor, it.ai) ? '<span class="fp-kind fp-kind-ai">AI</span>' : '');
    var genresHtml = (it.genres && it.genres.length)
      ? '<div class="fz-genres" style="margin-top:4px;">' + it.genres.slice(0, 5).map(function (g) { return '<span class="fz-genre">' + esc(g) + '</span>'; }).join('') + '</div>'
      : '';
    // 売れ行きの数値。販売数(実売)とレビュー件数を「並べて」常に表示する(Chami指定2026-07-14)。
    //   従来はどちらか一方だけ=追加方法で表示が割れていた。以後は両方を1行に「・」で連結する。
    var rc = it.reviewCount;
    var avg = (it.reviewAvg != null && it.reviewAvg !== '') ? (' ★' + it.reviewAvg) : '';
    var num = function (n) { return Number(n).toLocaleString('ja-JP'); };
    var sales = isSalesTarget_(it) ? salesOf(it.cid) : 'unavailable';
    // ① 販売数パート。どの作品でも必ず表示し、取得対象外・取得不可も区別する。
    var salesPart = '';
    if (!isInfoTarget_(it) || !isSalesTarget_(it)) {
      salesPart = '販売数 対象外';
    } else if (typeof sales === 'number') {
      salesPart = '販売数 ' + num(sales) + '本';
      // rank7d でも「+0本」は出さない=週次の伸びが正の時だけ🔥を前置(全部0に見える誤解を解消)。
      if (_sort === 'rank7d') {
        var sd = weekSalesDelta(it.cid, sales);
        if (sd != null && sd > 0) salesPart = '販売数 🔥 直近1週間 +' + num(sd) + '本 (累計 ' + num(sales) + '本)';
      }
    } else if (sales === 'unavailable') {
      salesPart = '販売数 取得不可';
    } else {
      salesPart = '販売数 取得待ち'; // PC(日本IP)のバッチ取得待ち
    }
    // ② レビューパート。販売数の直後に必ず併記し、取れない作品も欄自体は消さない。
    var reviewPart = !isInfoTarget_(it) ? 'レビュー 対象外'
      : ((rc != null) ? ('レビュー ' + num(rc) + '件' + avg) : 'レビュー 取得不可');
    var salesHtml = '<div class="cand-sales">' + salesPart + ' ・ ' + reviewPart + '</div>';
    var hasRef = refImgHas(it.cid);
    var _refRec = refImgOf(it.cid) || {};
    var refCmt = _refRec.comment || ''; // 保存済みコメント(動画生成用画像の真下に全文表示)
    var refMemo = _refRec.memo || '';   // メモ(コメントが無い時にカードへ水色で代替表示)
    // 動画生成用の画像=作品サムネの真下(左の画像列)に★全枚数を並べる(旧「先頭1枚のみ」を廃止・Chami 2026-08-15)。
    //   0枚時の札(⏳読込中/🔍確認中/⚠画像なし)は refSlotHtml_→refSlotState_ が per-cid で判定する
    //   =一括展開の完了だけで「消えた」と断定しない(Chami 2026-08-15「画像あるはずなのよ」)。
    var refImgHtml = '<div class="cand-refimgs" data-refslot="' + esc(it.cid) + '">' + refSlotHtml_(it.cid) + '</div>';
    // メモ(コメントの上・水色)とコメント(🙈/🗑と同じ管理行の左)は下の return 内で直接組み立てる。
    // 投稿済み作品はカード大枠をチャンネルのイメージカラーで太線囲み。両channel投稿は月詠み(外)＋宵桜(内)の二重。
    var _pAcc1 = !!postedMatchForCand_(it, 'acc1'), _pAcc2 = !!postedMatchForCand_(it, 'acc2');
    var _postCls = (_pAcc1 && _pAcc2) ? ' cand-posted-both' : (_pAcc1 ? ' cand-posted-acc1' : (_pAcc2 ? ' cand-posted-acc2' : ''));
    var _noComment = !refCmt && !refMemo; // コメント/メモ無し＝非表示/🗑を作品リンク行に統合し余白を縮小
    if (_noComment) _postCls += ' cand-nocomment';
    // 作品リンク群。(作品↗ / X↗ / X2↗ / 投稿編集 / 🦋)無コメント時は全幅行で非表示/🗑と同列に置くため変数化。
    var _actionsInner =
      ((!it.isTwitter && it.url) ? '<a class="vlink vlink-work" href="' + esc(it.url) + '" target="_blank" rel="noopener">作品↗</a>' : '') +
      ((_refRec.twitterUrl || it.twitterUrl) ? candUrlLink_(_refRec.twitterUrl || it.twitterUrl) : '') +
      refUrls2_(_refRec).map(function (su, i) { return candUrlLink_(su, i + 2); }).join('') +
      '<button type="button" class="cand-refimg-btn' + (hasRef ? ' has-img' : '') + '" data-refimg="' + esc(it.cid) + '">投稿編集</button>' +
      // 🦋(Bluesky添付画像)ボタンは全く使っていないため撤去(Chami依頼2026-07-29)。跡地へ「作品情報リロード」を配置。
      //   FANZA作品のみ対象(X/Bluesky候補にはFANZA情報が無い)。押すと単発でworkerから取り直し=サムネ未表示等を埋める。
      (isInfoTarget_(it) ? '<button type="button" class="cand-reload-btn" data-reloadinfo="' + esc(it.cid) + '" title="作品情報(サムネ・タイトル・価格等)を取得し直す">🔁作品情報</button>' : '');
    return '<div class="cand-card' + _postCls + '" data-work-search="' + esc(workSearchText_(it)) + '" data-memo-search="' + esc(normalizeWorkSearch_((refCmt || '') + ' ' + (refMemo || ''))) + '">' +
      '<div class="cand-thumbcol">' +
        (it.thumb ? '<img class="cand-thumb cand-thumb-click" data-thumbcid="' + esc(it.cid) + '" src="' + esc(it.thumb) + '" loading="lazy" alt="タップで画像を表示">' : '<div class="cand-thumb cand-thumb-ph"></div>') +
        refImgHtml +
      '</div>' +
      '<div class="cand-info">' +
        // 新作/同人バッジと同じ行にチャンネル表記を並べる(バッジ＝左／チャンネル＝右寄せ。投稿済み＝pillボタン／未投稿＝淡色表記)
        //   投稿済みなら Books 等と pill の間に「投稿日 ✔」をチャンネルテーマ色で表示。
        '<div class="cand-badges-row">' + badgesHtml + '<span class="cand-acct-group">' + postedDatesHtml_(it) + acctBadgesHtml_(it) + '</span></div>' +
        // ★タイトルがまだ来ていない(未取得/プレースホルダ)FANZA作品は「取得中です」を出す=
        //   追加直後に閉じても裏で追い続けている事を見せる(諦めない・Chami 2026-08-04)。
        '<div class="cand-title">' + ((isInfoTarget_(it) && (!it.title || it.title === '(タイトル未取得)'))
          ? '<span class="cand-title-fetching">⏳ 取得中です…</span>'
          : esc(it.title || '(無題)')) + '</div>' +
        (sub.length ? '<div class="cand-sub">' + sub.join('　') + '</div>' : '') +
        genresHtml +
        ((it.price != null || it.listPrice != null) ? '<div class="cand-price">' + priceHtml + '</div>' : '') +
        salesHtml +
        // 作品リンク行。(cand-info内＝画像の右の定位置)コメント/メモ無し時は同じ行の右端に 非表示/🗑 を統合。
        '<div class="cand-actions">' + _actionsInner + (_noComment ? '<span class="cand-actions-mspacer"></span>' + actionHtml : '') + '</div>' +
      '</div>' +
      // ★コメント・メモ両方ある時は、メモをコメントの上の行に独立表示する(Chami指定2026-07-24)。
      ((refCmt && refMemo) ? '<div class="cand-comment-row cand-memo-above"><span class="cand-manage-memo">' + esc(refMemo) + '</span></div>' : '') +
      // コメント(黒字)がある時＝黒字コメントと同じ行の右端へ 非表示/🗑 を統合し、間の余白を省く(Chami依頼2026-08-13)。
      //   旧: コメント行の下にボタン専用行をもう1本置いていたため、黒字とボタンの間に空白の帯ができていた。
      (refCmt ? '<div class="cand-comment-row cand-manage-row"><span class="cand-manage-comment">' + esc(refCmt) + '</span>' + actionHtml + '</div>' : '') +
      // コメント無し・メモのみ＝メモ(左)＋非表示/🗑(右)を同じ行に統合＝余白節約。コメント/メモ両無し時は作品リンク行に統合済み。
      ((!refCmt && refMemo) ? '<div class="cand-manage-row"><span class="cand-manage-memo">' + esc(refMemo) + '</span>' + actionHtml + '</div>' : '') +
      '</div>';
  }

  // 動画完成時、実際に前景として使った1枚だけを動画IDへ保存する。
  // 候補タブの全画像(ref)は一切コピーしないため、投稿履歴へ未採用画像が混ざらない。
  document.addEventListener('video-created', function (e) {
    var d = (e && e.detail) || {};
    if (!d.videoId || !d.sourceImageFile || d.test) return;
    fileToScaledDataUrl(d.sourceImageFile, function (durl, err) {
      if (!err && durl) usedImgSave_(d.videoId, [durl]);
    });
  });

  // ランキングタブ(yt-clicks.js)から「動画生成用に保存した画像」を参照するための公開API。
  try { window.Go5Cand = {
    render: render,
    notePosted: function (cid, account) { setPostedOff_(cid, account, false); invalidatePostedIndex_(); fetchPostedAuthority_(); }, // 本投稿で手動オフ宣言を解除(pill復帰)＋権威索引を更新

    refImgs: refImgsOf_,                                        // cid → 動画生成用の保存画像の配列(無ければ[])
    bskyImg: function (cid) { var r = bskyImgOf(cid); return (r && r.img) || ''; }, // cid → Bluesky添付画像(無ければ'')
    zoomImages: function (images, idx, opts) { openImgZoom_((images || []).filter(Boolean), idx || 0, opts); }, // 任意の画像配列をズーム。(スワイプ)opts.captions=ページ別見出し
    zoomRefImgs: function (cid) { var a = refImgsOf_(cid); if (a.length) openImgZoom_(a, 0, { onReorder: function (i) { return reorderRefImgToFirst_(cid, i); }, onPasteAdd: function (done) { pasteAddRefImgToFirst_(cid, done); } }); }, // タップで全画像ズーム＋1ページ目にする＋貼り付け新規追加
    postImgs: postImgsOf_,                                      // 履歴キー → 🛠️編集で添付した投稿画像の配列(無ければ[])
    postImgHas: function (key) { return postImgsOf_(key).length > 0; },
    postImgSave: postImgSave_,                                  // 履歴キー + 画像配列 を保存(write-through)
    usedImgs: usedImgsOf_,                                      // 履歴キー → 実際に動画へ使った画像だけ(候補画像とは別)
    usedImgKnown: usedImgKnown_,                                  // 履歴キーに明示保存済みか(空＝削除済みも区別)
    usedPrevCount: usedPrevCount_,                              // 履歴キー → 先頭何枚が投稿プレビュー画像か(見出し分け用)
    usedImgSave: usedImgSave_,                                  // 履歴キー + 使用画像配列 を保存(write-through)
    // ── 🛠️編集の画像添付(貼り付け＋用途選択・Chami依頼2026-07-15)用の公開API ──
    pasteImage: function (cb) { return pasteImageFromClipboard_(cb); }, // クリップボード画像→dataURL(cb(durl,err))
    refImgsSet: function (cid, arr) { if (!cid) return false; var cur = refImgOf(cid) || {}; return refImgSave(cid, { imgs: (arr || []).filter(Boolean), comment: cur.comment || '', memo: cur.memo || '', twitterUrl: cur.twitterUrl || '', twitterUrl2: cur.twitterUrl2 || '' }); }, // 動画で使った画像(配列)を差し替え保存(コメント等は保持)
    bskyImgSet: function (cid, durl) { if (!cid) return false; return bskyImgSave(cid, durl || ''); } // Bluesky添付画像(単発)を設定/クリア
  }; } catch (e) {}
  // 候補専用ページ(KouhoLists.html)から持ち越された「動画を作る」選択を、動画作成タブのある index.html 側で拾って実行する。
  //   (transferToMovie_ が movie DOM 不在時に sessionStorage へ退避→index.html へ遷移。ここが受け取り口)
  try {
    var _resumeCandToMovie = function () {
      if (!document.getElementById('author')) return; // 動画作成タブが無いページでは何もしない(退避側の担当)
      var raw = ''; try { raw = sessionStorage.getItem('cand_to_movie_pending') || ''; } catch (e) {}
      if (!raw) return;
      // ★壊れた/不完全な持ち越しはキーごと捨てる。残すと、affiliate.js のタブ復元ガード(b0d392c)が
      //   pending 有りと見て index.html を tabMovie に固定し続け、投稿履歴/ドラフトへ切り替わらなくなる。
      var p; try { p = JSON.parse(raw); } catch (e) { try { sessionStorage.removeItem('cand_to_movie_pending'); } catch (e1) {} return; }
      if (!p || !p.it) { try { sessionStorage.removeItem('cand_to_movie_pending'); } catch (e2) {} return; }
      // app.js/affiliate.js のタブ復元が落ち着いてから流し込む(タブ切替→入力欄の描画が先)。
      setTimeout(function () {
        var consume_ = function (imgDataUrl) {
          try { sessionStorage.removeItem('cand_to_movie_pending'); } catch (e) {}
          try { transferToMovie_(p.it, imgDataUrl || '', p.comment || '', p.workUrl || '', { cid: p.imageCid || '', index: p.imageIndex || 0 }); } catch (e) {}
        };
        if (p.imgDataUrl) { consume_(p.imgDataUrl); return; }
        if (p.imageCid) {
          Promise.resolve(ensureRefLoaded_(p.imageCid)).then(function () {
            return resolveRefImgsAwaited_(p.imageCid); // ★R2退避画像も"待って"から取り出す(acc2の「遷移しない」根治・④-1)
          }).then(function (imgs) {
            var idx = Math.max(0, Number(p.imageIndex) || 0);
            consume_((imgs && (imgs[idx] || imgs[0])) || '');
          }, function () { consume_(''); });
          return;
        }
        consume_('');
      }, 300);
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _resumeCandToMovie);
    else _resumeCandToMovie();
  } catch (e) {}
  // アプリを他アプリ/他タブから前面へ戻した時、候補パネルが表示中なら未取得タイトルを追い直す。
  //   (Chamiが候補追加→別アプリで確認→戻ってくる導線＝再操作なしで埋める。画面に無ければ何もしない)
  try {
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState !== 'visible') return;
      var el = document.getElementById('candList');
      if (!el || el.offsetParent === null) return; // 候補が画面に無い＝無駄な通信をしない
      // ★復帰のたび render() を呼ぶと page.innerHTML を丸ごと作り直す=画面が一瞬白くチラつく
      //   (Chami 2026-08-04・Twitter等と往復するたび発生・モーダルを開いたままでも背後が再構築される)。
      //   タイトル追い直しに全再描画は不要=(1)未取得の再取得フェーズを素早いへ戻し(kick)、
      //   (2)自動追跡タイマーだけ再武装する。実際にタイトルが埋まった時だけ scheduleInfoTick_→
      //   renderCandList が該当カードを部分更新する(チラつかない)。この handler 自体は 7/29 に
      //   追加された=それ以前にチラつきが無かったのはこの全再描画が無かったため。
      kickInfoBackfill_();
      try { scheduleInfoTick_(_activeTab, lsGet(itemsKey(_activeTab), '[]')); } catch (e) {}
    });
  } catch (e) {}
  hydrateImages_(); // IDBから画像をメモリへ＋旧localStorage画像を移行(5MB枠を解放)
  // IDBが使えない/展開が走らない端末でも、LSに積もった退避画像をR2へ逃がす解毒を一度は必ず動かす(冪等・非破壊)。
  try { setTimeout(function () { try { hydrateR2Refs_(); } catch (e) {} }, 2500); } catch (e) {}
  // 既存タブの移行: 登録済みサークルをPCバッチの追跡対象へ(登録済みはフラグでスキップ＝通信は初回のみ)
  ensureTrackedAll();
  schedulePoolSync_(); // 起動時: 📚タブを開かなくても保存済み候補を D1 へ同期(部門が読める)
}());
