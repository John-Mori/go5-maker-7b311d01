/**
 * bluesky.js — Bluesky 投稿のUI配線(統合版・v19)
 *   本文＝固定文のみ。(編集可)アフィリンクは「作品URL」から投稿時に自動付与、画像も自動添付。
 *   プレビューは実アカウントのアイコンを取得して表示。投稿される見た目そのもの。
 *   投稿手段：①動画作成後の自動投稿(編集できる確認)②今すぐ投稿(単独)③予約投稿。
 *   秘匿情報(アプリパスワード・シークレット)は console に出さない。
 *   v19: アカウント別(acc1/acc2)に設定を分離。gasUrl のみ共通。
 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };

  var els = {
    enable: $('bskyEnable'), text: $('bskyText'), count: $('postCount'), workUrl: $('bskyWorkUrl'),
    handle: $('bskyHandle'), appPw: $('bskyAppPw'), gasUrl: $('bskyGasUrl'), gasStatus: $('gasStatus'),
    testBtn: $('bskyTestBtn'), testResult: $('bskyTestResult'),
    bskyStatus: $('bskyStatus'), postStatus: $('postStatus'), postNow: $('postNowBtn'),
    schedAt: $('postSchedAt'), reserveBtn: $('postReserveBtn'), unattended: $('bskyUnattended'),
    postImg: $('postImg'), postImgName: $('postImgName'), postImgClear: $('postImgClear'), postImgPreview: $('postImgPreview'),
    pcImg: $('pcImg'), pcImgClear: $('pcImgClear'), pcImgPreview: $('pcImgPreview'), pcImgName: $('pcImgName'),
    pvName: $('pvName'), pvHandle: $('pvHandle'), pvBody: $('pvBody'),
    pvImgWrap: $('pvImgWrap'), pvImg: $('pvImg'), pvImgNote: $('pvImgNote'),
    pvAvatar: $('pvAvatar'), pvAvFallback: $('pvAvFallback'),
    pcModal: $('postConfirmModal'), pcText: $('pcText'), pcNote: $('pcNote'), pcOk: $('pcOk'), pcCancel: $('pcCancel'),
    pcWorkUrl: $('pcWorkUrl'), pcWorkWarn: $('pcWorkWarn'),
    shortUrlOut: $('shortUrlOut'), shortUrlCopy: $('shortUrlCopy'), ytDesc: $('ytDesc'), ytInsert: $('ytInsert'), ytCopy: $('ytCopy'),
    ytTitle: $('ytTitle'), ytTitleCopy: $('ytTitleCopy'), ytTags: $('ytTags'),
    discountSel: $('discountSel'), discountSel2: $('discountSel2'), discountSelPc: $('discountSelPc'),
    discountNew: $('discountNew'), discountNew2: $('discountNew2'), discountNewPc: $('discountNewPc'),
    histList: $('histList'), histRefresh: $('histRefresh'), histShowDiscarded: $('histShowDiscarded'),
    manualUrl: $('manualUrl'), manualTitle: $('manualTitle'), manualShortBtn: $('manualShortBtn'),
    manualResult: $('manualResult'), manualOut: $('manualOut'), manualCopy: $('manualCopy'),
    movieWorkUrl: $('movieWorkUrl'), movieWorkWarn: $('movieWorkWarn'),
    movieWorkAffi: $('movieWorkAffi'), movieWorkAffiCopy: $('movieWorkAffiCopy'), movieWorkInfo: $('movieWorkInfo'),
    ytQSave: $('ytQSave'), ytQLoad: $('ytQLoad'), ytReset: $('ytReset'), ytUndo: $('ytUndo'), ytRedo: $('ytRedo'), ytQInfo: $('ytQInfo'),
    bskyQSave: $('bskyQSave'), bskyQLoad: $('bskyQLoad'), bskyReset: $('bskyReset'), bskyUndo: $('bskyUndo'), bskyRedo: $('bskyRedo'), bskyQInfo: $('bskyQInfo'),
    affiUrls: $('affiUrls'),
    affiUrlsQSave: $('affiUrlsQSave'), affiUrlsQLoad: $('affiUrlsQLoad'), affiUrlsReset: $('affiUrlsReset'), affiUrlsUndo: $('affiUrlsUndo'), affiUrlsRedo: $('affiUrlsRedo'), affiUrlsQInfo: $('affiUrlsQInfo')
  };
  if (!els.text) return;

  var selectedPostFile = null, pcSelectedFile = null, lastImgUrl = null;
  // drive-upload.js と scheduler.js が動画作成フロー時に参照するため公開(ソフト参照)
  try { window.BskyExtra = { getFile: function () { return selectedPostFile; } }; } catch (e) {}
  // 一本道の背骨：直近の動画作成で発番された安定動画ID。投稿記録に串刺しで持たせる。
  var currentVideoId = '';

  // ---- 汎用永続化 ----
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  // 動画作成タブの「カテゴリ」チェック状態を読む。(キャラ/JK/ギャル/異世界・複数可・キャラ無し＝オリジナル)
  var MOVIE_ATTRS = [['chara', 'movieAttrChara'], ['jk', 'movieAttrJk'], ['gyaru', 'movieAttrGyaru'], ['isekai', 'movieAttrIsekai'], ['harem', 'movieAttrHarem'], ['ai', 'movieAttrAi'], ['ol', 'movieAttrOl'], ['soshu', 'movieAttrSoshu']];
  // 動画作成タブの「リビルド(作り直し)」チェック状態。ONなら「同じ作品を作り直した動画」として記録。
  function readRebuild() { var el = $('movieRebuild'); return !!(el && el.checked); }
  // リビルド対象として選んだ投稿履歴のvideoId。(未選択なら空)投稿履歴のGo5History.markRebuiltで「被リビルド」に自動反映する。
  function readRebuildTarget() { var el = $('movieRebuildTarget'); return (el && el.value) || ''; }
  // 「🔁リビルド」チェック時に、どの投稿をリビルドするか投稿履歴から選ぶピッカーを表示・選択肢を最新化する。
  var _rebuildList = []; // 現在ピッカーに出している投稿履歴(videoId→作品データ引き当て用)
  function refreshRebuildPicker_() {
    var row = $('movieRebuildTargetRow'), sel = $('movieRebuildTarget'), cb = $('movieRebuild');
    if (!row || !sel || !cb) return;
    if (!cb.checked) { row.hidden = true; return; }
    var list = (window.Go5History && window.Go5History.listForRebuildPicker) ? window.Go5History.listForRebuildPicker() : [];
    _rebuildList = list;
    var cur = sel.value;
    sel.innerHTML = '<option value="">(選択してください)</option>' + list.map(function (it) {
      var d = it.ts ? new Date(it.ts) : null;
      var dstr = d ? ((d.getMonth() + 1) + '/' + d.getDate() + ' ') : ''; // 投稿履歴と見比べやすいよう日付を先頭に
      return '<option value="' + it.videoId + '">' + escapeHtml(dstr + (it.title || '(無題)')) + '</option>';
    }).join('');
    if (cur && list.some(function (it) { return it.videoId === cur; })) sel.value = cur;
    row.hidden = false;
  }
  // リビルド対象を選んだら、その作品データ(作品URL→作者名/アフィリンク/割引/作品情報、作品状態)を自動反映。
  function onRebuildTargetChange_() {
    var sel = $('movieRebuildTarget'); if (!sel || !sel.value) return;
    var vid = sel.value, item = null;
    _rebuildList.forEach(function (x) { if (x.videoId === vid) item = x; });
    if (!item) return;
    if (item.workUrl) {
      if (els.movieWorkUrl) els.movieWorkUrl.value = item.workUrl;
      syncWorkUrl(item.workUrl, true); // 作者名(サークル名)/投稿バージョンURL(アフィID入り)/割引/FANZA作品情報を自動反映
    }
    applyWorkStateToUi_(item.workState); // 新作/準新作の作品状態を反映
  }
  // 作品状態(新作/準新作/旧作)を動画作成タブのチェックへ反映。新作は本文にも波及させる。
  function applyWorkStateToUi_(ws) {
    var shin = $('discountNew2'), jun = $('movieJunshinsaku');
    if (jun) jun.checked = (ws === '準新作');
    if (shin) { shin.checked = (ws === '新作'); try { shin.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {} }
    renderPreview();
  }
  (function wireRebuildPicker_() {
    var cb = $('movieRebuild'); if (!cb) return;
    cb.addEventListener('change', refreshRebuildPicker_);
    var sel = $('movieRebuildTarget'); if (sel) sel.addEventListener('change', onRebuildTargetChange_);
    document.addEventListener('account-changed', function () { if (cb.checked) refreshRebuildPicker_(); });
  })();
  // 投稿履歴タブの「🔁リビルドで作る」から呼ぶ：動画作成タブへ移動し、リビルドON＋対象を選択済みにして
  // 作品データ(作品URL/作者/割引/作品状態)を自動反映→作成ボタンへ誘導。(残り1タップ)
  try { window.Go5Rebuild = { startFromHistory: function (videoId) {
    if (!videoId) return;
    var tab = document.getElementById('tabMovie'); if (tab) tab.click();
    var cb = $('movieRebuild'); if (cb && !cb.checked) cb.checked = true;
    refreshRebuildPicker_();
    var sel = $('movieRebuildTarget');
    if (sel) { sel.value = videoId; onRebuildTargetChange_(); }
    setTimeout(function () {
      var mk = $('makeBtn'); if (!mk) return;
      try { mk.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) {}
      mk.classList.add('cta-ready-pulse');
      setTimeout(function () { mk.classList.remove('cta-ready-pulse'); }, 2400);
    }, 300);
  } }; } catch (e) {}
  function readMovieAttrs() {
    var o = {};
    MOVIE_ATTRS.forEach(function (p) { var el = $(p[1]); o[p[0]] = !!(el && el.checked); });
    return o;
  }
  // ---- カテゴリ自動チェック(FANZAジャンル名→該当カテゴリ) ----
  // 作品が決まったら(候補から/作品URL入力/ウィザード)、取得済みジャンル名で該当カテゴリへ自動チェック。
  // 全カテゴリを一旦外してから該当だけON＝前回のチェックを引き継がない。
  var GENRE_ATTR_KEYWORDS = {
    chara: ['二次創作'],
    jk: ['女子校生', '女子高生', 'JK'],
    gyaru: ['ギャル'],
    isekai: ['異世界', '転生'],
    harem: ['ハーレム'],
    ai: ['AI生成', 'AIイラスト', 'AIグラビア'],
    ol: ['OL'],
    soshu: ['総集編']
  };
  function setMovieAttrsFromGenres(genres) {
    var names = (genres || []).map(function (g) { return String(g || ''); });
    MOVIE_ATTRS.forEach(function (p) {
      var el = $(p[1]); if (!el) return;
      var kws = GENRE_ATTR_KEYWORDS[p[0]] || [];
      el.checked = names.some(function (n) { return kws.some(function (k) { return n.indexOf(k) >= 0; }); });
    });
  }
  // 同じ作品(cid)には1回だけ自動適用＝再描画・キャッシュヒットのたびに手動調整を上書きしない。(割引自動反映と同じ設計)
  // リロードを跨いでも尊重できるよう localStorage に記録する。
  function autoApplyAttrsFromInfo_(info) {
    if (!info) return;
    var cid = String(info.cid || ''); if (!cid) return;
    if (load('movie_auto_attrs_cid') === cid) return;
    save('movie_auto_attrs_cid', cid);
    setMovieAttrsFromGenres(info.genres || []);
  }
  // 候補タブ/ウィザードから使う公開口。reset=全カテゴリOFF(新規作成の起点)、applyGenres=即時チェック(cid指定で以後の自動適用を抑止)。
  try { window.Go5MovieAttrs = {
    reset: function () { save('movie_auto_attrs_cid', ''); MOVIE_ATTRS.forEach(function (p) { var el = $(p[1]); if (el) el.checked = false; }); },
    applyGenres: function (genres, cid) { if (cid) save('movie_auto_attrs_cid', String(cid)); setMovieAttrsFromGenres(genres || []); }
  }; } catch (e) {}
  // 新規作成の起点(候補から/ウィザード開始)で呼ぶ一括リセット: カテゴリ+狙い+コメント型+リビルド+2行モード。
  // 前回の選択・チェックを引き継がない。狙い・コメント型は生成前の必須選択なので未設定へ戻す。(Chami指定2026-07-14)
  try { window.Go5NewMovieReset = function () {
    if (window.Go5MovieAttrs) window.Go5MovieAttrs.reset();
    var g = $('movieGoal'); if (g) g.value = '';
    var ct = $('movieCmtType'); if (ct) ct.value = '';
    try { localStorage.removeItem('field_movieGoal'); localStorage.removeItem('field_movieCmtType'); } catch (e) {}
    var rb = $('movieRebuild');
    if (rb && rb.checked) { rb.checked = false; try { rb.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {} }
    var rbRow = $('movieRebuildTargetRow'), rbSel = $('movieRebuildTarget');
    if (rbSel) rbSel.value = ''; if (rbRow) rbRow.hidden = true;
    // 2行モード(コメント/作者)もOFFへ。change発火で保存値・行数・プレビューまで通常経路で同期させる。
    ['topTwoLine', 'authorTwoLine'].forEach(function (id) {
      var el = $(id);
      if (el && el.checked) { el.checked = false; try { el.dispatchEvent(new Event('change', { bubbles: true })); } catch (e) {} }
    });
    try { if (window.Go5PromoLabel) window.Go5PromoLabel.clear(); } catch (e) {} // 販促ラベルも前作の割引で焼かない
  }; } catch (e) {}
  // 投稿時の作品状態を判定：新作(discountNew2) > 準新作(movieJunshinsaku) > 旧作。(どちらも無し)
  function readWorkState() {
    var shin = $('discountNew2') && $('discountNew2').checked;
    var jun = $('movieJunshinsaku') && $('movieJunshinsaku').checked;
    return shin ? '新作' : (jun ? '準新作' : '旧作');
  }

  // ---- アカウント別永続化ヘルパ ----
  // ★読み出し側(yt-clicks.js acct())と必ず同じ解決を使う。ここが分裂していると
  //   「acc2で書いた履歴をacc1から読む」状態になり宵桜艶帖の履歴だけ消えて見える(INC-112)。
  function acctId() {
    try { if (window.Go5Acct) return window.Go5Acct.current(); } catch (e) {}
    return (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1');
  }
  function pk(base) { return base + '__' + acctId(); }

  // ---- アカウント同定(DID)：投稿の所属を「今のUI」ではなくpost_uriのDIDで確定する ----
  // 現在のUIに依存せず特定アカウントのハンドル/DIDを読むための直接キー。
  function handleOfAcct_(a) { try { return (localStorage.getItem('bsky_handle__' + a) || '').trim().replace(/^@/, ''); } catch (e) { return ''; } }
  function acctDid_(a) { try { return (localStorage.getItem('bsky_did__' + a) || '').trim(); } catch (e) { return ''; } }
  function setAcctDid_(a, did) { if (a && /^did:/.test(did || '')) { try { localStorage.setItem('bsky_did__' + a, did); } catch (e) {} } }
  // at://did:plc:XXXX/app.bsky.feed.post/… から DID を取り出す。(実際に投稿したアカウントの正体)
  function didFromUri_(uri) { var m = String(uri || '').match(/^at:\/\/(did:[^/]+)/); return m ? m[1] : ''; }
  // 既知DID → acctId。(未キャッシュなら空)
  function acctOfDid_(did) { if (!did) return ''; if (acctDid_('acc1') === did) return 'acc1'; if (acctDid_('acc2') === did) return 'acc2'; return ''; }
  // 両アカウントのDIDを「ハンドル(⚙設定)→resolveHandle」を正として解決・上書きする。(1セッション1回)
  //   ハンドル解決を権威にすることで、過去にイベント由来で誤学習した bsky_did__ の汚染も治す。
  var _didsResolved = false;
  function ensureAcctDids_(cb, force) {
    if (_didsResolved && !force) { if (cb) cb(); return; }
    var need = ['acc1', 'acc2'].filter(function (a) { return handleOfAcct_(a); });
    if (!need.length) { _didsResolved = true; if (cb) cb(); return; }
    var pend = need.length;
    need.forEach(function (a) {
      fetch('https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?handle=' + encodeURIComponent(handleOfAcct_(a)))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j && j.did) setAcctDid_(a, j.did); }) // ハンドル解決を正として上書き(汚染治癒)
        .catch(function () {})
        .then(function () { if (--pend === 0) { _didsResolved = true; if (cb) cb(); } });
    });
  }
  function loadA(base) { try { return localStorage.getItem(pk(base)); } catch (e) { return null; } }
  function saveA(base, v) { try { localStorage.setItem(pk(base), v); } catch (e) {} }

  // ---- DOM初期値の保持(空アカウント時のデフォルト) ----
  var DEF = {
    text: (els.text ? els.text.value : ''),
    ytDesc: (els.ytDesc ? els.ytDesc.value : ''),
    ytTags: (els.ytTags ? els.ytTags.value : ''),
    workUrl: '', handle: '', appPw: ''
  };
  // アカウント別の本文テンプレ既定。(保存が空のときに使う)〇 は割引％のプレースホルダ。
  //   ★2026-07-20: PR行(↓詳細はこちらから…)はcomposePostText/renderPreviewが自動で付け足すため、
  //   ここには含めない(旧テンプレには含まれていた＝自動付与分と重複し「本文が一部重なる/URLが
  //   いつも下に来る」不具合の原因だった。旧保存値は下のmigrateDedupPrLine_で1回だけ剥がす)。
  var DEF_TEXT = {
    acc1: 'おすすめ漫画見つけた💕',
    acc2: '続きが気になっちゃう一冊、みつけた📚'
  };
  function defText() { return DEF_TEXT[acctId()] || DEF_TEXT.acc1; }

  // アカウント別の YouTube説明欄テンプレ既定。(保存が空のときに使う)1行目の短縮URLプレースホルダは投稿後に自動で実URLへ置換。
  var DEF_YTDESC = {
    acc1: '↑ URLを長押し&リンクを開く ↑\nこちらからアクセスしてね💕\n\n\n\n\n【感想📖】',
    acc2: '(短縮URLが入ります)\n\n⬆️URLを長押し&リンクを開く\n続きはこちらからどうぞ💫\n\n\n\n\n📚ひとこと📚'
  };
  function defYtDesc() { return DEF_YTDESC[acctId()] || DEF_YTDESC.acc1; }

  // ---- 一度だけ移行(既存の共有値を現在のアカウント名前空間へコピー) ----
  (function migrateOnce() {
    if (load('acct_split_migrated') === '1') return;
    var a = acctId();
    ['bsky_enable', 'bsky_text', 'bsky_work_url', 'bsky_handle', 'bsky_app_pw', 'bsky_unattended', 'yt_desc', 'yt_tags'].forEach(function (base) {
      var legacy = load(base);
      if (legacy != null && load(base + '__' + a) == null) { try { localStorage.setItem(base + '__' + a, legacy); } catch (e) {} }
    });
    save('acct_split_migrated', '1');
  })();

  // ---- gasUrl(共有)の復元 ----
  if (els.gasUrl) { var gv = load('bsky_gas_url'); if (gv != null) els.gasUrl.value = gv; }

  // ---- 現在アカウントの設定を画面に反映 ----
  function applyAccount() {
    // enable / unattended
    if (els.enable) els.enable.checked = (loadA('bsky_enable') === '1');
    if (els.unattended) els.unattended.checked = (loadA('bsky_unattended') === '1');

    // テキスト系(null なら DEF を使用)
    var tv = loadA('bsky_text'); if (els.text) els.text.value = (tv != null && tv !== '') ? tv : defText();
    if (els.discountSel) els.discountSel.value = '';
    if (els.discountSel2) els.discountSel2.value = '';
    if (els.discountNew) els.discountNew.checked = false;
    if (els.discountNew2) els.discountNew2.checked = false;
    ensureDiscUrlsSeeded_(); renderDiscUrlList_(); // 🔥セール案内URL一覧(アカウント別・選択は永続)
    if (els.histList) loadHistory();
    var wv = loadA('bsky_work_url'); var wval = (wv != null ? wv : DEF.workUrl);
    if (els.workUrl) els.workUrl.value = wval;
    if (els.movieWorkUrl) els.movieWorkUrl.value = wval;
    updateMovieWorkLink(wval);
    updateMovieWorkAffi(wval);
    scheduleMovieWorkInfo(wval);
    updateBskyWorkLink(wval);
    paintWorkWarn(els.movieWorkWarn, wval);
    var hv = loadA('bsky_handle'); if (els.handle) els.handle.value = (hv != null ? hv : DEF.handle);
    var pv = loadA('bsky_app_pw'); if (els.appPw) els.appPw.value = (pv != null ? pv : DEF.appPw);
    var dv = loadA('yt_desc'); if (els.ytDesc) els.ytDesc.value = (dv != null ? dv : defYtDesc());
    // YTタグは全チャンネル共通。(Chami指定2026-07-12: #マンガ紹介等の検証はチャンネル横断で統一変更する)
    //   初回はアカウント別の旧値(acc1優先)から共有キーへ移行。
    var tgv = load('yt_tags_shared');
    if (tgv == null) { tgv = load('yt_tags__acc1') != null ? load('yt_tags__acc1') : loadA('yt_tags'); if (tgv != null) save('yt_tags_shared', tgv); }
    if (els.ytTags) els.ytTags.value = (tgv != null ? tgv : DEF.ytTags);

    // 本文の括弧書き自動クリーンアップ(移行直後の旧注記を除去)
    if (els.text && els.text.value) {
      var cleaned = els.text.value.split('\n').filter(function (line) {
        return !/^\s*[((].*(自動で追加|自動で添付|自動添付|自動で付).*[))]\s*$/.test(line);
      }).join('\n').replace(/\n{3,}/g, '\n\n').replace(/^\n+|\n+$/g, '');
      if (cleaned !== els.text.value) { els.text.value = cleaned; saveA('bsky_text', cleaned); }
    }

    // アバター再取得(ハンドル変更に追従)
    var hHandle = (els.handle ? (els.handle.value || '').trim().replace(/^@/, '') : '');
    avatarFor = null; // キャッシュを無効化して再取得を強制
    ensureAvatar(hHandle);

    // 依存UIを更新
    renderPreview();
    updateGasStatus();
    buildTitle();
    if (typeof refreshQuickInfo === 'function') refreshQuickInfo();
  }

  // ---- gasUrl の保存配線(共有) ----
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
  if (els.workUrl) els.workUrl.addEventListener('input', function () { syncWorkUrl(els.workUrl.value, false); });
  if (els.handle) els.handle.addEventListener('input', function () { saveA('bsky_handle', els.handle.value); renderPreview(); updateGasStatus(); });
  if (els.appPw) els.appPw.addEventListener('input', function () { saveA('bsky_app_pw', els.appPw.value); renderPreview(); updateGasStatus(); });

  // ---- 🔌 接続テスト(ログインだけ試す・投稿しない)----
  function setTestResult(msg, kind) {
    if (!els.testResult) return;
    els.testResult.hidden = false;
    els.testResult.innerHTML = msg;
    els.testResult.className = 'status ' + (kind || '');
  }
  // ログイン失敗の生メッセージを、原因の分かりやすい案内に変換
  function friendlyLoginError(raw) {
    var m = String(raw || '');
    if (/Invalid identifier or password/i.test(m)) {
      return 'ハンドルかアプリパスワードが違います。<br>' +
        '・パスワードは Bluesky の<b>アプリパスワード</b>(<code>xxxx-xxxx-xxxx-xxxx</code>)です。(通常のログインPWではありません)<br>' +
        '・失効している場合があるので<b>作り直して貼り直す</b>と確実です。<br>' +
        '・ハンドルは <code>@</code> 抜き・ドメインまで。(例 <code>yourname.bsky.social</code>)';
    }
    if (/Rate Limit|429/i.test(m)) return '試行が多すぎます。少し時間をおいて再度お試しください。';
    if (/Failed to fetch|NetworkError|load failed/i.test(m)) return '通信に失敗しました。ネット接続をご確認ください。';
    return m;
  }
  if (els.testBtn) {
    els.testBtn.addEventListener('click', function () {
      var c = creds();
      if (!c.handle || !c.appPw) { setTestResult('ハンドルとアプリパスワードを入力してから押してください。', 'off'); return; }
      if (!window.BlueskyCore || !window.BlueskyCore.blueskyVerify) { setTestResult('投稿モジュール未読込。(ページを再読み込みしてください)', 'off'); return; }
      var btn = els.testBtn, orig = btn.textContent;
      btn.disabled = true; btn.textContent = '接続を確認中…';
      setTestResult('接続を確認中…', '');
      window.BlueskyCore.blueskyVerify({ identifier: c.handle, appPassword: c.appPw })
        .then(function (r) { setTestResult('✅ ログイン成功<br><span class="tr-acct">アカウント: @' + (r.handle || c.handle) + '</span><br>このアカウントで投稿できます。', 'on'); })
        .catch(function (e) { setTestResult('⚠️ ログインできません：<br>' + friendlyLoginError(e && e.message ? e.message : e), 'off'); })
        .then(function () { btn.disabled = false; btn.textContent = orig; });
    });
  }
  if (els.ytDesc) els.ytDesc.addEventListener('input', function () { saveA('yt_desc', els.ytDesc.value); });
  if (els.ytTags) els.ytTags.addEventListener('input', function () { save('yt_tags_shared', els.ytTags.value); buildTitle(); }); // タグは全チャンネル共通保存

  // ---- 説明欄／本文の編集補助：Qセーブ／Qロード／リセット／元に戻す↶／やり直す↷(アカウント別・確認なし・再読込耐性あり) ----
  // ・Qセーブ＝今の文面を「お気に入りの下書き」として localStorage に退避。(アカウント別)
  // ・Qロード＝退避した下書きを復元。・リセット＝アカウント別の既定テンプレ文「のみ」に戻す。
  // ・元に戻す↶／やり直す↷＝Excel風の取り消し/やり直し。手入力・Qロード・リセットを履歴に積み、双方向に移動できる。
  //   履歴は localStorage(アカウント別)に保存＝再読込しても残る。
  var quickList = [];
  var STACK_MAX = 50;
  function fmtAt(ms) {
    if (!ms) return '';
    var d = new Date(Number(ms));
    var p = function (n) { return (n < 10 ? '0' : '') + n; };
    return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }
  function refreshQuickInfo() {
    quickList.forEach(function (q) {
      if (!q.info) return;
      var at = loadA(q.base + '_quick_at');
      q.info.textContent = at ? ('Q保存: ' + fmtAt(at)) : 'Q未保存';
    });
  }
  function setupQuickEdit(cfg) {
    // cfg: { ta, base, defFn, qSave, qLoad, reset, undo, redo, info }
    if (!cfg.ta) return;
    var UNDO = cfg.base + '_undostack', REDO = cfg.base + '_redostack';
    function loadStack(k) { try { var a = JSON.parse(loadA(k) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
    function saveStack(k, a) { saveA(k, JSON.stringify(a.slice(-STACK_MAX))); }
    function setVal(v) {
      cfg.ta.value = (v == null ? '' : v);
      saveA(cfg.base, cfg.ta.value);
      // 既存の input リスナ(保存＋プレビュー同期)を確実に走らせる。
      try { cfg.ta.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
    }
    // 変更前の文面を undo に積み、redo を捨てる。(新しい編集が入ったら やり直し は無効)
    function pushHistory(prevVal) {
      var u = loadStack(UNDO); u.push(prevVal == null ? '' : prevVal); saveStack(UNDO, u); saveStack(REDO, []);
    }
    if (cfg.qSave) cfg.qSave.addEventListener('click', function () {
      saveA(cfg.base + '_quick', cfg.ta.value);
      saveA(cfg.base + '_quick_at', String(Date.now()));
      refreshQuickInfo();
    });
    if (cfg.qLoad) cfg.qLoad.addEventListener('click', function () {
      var q = loadA(cfg.base + '_quick');
      if (q == null) { if (cfg.info) cfg.info.textContent = 'Q未保存(先にQセーブ)'; return; }
      pushHistory(cfg.ta.value);
      setVal(q);
    });
    if (cfg.reset) cfg.reset.addEventListener('click', function () {
      pushHistory(cfg.ta.value);
      setVal(cfg.defFn()); // 既定テンプレ文「のみ」に戻す(割引文など差し込み分も消える)
    });
    if (cfg.undo) cfg.undo.addEventListener('click', function () {
      var u = loadStack(UNDO);
      if (!u.length) { if (cfg.info) cfg.info.textContent = '元に戻す履歴がありません'; return; }
      var r = loadStack(REDO); r.push(cfg.ta.value); saveStack(REDO, r);
      var v = u.pop(); saveStack(UNDO, u);
      setVal(v);
    });
    if (cfg.redo) cfg.redo.addEventListener('click', function () {
      var r = loadStack(REDO);
      if (!r.length) { if (cfg.info) cfg.info.textContent = 'やり直す履歴がありません'; return; }
      var u = loadStack(UNDO); u.push(cfg.ta.value); saveStack(UNDO, u);
      var v = r.pop(); saveStack(REDO, r);
      setVal(v);
    });
    // 手入力は「編集セッション単位」で履歴化：フォーカス時の値を覚え、変化があれば確定時(blur/change)に1回だけ積む。
    var sessionStart = null;
    cfg.ta.addEventListener('focus', function () { sessionStart = cfg.ta.value; });
    cfg.ta.addEventListener('change', function () {
      if (sessionStart != null && cfg.ta.value !== sessionStart) { pushHistory(sessionStart); sessionStart = cfg.ta.value; }
    });
    quickList.push({ base: cfg.base, info: cfg.info });
  }
  setupQuickEdit({ ta: els.ytDesc, base: 'yt_desc', defFn: defYtDesc, qSave: els.ytQSave, qLoad: els.ytQLoad, reset: els.ytReset, undo: els.ytUndo, redo: els.ytRedo, info: els.ytQInfo });
  setupQuickEdit({ ta: els.text, base: 'bsky_text', defFn: defText, qSave: els.bskyQSave, qLoad: els.bskyQLoad, reset: els.bskyReset, undo: els.bskyUndo, redo: els.bskyRedo, info: els.bskyQInfo });
  setupQuickEdit({ ta: els.affiUrls, base: 'affi_urls', defFn: function () { return ''; }, qSave: els.affiUrlsQSave, qLoad: els.affiUrlsQLoad, reset: els.affiUrlsReset, undo: els.affiUrlsUndo, redo: els.affiUrlsRedo, info: els.affiUrlsQInfo });
  refreshQuickInfo();

  // ---- 割引％ドロップダウン(アカウント別の割引文テンプレ) ----
  // acc1：本文1行目の直下に「N%オフのおトク作品！」を挿入／なしで削除。
  // acc2：本文テンプレに含まれる「しかも今なら〇%オフ💕」の数字を差し替え／なしで〇に戻す。
  // build(n, isNew)：isNew=新作チェック時の文面。mark は通常版／新作版の両方にマッチする。(切替時に同じ行を差し替えるため)
  var DISC = {
    acc1: {
      build: function (n, isNew) { return isNew ? ('なんと今なら' + n + '%オフの新作&おトク作品！✨') : ('なんと今なら' + n + '%オフのおトク作品！✨'); },
      placeholder: 'なんと今なら〇%オフのおトク作品！✨', mark: /(?:しかも|なんと)今なら[^\n]*オフ/, persistent: false
    },
    acc2: {
      build: function (n, isNew) { return isNew ? ('しかも今なら' + n + '%オフの新作💕') : ('しかも今なら' + n + '%オフ💕'); },
      placeholder: 'しかも今なら〇%オフ💕', mark: /(?:しかも|なんと)今なら[^\n]*オフ/, persistent: false
    }
  };
  // 割引文の挿入/差し替え/削除を行う純粋関数。(対象テキストを受け取り新テキストを返す)isNew=新作用の文面。
  function discApply(text, val, isNew) {
    var cfg = DISC[acctId()] || DISC.acc1;
    var lines = String(text == null ? '' : text).split('\n');
    var idx = -1;
    for (var i = 0; i < lines.length; i++) { if (cfg.mark.test(lines[i])) { idx = i; break; } }
    if (val === '') {
      if (cfg.persistent) { if (idx >= 0) lines[idx] = cfg.placeholder; else lines.splice(Math.min(1, lines.length), 0, cfg.placeholder); }
      else if (idx >= 0) lines.splice(idx, 1);
    } else {
      var nl = cfg.build(val === 'custom' ? '' : val, isNew);  // custom は数字なし(ユーザーが入力)
      if (idx >= 0) lines[idx] = nl; else lines.splice(Math.min(1, lines.length), 0, nl);
    }
    return lines.join('\n');
  }
  // 本文(自動投稿/今すぐ投稿で共通)側の「新作」状態。2つのチェックボックスは同期。
  function isNewBody() { return !!(els.discountNew && els.discountNew.checked) || !!(els.discountNew2 && els.discountNew2.checked); }
  function syncNewBody(on) {
    if (els.discountNew) els.discountNew.checked = on;
    if (els.discountNew2) els.discountNew2.checked = on;
  }
  function curDiscVal() { return (els.discountSel && els.discountSel.value) || (els.discountSel2 && els.discountSel2.value) || ''; }
  function setDiscountLine(val) {
    if (!els.text) return;
    els.text.value = discApply(els.text.value, val, isNewBody());
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
  // 「新作」チェック切替：両チェックを同期し、選択中の割引文があれば新作版/通常版へ即差し替え。
  function onNewBodyToggle(on) { syncNewBody(on); if (curDiscVal() !== '') applyDiscount(curDiscVal()); }
  if (els.discountNew) els.discountNew.addEventListener('change', function () { onNewBodyToggle(els.discountNew.checked); });
  if (els.discountNew2) els.discountNew2.addEventListener('change', function () { onNewBodyToggle(els.discountNew2.checked); });
  // 投稿確認モーダル内：この投稿のテキスト(pcText)にだけ割引文を反映。(保存はしない)新作チェックも独立。
  function applyDiscountPc() {
    if (els.pcText) els.pcText.value = discApply(els.pcText.value, (els.discountSelPc && els.discountSelPc.value) || '', !!(els.discountNewPc && els.discountNewPc.checked));
  }
  if (els.discountSelPc) els.discountSelPc.addEventListener('change', applyDiscountPc);
  if (els.discountNewPc) els.discountNewPc.addEventListener('change', applyDiscountPc);

  // ---- 🔥 割引一覧(セール)ページのアフィリンクを本文へ添付(永続トグル・composePostTextに統合) ----
  //   ・一覧/キャンペーンURLは cid が無く作品リンク生成では弾かれるため buildFanzaListLink で包む。
  //   ・★セール会場リンクはここで事前に短縮してキャッシュする。(作品リンクも無改変ではなく、
  //     投稿直前にmeasureWorkLink_が同じ経路で短縮リンクへ差し替える＝どちらも最終投稿文では短縮リンク。
  //     訂正2026-07-20: 旧コメント「作品リンクは生のまま」は誤り)
  //     短縮は makeShortAndShare。(自前worker[チャンネル別ドメイン]→da.gd→TinyURL、全滅時はフルURL)302素通しなので af_id は保持。
  //   ・ON/OFFは端末に永続化＋composePostText()が最後に付け足す＝「案内する作品URL」より必ず後ろに来る。
  //     動画作成後の自動投稿(投稿確認モーダル)もcomposePostText()で本文を作るため自動的に反映される。
  var DISCOUNT_LIST_URL = 'https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=mens/'; // 初回だけの既定シード(下のensureDiscUrlsSeeded_)
  function DISCOUNT_LEAD_() { return acctId() === 'acc2' ? '🏮 大幅割引セール中の同人祭ページ 🏮' : '⭐大幅割引セール中の同人はこちら 🎀'; }
  // 作品URLの直前に挟む定型のPR明示行。(本文の標準構成・composePostTextとrenderPreviewの両方で使用)
  // PR行・セール行はアカウント別文言(2026-07-13 Chami共有: 順番=共通・文言=チャンネルの世界観に合わせ差し替え)
  function PR_LINE_() { return acctId() === 'acc2' ? '↓詳しくはこちらから🌙 #PR #漫画' : '↓詳細はこちらから🎀 #PR #漫画'; }

  // 本文に貼り付け済みの「古い完成形」(PR行/セール行+当時の短縮URL)を取り除く。
  //   実体は純粋関数 BlueskyCore.stripAutoBlocks(＝Nodeテスト対象)。詳しい経緯はそちらのコメント参照。
  //   core未読込(読み込み順の事故)でも投稿本文を壊さないよう、素通しにフォールバックする。
  function stripAutoBlocks_(text) {
    if (window.BlueskyCore && typeof window.BlueskyCore.stripAutoBlocks === 'function') {
      return window.BlueskyCore.stripAutoBlocks(text);
    }
    return String(text == null ? '' : text).replace(/[ \t\r\n]+$/, '');
  }
  try { window.__go5StripAutoBlocks = stripAutoBlocks_; } catch (e) {} // 検証用フック
  // フックの深掘り＋CTA行を差し込む(X案2・Chami承認2026-07-21)。ch共通・実体は純粋関数
  //   BlueskyCore.insertHookCta(＝Nodeテスト対象)。core未読込でも壊れないよう素通しにフォールバック。
  function applyHookCta_(caption) {
    if (window.BlueskyCore && typeof window.BlueskyCore.insertHookCta === 'function') {
      return window.BlueskyCore.insertHookCta(caption);
    }
    return caption;
  }
  var DISC_ON_KEY = 'bsky_discount_list_on';
  function discountListOn_() { return true; } // 常時ON(標準投稿形式の一部・2026-07-14 Chami指定でトグルUI廃止=セール行は常に添える)
  function setDiscountListOn_(on) { try { localStorage.setItem(DISC_ON_KEY, on ? '1' : '0'); } catch (e) {} }
  function curAfId_() { try { return (localStorage.getItem('fanza_af_id') || '').trim(); } catch (e) { return ''; } }

  // ---- 🔥 セール案内URLの複数管理(名前付き・追加/選択/保存/削除・選択は永続) ----
  //   Chami依頼2026-07-20:「セール中の案内URLはキャンペーン/季節で増減するので、追加・選択・保存・
  //   削除ができ、選んだものはリセットせず次回も同じものを使う」。アカウント別(acc1/acc2で別々に持てる)。
  //   永続キーは core/storage-keys.js の許可リストへ登録済み(sync対象)。
  function discUrlsKey_() { return 'bsky_discount_urls__' + acctId(); }
  function discSelKey_() { return 'bsky_discount_selected__' + acctId(); }
  function discUrlsLoad_() { try { var a = JSON.parse(localStorage.getItem(discUrlsKey_()) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
  function discUrlsSave_(arr) { try { localStorage.setItem(discUrlsKey_(), JSON.stringify(arr.slice(0, 50))); } catch (e) {} }
  function discSelectedId_() { try { return localStorage.getItem(discSelKey_()) || ''; } catch (e) { return ''; } }
  function discSetSelectedId_(id) { try { localStorage.setItem(discSelKey_(), id || ''); } catch (e) {} }
  // 初回のみ：旧・単一URL運用の既定値(DISCOUNT_LIST_URL)を「名前付きリストの1件目」として移行・選択する。
  function ensureDiscUrlsSeeded_() {
    var acc = acctId();
    if (load('disc_urls_seeded__' + acc) === '1') return;
    save('disc_urls_seeded__' + acc, '1');
    if (discUrlsLoad_().length) return; // 既に何か登録済みなら何もしない
    var seed = { id: 'seed-' + acc, name: '既定のセールページ', url: DISCOUNT_LIST_URL, at: Date.now() };
    discUrlsSave_([seed]);
    if (!discSelectedId_()) discSetSelectedId_(seed.id);
  }
  // 現在選択中のエントリ。(選択IDが失効していたら先頭にフォールバック／1件も無ければ null)
  function discCurrentEntry_() {
    var arr = discUrlsLoad_(); if (!arr.length) return null;
    var sel = discSelectedId_(), found = null;
    arr.forEach(function (e) { if (e.id === sel) found = e; });
    return found || arr[0];
  }

  // ---- 🔥 セール案内リンクのキャッシュ(ドメイン自己修復・恒久対策2026-07-20) ----
  //   旧実装は af_id だけをキーにしていたため、短縮先ドメインを変えると(v1→v2、v2→v3で2回発生)
  //   古いキャッシュが残り続け、その都度キー名を手動で改名する運用になっていた。
  //   → キャッシュキーに「選択中のエントリ」「af_id」「実際の短縮先ドメイン(workerBase())」を
  //   すべて含める。ドメインが変われば workerBase() の返り値も変わり、キーが自動的に別物になる
  //   ため古い値には二度とヒットせず自動で作り直される＝以後、手動でのキー改名が不要になる。
  var DISC_CACHE_KEY = 'bsky_discount_link_cache'; // 中身はキャッシュのみ(storage-keysに未登録=既定で同期しない・意図通り)
  function discCacheLoad_() { try { var o = JSON.parse(localStorage.getItem(DISC_CACHE_KEY) || '{}'); return (o && typeof o === 'object') ? o : {}; } catch (e) { return {}; } }
  // キー組み立ては bluesky-core.js の純粋関数(buildDiscountCacheKey・テスト済)へ委譲。
  function discCacheKeyFor_(entry, af) {
    var o = { account: acctId(), entryId: entry ? entry.id : '', afId: af, domain: workerBase() };
    return (window.BlueskyCore && window.BlueskyCore.buildDiscountCacheKey) ? window.BlueskyCore.buildDiscountCacheKey(o) : [o.account, o.entryId, o.afId, o.domain].join('|');
  }
  function discCacheGet_(key) { return discCacheLoad_()[key] || ''; }
  function discCacheSet_(key, link) {
    var c = discCacheLoad_();
    c[key] = link;
    var keys = Object.keys(c);
    if (keys.length > 30) { keys.slice(0, keys.length - 30).forEach(function (k) { delete c[k]; }); } // 古いエントリ/旧ドメイン分は溜め過ぎない
    try { localStorage.setItem(DISC_CACHE_KEY, JSON.stringify(c)); } catch (e) {}
  }
  // ---- 紹介用短縮リンクのキャッシュ(2026-07-23 プレースホルダ方式) ----
  //   composePostText/renderPreviewの両方が「今の作品URLに対応する短縮リンク」を必要とするたび
  //   毎回ネットワーク往復させないための素朴なメモリキャッシュ。resolveAffLink()(生の長いリンク)を
  //   キーにする＝作品URL・af_idのどちらが変わってもresolveAffLink()の戻り値が変わるため自動的に
  //   無効化される(割引リンクキャッシュと同じ設計思想)。
  var workShortCache_ = { forLink: '', shareUrl: '' };
  function cachedWorkShortLink_() {
    var raw = resolveAffLink();
    return (raw && workShortCache_.forLink === raw) ? workShortCache_.shareUrl : '';
  }
  function ensureWorkShortLink_(onReady) {
    var raw = resolveAffLink(); if (!raw) return;
    if (workShortCache_.forLink === raw && workShortCache_.shareUrl) { if (onReady) onReady(workShortCache_.shareUrl); return; }
    if (workShortCache_._pendingFor === raw) return; // 同じリンクへの取得が既に進行中なら二重発火しない
    workShortCache_._pendingFor = raw;
    // ★実際の取得(makeShortAndShare)は次のティックへ遅延させる。
    //   composePostText/renderPreviewはapplyAccount()の初回同期呼び出し(スクリプト冒頭・DOM構築中)から
    //   既に呼ばれるが、makeShortAndShareが依存するSHORT(workerBase()等)はまだ後方(このファイルの
    //   下の方)で`var SHORT = {...}`として代入される前＝初回はundefinedのまま参照して例外になる
    //   (実際にこの事故が起きた：script全体が初回ロード時に静かに止まっていた)。
    //   setTimeoutで1ティック遅らせれば、その時点ではスクリプト全体の実行が完了しSHORTも代入済みになる。
    setTimeout(function () {
      makeShortAndShare(raw).then(function (r) {
        var share = (r && (r.shareUrl || r.shortUrl)) || '';
        if (share) {
          workShortCache_ = { forLink: raw, shareUrl: share };
          // ★X欄(wireXTweet_)は別のIIFEスコープに居るため直接呼べない。DOMイベントで疎結合に通知する。
          try { document.dispatchEvent(new CustomEvent('go5-work-short-ready')); } catch (e) {}
        } else workShortCache_._pendingFor = ''; // 失敗時は再試行できるようにペンディング解除
        if (onReady && share) onReady(share);
      }).catch(function () { workShortCache_._pendingFor = ''; });
    }, 0);
  }
  // 選択中エントリ×af_id×現ドメインでキャッシュ済みか。
  function cachedDiscountLink_() {
    var af = curAfId_(); if (!af) return '';
    var entry = discCurrentEntry_(); if (!entry) return '';
    return discCacheGet_(discCacheKeyFor_(entry, af));
  }
  function ensureDiscountLink_(onReady) {
    var af = curAfId_(); if (!af) return;
    var entry = discCurrentEntry_(); if (!entry) return;
    var cached = cachedDiscountLink_();
    if (cached) { if (onReady) onReady(cached); return; }
    // 依頼2の自動解決(af_id欠落/未短縮のどちらも自動補完・既に短縮済みならそのまま)を利用。
    resolvePromoUrl(entry.url).then(function (r) {
      if (!r || !r.ok) return;
      discCacheSet_(discCacheKeyFor_(entry, af), r.link);
      if (onReady) onReady(r.link);
    });
  }
  function recomposePcText_() { if (els.pcText) els.pcText.value = composePostText(); }

  // ---- UI: セール案内URL一覧(選択・追加・削除)の描画・配線 ----
  function renderDiscUrlList_() {
    var wrap = $('discUrlList'); if (!wrap) return;
    var arr = discUrlsLoad_(), cur = discCurrentEntry_(), sel = cur ? cur.id : '';
    if (!arr.length) { wrap.innerHTML = '<div class="hint">(未登録。下から追加してください)</div>'; return; }
    wrap.innerHTML = arr.map(function (e) {
      var checked = (e.id === sel) ? ' checked' : '';
      return '<label class="disc-url-item">' +
        '<input type="radio" name="discUrlSel" value="' + escapeHtml(e.id) + '"' + checked + '>' +
        '<span style="flex:1;min-width:0;">' +
          '<span class="disc-url-name">' + escapeHtml(e.name || '(無題)') + '</span>' +
          '<span class="disc-url-url">' + escapeHtml(e.url) + '</span>' +
        '</span>' +
        '<button type="button" class="ghost disc-url-del" data-id="' + escapeHtml(e.id) + '">🗑</button>' +
        '</label>';
    }).join('');
    Array.prototype.forEach.call(wrap.querySelectorAll('input[name="discUrlSel"]'), function (r) {
      r.addEventListener('change', function () {
        discSetSelectedId_(r.value); // 選択は永続化(リセットしない・次回も同じものを使う)
        renderPreview();
        if (els.pcModal && !els.pcModal.hidden) recomposePcText_();
      });
    });
    Array.prototype.forEach.call(wrap.querySelectorAll('.disc-url-del'), function (b) {
      b.addEventListener('click', function () {
        var id = b.getAttribute('data-id');
        var arr2 = discUrlsLoad_(), target = null;
        arr2.forEach(function (x) { if (x.id === id) target = x; });
        if (!target) return;
        if (!window.confirm('「' + target.name + '」を削除しますか？')) return;
        arr2 = arr2.filter(function (x) { return x.id !== id; });
        discUrlsSave_(arr2);
        if (discSelectedId_() === id) discSetSelectedId_(arr2.length ? arr2[0].id : '');
        renderDiscUrlList_();
        renderPreview();
        if (els.pcModal && !els.pcModal.hidden) recomposePcText_();
      });
    });
  }
  (function wireDiscUrlAdd_() {
    var btn = $('discUrlAddBtn'); if (!btn) return;
    btn.addEventListener('click', function () {
      var nameEl = $('discUrlName'), urlEl = $('discUrlInput'), hint = $('discUrlHint');
      var name = ((nameEl && nameEl.value) || '').trim();
      var url = ((urlEl && urlEl.value) || '').trim();
      if (!/^https?:\/\//.test(url)) { if (hint) hint.textContent = 'URLは http:// か https:// で始めてください。'; return; }
      var arr = discUrlsLoad_();
      var entry = { id: 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), name: name || ('セールURL' + (arr.length + 1)), url: url, at: Date.now() };
      arr.unshift(entry); discUrlsSave_(arr);
      discSetSelectedId_(entry.id); // 追加したものをそのまま選択(=次回もこれを使う)
      if (nameEl) nameEl.value = ''; if (urlEl) urlEl.value = '';
      if (hint) hint.textContent = '「' + entry.name + '」を追加・選択しました。';
      renderDiscUrlList_();
      renderPreview();
      if (els.pcModal && !els.pcModal.hidden) recomposePcText_();
    });
  })();

  // 割引リンクの用意をPromise化(2026-07-13): 動画生成→投稿モーダルを「完成形」で開くための待ち合わせ。
  //   取得に失敗しても投稿は止めない。(4秒で諦めてそのまま進む)
  function ensureDiscountReadyP_() {
    return new Promise(function (res) {
      if (!discountListOn_() || cachedDiscountLink_()) return res();
      var done = false;
      var t = setTimeout(function () { if (!done) { done = true; res(); } }, 4000);
      ensureDiscountLink_(function () { if (!done) { done = true; clearTimeout(t); res(); } });
    });
  }
  // 投稿タブ／投稿確認モーダル、どちらのチェックボックスからでも同じ状態を共有・操作できるように配線。
  function wireDiscountListToggle_(id, statusSetter, onChanged) {
    var el = document.getElementById(id);
    if (!el) return;
    el.checked = discountListOn_();
    el.addEventListener('change', function () {
      setDiscountListOn_(el.checked);
      ['bskyDiscountListOn', 'pcDiscountListOn'].forEach(function (oid) { var o = document.getElementById(oid); if (o && o !== el) o.checked = el.checked; });
      if (el.checked) {
        var af = curAfId_();
        if (!af) { if (statusSetter) statusSetter('先に「AFIリンク」タブで af_id を設定してください。(未設定だと成果が付きません)'); }
        else if (!cachedDiscountLink_()) {
          if (statusSetter) statusSetter('割引一覧リンクを準備中…');
          ensureDiscountLink_(function () { if (statusSetter) statusSetter('割引一覧リンクを本文末尾に添えます。'); if (onChanged) onChanged(); });
        } else if (statusSetter) statusSetter('割引一覧リンクを本文末尾に添えます。');
      } else if (statusSetter) statusSetter('割引一覧リンクを外しました。');
      if (onChanged) onChanged();
    });
  }
  wireDiscountListToggle_('bskyDiscountListOn', function (m) { var s = document.getElementById('postStatus'); if (s) s.textContent = m; }, function () { renderPreview(); if (els.pcModal && !els.pcModal.hidden) recomposePcText_(); });
  wireDiscountListToggle_('pcDiscountListOn', function (m) { var s = document.getElementById('pcDiscStatus'); if (s) s.textContent = m; }, function () { recomposePcText_(); });

  // ---- 📝テンプレ帳: 本文定型文の名前付き保存/適用/削除(アカウント別・検証で文面を切替える用) ----
  function tplBookKey_() { return 'bsky_tpl_book__' + acctId(); }
  function tplBookLoad_() { try { return JSON.parse(localStorage.getItem(tplBookKey_()) || '[]') || []; } catch (e) { return []; } }
  function tplBookSave_(arr) { try { localStorage.setItem(tplBookKey_(), JSON.stringify(arr.slice(0, 30))); } catch (e) {} }
  function tplSelRefresh_() {
    var sel = $('bskyTplSel'); if (!sel) return;
    var book = tplBookLoad_();
    sel.innerHTML = '<option value="">(選択)</option>' + book.map(function (t, i) { return '<option value="' + i + '">' + escapeHtml(t.name) + '</option>'; }).join('');
  }
  (function wireTplBook_() {
    var sel = $('bskyTplSel'); if (!sel) return;
    $('bskyTplSave').addEventListener('click', function () {
      if (!els.text || !els.text.value.trim()) { var h = $('bskyTplHint'); if (h) h.textContent = '本文が空です。'; return; }
      var name = window.prompt('この定型文の名前(例: 断定型A / セール強調)', '');
      if (!name || !name.trim()) return;
      var book = tplBookLoad_().filter(function (t) { return t.name !== name.trim(); }); // 同名は上書き
      book.unshift({ name: name.trim(), text: els.text.value, at: new Date().getTime() });
      tplBookSave_(book); tplSelRefresh_(); sel.value = '0';
      var h2 = $('bskyTplHint'); if (h2) h2.textContent = '「' + name.trim() + '」として保存しました。';
    });
    $('bskyTplApply').addEventListener('click', function () {
      var book = tplBookLoad_(), t = book[parseInt(sel.value, 10)];
      if (!t) { var h = $('bskyTplHint'); if (h) h.textContent = 'テンプレを選択してください。'; return; }
      if (els.text) { els.text.value = t.text; saveA('bsky_text', t.text); renderPreview(); }
      var h2 = $('bskyTplHint'); if (h2) h2.textContent = '「' + t.name + '」を本文へ適用しました。(この文面が固定されます)';
    });
    $('bskyTplDel').addEventListener('click', function () {
      var book = tplBookLoad_(), i = parseInt(sel.value, 10), t = book[i];
      if (!t) return;
      if (!window.confirm('テンプレ「' + t.name + '」を削除しますか？')) return;
      book.splice(i, 1); tplBookSave_(book); tplSelRefresh_();
      var h = $('bskyTplHint'); if (h) h.textContent = '削除しました。';
    });
    tplSelRefresh_();
  })();

  // ---- アカウント切替で再読込 ----
  document.addEventListener('account-changed', function () { applyAccount(); tplSelRefresh_(); });

  // ---- テンプレ更新の一回限り移行(2026Q2)：旧テンプレ保存値を新テンプレへ。独自文(旧マーカー無し)は保持。----
  (function migrateTemplates2026q2() {
    if (load('feat_2026q2_migrated') === '1') return;
    try {  // ② acc2本文：↓全部はこちらから → ↓続きはこちらから
      var t2 = load('bsky_text__acc2');
      if (t2 && t2.indexOf('↓全部はこちらから') >= 0) save('bsky_text__acc2', t2.replace('↓全部はこちらから', '↓続きはこちらから'));
    } catch (e) {}
    ['acc1', 'acc2'].forEach(function (a) {  // ③ YouTube説明欄：旧共有テンプレ(感想/アクセス文を含む)を新テンプレへ
      try {
        var key = 'yt_desc__' + a, v = load(key);
        if (v == null || v.indexOf('【感想') >= 0 || v.indexOf('こちらからアクセスしてね') >= 0) save(key, DEF_YTDESC[a]);
      } catch (e) {}
    });
    save('feat_2026q2_migrated', '1');
  })();

  // ---- YouTube説明欄テンプレ更新の一回移行(v3)：旧/前テンプレ保存値を最新テンプレへ。独自文は保持。----
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

  // ---- composePostTextの自動PR行と重複する「旧テンプレ末尾のPR行」を1回だけ剥がす(2026-07-20) ----
  //   旧DEF_TEXTは末尾にPR行を含んでいた→composePostTextが同じ趣旨のPR行(PR_LINE_)をさらに自動追加
  //   するため「投稿本文が一部重なる/作品案内URLがいつも一番下」の原因になっていた(Chami報告)。
  //   末尾が旧テンプレの既知パターンと完全一致する場合のみ剥がす。(独自に書いた文はそのまま保持)
  (function migrateDedupPrLine_() {
    if (load('tpl_prline_dedup_v1') === '1') return;
    var TAIL = {
      acc1: /\n\n↓詳細はこちらから🎀 #PR #漫画\s*$/,
      acc2: /\n\n↓続きはこちらから🌙 #PR #漫画\s*$/
    };
    ['acc1', 'acc2'].forEach(function (a) {
      try {
        var key = 'bsky_text__' + a, v = load(key);
        if (v != null && TAIL[a].test(v)) save(key, v.replace(TAIL[a], ''));
      } catch (e) {}
    });
    save('tpl_prline_dedup_v1', '1');
  })();

  // ---- 初期化(移行→applyAccount の順) ----
  applyAccount();

  function setBskyStatus(m, html) { if (!els.bskyStatus) return; if (html) els.bskyStatus.innerHTML = m; else els.bskyStatus.textContent = m || ''; }
  function setPostStatus(m, html) { if (!els.postStatus) return; if (html) els.postStatus.innerHTML = m; else els.postStatus.textContent = m || ''; }
  function creds() { return { handle: (els.handle.value || '').trim(), appPw: (els.appPw.value || '').trim() }; }
  function firstUrl(t) { var m = String(t).match(/https?:\/\/[^\s]+/); return m ? m[0] : ''; }
  function escapeHtml(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
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
  // 一時的に自動追加(PR行/作品リンク/割引ブロック)を無効化中。(要望によりQ保存Q読込での手動運用に切替・両ch共通)
  // 再度有効化する場合は true に戻すだけでよい。
  var AUTO_APPEND_ENABLED = true; // 2026-07-13 Chami指定: 標準投稿形式(フック+PR行+短縮アフィ+セール行)を再有効化
  function composePostText() {
    // 貼り付け済みの古い完成形(PR行/セール行+旧URL)を剥がしてから組み直す＝二重化しない。
    var caption = stripAutoBlocks_(els.text.value);
    if (!AUTO_APPEND_ENABLED) return caption;
    caption = applyHookCta_(caption); // ★フックの深掘り＋CTA行(X案2・Chami承認2026-07-21)。PR行/リンクを付ける前に差し込む。
    var link = resolveAffLink();
    var PH = (window.BlueskyCore && window.BlueskyCore.WORK_LINK_PLACEHOLDER) || '紹介用短縮リンク';
    var out;
    if (caption.indexOf(PH) >= 0) {
      // ★プレースホルダ方式(2026-07-23 Chami指定): テンプレ帳の本文自体にPR行+プレースホルダが
      //   既に書かれている。旧来の「PR行の直下に自動でリンクを足す」処理はしない(足すと二重になる)。
      //   プレースホルダを実際の短縮リンクへ機械的に置換するだけでよい。
      var short = link ? cachedWorkShortLink_() : '';
      out = (window.BlueskyCore && window.BlueskyCore.fillWorkLinkPlaceholder)
        ? window.BlueskyCore.fillWorkLinkPlaceholder(caption, short, link)
        : caption;
      // 未キャッシュなら取得だけ開始し、出来次第プレビュー/モーダル/X欄へ反映。
      //   (投稿直前は既存の安全網measureWorkLink_が生リンクを検出して最終的に短縮するため、
      //   ここで取得が間に合わなくても実際に投稿される文には生リンクが残るだけで壊れない)
      if (link && !short) ensureWorkShortLink_(function () { renderPreview(); if (els.pcModal && !els.pcModal.hidden) recomposePcText_(); }); // X欄はgo5-work-short-readyイベントで自律的に追従する
    } else {
      // 本文に手動で作品URL/割引リンクを含めて書いた場合(例：しばらく手動投稿する場合)に、
      // 自動追加分と重複しないよう、既に本文へ含まれていればスキップする。
      // ★URLはPR行の「すぐ下の行」に置く(改行1つ)。PR行との間を空けるとURLが遠く見える/常に下段に
      //   見える不具合の元だった(Chami指定の完成形＝案内テンプレ文の直下に対応URL・2026-07-20)。
      out = (link && caption.indexOf(link) < 0) ? (caption + '\n\n' + PR_LINE_() + '\n' + link) : caption;
    }
    // 🔥割引一覧。(ON中は常に「案内する作品URL」より後ろに付く＝ここで最後に追加するだけで済む)
    if (discountListOn_()) {
      var dlink = cachedDiscountLink_();
      if (dlink) { if (caption.indexOf(dlink) < 0) out += '\n\n' + DISCOUNT_LEAD_() + '\n' + dlink; }
      else ensureDiscountLink_(function () { renderPreview(); if (els.pcModal && !els.pcModal.hidden) recomposePcText_(); }); // 未キャッシュなら取得だけ開始し、出来次第プレビュー/モーダルへ反映
    }
    return out;
  }
  try { window.__go5ComposePostText = composePostText; } catch (e) {} // 検証用フック(プレビューとの一致確認)

  // ---- アバター(実アカウントのアイコンを公開APIで取得) ----
  var avatarFor = null, avatarUrl = null, displayNameVal = null;
  function setAvatar(url) {
    if (!els.pvAvatar || !els.pvAvFallback) return;
    if (url) { els.pvAvatar.src = url; els.pvAvatar.hidden = false; els.pvAvFallback.style.display = 'none'; }
    else { els.pvAvatar.hidden = true; els.pvAvatar.removeAttribute('src'); els.pvAvFallback.style.display = ''; }
  }
  // ハンドル上の表示名＝Blueskyの displayName(取得できなければハンドル先頭／未設定なら「あなた」)
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

  // ---- プレビュー画像(単独=選択画像／無ければ動画の元写真／無ければ自動添付の注記) ----
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

  // ---- プレビュー描画(＝投稿される見た目) ----
  function renderPreview() {
    // ★composePostTextと同じ前処理を通す。(ここがズレると「プレビューと実際の投稿が違う」の原因になる)
    var caption = stripAutoBlocks_(els.text.value);
    if (AUTO_APPEND_ENABLED) caption = applyHookCta_(caption); // フックの深掘り＋CTA行(X案2・Chami承認2026-07-21)
    var link = resolveAffLink();
    var PH = (window.BlueskyCore && window.BlueskyCore.WORK_LINK_PLACEHOLDER) || '紹介用短縮リンク';
    var short = link ? cachedWorkShortLink_() : '';
    var PENDING = '(短縮リンク取得中…)';
    var hasPlaceholder = caption.indexOf(PH) >= 0;
    var hasRawLinkInCaption = !!(link && caption.indexOf(link) >= 0);
    var needFetch = false;
    // ★プレビューには生の長いリンクを一切出さない(Chami指定2026-07-23)。短縮できていれば短縮版、
    //   まだなら「取得中」の目印だけを見せる(生リンクの一瞬表示すら避ける)。実際に投稿される文の
    //   組み立ては composePostText 側にある(こちらは表示専用の派生ロジック)。
    var dispCaption = caption;
    if (hasPlaceholder) {
      if (short) dispCaption = dispCaption.split(PH).join(short);
      else { dispCaption = dispCaption.split(PH).join(PENDING); needFetch = true; }
    } else if (link && !hasRawLinkInCaption) {
      if (short) dispCaption += '\n\n' + PR_LINE_() + '\n' + short;
      else { dispCaption += '\n\n' + PR_LINE_() + '\n' + PENDING; needFetch = true; }
    } else if (hasRawLinkInCaption) {
      if (short) dispCaption = dispCaption.split(link).join(short);
      else { dispCaption = dispCaption.split(link).join(PENDING); needFetch = true; }
    }
    if (needFetch) ensureWorkShortLink_(function () { renderPreview(); if (els.pcModal && !els.pcModal.hidden) recomposePcText_(); });

    var html = dispCaption ? highlightLinks(escapeHtml(dispCaption)) : '<span class="ph">(本文)</span>';
    if (AUTO_APPEND_ENABLED && !link) html += '\n\n<span class="ph">(投稿時にアフィリンクを自動で追加します)</span>';
    // 🔥割引一覧(composePostTextと同じ位置＝作品URLより後ろ)をプレビューにも反映。同じ理由で重複防止。
    if (AUTO_APPEND_ENABLED && discountListOn_()) {
      var dlink = cachedDiscountLink_();
      if (dlink) { if (dispCaption.indexOf(dlink) < 0) html += '\n\n' + escapeHtml(DISCOUNT_LEAD_()) + '\n<span class="lnk">' + escapeHtml(dlink) + '</span>'; }
      else html += '\n\n<span class="ph">(🔥割引一覧リンクを準備中…)</span>';
    }
    if (els.pvBody) els.pvBody.innerHTML = html;

    if (els.count) { var n = countGraphemes(composePostText()); els.count.textContent = n + ' / 300'; els.count.classList.toggle('over', n > 300); }

    var h = (els.handle.value || '').trim().replace(/^@/, '');
    if (els.pvHandle) els.pvHandle.textContent = h ? ('@' + h) : '@(ハンドル未設定)';
    ensureAvatar(h); // 表示名(displayName)とアバターを設定(pvName はここで反映)

    var f = selectedPostFile || photoFile();
    if (f) showPreviewImage(f); else hidePreviewImage();
  }

  // 動画作成タブの写真選択にも追従(自動投稿の画像プレビュー反映)
  (function () { var p = $('photo'); if (p) p.addEventListener('change', function () { renderPreview(); }); })();

  // ---- 単独投稿の画像選択 ----
  if (els.postImg) {
    els.postImg.addEventListener('change', function () {
      var f = els.postImg.files[0]; if (!f) return;
      selectedPostFile = f;
      if (els.postImgName) els.postImgName.textContent = anonFileLabel_(f);
      if (els.postImgClear) els.postImgClear.style.display = '';
      if (els.postImgPreview) { els.postImgPreview.src = URL.createObjectURL(f); els.postImgPreview.style.display = ''; }
      renderPreview();
    });
  }
  if (els.postImgClear) {
    els.postImgClear.addEventListener('click', function () {
      if (els.postImgPreview && els.postImgPreview.src) { URL.revokeObjectURL(els.postImgPreview.src); els.postImgPreview.src = ''; els.postImgPreview.style.display = 'none'; }
      selectedPostFile = null; if (els.postImg) els.postImg.value = '';
      if (els.postImgName) els.postImgName.textContent = '未選択';
      els.postImgClear.style.display = 'none'; renderPreview();
    });
  }

  // ---- 確認モーダルの画像選択(動画フロー専用・selectedPostFile とは独立) ----
  if (els.pcImg) {
    els.pcImg.addEventListener('change', function () {
      var f = els.pcImg.files[0]; if (!f) return;
      pcSelectedFile = f;
      if (els.pcImgName) els.pcImgName.textContent = anonFileLabel_(f);
      if (els.pcImgClear) els.pcImgClear.style.display = '';
      if (els.pcImgPreview) { els.pcImgPreview.src = URL.createObjectURL(f); els.pcImgPreview.style.display = ''; }
    });
  }
  if (els.pcImgClear) {
    els.pcImgClear.addEventListener('click', function () {
      if (els.pcImgPreview && els.pcImgPreview.src) { URL.revokeObjectURL(els.pcImgPreview.src); els.pcImgPreview.src = ''; els.pcImgPreview.style.display = 'none'; }
      pcSelectedFile = null; if (els.pcImg) els.pcImg.value = '';
      if (els.pcImgName) els.pcImgName.textContent = '未選択(動画の元写真を添付)';
      els.pcImgClear.style.display = 'none';
    });
  }

  // ---- 画像圧縮(Bluesky blob 上限 ≈ 976KB) ----
  var MAX_BYTES = 950000;
  function toBlob(c, q) { return new Promise(function (r) { c.toBlob(r, 'image/jpeg', q); }); }
  // 選択画像の「表示名」を実ファイル名の代わりにランダムな英数字にする(実際のアップロードは
  //   バイナリのみ・Bluesky uploadBlob はファイル名を一切送らないため無関係。あくまで画面表示上、
  //   動画/候補のタイトルに由来する元ファイル名が見えてしまうのを防ぐための表示専用の匿名化)。
  function anonFileLabel_(file) {
    var ext = (file && file.name && /\.[0-9a-z]{1,5}$/i.test(file.name)) ? file.name.slice(file.name.lastIndexOf('.')) : '.jpg';
    var chars = 'abcdefghijklmnopqrstuvwxyz0123456789', s = '';
    for (var i = 0; i < 10; i++) s += chars.charAt(Math.floor(Math.random() * chars.length));
    return s + ext;
  }
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
  var PLACEHOLDER_URL = '(投稿するとここに短縮URLが入ります)';
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
    // 1行目が「短縮URLプレースホルダ」or 前回URL or URL なら置換。それ以外(例：↑案内文)は上に差し込む。
    if (f === PLACEHOLDER_URL || f === prevShortUrl || /^https?:\/\//.test(f) || /短縮URL/.test(f)) lines[0] = url;
    else lines.unshift(url);
    els.ytDesc.value = lines.join('\n'); saveA('yt_desc', els.ytDesc.value);
  }
  function setShareOutputs(shortUrl, fallbackUrl) {
    var url = shortUrl || fallbackUrl || '';
    if (els.shortUrlOut) els.shortUrlOut.textContent = url || '(短縮URLを取得できませんでした)';
    if (url) { putUrlTop(url); prevShortUrl = url; lastShortUrl = url; }
  }
  // ★前作の短縮リンクを説明欄に残さない(INC-70)：新しい動画を作ったら、1行目の短縮リンク行をプレースホルダに戻す。
  //   この作品を Bluesky に投稿すると shortenAndShow→putUrlTop が今回の短縮URLへ置換する。
  //   これをしないと、候補から別作品を作った直後にYT説明欄をコピーすると「前作のBluesky投稿」への案内が混入する。
  function resetYtDescShortLink_() {
    prevShortUrl = ''; lastShortUrl = '';
    if (els.shortUrlOut) els.shortUrlOut.textContent = PLACEHOLDER_URL;
    if (!els.ytDesc) return;
    var lines = els.ytDesc.value.split('\n'); if (!lines.length) return;
    var f = (lines[0] || '').trim();
    // 1行目が短縮URL(前作リンク)/プレースホルダ/「短縮URL」表記ならプレースホルダへ戻す(案内文などはそのまま)
    if (/^https?:\/\//.test(f) || f === PLACEHOLDER_URL || /短縮URL/.test(f)) {
      lines[0] = PLACEHOLDER_URL;
      els.ytDesc.value = lines.join('\n'); saveA('yt_desc', els.ytDesc.value);
    }
  }

  // ---- GAS 記録(共有シークレットは廃止) ----
  // workUrl(cid)に対応するFANZA取得済み情報(movieInfoCacheのキャッシュ)を返す。無ければ null。
  function fanzaInfoForWorkUrl_(url) {
    if (!url || !window.buildAffiliateLink) return null;
    var r = window.buildAffiliateLink(url, '');
    var cid = (r && r.ok) ? r.cid : '';
    return (cid && movieInfoCache[cid] && movieInfoCache[cid].title) ? movieInfoCache[cid] : null;
  }
  // drafts.js(下書きの作品名/作者表示)などから参照できるよう公開。(読み取りのみ)
  try { window.Go5WorkInfo = function (url) { return fanzaInfoForWorkUrl_(url); }; } catch (e) {}
  // ---- 投稿メタの「凍結」：予約時・即時投稿時に今のUIから採取し、以後の記録はこれだけを使う ----
  // これにより「記録する瞬間に別アカウントのタブを開いていた」等でUI状態が混ざる事故を無くす。
  function captureWorkUrl_() {
    var workUrl = '';
    try {
      workUrl = ((els.workUrl && els.workUrl.value) || '').trim() || loadA('bsky_work_url') || '';
      if (!workUrl) {
        var afEl = document.getElementById('affiUrls');
        var afRaw = afEl ? afEl.value : (localStorage.getItem('field_affiUrls') || '');
        workUrl = (afRaw || '').trim().split('\n').map(function (l) { return l.trim(); }).filter(Boolean)[0] || '';
      }
    } catch (e) {}
    return workUrl;
  }
  function fanzaSnapForWorkUrl_(workUrl) {
    try {
      var fc = (JSON.parse(localStorage.getItem('fanza_title_cache') || '{}') || {})[workUrl];
      if (fc && fc.priceInfo && fc.priceInfo.price != null) {
        return { price: fc.priceInfo.price, listPrice: fc.priceInfo.listPrice, discountPct: fc.priceInfo.discountPct || 0, at: new Date().toISOString() };
      }
    } catch (e) {}
    return null;
  }
  // 戦略ラベル(raw/戦略_画像選びとコメント.md §4): 狙い(成約/集客)とコメント型。(①〜⑧)
  // 動画ごとのラベルなので投稿後に未設定へ戻す。(前作の値が残ると分析を汚す)
  function readGoal() { var el = $('movieGoal'); return el ? (el.value || '') : ''; }
  function readCmtType() { var el = $('movieCmtType'); return el ? (el.value || '') : ''; }
  function captureMeta_() {
    var workUrl = captureWorkUrl_();
    return {
      videoId: currentVideoId || '',
      workUrl: workUrl,
      attrs: readMovieAttrs(),
      workState: readWorkState(),
      rebuild: readRebuild(),
      rebuildOf: readRebuildTarget(),              // リビルド対象として選んだ投稿履歴のvideoId
      goal: readGoal(),                            // 狙い(成約/集客)
      cmtType: readCmtType(),                      // コメント型(①〜⑧)
      fanzaSnap: fanzaSnapForWorkUrl_(workUrl),   // 履歴カード用(当時価格)
      fanzaInfo: fanzaInfoForWorkUrl_(workUrl) || null  // シート記録用(価格/レビュー)
    };
  }
  // 履歴アイテムから meta を復元。(過去データのアカウント矯正で使う)
  function metaFromHistItem_(it) {
    var attrs = {}; MOVIE_ATTRS.forEach(function (p) { attrs[p[0]] = !!it[p[0]]; });
    return { videoId: it.videoId || '', workUrl: it.workUrl || '', attrs: attrs, workState: it.workState || '', rebuild: !!it.rebuild, rebuildOf: it.rebuildOf || '', goal: it.goal || '', cmtType: it.cmtType || '', fanzaSnap: it.fanzaSnap || null, fanzaInfo: null };
  }

  // record.account でチャンネルを決め、record.meta(凍結済み)優先で記録する。
  // meta が無い旧経路のみ、記録先が現在UIと同じ時に限りUI状態を読む。(他アカウントの混入を防ぐ)
  function recordToSheet(record) {
    var gasUrl = (els.gasUrl.value || '').trim(); if (!gasUrl) return Promise.resolve(null);
    var account = record.account || acctId();
    var meta = record.meta || null;
    var uiSame = (account === acctId());
    var vid = record.videoId || (meta ? meta.videoId : '') || (uiSame ? currentVideoId : '') || '';
    var isTest = (window.IdGen && window.IdGen.isTestId) ? window.IdGen.isTestId(vid) : /^test-/.test(vid);
    var workUrl = record.workUrl || (meta ? meta.workUrl : '') || (uiSame ? captureWorkUrl_() : '');
    var attrs = meta ? meta.attrs : (uiSame ? readMovieAttrs() : {});
    var workState = record.workState || (meta ? meta.workState : (uiSame ? readWorkState() : ''));
    var rebuild = (record.rebuild != null) ? record.rebuild : (meta ? meta.rebuild : (uiSame ? readRebuild() : false));
    var rebuildOf = (record.rebuildOf != null) ? record.rebuildOf : (meta ? meta.rebuildOf : (uiSame ? readRebuildTarget() : ''));
    var payload = {
      op: 'upsert', testMode: isTest, status: '公開済',
      channel: account,                                   // ★所属アカウント＝post_uriのDIDで確定した正しいチャンネル
      title: record.title || '', postUrl: record.postUrl || '', affiliateUrl: record.affiliate || '',
      workUrl: workUrl, hashtags: record.hashtags || '', postUri: record.postUri || '',
      shortUrl: record.shortUrl || '', shareUrl: record.shareUrl || '', videoId: vid
    };
    if (record.postedAt) payload.postedAt = record.postedAt; // 過去データ矯正時は当時の投稿時刻を保持
    MOVIE_ATTRS.forEach(function (p) { payload[p[0]] = !!attrs[p[0]]; });
    payload.workState = workState;
    payload.rebuild = rebuild;
    if (rebuildOf) payload.rebuildOf = rebuildOf;
    // 狙い×コメント型(あるときだけ送る＝旧GASは未知フィールドを無視するので後方互換)
    var goal = record.goal || (meta ? meta.goal : (uiSame ? readGoal() : ''));
    var cmtType = record.cmtType || (meta ? meta.cmtType : (uiSame ? readCmtType() : ''));
    if (goal) payload.goal = goal;
    if (cmtType) payload.cmtType = cmtType;
    var mi = meta ? meta.fanzaInfo : (uiSame ? fanzaInfoForWorkUrl_(workUrl) : null);
    if (mi) {
      payload.fanza_list_price = mi.listPrice;
      payload.fanza_price = mi.price;
      payload.fanza_discount_pct = mi.discountPct;
      payload.fanza_fetched_at = mi.fetchedAt;
      payload.fanza_review_count = mi.reviewCount;
      payload.fanza_review_avg = mi.reviewAvg;
    }
    return fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) }).then(function (r) { return r.json(); }).catch(function () { return null; });
  }
  function updateGasStatus() {
    if (!els.gasStatus) return;
    var on = !!(els.gasUrl.value || '').trim();
    els.gasStatus.textContent = on ? '記録：ON(すべての投稿をこのGASに記録します)' : '記録：OFF(URL未設定。記録・検証するには設定してください)';
    els.gasStatus.className = 'gas-status ' + (on ? 'on' : 'off');
  }

  // 投稿成功通知(integration.js が書き戻し＋下のリスナが必ず記録)
  // account/meta＝投稿を実行した瞬間のアカウントと凍結メタ。(即時投稿は呼び出し時に確定)
  function notifyPosted(res, text, alt, account, meta, workShort) {
    var tags = (String(text).match(/#[^\s#]+/g) || []).join(' ');
    try { document.dispatchEvent(new CustomEvent('bluesky-posted', { detail: { post_uri: res.uri || '', post_url: res.postUrl || '', affiliate: firstUrl(text), hashtags: tags, posted_at: new Date().toISOString(), title: alt || (String(text).split('\n')[0] || ''), account: account || acctId(), meta: meta || null, work_short_url: (workShort && workShort.shortUrl) || '', work_share_url: (workShort && workShort.shareUrl) || '' } })); } catch (e) {}
  }
  // すべての投稿を一元的に記録(即時・自動・予約のどれでも必ず記録される)
  document.addEventListener('bluesky-posted', function (e) {
    var d = (e && e.detail) || {};
    var meta = d.meta || null;
    // 所属アカウントの確定：まずハンドル解決でDID台帳を権威に整えてから、post_uriのDIDで矯正する。(T4)
    //   旧実装は「台帳が空なら学習」で誤DIDを永続学習し得た。(learn-poisoning)学習を廃し、
    //   『両アカウントのDIDが解決済み・相異』の時だけDIDを権威にする＝汚染台帳での逆流ラベリングを防ぐ。
    ensureAcctDids_(function () {
      var account = d.account || acctId();
      var did = didFromUri_(d.post_uri);
      if (did) {
        var d1 = acctDid_('acc1'), d2 = acctDid_('acc2');
        var byDid = (d1 && d2 && d1 !== d2) ? acctOfDid_(did) : '';
        if (byDid && byDid !== account) account = byDid;   // UIの取り違えをDIDで矯正(台帳が健全な時だけ)
      }
      var uiSame = (account === acctId());
      var vid = (meta && meta.videoId) || (uiSame ? currentVideoId : '') || '';
      shortenAndShow(d.post_url, d.post_uri, d.title, function () {
      }, account, meta, (d.work_short_url ? { shortUrl: d.work_short_url, shareUrl: d.work_share_url || d.work_short_url } : null));
    });
  });

  // ---- 過去データのアカウント矯正(DID照合)：short_hist と シート行を正しいアカウントへ移す ----
  // post_uri の DID は「実際に投稿したアカウント」の確定情報。これで誤って別アカウントに入った
  // 履歴/シート行を正しい側へ移す。以後の投稿はDID検証(bluesky-posted)で常に正しく記録される。
  var _acctRepairBusy = false;
  function repairAccountsByDid_(cb) {
    if (_acctRepairBusy) { if (cb) cb({ ok: false, reason: 'busy' }); return; }
    _acctRepairBusy = true;
    ensureAcctDids_(function () {
      var d1 = acctDid_('acc1'), d2 = acctDid_('acc2');
      if (!d1 || !d2) { _acctRepairBusy = false; if (cb) cb({ ok: false, reason: 'DID未解決(両アカウントの⚙ハンドル設定が必要)' }); return; }
      var moved = [];
      ['acc1', 'acc2'].forEach(function (a) {
        var arr = histLoadFor_(a), keep = [];
        arr.forEach(function (it) {
          var correct = acctOfDid_(didFromUri_(it.postUri));
          if (correct && correct !== a) moved.push({ item: it, from: a, to: correct });
          else keep.push(it);
        });
        if (keep.length !== arr.length) histSaveFor_(a, keep);
      });
      moved.forEach(function (mv) {
        var arr = histLoadFor_(mv.to).filter(function (x) { return mv.item.postUri ? x.postUri !== mv.item.postUri : x.shortUrl !== mv.item.shortUrl; });
        arr.unshift(mv.item); histSaveFor_(mv.to, arr);
        // D4: YouTube URLマップ(verify_yt)も一緒に移す。移し忘れると移動先で再生数/投稿日時/題名が出ない
        //   。(検証タブは verify_yt__<acc>[itemKey] からYT URLを引くため)itemKey は 'u:'+postUri / 's:'+shortUrl。
        try {
          var mk = mv.item.postUri ? ('u:' + mv.item.postUri) : ('s:' + (mv.item.shortUrl || ''));
          var fk = 'verify_yt__' + mv.from, tk = 'verify_yt__' + mv.to;
          var fmap = JSON.parse(localStorage.getItem(fk) || '{}') || {};
          if (fmap[mk]) {
            var tmap = JSON.parse(localStorage.getItem(tk) || '{}') || {};
            tmap[mk] = fmap[mk]; delete fmap[mk];
            localStorage.setItem(fk, JSON.stringify(fmap));
            localStorage.setItem(tk, JSON.stringify(tmap));
          }
        } catch (e) {}
      });
      // シートも矯正：正チャンネルへ再upsert(当時の投稿日時を保持)＋誤チャンネルの行を削除。
      var gasUrl = (els.gasUrl.value || '').trim();
      if (gasUrl) {
        moved.forEach(function (mv) {
          var it = mv.item;
          recordToSheet({ account: mv.to, meta: metaFromHistItem_(it), title: it.title, postUrl: it.postUrl, postUri: it.postUri, videoId: it.videoId, shortUrl: it.shortUrl, shareUrl: it.shareUrl, workUrl: it.workUrl, workState: it.workState, rebuild: it.rebuild, postedAt: it.ts ? new Date(it.ts).toISOString() : '' });
          if (it.postUri) jsonpGet(gasUrl + '?action=delete&channel=' + encodeURIComponent(mv.from) + '&postUri=' + encodeURIComponent(it.postUri), function () {});
        });
      }
      _acctRepairBusy = false;
      if (cb) cb({ ok: true, moved: moved.length, toSheet: !!gasUrl });
    });
  }
  // 起動時に一度だけ自動矯正。(過去の取り違えを黙って直す)成功時のみフラグを立てる。
  function maybeRepairAccountsOnce_() {
    try { if (localStorage.getItem('acct_did_repair_v1') === '1') return; } catch (e) {}
    setTimeout(function () { repairAccountsByDid_(function (r) { if (r && r.ok) { try { localStorage.setItem('acct_did_repair_v1', '1'); } catch (e) {} } }); }, 4000);
  }
  // ハンドル→acctId。(⚙設定のハンドルと照合)postUrlのprofile部がハンドルの時に使う。
  function acctOfHandle_(h) {
    h = String(h || '').toLowerCase().replace(/^@/, ''); if (!h) return '';
    if (handleOfAcct_('acc1').toLowerCase() === h) return 'acc1';
    if (handleOfAcct_('acc2').toLowerCase() === h) return 'acc2';
    return '';
  }
  // bsky.app/profile/<did or handle>/post/… の profile 部を取り出す。
  function profileFromPostUrl_(u) { var m = String(u || '').match(/bsky\.app\/profile\/([^/?#]+)/i); return m ? m[1] : ''; }
  // 投稿の「確実な所属」を postUri(DID) → postUrlのprofile(DID/handle) で判定。分からなければ ''。
  function classifyByPost_(item) {
    if (!item) return '';
    var byDid = acctOfDid_(didFromUri_(item.postUri)); if (byDid) return byDid;
    var prof = profileFromPostUrl_(item.postUrl || item.shareUrl || '');
    if (prof) {
      if (/^did:/.test(prof)) { var d = acctOfDid_(prof); if (d) return d; }
      else { var h = acctOfHandle_(prof); if (h) return h; }
    }
    return '';
  }
  // DID台帳の妥当性を毎回検証。(force解決＋両DIDの相異＋表示名取得)分類・移動の前提ゲート。
  //   台帳が壊れている(片方未解決・同一DID)状態で分類すると全量誤移動になり得るため、必ずここを通す。
  function verifyLedger_(cb) {
    ensureAcctDids_(function () {
      var h1 = handleOfAcct_('acc1'), h2 = handleOfAcct_('acc2');
      var d1 = acctDid_('acc1'), d2 = acctDid_('acc2');
      var res = { h1: h1, h2: h2, d1: d1, d2: d2, dn1: '', dn2: '', ok: false, reason: '' };
      if (!h1 || !h2) { res.reason = '両アカウントのハンドルが未設定です(⚙で設定)'; cb(res); return; }
      if (!d1 || !d2) { res.reason = 'DID解決に失敗(ハンドルの綴り・通信を確認。メール形式は不可)'; cb(res); return; }
      if (d1 === d2) { res.reason = '両アカウントのハンドルが同一アカウントを指しています(⚙のハンドル設定を確認)'; cb(res); return; }
      // 表示名。(レポートでユーザーが取り違いを目視確認できるように)失敗しても続行。
      var pend = 2;
      function done() { if (--pend === 0) { res.ok = true; cb(res); } }
      [['dn1', h1], ['dn2', h2]].forEach(function (p) {
        fetch('https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=' + encodeURIComponent(p[1]))
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (j) { if (j && j.displayName) res[p[0]] = j.displayName; })
          .catch(function () {})
          .then(done);
      });
    }, true); // force=キャッシュ済み台帳を信じず毎回解決し直す
  }
  try {
    window.Go5AccountRepair = {
      run: repairAccountsByDid_, ensureDids: ensureAcctDids_,
      verifyLedger: verifyLedger_,               // 分類・移動の前提ゲート(force解決＋相異検証＋表示名)
      classifyByPost: classifyByPost_,           // DID/ハンドルで確定できる所属(yt-clicksの自動分類の土台)
      didReady: function () { return !!(acctDid_('acc1') && acctDid_('acc2') && acctDid_('acc1') !== acctDid_('acc2')); },
      ledgerFresh: function () { return _didsResolved; }, // このセッションでハンドル解決済み＝台帳を権威にしてよい(サニタイザが使用)
      sheetMove: null                            // (将来用フック)
    };
  } catch (e) {}
  // 自動修復は yt-clicks の多段分類(DID/ハンドル/YouTubeチャンネル)へ一本化したのでここでは呼ばない。
  //   (repairAccountsByDid_ は Go5AccountRepair.run として手動フォールバック用に残す)
  void maybeRepairAccountsOnce_;

  // 短縮URLの設定。一次＝自前 link-worker。(302即リダイレクト＋KVで開封数を計測)
  //   ・YT説明欄に貼る用途なのでURL長は問題にならない＝計測できる link-worker を最優先。
  //   ・WORKER_URL は go5-short の払い出しURL。SHARED_SECRET は Worker 側と同値。(公開可＝ソフト鍵)
  //   ・端末ごとに localStorage short_worker_url / short_shared_secret で上書き可。
  //   ・未設定/失敗時は da.gd→TinyURL→長いURL に安全フォールバック。(計測できないだけで壊れない)
  var SHORT = {
    // ★2026-07-20: 独自ドメインへ切替(da.gd外部依存の根絶・INC-108恒久策)。
    //   ★2026-07-20b: チャンネル別ドメイン。月詠み(acc1)=5mgl.com / 宵桜艶帖(acc2)=yoz2.com。
    //   どちらも同一r2 worker・同一KVのカスタムドメイン=計測は一括・記録はch別。既存
    //   r2.workers.devのコードも生存。E2E検証済(POST→<domain>/xxxxx・GET→302転送)。
    URL_BY_ACCT: { acc1: 'https://5mgl.com', acc2: 'https://yoz2.com' },
    WORKER_URL: 'https://5mgl.com',   // 既定(acct不明時fallback。stats/listは同一KVなのでどのドメインでも可)
    // 「これは自前の計測リンクか」判定に使う全ドメイン(旧r2も含める=既存リンク互換)
    WORKER_HOSTS: ['https://5mgl.com', 'https://yoz2.com', 'https://r2.trustsignalbot.workers.dev'],
    SHARED_SECRET: 'daremogamewoubawareteikukimihakanpekidekyukyokunoidol'
  };
  try {
    SHORT.SHARED_SECRET = localStorage.getItem('short_shared_secret') || SHORT.SHARED_SECRET;
  } catch (e) {}
  // 投稿用ベースURL: 端末上書き(short_worker_url)が最優先→現アカウント別→既定。
  function workerBase() {
    try { var ov = localStorage.getItem('short_worker_url'); if (ov) return ov; } catch (e) {}
    var acc = (typeof acctId === 'function') ? acctId() : 'acc1';
    return SHORT.URL_BY_ACCT[acc] || SHORT.WORKER_URL;
  }
  // 「そのURLは自前の短縮ドメインか?」一致したベースを返す(両ドメイン+旧r2+端末上書きに対応)。
  function ourShortBase(u) {
    u = String(u || '');
    var hosts = SHORT.WORKER_HOSTS.slice();
    try { var ov = localStorage.getItem('short_worker_url'); if (ov) hosts.push(ov); } catch (e) {}
    for (var i = 0; i < hosts.length; i++) {
      var b = hosts[i].replace(/\/+$/, '');
      if (b && u.indexOf(b + '/') === 0) return b;
    }
    return '';
  }
  // 検証タブ(yt-clicks.js)へ公開。WORKER_URL=stats/list用(KV共有)/ourBase=自前判定/base=現ch投稿用。
  try {
    window.Go5Short = { WORKER_URL: SHORT.WORKER_URL, WORKER_HOSTS: SHORT.WORKER_HOSTS,
                        SHARED_SECRET: SHORT.SHARED_SECRET, base: workerBase, ourBase: ourShortBase };
  } catch (e) {}
  // 「自分のクリックを計測から除外」：この端末(同ブラウザ)を対象外にする。worker が Cookie(go5nc) を立て、以後この端末の
  //   短縮URLアクセスは数えない。(アプリからのクリックも、Bluesky内蔵ブラウザからのクリックもCookie共有で除外＝iOS Safari)
  try {
    var _excBtn = document.getElementById('clickExcludeSelf');
    if (_excBtn) _excBtn.addEventListener('click', function () {
      var base = (workerBase() || '').replace(/\/+$/, '');  // 現チャンネルのドメインで自分を除外
      if (!base) { window.alert('短縮URLワーカーが未設定です'); return; }
      window.open(base + '/?nc=1', '_blank'); // トップレベル遷移で一次Cookieを確実にセット
      _excBtn.textContent = '✅ 除外しました(開いたページで確認)';
      setTimeout(function () { _excBtn.textContent = '🚫 自分のクリックを計測から除外(この端末)'; }, 4000);
    });
  } catch (e) {}
  function shortWorkerReady() {
    return /^https?:\/\//.test(workerBase()) && SHORT.SHARED_SECRET && SHORT.SHARED_SECRET.indexOf('PASTE_') !== 0;
  }
  function shortenViaWorker(longUrl) {
    if (!shortWorkerReady()) return Promise.resolve('');
    return fetch(workerBase().replace(/\/+$/, '') + '/api/shorten', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Shared-Secret': SHORT.SHARED_SECRET },
      body: 'url=' + encodeURIComponent(longUrl)
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { var s = (j && j.short) || ''; return /^https?:\/\//.test(s) ? s : ''; })
      .catch(function () { return ''; });
  }
  // 外部サービス短縮。(GET・テキスト返却)da.gd → TinyURL の順で保険に使う。
  //   ★6秒タイムアウト付き(2026-07-20 da.gd障害の教訓): da.gdが「拒否」でなく「無限タイムアウト」型で
  //   死ぬと(実測: 522/応答なし)、タイムアウト無しのfetchはブラウザ既定(数十秒〜)まで待ち、投稿UIが
  //   フリーズ同然になる。6秒で諦めて次のプロバイダ(TinyURL→r2)へ即フォールバックする。
  function shortenVia(api, longUrl) {
    var ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { try { ctl.abort(); } catch (e) {} }, 6000) : null;
    return fetch(api + encodeURIComponent(longUrl), ctl ? { signal: ctl.signal } : undefined)
      .then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (t) {
        if (timer) clearTimeout(timer);
        t = String(t || '').trim(); return /^https?:\/\//.test(t) ? t : '';
      })
      .catch(function () { if (timer) clearTimeout(timer); return ''; });
  }
  // 案A(da.gdチェーン)：true でr2短縮を da.gd でさらに短縮して“表示用の短いURL”にする。
  //   false にすると r2(=5mgl.com)URL をそのまま表示。(＝ワンフラグで即ロールバック)
  //   ★2026-07-20: 独自ドメイン5mgl.com化により表示URL自体が短い(5mgl.com/xxxxx≈14字)ため
  //   false に。da.gd/tinyurlは normal path から外れ、worker障害時の深いフォールバックにのみ残す。
  var USE_DAGD_CHAIN = false;
  // ── 表示用の短縮プロバイダ(da.gd代替策)──────────────────────────────
  //   上から順に試し、最初に成功した短縮URLを「共有URL」に採用する。
  //   ★da.gd が消えた/不調になったら、この配列を並べ替える or 差し替えるだけで置換できる。
  //   ブラウザからのCORS確認済み：da.gd(Access-Control-Allow-Origin:*)・tinyurl。(OK)
  //   予備候補(復活・CORS確認後に配列へ追加可)：is.gd '/create.php?format=simple&url=' / cleanuri 等。
  //   将来の本命：独自ドメインを r2 に Custom Domain 割当(docs/設計・調査 参照)＝この配列に依存しない。
  var SHARE_SHORTENERS = [
    function (u) { return shortenVia('https://da.gd/s?url=', u); },                    // 1) da.gd(最短・16字前後)
    function (u) { return shortenVia('https://tinyurl.com/api-create.php?url=', u); }  // 2) tinyurl(保険)
  ];
  function shortenShare(u) {
    var i = 0;
    function next() {
      if (i >= SHARE_SHORTENERS.length) return Promise.resolve('');
      var fn = SHARE_SHORTENERS[i++];
      return Promise.resolve().then(function () { return fn(u); })
        .then(function (s) { return /^https?:\/\//.test(s || '') ? s : next(); })
        .catch(function () { return next(); });
    }
    return next();
  }
  // 最終URL → { shortUrl(r2・計測用), shareUrl(短い共有・表示用) } を返す。
  //   r2成功時：shortUrl=r2、shareUrl=プロバイダで短縮したr2URL。計測は常にr2側で行う。
  //   全プロバイダ失敗時：shareUrl=r2。(長いが有効)r2失敗時：従来フォールバックで計測不可。(shortUrl=shareUrl)
  function makeShortAndShare(longUrl) {
    if (!longUrl) return Promise.resolve({ shortUrl: '', shareUrl: '' });
    return shortenViaWorker(longUrl).then(function (r2) {
      if (r2) {
        if (!USE_DAGD_CHAIN) return { shortUrl: r2, shareUrl: r2 };
        return shortenShare(r2).then(function (sh) { return { shortUrl: r2, shareUrl: (sh || r2) }; });
      }
      return shortenShare(longUrl).then(function (s) { var u = s || longUrl; return { shortUrl: u, shareUrl: u }; });
    });
  }
  // 後方互換：表示用(da.gd優先)の1本を返す薄いラッパ。(手動短縮などで使用)
  function shortenUrl(longUrl) {
    if (!longUrl) return Promise.resolve('');
    return makeShortAndShare(longUrl).then(function (r) { return r.shareUrl || r.shortUrl || ''; });
  }
  // 投稿履歴タブ(yt-clicks.js)から、過去投稿URLの計測用短縮リンク(r2+da.gd)を生成するために公開。
  try { window.Go5MakeShort = makeShortAndShare; } catch (e) {}

  // ---- 🔁 URL自動解決：af_id欠落/未短縮のどちらも自動で補い、最終的に「短縮済みアフィリンク」にする ----
  //   Chami依頼2026-07-20②。判定は affiliate-core.js の classifyPromoUrl/ensureAffiliateLink(純粋関数・
  //   tests/test_promo_url.js)。既に「短縮済み」なら判定だけでネットワークを叩かない(二重処理しない)。
  function shortHostList_() {
    // SHORT.WORKER_HOSTS は "https://xxx" 形式なので、ホスト名だけに変換して渡す。
    return SHORT.WORKER_HOSTS.map(function (h) { try { return new URL(h).hostname; } catch (e) { return ''; } }).filter(Boolean);
  }
  function resolvePromoUrl(rawUrl) {
    var url = (rawUrl || '').trim();
    if (!url) return Promise.resolve({ ok: false, error: 'empty' });
    if (!window.classifyPromoUrl || !window.ensureAffiliateLink) return Promise.resolve({ ok: false, error: 'module_missing' });
    var state = window.classifyPromoUrl(url, shortHostList_());
    if (state.isShortened) return Promise.resolve({ ok: true, link: url, changed: false }); // 既に短縮済み→そのまま
    var built = window.ensureAffiliateLink(url, curAfId_());
    if (!built.ok) return Promise.resolve({ ok: false, error: built.error });
    return makeShortAndShare(built.link).then(function (r) {
      var link = (r && (r.shareUrl || r.shortUrl)) || built.link;
      return { ok: true, link: link, changed: true };
    });
  }
  try { window.Go5ResolvePromoUrl = resolvePromoUrl; } catch (e) {}

  // ---- 導線2: 投稿本文の作品リンクを計測付き短縮へ置換 ----
  //   本文中の生のFANZA系リンク(al.fanza/dmm)を投稿直前に r2計測リンク(表示はda.gd)へ差し替える。
  //   手動運用の本文でも自動で効く。r2が取れない時は本文を変えず null。(安全側・投稿は止めない)
  //   これで「YT→投稿」(導線1=投稿URLの短縮・既存)と「投稿→FANZA」(導線2=本リンク)を別コードで計測できる。
  var WORK_LINK_RE = /https?:\/\/(?:al\.fanza\.co\.jp|www\.dmm\.co\.jp|book\.dmm\.co\.jp|book\.dmm\.com)\/[^\s]+/;
  function measureWorkLink_(text) {
    try {
      var m = String(text || '').match(WORK_LINK_RE);
      if (!m) return Promise.resolve({ text: text, workShort: null });
      var raw = m[0];
      return makeShortAndShare(raw).then(function (r) {
        // 自前ドメイン(5mgl.com/yoz2.com/旧r2)の計測URLが取れた時だけ置換
        //   (da.gd単独やフォールバック長URLでは置換しない=計測できない置換をしない)
        var ourOk = r && r.shortUrl && window.Go5Short && window.Go5Short.ourBase && window.Go5Short.ourBase(r.shortUrl);
        if (!ourOk) return { text: text, workShort: null };
        var disp = r.shareUrl || r.shortUrl;
        return { text: String(text).replace(raw, disp), workShort: { shortUrl: r.shortUrl, shareUrl: disp, original: raw } };
      }).catch(function () { return { text: text, workShort: null }; });
    } catch (e) { return Promise.resolve({ text: text, workShort: null }); }
  }
  try { window.__go5MeasureWork = measureWorkLink_; } catch (e) {} // 検証用フック

  function shortenAndShow(longUrl, postUri, title, onShort, account, meta, workShort) {
    if (!longUrl) return;
    if (els.shortUrlOut) els.shortUrlOut.textContent = '短縮URLを作成中…';
    makeShortAndShare(longUrl).then(function (res) {
      var short = res.shortUrl || '';                  // r2(計測用)
      var share = res.shareUrl || short || longUrl;    // da.gd(表示・概要欄・コピー用)
      // 表示・概要欄への反映は「今のUIと同じアカウントの投稿」のときだけ。(別アカウントの記録でUIを書き換えない)
      if (!account || account === acctId()) setShareOutputs(share, longUrl);
      histAdd({ account: account, meta: meta, title: title, shortUrl: short || share, shareUrl: share, postUrl: longUrl, postUri: postUri, videoId: (meta && meta.videoId) || (!account || account === acctId() ? currentVideoId : '') || '', workShortUrl: (workShort && workShort.shortUrl) || '', workShareUrl: (workShort && workShort.shareUrl) || '' });
      if (typeof onShort === 'function') onShort({ shortUrl: short, shareUrl: share });
    });
  }

  // JSONP(CORS回避)でGASから値を取得。<script>はCORS対象外なのでPOST応答が読めない環境でも確実。
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

  // ---- 過去の短縮URL履歴(端末内・アカウント別。GAS非依存で確実)----
  function histKeyFor_(a) { return 'short_hist__' + (a || acctId()); }
  // ★「中身が空」と「読めなかった(壊れている)」を区別する。区別しないと、パース失敗→[]→
  //   histAddが[新1件]で上書き保存＝**履歴全消し**が無言で起きる(そしてこの消え方は
  //   yt-clicks側の減少検知にも引っかからない)。読めない時は破損フラグを立てて保存を止める。
  // ★状態は関数経由で持つ。`var histBroken_ = {}` 形式だと、代入行より前に histLoadFor_ が
  //   呼ばれた場合(applyAccount→loadHistory が初期化より先に走る)に undefined へ代入して落ちる。
  //   関数宣言は巻き上げられるので、この形なら呼び出し順に依存しない。
  function histBrokenMap_() { return histBrokenMap_._ || (histBrokenMap_._ = {}); }
  function histBrokenSet_(k, v) { histBrokenMap_()[k] = v; }
  function histBrokenGet_(k) { return histBrokenMap_()[k] || null; }
  function histLoadFor_(a) {
    var k = histKeyFor_(a), raw = null;
    try { raw = localStorage.getItem(k); } catch (e) { histBrokenSet_(k, 'localStorage読み取り不可'); return []; }
    if (raw == null || raw === '') { histBrokenSet_(k, null); return []; }
    try {
      var v = JSON.parse(raw);
      if (!Array.isArray(v)) { histBrokenSet_(k, '配列ではない'); return []; }
      histBrokenSet_(k, null);
      return v;
    } catch (e) {
      histBrokenSet_(k, 'JSONが壊れている(' + raw.length + '文字)');
      try { console.warn('[go5 hist] 履歴が読めない。上書き保存を止めた:', k, histBrokenGet_(k)); } catch (e2) {}
      return [];
    }
  }
  // 指定アカウントで投稿済みの作品URL一覧。(候補タブの「投稿済み」判定用・重複投稿=P0-3の防止に使う)
  try { window.Go5PostedWorkUrls = function (a) { try { return histLoadFor_(a || acctId()).map(function (h) { return (h && h.workUrl) || ''; }).filter(Boolean); } catch (e) { return []; } }; } catch (e) {}
  // 指定アカウントの投稿履歴アイテム一覧。(候補タブの投稿詳細モーダル用＝いつ/何で投稿したか)
  //   投稿履歴タブの表示(yt-clicks allItems)と同じく「短縮URL履歴 + 手動追加分(verify_manual__)」を合成して返す。
  //   short_hist__ だけだと、手動で追加した投稿が『履歴には見えるのに投稿済みpillが光らない』事故になる。(INC-71追補)
  try { window.Go5PostedItems = function (a) {
    var acc = a || acctId(), out = [];
    try { out = histLoadFor_(acc) || []; } catch (e) { out = []; }
    try { var man = JSON.parse(localStorage.getItem('verify_manual__' + acc) || '[]'); if (man && man.length) out = out.concat(man); } catch (e) {}
    return out;
  }; } catch (e) {}
  // ★保存の前に2つ確かめる。①破損中のキーへは書かない(壊れた読み取り結果で上書き＝全消しを防ぐ)
  //   ②件数が減るなら証拠を残す。yt-clicks.js の recordLoss_ は「saveArr/saveArrFor_ が唯一の出口」を
  //   前提にしていたが、この関数が第3の出口として素通りしていた＝罠が犯人を捕れなかった理由(INC-112)。
  function histSaveFor_(a, arr) {
    var k = histKeyFor_(a);
    if (histBrokenGet_(k)) { try { console.warn('[go5 hist] 破損中のため保存を中止:', k, histBrokenGet_(k)); } catch (e) {} return; }
    try {
      var before = histLoadFor_(a);
      if (before.length && Array.isArray(arr) && arr.length < before.length) {
        try { window.Go5HistLoss && window.Go5HistLoss.record(k, before, arr); } catch (e) {}
      }
    } catch (e) {}
    try { localStorage.setItem(k, JSON.stringify(arr.slice(0, 200))); } catch (e) {
      try { console.warn('[go5 hist] 履歴の保存に失敗(容量超過の可能性):', k); } catch (e2) {}
    }
  }
  function histKey() { return histKeyFor_(acctId()); }
  function histLoad() { return histLoadFor_(acctId()); }
  function histSaveArr(a) { histSaveFor_(acctId(), a); }
  try { window.BlueskyPostHistory = { loadFor: histLoadFor_, saveFor: histSaveFor_, load: histLoad, saveArr: histSaveArr }; } catch (e) {}
  // rec.account＝所属アカウント。(未指定は現在UI)rec.meta＝凍結済み投稿メタ。(あれば優先)
  function histAdd(rec) {
    if (!rec || !rec.shortUrl) return; // 短縮URLが取れた投稿だけ記録
    var account = rec.account || acctId();
    var meta = rec.meta || null;
    var uiSame = (account === acctId());
    // 作品URL：metaがあればそれ、無ければ(現在UIと同じ時だけ)UIから採取。
    var workUrl = meta ? meta.workUrl : (uiSame ? captureWorkUrl_() : '');
    var a = histLoadFor_(account).filter(function (x) { return rec.postUri ? x.postUri !== rec.postUri : x.shortUrl !== rec.shortUrl; }); // 同一投稿の重複を排除
    var entry = { ts: rec.ts || new Date().getTime(), account: account, title: rec.title || '', shortUrl: rec.shortUrl, shareUrl: rec.shareUrl || '', postUrl: rec.postUrl || '', postUri: rec.postUri || '', videoId: rec.videoId || (meta ? meta.videoId : '') || '', confirmed: false };
    if (rec.rebuildBaseClicks != null) entry.rebuildBaseClicks = rec.rebuildBaseClicks; // リビルド前の動画までのクリック数(投稿履歴の括弧表示用)
    if (rec.workShortUrl) { entry.workShortUrl = rec.workShortUrl; entry.workShareUrl = rec.workShareUrl || ''; } // 導線2(投稿→FANZA)の計測リンク
    if (workUrl) {
      entry.workUrl = workUrl;
      // 作品cidも串刺しで保存。(候補タブの「投稿済み」判定を確実にする)workUrlはアフィリンク付き/
      //   計測パラメータ付きでも来るので、候補側と同じ normalizeWorkUrl→buildAffiliateLink で正規化して求める。
      try {
        if (window.buildAffiliateLink) {
          var nu = window.normalizeWorkUrl ? window.normalizeWorkUrl(workUrl) : workUrl;
          var cr = nu ? window.buildAffiliateLink(nu, '') : null;
          if (cr && cr.ok && cr.cid) entry.cid = cr.cid;
        }
      } catch (e) {}
      // 投稿時のFANZA価格スナップショット。(当時価格)metaがあればそれを、無ければUIキャッシュから。
      var snap = meta ? meta.fanzaSnap : (uiSame ? fanzaSnapForWorkUrl_(workUrl) : null);
      if (snap) entry.fanzaSnap = snap;
    }
    // 動画作成タブのカテゴリ属性・作品状態を引き継ぐ(manualOnly=手動短縮のときは付けない)
    if (!rec.manualOnly) {
      var attrs = meta ? meta.attrs : (uiSame ? readMovieAttrs() : {});
      MOVIE_ATTRS.forEach(function (p) { if (attrs[p[0]]) entry[p[0]] = true; });
      entry.workState = meta ? meta.workState : (uiSame ? readWorkState() : '旧作'); // 投稿時の作品状態
      var rb = meta ? meta.rebuild : (uiSame ? readRebuild() : false); if (rb) entry.rebuild = true;
      var rbOf = meta ? meta.rebuildOf : (uiSame ? readRebuildTarget() : ''); if (rb && rbOf) entry.rebuildOf = rbOf;
      var gl = meta ? meta.goal : (uiSame ? readGoal() : ''); if (gl) entry.goal = gl;               // 狙い(成約/集客)
      var ct = meta ? meta.cmtType : (uiSame ? readCmtType() : ''); if (ct) entry.cmtType = ct;      // コメント型(①〜⑧)
      if (uiSame) {
        var rbEl = $('movieRebuild'); if (rbEl) rbEl.checked = false; // UIと同じ時だけ一度きりフラグをOFF
        var rbRow = $('movieRebuildTargetRow'), rbSel = $('movieRebuildTarget');
        if (rbSel) rbSel.value = ''; if (rbRow) rbRow.hidden = true;
        // 狙い/コメント型は動画ごとのラベル＝前作の値が残ると分析を汚すため未設定へ戻す(field_も消す)
        var gEl = $('movieGoal'); if (gEl) gEl.value = '';
        var ctEl = $('movieCmtType'); if (ctEl) ctEl.value = '';
        try { localStorage.removeItem('field_movieGoal'); localStorage.removeItem('field_movieCmtType'); } catch (e) {}
      }
    }
    a.unshift(entry);
    histSaveFor_(account, a);
    if (uiSame && els.histList) renderHistory(a); // 現在UIの履歴だけ即描画(他アカウントは切替時に反映)
    // リビルド対象を選んでいたら、その投稿履歴に「被リビルド」の印を自動で付ける。
    //   ★上のhistSaveFor_の後に呼ぶこと＝先に呼ぶと、その変更が上書き保存(a=更新前のスナップショット)で消える。
    if (!rec.manualOnly && rb && rbOf) { try { window.Go5History && window.Go5History.markRebuilt(rbOf, account); } catch (e) {} }
  }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  function loadHistory() { if (els.histList) renderHistory(histLoad()); }
  // 履歴アイテムの同一性キー。(破棄/採用フラグの付け外しに使う)postUri 優先、無ければ shortUrl。
  function histKeyOf(it) { return it && it.postUri ? 'u:' + it.postUri : 's:' + (it && it.shortUrl || ''); }
  function histMatch(it, uri, short) { return uri ? it.postUri === uri : it.shortUrl === short; }
  // 重複(同題名が2件以上)の判定マップを作る。破棄済みは除いて数える＝採用候補の重複だけ目立たせる。
  function dupTitleSet(items) {
    var cnt = {}, dup = {};
    items.forEach(function (it) { if (it.discarded) return; var t = (it.title || '').trim(); if (!t) return; cnt[t] = (cnt[t] || 0) + 1; });
    Object.keys(cnt).forEach(function (t) { if (cnt[t] >= 2) dup[t] = true; });
    return dup;
  }
  function renderHistory(items) {
    if (!els.histList) return;
    var showDiscarded = !!(els.histShowDiscarded && els.histShowDiscarded.checked);
    var dup = dupTitleSet(items);
    var view = items.filter(function (it) { return showDiscarded || !it.discarded; });
    if (!items.length) { els.histList.innerHTML = '<p class="hint">このアカウントの履歴はまだありません。(投稿して短縮URLが出ると、ここに自動で貯まります)</p>'; return; }
    if (!view.length) { els.histList.innerHTML = '<p class="hint">表示できる履歴がありません。(すべて破棄済み)「🗂 破棄も表示」で確認できます。</p>'; return; }
    els.histList.innerHTML = view.map(function (it) {
      var short = it.shareUrl || it.shortUrl || ''; // コピー・概要欄へは短い共有URL(da.gd)を優先
      var t = (it.title || '').trim();
      var badges = (it.adopted ? '<span class="hist-badge adopt">⭐本採用</span>' : '') +
        (dup[t] ? '<span class="hist-badge dup">重複</span>' : '') +
        (it.discarded ? '<span class="hist-badge discarded">破棄</span>' : '');
      var d = 'data-uri="' + escapeHtml(it.postUri || '') + '" data-short="' + escapeHtml(short) + '" data-title="' + escapeHtml(it.title || '') + '"';
      return '<div class="hist-row' + (it.discarded ? ' is-discarded' : '') + '">' +
        '<div class="hist-meta">' + escapeHtml(fmtTs(it.ts)) + '　' + escapeHtml(it.title || '(無題)') + ' ' + badges + '</div>' +
        '<div class="hist-act">' +
        '<code class="hist-url">' + escapeHtml(short) + '</code>' +
        '<button class="copy-btn hist-copy" type="button" data-url="' + escapeHtml(short) + '">コピー</button>' +
        '<button class="ghost hist-ins" type="button" data-url="' + escapeHtml(short) + '">概要欄へ</button>' +
        (it.postUrl ? '<a class="ghost" href="' + escapeHtml(it.postUrl) + '" target="_blank" rel="noopener">投稿↗</a>' : '') +
        '<button class="ghost hist-adopt" type="button" ' + d + '>' + (it.adopted ? '⭐解除' : '⭐本採用') + '</button>' +
        (it.discarded
          ? '<button class="ghost hist-restore" type="button" ' + d + '>↩ 復元</button>'
          : '<button class="ghost hist-discard" type="button" ' + d + '>🚫 破棄</button>') +
        '<button class="ghost hist-del" type="button" ' + d + '>🗑 削除</button>' +
        '</div></div>';
    }).join('');
    els.histList.querySelectorAll('.hist-copy').forEach(function (b) { b.addEventListener('click', function () { copyText(b.getAttribute('data-url'), b); }); });
    els.histList.querySelectorAll('.hist-ins').forEach(function (b) { b.addEventListener('click', function () { setShareOutputs(b.getAttribute('data-url'), ''); b.textContent = '✓ 入れました'; setTimeout(function () { b.textContent = '概要欄へ'; }, 1500); }); });
    els.histList.querySelectorAll('.hist-discard').forEach(function (b) { b.addEventListener('click', function () { setHistFlag(b.getAttribute('data-uri'), b.getAttribute('data-short'), { discarded: true }); }); });
    els.histList.querySelectorAll('.hist-restore').forEach(function (b) { b.addEventListener('click', function () { setHistFlag(b.getAttribute('data-uri'), b.getAttribute('data-short'), { discarded: false }); }); });
    els.histList.querySelectorAll('.hist-adopt').forEach(function (b) { b.addEventListener('click', function () { toggleAdopt(b.getAttribute('data-uri'), b.getAttribute('data-short')); }); });
    els.histList.querySelectorAll('.hist-del').forEach(function (b) { b.addEventListener('click', function () { deleteHistory(b.getAttribute('data-uri'), b.getAttribute('data-short'), b.getAttribute('data-title')); }); });
  }
  // 破棄/復元。(ソフト)フラグを立てるだけで実体は残る＝復元可。
  function setHistFlag(postUri, short, patch) {
    var a = histLoad();
    a.forEach(function (x) { if (histMatch(x, postUri, short)) { for (var k in patch) x[k] = patch[k]; } });
    histSaveArr(a); renderHistory(a);
  }
  // 本採用トグル。同じ題名の他アイテムの本採用は自動で外す。(1題名＝1本採用)
  function toggleAdopt(postUri, short) {
    var a = histLoad();
    var target = null;
    a.forEach(function (x) { if (histMatch(x, postUri, short)) target = x; });
    if (!target) return;
    var willAdopt = !target.adopted;
    var t = (target.title || '').trim();
    a.forEach(function (x) { if (willAdopt && t && (x.title || '').trim() === t) x.adopted = false; });
    target.adopted = willAdopt;
    histSaveArr(a); renderHistory(a);
  }
  // 物理削除。(ハード)実体を消す＝取り消し不可。
  function deleteHistory(postUri, short, title) {
    if (!window.confirm('「' + (title || 'この投稿') + '」を履歴から完全に削除しますか？\n(取り消せません。隠すだけなら「🚫 破棄」を使ってください)')) return;
    var a = histLoad().filter(function (x) { return !histMatch(x, postUri, short); });
    histSaveArr(a); renderHistory(a);
  }
  if (els.histRefresh) els.histRefresh.addEventListener('click', loadHistory);
  if (els.histShowDiscarded) els.histShowDiscarded.addEventListener('change', loadHistory);
  // 過去の短縮URL履歴はAFIリンクタブに移設。タブを開いたら最新を描画。
  var affiTabBtn_ = document.getElementById('tabAffi');
  if (affiTabBtn_) affiTabBtn_.addEventListener('click', loadHistory);

  // ---- 手動短縮(アプリ外で単独投稿した分のURLを貼って短縮＋履歴追加)----
  if (els.manualShortBtn) els.manualShortBtn.addEventListener('click', function () {
    var url = (els.manualUrl && els.manualUrl.value || '').trim();
    if (!/^https?:\/\//.test(url)) {
      if (els.manualOut) els.manualOut.textContent = 'URLは http:// か https:// で始めてください';
      if (els.manualResult) els.manualResult.hidden = false;
      return;
    }
    var btn = els.manualShortBtn, orig = btn.textContent;
    btn.disabled = true; btn.textContent = '短縮中…';
    makeShortAndShare(url).then(function (res) {
      var s = (res && (res.shareUrl || res.shortUrl)) || url;  // 失敗時は元URLで代替
      // 計測コード(r2)が取れたら添える=クリック数は検証タブ「🔗短縮リンク台帳」で見られる
      var w = ((window.Go5Short && window.Go5Short.WORKER_URL) || '').replace(/\/+$/, '');
      var code = (res && res.shortUrl && w && res.shortUrl.indexOf(w + '/') === 0) ? res.shortUrl.slice(w.length + 1) : '';
      if (els.manualOut) els.manualOut.textContent = s + (code ? ' (計測コード: ' + code + ' → 台帳で確認可)' : ' (計測なし)');
      if (els.manualResult) els.manualResult.hidden = false;
      // 履歴(投稿履歴タブ)には追加しない。短縮URLと計測コードを表示するだけ。(台帳=/api/listが記録の正)
      btn.textContent = '✓ 短縮しました'; setTimeout(function () { btn.textContent = orig; btn.disabled = false; }, 1600);
      if (els.manualUrl) els.manualUrl.value = '';
    });
  });
  if (els.manualCopy) els.manualCopy.addEventListener('click', function () { copyText(els.manualOut.textContent, els.manualCopy); });

  // ---- 編集できる確認モーダル(方法①自動投稿) ----
  // 直近に“実際に投稿した”作品URL。(取り違え＝前回のまま投稿、の検知用。アカウント別)
  function lastPostedWork() { return loadA('bsky_last_posted_work') || ''; }
  function setLastPostedWork(v) { saveA('bsky_last_posted_work', v); }

  // 作品URLの取り違え警告。(動画作成タブ・確認モーダルで共通利用)
  function workWarnInfo(url) {
    var w = String(url || '').trim();
    if (!w) return { msg: '⚠️ 作品URLが空です。アフィリンク無しで投稿されます。', color: '#ffb4a2' };
    if (w === lastPostedWork()) return { msg: '⚠️ 前回の投稿と同じ作品URLです。今日の作品で合っていますか？', color: '#ffd479' };
    return { msg: '📕 この作品を案内します。', color: '#9fd6a0' };
  }
  function paintWorkWarn(el, url) { if (!el) return; var i = workWarnInfo(url); el.textContent = i.msg; el.style.color = i.color; }
  function updateMovieWorkLink(url) {
    var el = document.getElementById('movieWorkLink');
    if (!el) return;
    // 空のときは href を外して「ただのテキスト」にする。(# へのページ移動を防ぐ＝リンクとして見せない)
    if (url) { el.href = url; el.textContent = url; el.style.color = 'var(--accent)'; }
    else { el.removeAttribute('href'); el.textContent = '(URLを入力してください)'; el.style.color = 'var(--sub)'; }
  }
  function updateBskyWorkLink(url) {
    var el = document.getElementById('bskyWorkLink');
    if (!el) return;
    if (url) { el.href = url; el.textContent = url; el.style.color = 'var(--accent)'; }
    else { el.removeAttribute('href'); el.textContent = '(URLを入力してください)'; el.style.color = 'var(--sub)'; }
  }
  function updateBskyWorkAffiPreview(url) {
    var el = document.getElementById('bskyWorkAffiPreview');
    if (!el) return;
    if (!url || !url.trim()) { el.textContent = ''; return; }
    var afId = '';
    try { afId = (localStorage.getItem('fanza_af_id') || '').trim(); } catch (e) {}
    var r = window.buildAffiliateLink ? window.buildAffiliateLink(url, afId) : null;
    if (r && r.ok) {
      el.style.color = 'var(--accent)';
      el.innerHTML = '<img class="emico" src="assets/icons/ic-link.png" alt=""> ' + escapeHtml(r.link);
    } else {
      el.style.color = 'var(--warn, #e53)';
      el.textContent = r ? (r.error === 'no_cid' ? '⚠ 作品IDが見つかりません' : '⚠ URLが不正です') : '';
    }
  }

  // ---- 動画作成タブ：投稿バージョンURL(アフィリンク)＋作品情報(FANZA) ----
  // 動画作成タブの作品URL欄に、あなたのアフィIDを入れた「投稿バージョンURL」を自動生成して表示。
  function updateMovieWorkAffi(url) {
    var el = els.movieWorkAffi;
    if (!el) return;
    if (!url || !url.trim()) { el.value = ''; return; }
    var afId = '';
    try { afId = (localStorage.getItem('fanza_af_id') || '').trim(); } catch (e) {}
    var r = window.buildAffiliateLink ? window.buildAffiliateLink(url, afId) : null;
    el.value = (r && r.ok) ? r.link : '';
  }

  // #author(作者名)へサークル名/作者名を自動入力。手動で書き換えた値は尊重。(自動で入れた値だけ上書き)
  // 「前回自動入力した値」は localStorage に永続化＝リロード後や翌日でも、残っている前回の
  // 自動入力値を新しい作品のサークル名で正しく上書きできる。(ウィザード①今から1本の経路もここを通る)
  var movieAuthorAutofilled = load('author_autofill_last') || '';
  function autofillAuthor(circle) {
    if (!circle) return;
    var a = document.getElementById('author');
    if (!a) return;
    var cur = (a.value || '').trim();
    if (cur && cur !== movieAuthorAutofilled) return; // ユーザーが手入力済み＝触らない
    a.value = circle;
    movieAuthorAutofilled = circle;
    save('author_autofill_last', circle);
    try { a.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
    renderPreview();
  }

  // 作品情報表示。(作品名・サークル名・定価・セール)cid→FanzaCore で取得。結果は簡易キャッシュ。
  var movieInfoCache = {}; // cid -> info({__error} も入れて再取得を抑制)
  var movieInfoSeq = 0;    // 競合防止(URL連続変更時に古い結果で上書きしない)
  function renderMovieInfoLoading() {
    if (els.movieWorkInfo) { els.movieWorkInfo.style.color = 'var(--sub)'; els.movieWorkInfo.textContent = '⏳ 作品情報を取得中…'; }
  }
  function renderMovieInfo(info) {
    var el = els.movieWorkInfo;
    if (!el) return;
    if (!info || !info.title) { el.style.color = 'var(--sub)'; el.textContent = ''; return; }
    var yen = function (n) { return (n != null && !isNaN(n)) ? '¥' + Number(n).toLocaleString('ja-JP') : '—'; };
    var lines = [];
    lines.push('<div><b>作品名</b>：' + escapeHtml(info.title) + '</div>');
    lines.push('<div><b>サークル名</b>：' + (info.author ? escapeHtml(info.author) : '—') + '</div>');
    lines.push('<div><b>定価</b>：' + yen(info.listPrice) + '</div>');
    var onSale = info.listPrice && info.price && info.discountPct > 0 && info.price < info.listPrice;
    if (onSale) {
      lines.push('<div style="color:#e0554e;font-weight:700;"><b>セール中</b>：' + yen(info.price) + '(' + info.discountPct + '%OFF)</div>');
    } else {
      lines.push('<div style="color:var(--sub);">セールなし</div>');
    }
    el.style.color = 'var(--ink)';
    el.innerHTML = lines.join('');
    autoApplyDiscountFromInfo_(info); // 現在の割引率を投稿文へ自動反映(取得できない時だけ手動ドロップダウンが効く)
    autoApplyAttrsFromInfo_(info); // ジャンル→カテゴリ自動チェック(同一cidは1回だけ＝手動調整を尊重)
    try { if (window.Go5PromoLabel) window.Go5PromoLabel.notify(info); } catch (e) {} // 販促ラベル(今なら◯%OFF)を元写真へ焼き込み
  }
  // 作品URLから取得できた「現在の割引率」を投稿文へ自動反映する。取得できなかった/セール無しの
  // ときは何もしない。(＝割引文ドロップダウンでの手動指定がそのまま使える・補助的フォールバック)
  // ※同じ作品(cid)には1回だけ自動適用する。再描画・キャッシュヒットのたびに発火すると、
  //   ユーザーが手で選び直した割引％を毎回上書きしてしまうため。(v164のリグレッション対策)
  var _autoDiscDoneCid = '';
  function autoApplyDiscountFromInfo_(info) {
    if (!info || !info.title) return; // 取得失敗＝手動フォールバックのため触らない
    var cid = info.cid || info.title; // cid欠落時はタイトルで代用
    if (cid === _autoDiscDoneCid) return; // この作品には適用済み＝手動変更を尊重
    _autoDiscDoneCid = cid;
    var onSale = info.listPrice && info.price && info.discountPct > 0 && info.price < info.listPrice;
    applyDiscount(onSale ? String(info.discountPct) : '');
  }
  function fetchMovieWorkInfo(url) {
    var el = els.movieWorkInfo;
    if (!url || !url.trim()) { if (el) { el.textContent = ''; } return; }
    var r = window.buildAffiliateLink ? window.buildAffiliateLink(url, '') : null;
    var cid = (r && r.ok) ? r.cid : '';
    if (!cid) { if (el) { el.style.color = 'var(--sub)'; el.textContent = ''; } return; }
    try { if (window.Go5PromoLabel) window.Go5PromoLabel.begin(cid); } catch (e) {} // 作品替え=前作の%で焼かない
    var workerUrl = '', secret = '';
    try { workerUrl = localStorage.getItem('fanza_worker_url') || ''; } catch (e) {}
    try { secret = localStorage.getItem('fanza_shared_secret') || ''; } catch (e) {}
    if (!workerUrl || typeof window.FanzaCore === 'undefined') { if (el) { el.style.color = 'var(--sub)'; el.textContent = ''; } return; }
    // キャッシュヒット(成功情報)はそのまま反映。
    if (movieInfoCache[cid] && movieInfoCache[cid].title) { renderMovieInfo(movieInfoCache[cid]); autofillAuthor(movieInfoCache[cid].author); return; }
    var seq = ++movieInfoSeq;
    renderMovieInfoLoading();
    window.FanzaCore.fetchFanzaInfo(cid, workerUrl, secret, url).then(function (info) {
      if (seq !== movieInfoSeq) return; // 途中でURLが変わった＝破棄
      if (info && info.title) {
        movieInfoCache[cid] = info;
        renderMovieInfo(info);
        autofillAuthor(info.author);
      } else {
        if (el) { el.style.color = 'var(--sub)'; el.textContent = '(作品情報を取得できませんでした' + (info && info.reason ? '：' + info.reason : '') + ')'; }
      }
    }).catch(function () { if (seq === movieInfoSeq && el) { el.style.color = 'var(--sub)'; el.textContent = ''; } });
  }
  // 連続入力での過剰なFANZA取得を抑える。(デバウンス)
  var movieInfoTimer = null;
  function scheduleMovieWorkInfo(url) {
    if (movieInfoTimer) clearTimeout(movieInfoTimer);
    movieInfoTimer = setTimeout(function () { fetchMovieWorkInfo(url); }, 500);
  }

  // 作品URLを一元的に更新。(動画作成タブ⇔投稿タブ⇔localStorage を同期)fromMovie=動画作成タブ起点。
  function syncWorkUrl(v, fromMovie) {
    saveA('bsky_work_url', v);
    if (els.workUrl && fromMovie) els.workUrl.value = v;
    if (els.movieWorkUrl && !fromMovie) els.movieWorkUrl.value = v;
    updateMovieWorkLink(v);
    updateMovieWorkAffi(v);
    scheduleMovieWorkInfo(v);
    updateBskyWorkLink(v);
    updateBskyWorkAffiPreview(v);
    paintWorkWarn(els.movieWorkWarn, v);
    renderPreview(); updateGasStatus();
  }
  if (els.movieWorkUrl) els.movieWorkUrl.addEventListener('input', function () { syncWorkUrl(els.movieWorkUrl.value, true); });

  // 動画作成タブ 作品URL クリア／戻す(クリアで空に、戻すで直前値を復元)
  var movieWorkCleared = '';
  var movieWorkClearBtn = $('movieWorkClear');
  if (movieWorkClearBtn) {
    movieWorkClearBtn.addEventListener('click', function () {
      var cur = (els.movieWorkUrl && els.movieWorkUrl.value) || loadA('bsky_work_url') || '';
      if (cur) movieWorkCleared = cur; // 戻す用に退避
      // ★テキストボックス本体も消す(syncWorkUrl は fromMovie=true 時に movieWorkUrl を触らないため明示クリア)
      if (els.movieWorkUrl) els.movieWorkUrl.value = '';
      syncWorkUrl('', true);
      // 生成表示(投稿バージョンURL・作品情報)も消す
      if (els.movieWorkAffi) els.movieWorkAffi.value = '';
      if (els.movieWorkInfo) els.movieWorkInfo.textContent = '';
    });
  }
  // 投稿バージョンURL コピー
  if (els.movieWorkAffiCopy) {
    els.movieWorkAffiCopy.addEventListener('click', function () {
      var v = els.movieWorkAffi ? els.movieWorkAffi.value : '';
      if (v) copyText(v, els.movieWorkAffiCopy);
    });
  }
  var movieWorkUndoBtn = $('movieWorkUndo');
  if (movieWorkUndoBtn) {
    movieWorkUndoBtn.addEventListener('click', function () {
      if (!movieWorkCleared) return;
      syncWorkUrl(movieWorkCleared, true);
      movieWorkCleared = '';
    });
  }

  function confirmEditable(text, note) {
    return new Promise(function (resolve) {
      if (!els.pcModal) { resolve(window.confirm(text) ? text : null); return; }

      // 「案内する作品URL」を明示＆その場で差し替え可能に。(動画は作り直さない)
      // 変更したら本文末尾のアフィリンクを作り直す。取り違え(前回と同じ)は警告する。
      function curWork() { return (els.pcWorkUrl ? els.pcWorkUrl.value : (els.workUrl && els.workUrl.value) || '').trim(); }
      function updateWorkWarn() { paintWorkWarn(els.pcWorkWarn, curWork()); }
      function recompose() {
        // resolveAffLink は els.workUrl を見るので一時同期 → 本文を作り直し。
        if (els.pcWorkUrl && els.workUrl) els.workUrl.value = els.pcWorkUrl.value;
        els.pcText.value = composePostText();
        updateWorkWarn();
      }

      if (els.pcWorkUrl) els.pcWorkUrl.value = (els.workUrl && els.workUrl.value || '').trim();
      els.pcText.value = text;
      if (els.discountSelPc) els.discountSelPc.value = '';
      var pcDiscEl = document.getElementById('pcDiscountListOn'); if (pcDiscEl) pcDiscEl.checked = discountListOn_(); // 現在のON/OFFを反映
      var pcDiscStatusEl = document.getElementById('pcDiscStatus'); if (pcDiscStatusEl) pcDiscStatusEl.textContent = '';
      // 画像選択をリセット(モーダルを開くたびに白紙から選択させる)
      pcSelectedFile = null;
      if (els.pcImg) els.pcImg.value = '';
      if (els.pcImgName) els.pcImgName.textContent = '未選択(動画の元写真を添付)';
      if (els.pcImgClear) els.pcImgClear.style.display = 'none';
      if (els.pcImgPreview) { els.pcImgPreview.src = ''; els.pcImgPreview.style.display = 'none'; }
      updateWorkWarn();
      // 背後の入力欄のフォーカスを外してから表示(iOSでカーソル(キャレット)がモーダル上に
      // 浮いて見える・変な位置で点滅する問題の対策)。
      try { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); } catch (e) {}
      els.pcModal.hidden = false;

      function onWork() { recompose(); }
      if (els.pcWorkUrl) els.pcWorkUrl.addEventListener('input', onWork);
      function cleanup() {
        els.pcModal.hidden = true;
        els.pcOk.removeEventListener('click', ok); els.pcCancel.removeEventListener('click', cancel);
        if (els.pcWorkUrl) els.pcWorkUrl.removeEventListener('input', onWork);
      }
      function ok() {
        // 確定した作品URLを保存＆反映。(記録・YT説明欄・プレビューの作品も揃う)
        if (els.pcWorkUrl && els.workUrl) { var w = els.pcWorkUrl.value.trim(); els.workUrl.value = w; if (els.movieWorkUrl) els.movieWorkUrl.value = w; saveA('bsky_work_url', w); setLastPostedWork(w); paintWorkWarn(els.movieWorkWarn, w); updateMovieWorkLink(w); updateBskyWorkLink(w); }
        var v = els.pcText.value; cleanup(); resolve(v);
      }
      function cancel() { cleanup(); resolve(null); }
      els.pcOk.addEventListener('click', ok); els.pcCancel.addEventListener('click', cancel);
    });
  }

  // ---- 方法②：今すぐ投稿(単独) ----
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
      var postAcct = acctId(), postMeta = captureMeta_(); // 投稿を押した瞬間のアカウント・メタを凍結
      var _ws = null; // 導線2(投稿→FANZA)の計測リンク情報
      measureWorkLink_(text)
        .then(function (mw) { text = mw.text; _ws = mw.workShort; return (f ? compressFile(f) : Promise.resolve(null)); })
        .then(function (blob) { return window.BlueskyCore.blueskyPostRaw({ identifier: c.handle, appPassword: c.appPw, text: text, imageBlob: blob, alt: alt }); })
        .then(function (res) { setPostStatus('✅ 投稿しました → <a href="' + res.postUrl + '" target="_blank" rel="noopener">投稿を開く</a>', true); notifyPosted(res, text, alt, postAcct, postMeta, _ws); })
        .catch(function (e) { setPostStatus('⚠️ 投稿に失敗：<br>' + friendlyLoginError(e && e.message ? e.message : e), true); })
        .then(function () { els.postNow.disabled = false; });
    });
  }

  // ---- 無人予約(Phase5)：GASへ送信し、時間トリガーが投稿(タブを閉じてもOK) ----
  function reserveUnattended(text, blob, ms, slotId, meta) {
    var gasUrl = (els.gasUrl.value || '').trim();
    if (!gasUrl) { setPostStatus('無人予約には⚙の「記録用URL(GAS)」設定が必要です。'); return; }
    var payload = { type: 'reserve', channel: (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'), scheduled_at: new Date(ms).toISOString(), text: text, slot_id: slotId || '' };
    if (meta) payload.meta = meta; // 動画メタを中継＝GAS無人投稿でも videoId/カテゴリ/作品状態/リビルド元が記録される(D-1)
    function send() {
      setPostStatus('☁️ 無人予約を送信中…');
      fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j && j.ok) setPostStatus('☁️ 無人予約しました：' + new Date(ms).toLocaleString('ja-JP') + '(タブを閉じてもOK)');
          else setPostStatus('予約に失敗：' + ((j && j.error) || '不明'));
        })
        .catch(function () { setPostStatus('予約送信に失敗。(GAS URL・通信をご確認ください)'); });
    }
    if (blob) { var fr = new FileReader(); fr.onload = function () { payload.image = fr.result; send(); }; fr.onerror = function () { send(); }; fr.readAsDataURL(blob); }
    else send();
  }

  // ---- 方法③：予約投稿(無人＝GAS／開いている間＝端末タイマー) ----
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
      measureWorkLink_(text).then(function (mw) {
      text = mw.text; // 予約本文も導線2計測リンクへ置換してから予約する(発火時の再置換は不要)
      if (unattended) {
        var _uMeta = captureMeta_(); // 予約時に動画メタを凍結(発火時UIに依存させない・D-1)
        (f ? compressFile(f) : Promise.resolve(null)).then(function (blob) { reserveUnattended(text, blob, ms, slotId, _uMeta); });
        return;
      }
      var c = creds();
      if (!c.handle || !c.appPw) { setPostStatus('⚙設定でハンドルとアプリパスワードを入れてください。(無人予約ならGAS設定)'); return; }
      if (!window.Scheduler) { setPostStatus('スケジューラ未読込。'); return; }
      var _mMeta = captureMeta_(); // 予約時のアカウント・メタを凍結(発火時のUI状態に依存させない)
      (f ? compressFile(f) : Promise.resolve(null)).then(function (blob) {
        window.Scheduler.reserve({ slotId: slotId, text: text, imageBlob: blob, scheduledAtMs: ms, alt: alt, handle: c.handle, appPw: c.appPw, account: acctId(), meta: _mMeta });
        setPostStatus('⏰ 予約しました：' + new Date(ms).toLocaleString('ja-JP') + '(このタブを開いている間に自動投稿)');
      });
      });
    });
  }

  // ---- 方法①：動画作成後の自動投稿(編集できる確認) ----
  // ── 🔁リビルドの「Bluesky投稿引き継ぎ」 ──────────────────────────────
  // リビルド元と同じ作品なら、Blueskyへ再投稿せず前回の投稿(postUri/短縮URL/クリック計測)を
  // 新しい動画に引き継ぐ。短縮URLが同一なのでクリック数は自然に「新旧の総合値」になる。
  function sameWorkCid_(u1, u2) {
    try {
      if (!u1 || !u2 || !window.buildAffiliateLink) return false;
      var n1 = window.normalizeWorkUrl ? window.normalizeWorkUrl(u1) : u1;
      var n2 = window.normalizeWorkUrl ? window.normalizeWorkUrl(u2) : u2;
      var r1 = n1 ? window.buildAffiliateLink(n1, '') : null;
      var r2 = n2 ? window.buildAffiliateLink(n2, '') : null;
      return !!(r1 && r2 && r1.ok && r2.ok && r1.cid === r2.cid);
    } catch (e) { return false; }
  }
  // 引き継ぎ実行(履歴は「置き換え」＝旧アイテムはローカル履歴から消え、新アイテムがURL群を引き継ぐ。
  //   旧動画のクリック実績は rebuildBaseClicks として新アイテムに保存＝投稿履歴で「総合値(旧値)」表示。
  //   記録シートは videoId 別行なので旧行は残る＝分析はシートで可能・新行はリビルド元IDで系譜が追える)。
  function inheritRebuildPost_(old, ev) {
    var account = acctId(), meta = captureMeta_();
    var newVid = (ev && ev.detail && ev.detail.videoId) || currentVideoId || '';
    var title = (ev && ev.detail && ev.detail.title) || old.title || '';
    var baseClicks = null; // リビルド時点までのクリック数(括弧表示のスナップショット)
    try { if (window.Go5Clicks && old.shortUrl) baseClicks = window.Go5Clicks.of(old.shortUrl); } catch (e) {}
    histAdd({ account: account, meta: meta, title: title, shortUrl: old.shortUrl || '', shareUrl: old.shareUrl || old.shortUrl || '', postUrl: old.postUrl || '', postUri: old.postUri || '', videoId: newVid, rebuildBaseClicks: baseClicks });
    recordToSheet({ account: account, meta: meta, title: title, postUrl: old.postUrl || '', postUri: old.postUri || '', shortUrl: old.shortUrl || '', shareUrl: old.shareUrl || '', videoId: newVid });
    _skipNextYtReset = true; // 直後に走る video-created の説明欄リセット(INC-70)を1回スキップ(旧短縮URLを残す)
    setShareOutputs(old.shareUrl || old.shortUrl || '', old.postUrl || ''); // YT説明欄へも旧短縮URLを反映
    setBskyStatus('🔁 リビルド：Blueskyへは再投稿せず、前回の投稿を引き継ぎました。(短縮URL・クリック計測は継続)');
  }
  // 引き継ぎ条件を満たせば確認のうえ実行して true。(自動投稿ON/OFFに関わらず video-created 直後に判定)
  function maybeInheritRebuild_(ev) {
    try {
      if (!readRebuild()) return false;
      var rbVid = readRebuildTarget(); if (!rbVid) return false;
      var old = null; histLoad().forEach(function (x) { if (x.videoId === rbVid) old = x; });
      if (!old || (!old.postUri && !old.shortUrl)) return false; // 引き継げる投稿が無い
      if (!sameWorkCid_(old.workUrl, captureWorkUrl_())) return false; // 別作品なら通常フロー(新規投稿)
      if (!window.confirm('リビルド元と同じ作品です。\nBlueskyへは再投稿せず、前回の投稿(短縮URL・クリック計測)をこの動画に引き継ぎます。よろしいですか？\n\n(キャンセル＝通常どおりBlueskyへ新規投稿します)')) return false;
      inheritRebuildPost_(old, ev);
      return true;
    } catch (e) { return false; }
  }

  function handleVideoCreated(ev) {
    if (maybeInheritRebuild_(ev)) return; // 🔁同一作品のリビルド＝前回のBluesky投稿を引き継ぎ(再投稿しない)
    if (!els.enable || !els.enable.checked) return;
    var c = creds();
    if (!c.handle || !c.appPw) { setBskyStatus('「🦋 投稿」タブの⚙でハンドルとアプリパスワードを入れると自動投稿します。(今回はスキップ)'); return; }
    if (!window.BlueskyCore) { setBskyStatus('投稿モジュール未読込。'); return; }
    var composed = composePostText();
    if (!composed.trim()) { setBskyStatus('投稿本文が空です。(「🦋 投稿」タブで入力)'); return; }
    var alt = (ev && ev.detail && ev.detail.title) ? String(ev.detail.title) : (composed.split('\n')[0] || '');
    // ★2026-07-13 Chami指定: モーダルを「完成形」で開く——①割引行を確定 ②アフィリンクを計測付き短縮に変換してから表示。
    //   (従来は生リンクで表示し投稿直前に短縮していた。ユーザーがモーダルで見る文=実際に投稿される文、に揃える)
    ensureDiscountReadyP_().then(function () {
      composed = composePostText(); // 割引リンク確定後に再構成
      return measureWorkLink_(composed);
    }).then(function (pre) {
      return { text: pre.text };
    }).catch(function () { return { text: composed }; }).then(function (prep) {
    confirmEditable(prep.text, null).then(function (edited) {
      if (edited == null) { setBskyStatus('自動投稿をキャンセルしました。'); return; }
      if (!edited.trim()) { setBskyStatus('本文が空のため中止しました。'); return; }
      // 導線2: 本文中の作品リンクを計測付き短縮へ置換してから投稿/予約する
      measureWorkLink_(edited).then(function (mw) {
      edited = mw.text; var _ws = mw.workShort;
      // 予約時刻チェック(movieSchedAt に値があれば即時投稿せず予約)
      var msEl = $('movieSchedAt'), schedMs = msEl && msEl.value ? new Date(msEl.value).getTime() : NaN;
      if (!isNaN(schedMs) && schedMs > Date.now()) {
        if (!window.Scheduler) { setBskyStatus('スケジューラ未読込。'); return; }
        var imgF = pcSelectedFile || photoFile();
        var imgP = imgF ? compressFile(imgF) : (function () { var cv = $('cv'); return cv ? compressCanvas(cv) : Promise.resolve(null); })();
        var _acMeta = captureMeta_(); // 予約時にメタ凍結
        imgP.then(function (blob) {
          window.Scheduler.reserve({ account: acctId(), meta: _acMeta, slotId: window.__activeSlot__ ? window.__activeSlot__.id : null, text: edited, imageBlob: blob, scheduledAtMs: schedMs, alt: alt, handle: c.handle, appPw: c.appPw });
          setBskyStatus('⏰ 予約しました：' + new Date(schedMs).toLocaleString('ja-JP'));
          if (msEl) msEl.value = '';
        });
        return;
      }
      var gasSet = !!(els.gasUrl.value || '').trim();
      setBskyStatus('Bluesky に投稿中…');
      var _postAcct = acctId(), _postMeta = captureMeta_(); // 投稿実行時のアカウント・メタを凍結
      // モーダル選択画像を優先。未選択なら動画の元写真→Canvas の順にフォールバック
      var imgFile = pcSelectedFile || photoFile();
      var imgPrep = imgFile
        ? compressFile(imgFile)
        : (function () { var cv = $('cv'); return cv ? compressCanvas(cv) : Promise.resolve(null); })();
      imgPrep
        .then(function (blob) { return window.BlueskyCore.blueskyPostRaw({ identifier: c.handle, appPassword: c.appPw, text: edited, imageBlob: blob, alt: alt }); })
        .then(function (res) {
          setBskyStatus('✅ Bluesky に投稿しました<br>@' + (res.handle || c.handle) + (gasSet ? '  ✏️記録しました' : ''), true);
          notifyPosted(res, edited, alt, _postAcct, _postMeta, _ws);
          // Bluesky独自の画像を添付したときだけ、その画像を Drive の同じ動画フォルダへ後追い保存。(drive-upload.js が購読)
          // 未添付(pcSelectedFile が無い＝動画の元写真をそのまま投稿)なら動画の画像と同一なので重複保存しない。
          try {
            if (pcSelectedFile) document.dispatchEvent(new CustomEvent('bsky-image-posted', { detail: { file: pcSelectedFile, title: (ev && ev.detail && ev.detail.title) || '', videoId: (ev && ev.detail && ev.detail.videoId) || '' } }));
          } catch (e2) {}
        })
        .catch(function (e) { setBskyStatus('⚠️ 投稿に失敗しました：<br>' + friendlyLoginError(e && e.message ? e.message : e), true); });
      }); // measureWorkLink_
    });
    }); // 完成形プリペア(割引確定+短縮)のthen
  }
  document.addEventListener('video-created', handleVideoCreated);
  // 自動投稿のON/OFFに関わらず、発番された安定動画IDは常に保持。(投稿記録の背骨キー)
  var _skipNextYtReset = false; // リビルド引き継ぎ時は説明欄の旧短縮URLを保持する(リセットを1回スキップ)
  document.addEventListener('video-created', function (e) {
    var d = (e && e.detail) || {};
    if (d.videoId) currentVideoId = d.videoId;
    if (_skipNextYtReset) { _skipNextYtReset = false; return; } // 引き継ぎ済み＝旧短縮URLが正
    resetYtDescShortLink_(); // 新作の動画＝前作の短縮リンクを説明欄から消す(この作品を投稿すると新リンクが入る・INC-70)
  });
  // ※旧「Bsky添付画像を自動ダウンロード」は廃止(iPhoneで毎回『ダウンロードしますか？』が
  //   出て邪魔＆Drive保存と干渉するため)。添付画像は投稿成功時に Drive へ保存する。(drive-upload.js)

  if (els.shortUrlCopy) els.shortUrlCopy.addEventListener('click', function () { if (lastShortUrl) copyText(lastShortUrl, els.shortUrlCopy); });
  if (els.ytCopy) els.ytCopy.addEventListener('click', function () { if (els.ytDesc) copyText(els.ytDesc.value, els.ytCopy); });
  if (els.ytInsert) els.ytInsert.addEventListener('click', function () { if (lastShortUrl) putUrlTop(lastShortUrl); });

  var lastTitle = '';
  var topEl = document.getElementById('top');
  var ytTagWarnEl = document.getElementById('ytTagWarn');
  // S-3: タグは3〜5個(#Shorts＋ジャンル語＋作品固有)が目安。タイトル上に表示されるのは上位3個のみ。
  //   公式仕様: 60個超で全タグ無視(「15個で無効」は二次ブログ由来の誤情報と判明・2026-07-05裏取り済
  //   https://support.google.com/youtube/answer/6390658)。※非破壊：ユーザーのタグは書き換えず注意表示のみ。
  function updateTagWarn(tags) {
    if (!ytTagWarnEl) return;
    var list = (tags.match(/#[^\s#]+/g) || []);
    var n = list.length;
    var hasShorts = list.some(function (t) { return /^#shorts$/i.test(t); });
    var msg = '', col = 'var(--sub)';
    if (n > 60) { msg = '⚠ タグが' + n + '個＝60個超はYouTubeが全タグを無視します。(公式仕様)3〜5個に絞ってください。'; col = '#e6a14e'; }
    else if (n === 0) { msg = 'ℹ タグ未設定。#Shorts＋ジャンル語で3〜5個入れるとフィードで有利です。'; col = 'var(--sub)'; }
    else if (n < 3) { msg = 'ℹ タグ' + n + '個。#Shorts＋ジャンル語＋作品固有で3〜5個が目安です。'; col = 'var(--sub)'; }
    else if (n > 5) { msg = 'ℹ タグ' + n + '個。表示されるのは上位3個だけ＝3〜5個に絞ると評価が集中します。' + (hasShorts ? '' : ' #Shorts も入れると◎。'); col = 'var(--sub)'; }
    else { msg = '✓ タグ' + n + '個(3〜5個)' + (hasShorts ? '' : '・#Shorts を足すと◎'); col = hasShorts ? '#7fb98a' : 'var(--sub)'; }
    ytTagWarnEl.textContent = msg;
    ytTagWarnEl.style.color = col;
  }
  function buildTitle() {
    if (!els.ytTitle) return;
    // ★2行モードの改行はYouTube題名に持ち込まない(Chami指定2026-07-19)。
    //   YouTubeの題名は1行が仕様。改行を空白に置換もしない=詰めて連結する(Chami明示)。
    //   ここは video-created の detail.title とは別経路で #top を直読みしているため、
    //   app.js 側の対処だけでは漏れる(コピーボタンでそのままクリップボードへ入る)。
    var comment = (topEl && topEl.value ? String(topEl.value).replace(/\n+/g, '').trim() : '');
    var tags = (els.ytTags && els.ytTags.value ? els.ytTags.value.trim() : '');
    var title = comment + (comment && tags ? ' ' : '') + tags;
    lastTitle = title;
    els.ytTitle.textContent = title || '(「動画作成」タブのコメントを入れると題名が出ます)';
    updateTagWarn(tags);
  }
  if (els.ytTags) els.ytTags.addEventListener('input', buildTitle);
  if (topEl) { topEl.addEventListener('input', buildTitle); topEl.addEventListener('change', buildTitle); } // change＝候補からの転記(setVal)でも題名を更新
  var tabPostBtn = document.getElementById('tabPost'); if (tabPostBtn) tabPostBtn.addEventListener('click', buildTitle);
  var tabYtBtn = document.getElementById('tabYT'); if (tabYtBtn) tabYtBtn.addEventListener('click', buildTitle); // 題名表示はYouTubeタブ内＝開くたび最新のコメントで再構築
  if (els.ytTitleCopy) els.ytTitleCopy.addEventListener('click', function () { if (lastTitle) copyText(lastTitle, els.ytTitleCopy); });
  buildTitle();

  // ---- ⏰ 予約して投稿(動画作成タブ) ----
  var movieSchedRow = $('movieSchedRow');
  var makeReserveBtn = $('makeReserveBtn');
  var makeReserveConfirmBtn = $('makeReserveConfirmBtn');

  if (makeReserveBtn && movieSchedRow) {
    makeReserveBtn.addEventListener('click', function () {
      var showing = movieSchedRow.style.display !== 'none';
      movieSchedRow.style.display = showing ? 'none' : '';
    });
  }

  if (makeReserveConfirmBtn) {
    makeReserveConfirmBtn.addEventListener('click', function () {
      var schedAtEl = $('movieSchedAt');
      if (!schedAtEl || !schedAtEl.value) { alert('予約時刻を選択してください。'); return; }
      var ms = new Date(schedAtEl.value).getTime();
      if (isNaN(ms) || ms <= Date.now()) { alert('未来の時刻を選択してください。'); return; }
      // 予約モードなので Bsky 投稿を確実に有効化してから動画作成を実行
      if (els.enable) els.enable.checked = true;
      var makeBtnEl = $('makeBtn');
      if (makeBtnEl) makeBtnEl.click();
    });
  }

  // ---- X(Twitter)投稿用テキスト(コピペ手動投稿・2026-07-21) ----
  (function wireXTweet_() {
    var xTxt = document.getElementById('xTweetText');
    var xCnt = document.getElementById('xTweetCount');
    var xCopy = document.getElementById('xTweetCopyBtn');
    var xShortBtn = document.getElementById('xTweetUseShort');
    var xStatus = document.getElementById('xTweetStatus');
    var xAcctHint = document.getElementById('xAcctHint');
    if (!xTxt) return;

    // X アカウントヒント(固定値は core/account.js Go5Acct に集約済み・そちらを参照)
    function updateXAcctHint_() {
      if (!xAcctHint) return;
      if (!window.Go5Acct) return;
      var name   = window.Go5Acct.xNameOf();
      var handle = window.Go5Acct.xHandleOf();
      xAcctHint.textContent = (name && handle) ? '📮 投稿先: ' + name + ' (@' + handle + ')' : '';
    }
    document.addEventListener('account-changed', updateXAcctHint_);
    updateXAcctHint_();

    // 短縮URL差し替えのオーバーライド(「📎 短縮URLを挿入」クリック後に保持)
    var _xOverrideShort = '';

    // X文字数カウント(URL=23文字換算・Xの実装に準拠)
    // Xの加重文字数。実体は BlueskyCore.xWeightedLength(＝Nodeテスト対象)。
    //   ★日本語と絵文字は重み2で数える必要がある(X公式仕様)。1文字=1で数えると書ける量を
    //   約2倍に見せてしまい、「余裕あり」と出た文がXで弾かれる。
    //   core未読込時は安全側(重み2)に倒す＝過小表示で投稿が弾かれるより、多めに見せて縮めてもらう方がまし。
    function xCount(text) {
      if (window.BlueskyCore && typeof window.BlueskyCore.xWeightedLength === 'function') {
        return window.BlueskyCore.xWeightedLength(text);
      }
      var urls = (String(text || '').match(/https?:\/\/[^\s]+/g) || []);
      var noUrl = String(text || '').replace(/https?:\/\/[^\s]+/g, '');
      return Array.from(noUrl).length * 2 + urls.length * 23;
    }

    // Xツイート用本文を組み立てる
    //   ★本文はBlueskyと共通(Chami指定2026-07-21「投稿する内容はブルースカイもXも同じ」)。
    //   新しい文言生成はせず、既存の composePostText()(セール行含む・投稿ボタン③つで実績のある
    //   組み立て)をそのまま使う。「📎 短縮URLを挿入」で作品リンクだけ手動プレビュー差し替え可能。
    var X_LINK_PENDING = '(短縮リンク取得中…)'; // Blueskyプレビューと共通の目印文字列
    function composeXText() {
      var base = composePostText();
      var rawLink = resolveAffLink();
      // 短縮URLオーバーライド時：本文内の生リンクを差し替え(手動プレビュー用。実際のコピー時は
      // measureWorkLink_ が同じ計測付き短縮へ差し替えるため、押し忘れても生リンクのままにはならない)
      if (_xOverrideShort && rawLink && base.indexOf(rawLink) >= 0) {
        return base.replace(rawLink, _xOverrideShort);
      }
      // ★composePostTextは実送信時の安全網として生の長いリンクへフォールバックすることがある
      //   (紹介用短縮リンクの取得が間に合わなかった場合)。表示欄には生リンクを一切出さない
      //   (Chami指定2026-07-23・Blueskyプレビューと同じ方針)ので、ここで短縮版か取得中の目印へ
      //   差し替える。取得中ならensureWorkShortLink_を起動し、出来次第X欄も再構成する
      //   (go5-work-short-readyイベント経由・composePostText側と二重発火しない共有キャッシュ)。
      if (rawLink && base.indexOf(rawLink) >= 0) {
        var short = cachedWorkShortLink_();
        if (short) return base.split(rawLink).join(short);
        ensureWorkShortLink_(function () {}); // composePostText側と同じキャッシュ・二重取得はしない
        return base.split(rawLink).join(X_LINK_PENDING);
      }
      return base;
    }

    function updateXCount_(text) {
      var t = (text !== undefined) ? text : xTxt.value;
      var n = xCount(t);
      if (xCnt) {
        // 「280」は文字数ではなく加重の上限。日本語は1字=2で効くため、素の字数と一致しない。
        // 数字だけだと「まだ書ける」と誤解されるので単位を明示する。
        xCnt.textContent = n + ' / 280 (Xの換算・日本語は1字=2)';
        xCnt.style.color = n > 280 ? '#e74c3c' : n > 240 ? '#e6a14e' : 'var(--sub)';
      }
    }

    function refreshXTweet() {
      updateXAcctHint_(); // 投稿先の表示も一緒に更新(生成のたびに正しい宛先が出る)
      var text = composeXText();
      xTxt.value = text;
      updateXCount_(text);
    }

    // ★X欄はその場で短くできるようにする(readonlyを解除)。
    //   Xは加重280で日本語1字=2。フック行・CTA行が入った現行テンプレは残りが数十しかなく、
    //   キャプションを少し伸ばすと超える。readonlyのままだと超えた時に**アプリ内で短くする術が無く**、
    //   Blueskyのキャプションを削る(=Blueskyの投稿文まで変わる)しかなかった。
    //   ここはコピー用の作業領域なので、直接削れる方が用途に合う。
    //   ※キャプション/作品URL/アカウントを変えると再生成で上書きされる(意図的な操作時のみ)。
    if (xTxt) {
      xTxt.removeAttribute('readonly');
      xTxt.addEventListener('input', function () { updateXCount_(); });
    }

    // 本文・作品URL変更時に再生成(短縮URL差し替えはリセット)
    if (els.text) els.text.addEventListener('input', function () { _xOverrideShort = ''; refreshXTweet(); });
    if (els.workUrl) els.workUrl.addEventListener('input', function () { _xOverrideShort = ''; refreshXTweet(); });
    if (els.movieWorkUrl) els.movieWorkUrl.addEventListener('input', function () { _xOverrideShort = ''; refreshXTweet(); });
    document.addEventListener('account-changed', function () { _xOverrideShort = ''; refreshXTweet(); });
    // ★composePostText側で紹介用短縮リンクの取得が完了した時にX欄も追従させる(別IIFEスコープのため疎結合通知)。
    document.addEventListener('go5-work-short-ready', function () { refreshXTweet(); });
    refreshXTweet();

    // 📎 短縮URLを挿入：link-worker 経由で作品URLを短縮し、生リンクを差し替える
    if (xShortBtn) {
      xShortBtn.addEventListener('click', function () {
        var raw = resolveAffLink();
        if (!raw) { if (xStatus) xStatus.textContent = '先に作品URLを入力してください。'; return; }
        xShortBtn.disabled = true;
        if (xStatus) xStatus.textContent = '短縮リンクを取得中…';
        makeShortAndShare(raw).then(function (res) {
          var shortLink = res.shareUrl || res.shortUrl || '';
          if (!shortLink) { if (xStatus) xStatus.textContent = '⚠️ 短縮リンクの取得に失敗しました。生URLを使います。'; return; }
          _xOverrideShort = shortLink;
          var text = composeXText();
          xTxt.value = text;
          updateXCount_(text);
          if (xStatus) xStatus.textContent = '✅ 短縮URLを挿入しました。';
        }).catch(function () {
          if (xStatus) xStatus.textContent = '⚠️ 短縮リンクの取得に失敗しました。';
        }).then(function () { xShortBtn.disabled = false; });
      });
    }

    // 📋 コピー
    //   ★コピー直前に measureWorkLink_(Blueskyの今すぐ投稿/予約と同じ関数)を通し、作品リンクを
    //   計測付き短縮URLへ差し替えてからコピーする。「📎 短縮URLを挿入」を押し忘れても、
    //   コピーした時点で完成形になっている(AD-GL決定③・Chami指定2026-07-21)。
    if (xCopy) {
      xCopy.addEventListener('click', function () {
        var text = xTxt.value;
        if (!text.trim()) { if (xStatus) xStatus.textContent = '本文がありません。'; return; }
        // ★「取得中」の目印はプレビュー専用の表示であり、このままコピーすると意味不明な文字列が
        //   実際にXへ投稿されてしまう。取得できるまでコピーさせない(Chami指定の完成形保証)。
        if (text.indexOf(X_LINK_PENDING) >= 0) { if (xStatus) xStatus.textContent = '⏳ 短縮リンクを取得中です。少し待ってからコピーしてください。'; return; }
        xCopy.disabled = true;
        if (xStatus) xStatus.textContent = '計測用の短縮URLへ変換中…';
        measureWorkLink_(text).then(function (mw) {
          var finalText = mw.text;
          xTxt.value = finalText; updateXCount_(finalText); // 表示＝実際にコピーする文と一致させる
          var n = xCount(finalText);
          if (n > 280) { if (xStatus) xStatus.textContent = '⚠️ Xの換算で' + n + '(上限280)。日本語は1字=2で効きます。短くしてから投稿してください。'; return; }
          function done() { if (xStatus) xStatus.textContent = '✅ コピーしました。Xに貼り付けて投稿してください。'; }
          try {
            if (navigator.clipboard) {
              navigator.clipboard.writeText(finalText).then(done).catch(function () { xTxt.select(); document.execCommand('copy'); done(); });
            } else { xTxt.select(); document.execCommand('copy'); done(); }
          } catch (e) { if (xStatus) xStatus.textContent = '⚠️ コピーに失敗しました。手動で選択してください。'; }
        }).then(function () { xCopy.disabled = false; });
      });
    }
  })();
})();
