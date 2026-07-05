/**
 * bluesky.js — Bluesky 投稿のUI配線（統合版・v19）
 *   本文＝固定文のみ（編集可）。アフィリンクは「作品URL」から投稿時に自動付与、画像も自動添付。
 *   プレビューは実アカウントのアイコンを取得して表示。投稿される見た目そのもの。
 *   投稿手段：①動画作成後の自動投稿（編集できる確認）②今すぐ投稿（単独）③予約投稿。
 *   秘匿情報（アプリパスワード・シークレット）は console に出さない。
 *   v19: アカウント別（acc1/acc2）に設定を分離。gasUrl のみ共通。
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
  // drive-upload.js と scheduler.js が動画作成フロー時に参照するため公開（ソフト参照）
  try { window.BskyExtra = { getFile: function () { return selectedPostFile; } }; } catch (e) {}
  // 一本道の背骨：直近の動画作成で発番された安定動画ID。投稿記録に串刺しで持たせる。
  var currentVideoId = '';

  // ---- 汎用永続化 ----
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  // 動画作成タブの「カテゴリ」チェック状態を読む（キャラ/JK/ギャル/異世界・複数可・キャラ無し＝オリジナル）。
  var MOVIE_ATTRS = [['chara', 'movieAttrChara'], ['jk', 'movieAttrJk'], ['gyaru', 'movieAttrGyaru'], ['isekai', 'movieAttrIsekai'], ['ai', 'movieAttrAi'], ['ol', 'movieAttrOl'], ['soshu', 'movieAttrSoshu']];
  // 動画作成タブの「リビルド(作り直し)」チェック状態。ONなら「同じ作品を作り直した動画」として記録。
  function readRebuild() { var el = $('movieRebuild'); return !!(el && el.checked); }
  // リビルド対象として選んだ投稿履歴のvideoId（未選択なら空）。投稿履歴のGo5History.markRebuiltで「被リビルド」に自動反映する。
  function readRebuildTarget() { var el = $('movieRebuildTarget'); return (el && el.value) || ''; }
  // 「🔁リビルド」チェック時に、どの投稿をリビルドするか投稿履歴から選ぶピッカーを表示・選択肢を最新化する。
  var _rebuildList = []; // 現在ピッカーに出している投稿履歴（videoId→作品データ引き当て用）
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
  // リビルド対象を選んだら、その作品データ（作品URL→作者名/アフィリンク/割引/作品情報、作品状態）を自動反映。
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
  // 作品データ（作品URL/作者/割引/作品状態）を自動反映→作成ボタンへ誘導（残り1タップ）。
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
  // 投稿時の作品状態を判定：新作(discountNew2) > 準新作(movieJunshinsaku) > 旧作(どちらも無し)。
  function readWorkState() {
    var shin = $('discountNew2') && $('discountNew2').checked;
    var jun = $('movieJunshinsaku') && $('movieJunshinsaku').checked;
    return shin ? '新作' : (jun ? '準新作' : '旧作');
  }

  // ---- アカウント別永続化ヘルパ ----
  function acctId() { return (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'); }
  function pk(base) { return base + '__' + acctId(); }

  // ---- アカウント同定（DID）：投稿の所属を「今のUI」ではなくpost_uriのDIDで確定する ----
  // 現在のUIに依存せず特定アカウントのハンドル/DIDを読むための直接キー。
  function handleOfAcct_(a) { try { return (localStorage.getItem('bsky_handle__' + a) || '').trim().replace(/^@/, ''); } catch (e) { return ''; } }
  function acctDid_(a) { try { return (localStorage.getItem('bsky_did__' + a) || '').trim(); } catch (e) { return ''; } }
  function setAcctDid_(a, did) { if (a && /^did:/.test(did || '')) { try { localStorage.setItem('bsky_did__' + a, did); } catch (e) {} } }
  // at://did:plc:XXXX/app.bsky.feed.post/… から DID を取り出す（実際に投稿したアカウントの正体）。
  function didFromUri_(uri) { var m = String(uri || '').match(/^at:\/\/(did:[^/]+)/); return m ? m[1] : ''; }
  // 既知DID → acctId（未キャッシュなら空）。
  function acctOfDid_(did) { if (!did) return ''; if (acctDid_('acc1') === did) return 'acc1'; if (acctDid_('acc2') === did) return 'acc2'; return ''; }
  // 両アカウントのDIDを「ハンドル(⚙設定)→resolveHandle」を正として解決・上書きする（1セッション1回）。
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
        .then(function (j) { if (j && j.did) setAcctDid_(a, j.did); }) // ハンドル解決を正として上書き（汚染治癒）
        .catch(function () {})
        .then(function () { if (--pend === 0) { _didsResolved = true; if (cb) cb(); } });
    });
  }
  function loadA(base) { try { return localStorage.getItem(pk(base)); } catch (e) { return null; } }
  function saveA(base, v) { try { localStorage.setItem(pk(base), v); } catch (e) {} }

  // ---- DOM初期値の保持（空アカウント時のデフォルト） ----
  var DEF = {
    text: (els.text ? els.text.value : ''),
    ytDesc: (els.ytDesc ? els.ytDesc.value : ''),
    ytTags: (els.ytTags ? els.ytTags.value : ''),
    workUrl: '', handle: '', appPw: ''
  };
  // アカウント別の本文テンプレ既定（保存が空のときに使う）。〇 は割引％のプレースホルダ。
  var DEF_TEXT = {
    acc1: 'おすすめ漫画見つけた💕\n\n↓詳細はこちらから🎀 #PR #漫画',
    acc2: '続きが気になっちゃう一冊、みつけた📚\n\n↓続きはこちらから🌙 #PR #漫画'
  };
  function defText() { return DEF_TEXT[acctId()] || DEF_TEXT.acc1; }

  // アカウント別の YouTube説明欄テンプレ既定（保存が空のときに使う）。1行目の短縮URLプレースホルダは投稿後に自動で実URLへ置換。
  var DEF_YTDESC = {
    acc1: '↑ URLを長押し&リンクを開く ↑\nこちらからアクセスしてね💕\n\n\n\n\n【感想📖】',
    acc2: '(短縮URLが入ります)\n\n⬆️URLを長押し&リンクを開く\n続きはこちらからどうぞ💫\n\n\n\n\n📚ひとこと📚'
  };
  function defYtDesc() { return DEF_YTDESC[acctId()] || DEF_YTDESC.acc1; }

  // ---- 一度だけ移行（既存の共有値を現在のアカウント名前空間へコピー） ----
  (function migrateOnce() {
    if (load('acct_split_migrated') === '1') return;
    var a = acctId();
    ['bsky_enable', 'bsky_text', 'bsky_work_url', 'bsky_handle', 'bsky_app_pw', 'bsky_unattended', 'yt_desc', 'yt_tags'].forEach(function (base) {
      var legacy = load(base);
      if (legacy != null && load(base + '__' + a) == null) { try { localStorage.setItem(base + '__' + a, legacy); } catch (e) {} }
    });
    save('acct_split_migrated', '1');
  })();

  // ---- gasUrl（共有）の復元 ----
  if (els.gasUrl) { var gv = load('bsky_gas_url'); if (gv != null) els.gasUrl.value = gv; }

  // ---- 現在アカウントの設定を画面に反映 ----
  function applyAccount() {
    // enable / unattended
    if (els.enable) els.enable.checked = (loadA('bsky_enable') === '1');
    if (els.unattended) els.unattended.checked = (loadA('bsky_unattended') === '1');

    // テキスト系（null なら DEF を使用）
    var tv = loadA('bsky_text'); if (els.text) els.text.value = (tv != null && tv !== '') ? tv : defText();
    if (els.discountSel) els.discountSel.value = '';
    if (els.discountSel2) els.discountSel2.value = '';
    if (els.discountNew) els.discountNew.checked = false;
    if (els.discountNew2) els.discountNew2.checked = false;
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
    var tgv = loadA('yt_tags'); if (els.ytTags) els.ytTags.value = (tgv != null ? tgv : DEF.ytTags);

    // 本文の括弧書き自動クリーンアップ（移行直後の旧注記を除去）
    if (els.text && els.text.value) {
      var cleaned = els.text.value.split('\n').filter(function (line) {
        return !/^\s*[（(].*(自動で追加|自動で添付|自動添付|自動で付).*[)）]\s*$/.test(line);
      }).join('\n').replace(/\n{3,}/g, '\n\n').replace(/^\n+|\n+$/g, '');
      if (cleaned !== els.text.value) { els.text.value = cleaned; saveA('bsky_text', cleaned); }
    }

    // アバター再取得（ハンドル変更に追従）
    var hHandle = (els.handle ? (els.handle.value || '').trim().replace(/^@/, '') : '');
    avatarFor = null; // キャッシュを無効化して再取得を強制
    ensureAvatar(hHandle);

    // 依存UIを更新
    renderPreview();
    updateGasStatus();
    buildTitle();
    if (typeof refreshQuickInfo === 'function') refreshQuickInfo();
  }

  // ---- gasUrl の保存配線（共有） ----
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

  // ---- 🔌 接続テスト（ログインだけ試す・投稿しない）----
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
        '・パスワードは Bluesky の<b>アプリパスワード</b>（<code>xxxx-xxxx-xxxx-xxxx</code>）です（通常のログインPWではありません）。<br>' +
        '・失効している場合があるので<b>作り直して貼り直す</b>と確実です。<br>' +
        '・ハンドルは <code>@</code> 抜き・ドメインまで（例 <code>yourname.bsky.social</code>）。';
    }
    if (/Rate Limit|429/i.test(m)) return '試行が多すぎます。少し時間をおいて再度お試しください。';
    if (/Failed to fetch|NetworkError|load failed/i.test(m)) return '通信に失敗しました。ネット接続をご確認ください。';
    return m;
  }
  if (els.testBtn) {
    els.testBtn.addEventListener('click', function () {
      var c = creds();
      if (!c.handle || !c.appPw) { setTestResult('ハンドルとアプリパスワードを入力してから押してください。', 'off'); return; }
      if (!window.BlueskyCore || !window.BlueskyCore.blueskyVerify) { setTestResult('投稿モジュール未読込(ページを再読み込みしてください)。', 'off'); return; }
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
  if (els.ytTags) els.ytTags.addEventListener('input', function () { saveA('yt_tags', els.ytTags.value); buildTitle(); });

  // ---- 説明欄／本文の編集補助：Qセーブ／Qロード／リセット／元に戻す↶／やり直す↷（アカウント別・確認なし・再読込耐性あり） ----
  // ・Qセーブ＝今の文面を「お気に入りの下書き」として localStorage に退避（アカウント別）。
  // ・Qロード＝退避した下書きを復元。・リセット＝アカウント別の既定テンプレ文「のみ」に戻す。
  // ・元に戻す↶／やり直す↷＝Excel風の取り消し/やり直し。手入力・Qロード・リセットを履歴に積み、双方向に移動できる。
  //   履歴は localStorage（アカウント別）に保存＝再読込しても残る。
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
      // 既存の input リスナ（保存＋プレビュー同期）を確実に走らせる。
      try { cfg.ta.dispatchEvent(new Event('input', { bubbles: true })); } catch (e) {}
    }
    // 変更前の文面を undo に積み、redo を捨てる（新しい編集が入ったら やり直し は無効）。
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
      if (q == null) { if (cfg.info) cfg.info.textContent = 'Q未保存（先にQセーブ）'; return; }
      pushHistory(cfg.ta.value);
      setVal(q);
    });
    if (cfg.reset) cfg.reset.addEventListener('click', function () {
      pushHistory(cfg.ta.value);
      setVal(cfg.defFn()); // 既定テンプレ文「のみ」に戻す（割引文など差し込み分も消える）
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

  // ---- 割引％ドロップダウン（アカウント別の割引文テンプレ） ----
  // acc1：本文1行目の直下に「N%オフのおトク作品！」を挿入／なしで削除。
  // acc2：本文テンプレに含まれる「しかも今なら〇%オフ💕」の数字を差し替え／なしで〇に戻す。
  // build(n, isNew)：isNew=新作チェック時の文面。mark は通常版／新作版の両方にマッチする（切替時に同じ行を差し替えるため）。
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
  // 割引文の挿入/差し替え/削除を行う純粋関数（対象テキストを受け取り新テキストを返す）。isNew=新作用の文面。
  function discApply(text, val, isNew) {
    var cfg = DISC[acctId()] || DISC.acc1;
    var lines = String(text == null ? '' : text).split('\n');
    var idx = -1;
    for (var i = 0; i < lines.length; i++) { if (cfg.mark.test(lines[i])) { idx = i; break; } }
    if (val === '') {
      if (cfg.persistent) { if (idx >= 0) lines[idx] = cfg.placeholder; else lines.splice(Math.min(1, lines.length), 0, cfg.placeholder); }
      else if (idx >= 0) lines.splice(idx, 1);
    } else {
      var nl = cfg.build(val === 'custom' ? '' : val, isNew);  // custom は数字なし（ユーザーが入力）
      if (idx >= 0) lines[idx] = nl; else lines.splice(Math.min(1, lines.length), 0, nl);
    }
    return lines.join('\n');
  }
  // 本文（自動投稿/今すぐ投稿で共通）側の「新作」状態。2つのチェックボックスは同期。
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
  // 投稿確認モーダル内：この投稿のテキスト(pcText)にだけ割引文を反映（保存はしない）。新作チェックも独立。
  function applyDiscountPc() {
    if (els.pcText) els.pcText.value = discApply(els.pcText.value, (els.discountSelPc && els.discountSelPc.value) || '', !!(els.discountNewPc && els.discountNewPc.checked));
  }
  if (els.discountSelPc) els.discountSelPc.addEventListener('change', applyDiscountPc);
  if (els.discountNewPc) els.discountNewPc.addEventListener('change', applyDiscountPc);

  // ---- アカウント切替で再読込 ----
  document.addEventListener('account-changed', function () { applyAccount(); });

  // ---- テンプレ更新の一回限り移行（2026Q2）：旧テンプレ保存値を新テンプレへ。独自文（旧マーカー無し）は保持。----
  (function migrateTemplates2026q2() {
    if (load('feat_2026q2_migrated') === '1') return;
    try {  // ② acc2本文：↓全部はこちらから → ↓続きはこちらから
      var t2 = load('bsky_text__acc2');
      if (t2 && t2.indexOf('↓全部はこちらから') >= 0) save('bsky_text__acc2', t2.replace('↓全部はこちらから', '↓続きはこちらから'));
    } catch (e) {}
    ['acc1', 'acc2'].forEach(function (a) {  // ③ YouTube説明欄：旧共有テンプレ（感想/アクセス文を含む）を新テンプレへ
      try {
        var key = 'yt_desc__' + a, v = load(key);
        if (v == null || v.indexOf('【感想') >= 0 || v.indexOf('こちらからアクセスしてね') >= 0) save(key, DEF_YTDESC[a]);
      } catch (e) {}
    });
    save('feat_2026q2_migrated', '1');
  })();

  // ---- YouTube説明欄テンプレ更新の一回移行（v3）：旧/前テンプレ保存値を最新テンプレへ。独自文は保持。----
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

  // ---- 初期化（移行→applyAccount の順） ----
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
  function composePostText() {
    var caption = (els.text.value || '').replace(/[ \t\r\n]+$/, '');
    var link = resolveAffLink();
    return link ? (caption + '\n\n' + link) : caption;
  }

  // ---- アバター（実アカウントのアイコンを公開APIで取得） ----
  var avatarFor = null, avatarUrl = null, displayNameVal = null;
  function setAvatar(url) {
    if (!els.pvAvatar || !els.pvAvFallback) return;
    if (url) { els.pvAvatar.src = url; els.pvAvatar.hidden = false; els.pvAvFallback.style.display = 'none'; }
    else { els.pvAvatar.hidden = true; els.pvAvatar.removeAttribute('src'); els.pvAvFallback.style.display = ''; }
  }
  // ハンドル上の表示名＝Blueskyの displayName（取得できなければハンドル先頭／未設定なら「あなた」）
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

  // ---- プレビュー画像（単独=選択画像／無ければ動画の元写真／無ければ自動添付の注記） ----
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

  // ---- プレビュー描画（＝投稿される見た目） ----
  function renderPreview() {
    var caption = els.text.value;
    var link = resolveAffLink();
    var html = caption ? highlightLinks(escapeHtml(caption)) : '<span class="ph">（本文）</span>';
    html += link ? ('\n\n<span class="lnk">' + escapeHtml(link) + '</span>')
                 : '\n\n<span class="ph">（投稿時にアフィリンクを自動で追加します）</span>';
    if (els.pvBody) els.pvBody.innerHTML = html;

    if (els.count) { var n = countGraphemes(composePostText()); els.count.textContent = n + ' / 300'; els.count.classList.toggle('over', n > 300); }

    var h = (els.handle.value || '').trim().replace(/^@/, '');
    if (els.pvHandle) els.pvHandle.textContent = h ? ('@' + h) : '@（ハンドル未設定）';
    ensureAvatar(h); // 表示名(displayName)とアバターを設定（pvName はここで反映）

    var f = selectedPostFile || photoFile();
    if (f) showPreviewImage(f); else hidePreviewImage();
  }

  // 動画作成タブの写真選択にも追従（自動投稿の画像プレビュー反映）
  (function () { var p = $('photo'); if (p) p.addEventListener('change', function () { renderPreview(); }); })();

  // ---- 単独投稿の画像選択 ----
  if (els.postImg) {
    els.postImg.addEventListener('change', function () {
      var f = els.postImg.files[0]; if (!f) return;
      selectedPostFile = f;
      if (els.postImgName) els.postImgName.textContent = f.name;
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

  // ---- 確認モーダルの画像選択（動画フロー専用・selectedPostFile とは独立） ----
  if (els.pcImg) {
    els.pcImg.addEventListener('change', function () {
      var f = els.pcImg.files[0]; if (!f) return;
      pcSelectedFile = f;
      if (els.pcImgName) els.pcImgName.textContent = f.name;
      if (els.pcImgClear) els.pcImgClear.style.display = '';
      if (els.pcImgPreview) { els.pcImgPreview.src = URL.createObjectURL(f); els.pcImgPreview.style.display = ''; }
    });
  }
  if (els.pcImgClear) {
    els.pcImgClear.addEventListener('click', function () {
      if (els.pcImgPreview && els.pcImgPreview.src) { URL.revokeObjectURL(els.pcImgPreview.src); els.pcImgPreview.src = ''; els.pcImgPreview.style.display = 'none'; }
      pcSelectedFile = null; if (els.pcImg) els.pcImg.value = '';
      if (els.pcImgName) els.pcImgName.textContent = '未選択（動画の元写真を添付）';
      els.pcImgClear.style.display = 'none';
    });
  }

  // ---- 画像圧縮（Bluesky blob 上限 ≈ 976KB） ----
  var MAX_BYTES = 950000;
  function toBlob(c, q) { return new Promise(function (r) { c.toBlob(r, 'image/jpeg', q); }); }
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
  var PLACEHOLDER_URL = '（投稿するとここに短縮URLが入ります）';
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
    // 1行目が「短縮URLプレースホルダ」or 前回URL or URL なら置換。それ以外（例：↑案内文）は上に差し込む。
    if (f === PLACEHOLDER_URL || f === prevShortUrl || /^https?:\/\//.test(f) || /短縮URL/.test(f)) lines[0] = url;
    else lines.unshift(url);
    els.ytDesc.value = lines.join('\n'); saveA('yt_desc', els.ytDesc.value);
  }
  function setShareOutputs(shortUrl, fallbackUrl) {
    var url = shortUrl || fallbackUrl || '';
    if (els.shortUrlOut) els.shortUrlOut.textContent = url || '（短縮URLを取得できませんでした）';
    if (url) { putUrlTop(url); prevShortUrl = url; lastShortUrl = url; }
  }
  // ★前作の短縮リンクを説明欄に残さない（INC-70）：新しい動画を作ったら、1行目の短縮リンク行をプレースホルダに戻す。
  //   この作品を Bluesky に投稿すると shortenAndShow→putUrlTop が今回の短縮URLへ置換する。
  //   これをしないと、候補から別作品を作った直後にYT説明欄をコピーすると「前作のBluesky投稿」への案内が混入する。
  function resetYtDescShortLink_() {
    prevShortUrl = ''; lastShortUrl = '';
    if (els.shortUrlOut) els.shortUrlOut.textContent = PLACEHOLDER_URL;
    if (!els.ytDesc) return;
    var lines = els.ytDesc.value.split('\n'); if (!lines.length) return;
    var f = (lines[0] || '').trim();
    // 1行目が短縮URL(前作リンク)/プレースホルダ/「短縮URL」表記ならプレースホルダへ戻す（案内文などはそのまま）
    if (/^https?:\/\//.test(f) || f === PLACEHOLDER_URL || /短縮URL/.test(f)) {
      lines[0] = PLACEHOLDER_URL;
      els.ytDesc.value = lines.join('\n'); saveA('yt_desc', els.ytDesc.value);
    }
  }

  // ---- GAS 記録（共有シークレットは廃止） ----
  // workUrl（cid）に対応するFANZA取得済み情報（movieInfoCacheのキャッシュ）を返す。無ければ null。
  function fanzaInfoForWorkUrl_(url) {
    if (!url || !window.buildAffiliateLink) return null;
    var r = window.buildAffiliateLink(url, '');
    var cid = (r && r.ok) ? r.cid : '';
    return (cid && movieInfoCache[cid] && movieInfoCache[cid].title) ? movieInfoCache[cid] : null;
  }
  // drafts.js（下書きの作品名/作者表示）などから参照できるよう公開（読み取りのみ）。
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
  // 戦略ラベル（raw/戦略_画像選びとコメント.md §4）: 狙い(成約/集客)とコメント型(①〜⑧)。
  // 動画ごとのラベルなので投稿後に未設定へ戻す（前作の値が残ると分析を汚す）。
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
      goal: readGoal(),                            // 狙い（成約/集客）
      cmtType: readCmtType(),                      // コメント型（①〜⑧）
      fanzaSnap: fanzaSnapForWorkUrl_(workUrl),   // 履歴カード用（当時価格）
      fanzaInfo: fanzaInfoForWorkUrl_(workUrl) || null  // シート記録用（価格/レビュー）
    };
  }
  // 履歴アイテムから meta を復元（過去データのアカウント矯正で使う）。
  function metaFromHistItem_(it) {
    var attrs = {}; MOVIE_ATTRS.forEach(function (p) { attrs[p[0]] = !!it[p[0]]; });
    return { videoId: it.videoId || '', workUrl: it.workUrl || '', attrs: attrs, workState: it.workState || '', rebuild: !!it.rebuild, rebuildOf: it.rebuildOf || '', goal: it.goal || '', cmtType: it.cmtType || '', fanzaSnap: it.fanzaSnap || null, fanzaInfo: null };
  }

  // record.account でチャンネルを決め、record.meta（凍結済み）優先で記録する。
  // meta が無い旧経路のみ、記録先が現在UIと同じ時に限りUI状態を読む（他アカウントの混入を防ぐ）。
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
    // 狙い×コメント型（あるときだけ送る＝旧GASは未知フィールドを無視するので後方互換）
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
    els.gasStatus.textContent = on ? '記録：ON（すべての投稿をこのGASに記録します）' : '記録：OFF（URL未設定。記録・検証するには設定してください）';
    els.gasStatus.className = 'gas-status ' + (on ? 'on' : 'off');
  }

  // 投稿成功通知（integration.js が書き戻し＋下のリスナが必ず記録）
  // account/meta＝投稿を実行した瞬間のアカウントと凍結メタ（即時投稿は呼び出し時に確定）。
  function notifyPosted(res, text, alt, account, meta) {
    var tags = (String(text).match(/#[^\s#]+/g) || []).join(' ');
    try { document.dispatchEvent(new CustomEvent('bluesky-posted', { detail: { post_uri: res.uri || '', post_url: res.postUrl || '', affiliate: firstUrl(text), hashtags: tags, posted_at: new Date().toISOString(), title: alt || (String(text).split('\n')[0] || ''), account: account || acctId(), meta: meta || null } })); } catch (e) {}
  }
  // すべての投稿を一元的に記録（即時・自動・予約のどれでも必ず記録される）
  document.addEventListener('bluesky-posted', function (e) {
    var d = (e && e.detail) || {};
    var meta = d.meta || null;
    // 所属アカウントの確定：①イベントに載った account（予約/即時で凍結） → ②post_uriのDID照合で矯正。
    var account = d.account || acctId();
    var did = didFromUri_(d.post_uri);
    if (did) {
      if (!acctDid_(account)) setAcctDid_(account, did); // 台帳が空の時だけ学習（権威はハンドル解決＝ensureAcctDids_）
      var byDid = acctOfDid_(did);
      if (byDid && byDid !== account) account = byDid;   // UIの取り違えをDIDで矯正
    }
    var uiSame = (account === acctId());
    var vid = (meta && meta.videoId) || (uiSame ? currentVideoId : '') || '';
    // まず即時記録（短縮URLが遅い/失敗しても投稿は確実に残す）。videoIdがあれば後追いで同一行へ追記。
    recordToSheet({ account: account, meta: meta, title: d.title || '', postUrl: d.post_url, affiliate: d.affiliate, hashtags: d.hashtags, postUri: d.post_uri, videoId: vid });
    shortenAndShow(d.post_url, d.post_uri, d.title, function (res) {
      // 短縮URL確定 → videoId があれば同一行へ upsert（shortUrl=r2計測用 / shareUrl=da.gd表示用）。
      var short = res && (res.shortUrl || res.shareUrl);
      if (vid && short) recordToSheet({ account: account, meta: meta, postUrl: d.post_url, postUri: d.post_uri, videoId: vid, shortUrl: (res.shortUrl || res.shareUrl), shareUrl: res.shareUrl || '' });
    }, account, meta);
  });

  // ---- 過去データのアカウント矯正（DID照合）：short_hist と シート行を正しいアカウントへ移す ----
  // post_uri の DID は「実際に投稿したアカウント」の確定情報。これで誤って別アカウントに入った
  // 履歴/シート行を正しい側へ移す。以後の投稿はDID検証(bluesky-posted)で常に正しく記録される。
  var _acctRepairBusy = false;
  function repairAccountsByDid_(cb) {
    if (_acctRepairBusy) { if (cb) cb({ ok: false, reason: 'busy' }); return; }
    _acctRepairBusy = true;
    ensureAcctDids_(function () {
      var d1 = acctDid_('acc1'), d2 = acctDid_('acc2');
      if (!d1 || !d2) { _acctRepairBusy = false; if (cb) cb({ ok: false, reason: 'DID未解決（両アカウントの⚙ハンドル設定が必要）' }); return; }
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
      });
      // シートも矯正：正チャンネルへ再upsert（当時の投稿日時を保持）＋誤チャンネルの行を削除。
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
  // 起動時に一度だけ自動矯正（過去の取り違えを黙って直す）。成功時のみフラグを立てる。
  function maybeRepairAccountsOnce_() {
    try { if (localStorage.getItem('acct_did_repair_v1') === '1') return; } catch (e) {}
    setTimeout(function () { repairAccountsByDid_(function (r) { if (r && r.ok) { try { localStorage.setItem('acct_did_repair_v1', '1'); } catch (e) {} } }); }, 4000);
  }
  // ハンドル→acctId（⚙設定のハンドルと照合）。postUrlのprofile部がハンドルの時に使う。
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
  // DID台帳の妥当性を毎回検証（force解決＋両DIDの相異＋表示名取得）。分類・移動の前提ゲート。
  //   台帳が壊れている（片方未解決・同一DID）状態で分類すると全量誤移動になり得るため、必ずここを通す。
  function verifyLedger_(cb) {
    ensureAcctDids_(function () {
      var h1 = handleOfAcct_('acc1'), h2 = handleOfAcct_('acc2');
      var d1 = acctDid_('acc1'), d2 = acctDid_('acc2');
      var res = { h1: h1, h2: h2, d1: d1, d2: d2, dn1: '', dn2: '', ok: false, reason: '' };
      if (!h1 || !h2) { res.reason = '両アカウントのハンドルが未設定です（⚙で設定）'; cb(res); return; }
      if (!d1 || !d2) { res.reason = 'DID解決に失敗（ハンドルの綴り・通信を確認。メール形式は不可）'; cb(res); return; }
      if (d1 === d2) { res.reason = '両アカウントのハンドルが同一アカウントを指しています（⚙のハンドル設定を確認）'; cb(res); return; }
      // 表示名（レポートでユーザーが取り違いを目視確認できるように）。失敗しても続行。
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
      verifyLedger: verifyLedger_,               // 分類・移動の前提ゲート（force解決＋相異検証＋表示名）
      classifyByPost: classifyByPost_,           // DID/ハンドルで確定できる所属（yt-clicksの自動分類の土台）
      didReady: function () { return !!(acctDid_('acc1') && acctDid_('acc2') && acctDid_('acc1') !== acctDid_('acc2')); },
      sheetMove: null                            // （将来用フック）
    };
  } catch (e) {}
  // 自動修復は yt-clicks の多段分類(DID/ハンドル/YouTubeチャンネル)へ一本化したのでここでは呼ばない。
  //   （repairAccountsByDid_ は Go5AccountRepair.run として手動フォールバック用に残す）
  void maybeRepairAccountsOnce_;

  // 短縮URLの設定。一次＝自前 link-worker（302即リダイレクト＋KVで開封数を計測）。
  //   ・YT説明欄に貼る用途なのでURL長は問題にならない＝計測できる link-worker を最優先。
  //   ・WORKER_URL は go5-short の払い出しURL。SHARED_SECRET は Worker 側と同値（公開可＝ソフト鍵）。
  //   ・端末ごとに localStorage short_worker_url / short_shared_secret で上書き可。
  //   ・未設定/失敗時は da.gd→TinyURL→長いURL に安全フォールバック（計測できないだけで壊れない）。
  var SHORT = {
    WORKER_URL: 'https://r2.trustsignalbot.workers.dev',
    SHARED_SECRET: 'daremogamewoubawareteikukimihakanpekidekyukyokunoidol'
  };
  try {
    SHORT.WORKER_URL = localStorage.getItem('short_worker_url') || SHORT.WORKER_URL;
    SHORT.SHARED_SECRET = localStorage.getItem('short_shared_secret') || SHORT.SHARED_SECRET;
  } catch (e) {}
  // 検証タブ（yt-clicks.js）が短縮URLのクリック数を /api/stats から読むために公開（ソフト鍵＝公開可）。
  try { window.Go5Short = { WORKER_URL: SHORT.WORKER_URL, SHARED_SECRET: SHORT.SHARED_SECRET }; } catch (e) {}
  function shortWorkerReady() {
    return /^https?:\/\//.test(SHORT.WORKER_URL) && SHORT.SHARED_SECRET && SHORT.SHARED_SECRET.indexOf('PASTE_') !== 0;
  }
  function shortenViaWorker(longUrl) {
    if (!shortWorkerReady()) return Promise.resolve('');
    return fetch(SHORT.WORKER_URL.replace(/\/+$/, '') + '/api/shorten', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Shared-Secret': SHORT.SHARED_SECRET },
      body: 'url=' + encodeURIComponent(longUrl)
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { var s = (j && j.short) || ''; return /^https?:\/\//.test(s) ? s : ''; })
      .catch(function () { return ''; });
  }
  // 外部サービス短縮（GET・テキスト返却）。da.gd → TinyURL の順で保険に使う。
  function shortenVia(api, longUrl) {
    return fetch(api + encodeURIComponent(longUrl))
      .then(function (r) { return r.ok ? r.text() : ''; })
      .then(function (t) { t = String(t || '').trim(); return /^https?:\/\//.test(t) ? t : ''; })
      .catch(function () { return ''; });
  }
  // 案A（da.gdチェーン）：true でr2短縮を da.gd でさらに短縮して“表示用の短いURL”にする。
  //   false にすると従来どおり r2URL をそのまま表示（＝ワンフラグで即ロールバック）。
  var USE_DAGD_CHAIN = true;
  // ── 表示用の短縮プロバイダ（da.gd代替策）──────────────────────────────
  //   上から順に試し、最初に成功した短縮URLを「共有URL」に採用する。
  //   ★da.gd が消えた/不調になったら、この配列を並べ替える or 差し替えるだけで置換できる。
  //   ブラウザからのCORS確認済み：da.gd(Access-Control-Allow-Origin:*)・tinyurl(OK)。
  //   予備候補（復活・CORS確認後に配列へ追加可）：is.gd '/create.php?format=simple&url=' / cleanuri 等。
  //   将来の本命：独自ドメインを r2 に Custom Domain 割当（docs/設計・調査 参照）＝この配列に依存しない。
  var SHARE_SHORTENERS = [
    function (u) { return shortenVia('https://da.gd/s?url=', u); },                    // 1) da.gd（最短・16字前後）
    function (u) { return shortenVia('https://tinyurl.com/api-create.php?url=', u); }  // 2) tinyurl（保険）
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
  //   全プロバイダ失敗時：shareUrl=r2（長いが有効）。r2失敗時：従来フォールバックで計測不可(shortUrl=shareUrl)。
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
  // 後方互換：表示用（da.gd優先）の1本を返す薄いラッパ（手動短縮などで使用）。
  function shortenUrl(longUrl) {
    if (!longUrl) return Promise.resolve('');
    return makeShortAndShare(longUrl).then(function (r) { return r.shareUrl || r.shortUrl || ''; });
  }
  // 投稿履歴タブ(yt-clicks.js)から、過去投稿URLの計測用短縮リンク(r2+da.gd)を生成するために公開。
  try { window.Go5MakeShort = makeShortAndShare; } catch (e) {}
  function shortenAndShow(longUrl, postUri, title, onShort, account, meta) {
    if (!longUrl) return;
    if (els.shortUrlOut) els.shortUrlOut.textContent = '短縮URLを作成中…';
    makeShortAndShare(longUrl).then(function (res) {
      var short = res.shortUrl || '';                  // r2（計測用）
      var share = res.shareUrl || short || longUrl;    // da.gd（表示・概要欄・コピー用）
      // 表示・概要欄への反映は「今のUIと同じアカウントの投稿」のときだけ（別アカウントの記録でUIを書き換えない）。
      if (!account || account === acctId()) setShareOutputs(share, longUrl);
      histAdd({ account: account, meta: meta, title: title, shortUrl: short || share, shareUrl: share, postUrl: longUrl, postUri: postUri, videoId: (meta && meta.videoId) || (!account || account === acctId() ? currentVideoId : '') || '' });
      if (typeof onShort === 'function') onShort({ shortUrl: short, shareUrl: share });
    });
  }

  // JSONP（CORS回避）でGASから値を取得。<script>はCORS対象外なのでPOST応答が読めない環境でも確実。
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

  // ---- 過去の短縮URL履歴（端末内・アカウント別。GAS非依存で確実）----
  function histKeyFor_(a) { return 'short_hist__' + (a || acctId()); }
  function histLoadFor_(a) { try { return JSON.parse(localStorage.getItem(histKeyFor_(a)) || '[]'); } catch (e) { return []; } }
  // 指定アカウントで投稿済みの作品URL一覧（候補タブの「投稿済み」判定用・重複投稿=P0-3の防止に使う）。
  try { window.Go5PostedWorkUrls = function (a) { try { return histLoadFor_(a || acctId()).map(function (h) { return (h && h.workUrl) || ''; }).filter(Boolean); } catch (e) { return []; } }; } catch (e) {}
  // 指定アカウントの投稿履歴アイテム一覧（候補タブの投稿詳細モーダル用＝いつ/何で投稿したか）。
  //   投稿履歴タブの表示(yt-clicks allItems)と同じく「短縮URL履歴 + 手動追加分(verify_manual__)」を合成して返す。
  //   short_hist__ だけだと、手動で追加した投稿が『履歴には見えるのに投稿済みpillが光らない』事故になる（INC-71追補）。
  try { window.Go5PostedItems = function (a) {
    var acc = a || acctId(), out = [];
    try { out = histLoadFor_(acc) || []; } catch (e) { out = []; }
    try { var man = JSON.parse(localStorage.getItem('verify_manual__' + acc) || '[]'); if (man && man.length) out = out.concat(man); } catch (e) {}
    return out;
  }; } catch (e) {}
  function histSaveFor_(a, arr) { try { localStorage.setItem(histKeyFor_(a), JSON.stringify(arr.slice(0, 200))); } catch (e) {} }
  function histKey() { return histKeyFor_(acctId()); }
  function histLoad() { return histLoadFor_(acctId()); }
  function histSaveArr(a) { histSaveFor_(acctId(), a); }
  // rec.account＝所属アカウント（未指定は現在UI）。rec.meta＝凍結済み投稿メタ（あれば優先）。
  function histAdd(rec) {
    if (!rec || !rec.shortUrl) return; // 短縮URLが取れた投稿だけ記録
    var account = rec.account || acctId();
    var meta = rec.meta || null;
    var uiSame = (account === acctId());
    // 作品URL：metaがあればそれ、無ければ（現在UIと同じ時だけ）UIから採取。
    var workUrl = meta ? meta.workUrl : (uiSame ? captureWorkUrl_() : '');
    var a = histLoadFor_(account).filter(function (x) { return rec.postUri ? x.postUri !== rec.postUri : x.shortUrl !== rec.shortUrl; }); // 同一投稿の重複を排除
    var entry = { ts: rec.ts || new Date().getTime(), account: account, title: rec.title || '', shortUrl: rec.shortUrl, shareUrl: rec.shareUrl || '', postUrl: rec.postUrl || '', postUri: rec.postUri || '', videoId: rec.videoId || (meta ? meta.videoId : '') || '' };
    if (rec.rebuildBaseClicks != null) entry.rebuildBaseClicks = rec.rebuildBaseClicks; // リビルド前の動画までのクリック数（投稿履歴の括弧表示用）
    if (workUrl) {
      entry.workUrl = workUrl;
      // 作品cidも串刺しで保存（候補タブの「投稿済み」判定を確実にする）。workUrlはアフィリンク付き/
      //   計測パラメータ付きでも来るので、候補側と同じ normalizeWorkUrl→buildAffiliateLink で正規化して求める。
      try {
        if (window.buildAffiliateLink) {
          var nu = window.normalizeWorkUrl ? window.normalizeWorkUrl(workUrl) : workUrl;
          var cr = nu ? window.buildAffiliateLink(nu, '') : null;
          if (cr && cr.ok && cr.cid) entry.cid = cr.cid;
        }
      } catch (e) {}
      // 投稿時のFANZA価格スナップショット（当時価格）。metaがあればそれを、無ければUIキャッシュから。
      var snap = meta ? meta.fanzaSnap : (uiSame ? fanzaSnapForWorkUrl_(workUrl) : null);
      if (snap) entry.fanzaSnap = snap;
    }
    // 動画作成タブのカテゴリ属性・作品状態を引き継ぐ（manualOnly=手動短縮のときは付けない）
    if (!rec.manualOnly) {
      var attrs = meta ? meta.attrs : (uiSame ? readMovieAttrs() : {});
      MOVIE_ATTRS.forEach(function (p) { if (attrs[p[0]]) entry[p[0]] = true; });
      entry.workState = meta ? meta.workState : (uiSame ? readWorkState() : '旧作'); // 投稿時の作品状態
      var rb = meta ? meta.rebuild : (uiSame ? readRebuild() : false); if (rb) entry.rebuild = true;
      var rbOf = meta ? meta.rebuildOf : (uiSame ? readRebuildTarget() : ''); if (rb && rbOf) entry.rebuildOf = rbOf;
      var gl = meta ? meta.goal : (uiSame ? readGoal() : ''); if (gl) entry.goal = gl;               // 狙い（成約/集客）
      var ct = meta ? meta.cmtType : (uiSame ? readCmtType() : ''); if (ct) entry.cmtType = ct;      // コメント型（①〜⑧）
      if (uiSame) {
        var rbEl = $('movieRebuild'); if (rbEl) rbEl.checked = false; // UIと同じ時だけ一度きりフラグをOFF
        var rbRow = $('movieRebuildTargetRow'), rbSel = $('movieRebuildTarget');
        if (rbSel) rbSel.value = ''; if (rbRow) rbRow.hidden = true;
        // 狙い/コメント型は動画ごとのラベル＝前作の値が残ると分析を汚すため未設定へ戻す（field_も消す）
        var gEl = $('movieGoal'); if (gEl) gEl.value = '';
        var ctEl = $('movieCmtType'); if (ctEl) ctEl.value = '';
        try { localStorage.removeItem('field_movieGoal'); localStorage.removeItem('field_movieCmtType'); } catch (e) {}
      }
    }
    a.unshift(entry);
    histSaveFor_(account, a);
    if (uiSame && els.histList) renderHistory(a); // 現在UIの履歴だけ即描画（他アカウントは切替時に反映）
    // リビルド対象を選んでいたら、その投稿履歴に「被リビルド」の印を自動で付ける。
    //   ★上のhistSaveFor_の後に呼ぶこと＝先に呼ぶと、その変更が上書き保存(a=更新前のスナップショット)で消える。
    if (!rec.manualOnly && rb && rbOf) { try { window.Go5History && window.Go5History.markRebuilt(rbOf, account); } catch (e) {} }
  }
  function fmtTs(ts) { try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return p(d.getMonth() + 1) + '/' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); } catch (e) { return ''; } }
  function loadHistory() { if (els.histList) renderHistory(histLoad()); }
  // 履歴アイテムの同一性キー（破棄/採用フラグの付け外しに使う）。postUri 優先、無ければ shortUrl。
  function histKeyOf(it) { return it && it.postUri ? 'u:' + it.postUri : 's:' + (it && it.shortUrl || ''); }
  function histMatch(it, uri, short) { return uri ? it.postUri === uri : it.shortUrl === short; }
  // 重複（同題名が2件以上）の判定マップを作る。破棄済みは除いて数える＝採用候補の重複だけ目立たせる。
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
    if (!items.length) { els.histList.innerHTML = '<p class="hint">このアカウントの履歴はまだありません（投稿して短縮URLが出ると、ここに自動で貯まります）。</p>'; return; }
    if (!view.length) { els.histList.innerHTML = '<p class="hint">表示できる履歴がありません（すべて破棄済み）。「🗂 破棄も表示」で確認できます。</p>'; return; }
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
  // 破棄/復元（ソフト）。フラグを立てるだけで実体は残る＝復元可。
  function setHistFlag(postUri, short, patch) {
    var a = histLoad();
    a.forEach(function (x) { if (histMatch(x, postUri, short)) { for (var k in patch) x[k] = patch[k]; } });
    histSaveArr(a); renderHistory(a);
  }
  // 本採用トグル。同じ題名の他アイテムの本採用は自動で外す（1題名＝1本採用）。
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
  // 物理削除（ハード）。実体を消す＝取り消し不可。
  function deleteHistory(postUri, short, title) {
    if (!window.confirm('「' + (title || 'この投稿') + '」を履歴から完全に削除しますか？\n（取り消せません。隠すだけなら「🚫 破棄」を使ってください）')) return;
    var a = histLoad().filter(function (x) { return !histMatch(x, postUri, short); });
    histSaveArr(a); renderHistory(a);
  }
  if (els.histRefresh) els.histRefresh.addEventListener('click', loadHistory);
  if (els.histShowDiscarded) els.histShowDiscarded.addEventListener('change', loadHistory);
  // 過去の短縮URL履歴はAFIリンクタブに移設。タブを開いたら最新を描画。
  var affiTabBtn_ = document.getElementById('tabAffi');
  if (affiTabBtn_) affiTabBtn_.addEventListener('click', loadHistory);

  // ---- 手動短縮（アプリ外で単独投稿した分のURLを貼って短縮＋履歴追加）----
  if (els.manualShortBtn) els.manualShortBtn.addEventListener('click', function () {
    var url = (els.manualUrl && els.manualUrl.value || '').trim();
    if (!/^https?:\/\//.test(url)) {
      if (els.manualOut) els.manualOut.textContent = 'URLは http:// か https:// で始めてください';
      if (els.manualResult) els.manualResult.hidden = false;
      return;
    }
    var btn = els.manualShortBtn, orig = btn.textContent;
    btn.disabled = true; btn.textContent = '短縮中…';
    shortenUrl(url).then(function (short) {
      var s = short || url;  // 失敗時は元URLで代替
      if (els.manualOut) els.manualOut.textContent = s;
      if (els.manualResult) els.manualResult.hidden = false;
      // 履歴（投稿履歴タブ）には追加しない。短縮URLを表示するだけ。
      btn.textContent = '✓ 短縮しました'; setTimeout(function () { btn.textContent = orig; btn.disabled = false; }, 1600);
      if (els.manualUrl) els.manualUrl.value = '';
    });
  });
  if (els.manualCopy) els.manualCopy.addEventListener('click', function () { copyText(els.manualOut.textContent, els.manualCopy); });

  // ---- 編集できる確認モーダル（方法①自動投稿） ----
  // 直近に“実際に投稿した”作品URL（取り違え＝前回のまま投稿、の検知用。アカウント別）。
  function lastPostedWork() { return loadA('bsky_last_posted_work') || ''; }
  function setLastPostedWork(v) { saveA('bsky_last_posted_work', v); }

  // 作品URLの取り違え警告（動画作成タブ・確認モーダルで共通利用）。
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
    // 空のときは href を外して「ただのテキスト」にする（# へのページ移動を防ぐ＝リンクとして見せない）。
    if (url) { el.href = url; el.textContent = url; el.style.color = 'var(--accent)'; }
    else { el.removeAttribute('href'); el.textContent = '（URLを入力してください）'; el.style.color = 'var(--sub)'; }
  }
  function updateBskyWorkLink(url) {
    var el = document.getElementById('bskyWorkLink');
    if (!el) return;
    if (url) { el.href = url; el.textContent = url; el.style.color = 'var(--accent)'; }
    else { el.removeAttribute('href'); el.textContent = '（URLを入力してください）'; el.style.color = 'var(--sub)'; }
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

  // #author（作者名）へサークル名/作者名を自動入力。手動で書き換えた値は尊重（自動で入れた値だけ上書き）。
  // 「前回自動入力した値」は localStorage に永続化＝リロード後や翌日でも、残っている前回の
  // 自動入力値を新しい作品のサークル名で正しく上書きできる（ウィザード①今から1本の経路もここを通る）。
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

  // 作品情報表示（作品名・サークル名・定価・セール）。cid→FanzaCore で取得。結果は簡易キャッシュ。
  var movieInfoCache = {}; // cid -> info（{__error} も入れて再取得を抑制）
  var movieInfoSeq = 0;    // 競合防止（URL連続変更時に古い結果で上書きしない）
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
      lines.push('<div style="color:#e0554e;font-weight:700;"><b>セール中</b>：' + yen(info.price) + '（' + info.discountPct + '%OFF）</div>');
    } else {
      lines.push('<div style="color:var(--sub);">セールなし</div>');
    }
    el.style.color = 'var(--ink)';
    el.innerHTML = lines.join('');
    autoApplyDiscountFromInfo_(info); // 現在の割引率を投稿文へ自動反映（取得できない時だけ手動ドロップダウンが効く）
  }
  // 作品URLから取得できた「現在の割引率」を投稿文へ自動反映する。取得できなかった/セール無しの
  // ときは何もしない（＝割引文ドロップダウンでの手動指定がそのまま使える・補助的フォールバック）。
  // ※同じ作品(cid)には1回だけ自動適用する。再描画・キャッシュヒットのたびに発火すると、
  //   ユーザーが手で選び直した割引％を毎回上書きしてしまうため（v164のリグレッション対策）。
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
    var workerUrl = '', secret = '';
    try { workerUrl = localStorage.getItem('fanza_worker_url') || ''; } catch (e) {}
    try { secret = localStorage.getItem('fanza_shared_secret') || ''; } catch (e) {}
    if (!workerUrl || typeof window.FanzaCore === 'undefined') { if (el) { el.style.color = 'var(--sub)'; el.textContent = ''; } return; }
    // キャッシュヒット（成功情報）はそのまま反映。
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
        if (el) { el.style.color = 'var(--sub)'; el.textContent = '（作品情報を取得できませんでした' + (info && info.reason ? '：' + info.reason : '') + '）'; }
      }
    }).catch(function () { if (seq === movieInfoSeq && el) { el.style.color = 'var(--sub)'; el.textContent = ''; } });
  }
  // 連続入力での過剰なFANZA取得を抑える（デバウンス）。
  var movieInfoTimer = null;
  function scheduleMovieWorkInfo(url) {
    if (movieInfoTimer) clearTimeout(movieInfoTimer);
    movieInfoTimer = setTimeout(function () { fetchMovieWorkInfo(url); }, 500);
  }

  // 作品URLを一元的に更新（動画作成タブ⇔投稿タブ⇔localStorage を同期）。fromMovie=動画作成タブ起点。
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

  // 動画作成タブ 作品URL クリア／戻す（クリアで空に、戻すで直前値を復元）
  var movieWorkCleared = '';
  var movieWorkClearBtn = $('movieWorkClear');
  if (movieWorkClearBtn) {
    movieWorkClearBtn.addEventListener('click', function () {
      var cur = (els.movieWorkUrl && els.movieWorkUrl.value) || loadA('bsky_work_url') || '';
      if (cur) movieWorkCleared = cur; // 戻す用に退避
      // ★テキストボックス本体も消す（syncWorkUrl は fromMovie=true 時に movieWorkUrl を触らないため明示クリア）
      if (els.movieWorkUrl) els.movieWorkUrl.value = '';
      syncWorkUrl('', true);
      // 生成表示（投稿バージョンURL・作品情報）も消す
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

      // 「案内する作品URL」を明示＆その場で差し替え可能に（動画は作り直さない）。
      // 変更したら本文末尾のアフィリンクを作り直す。取り違え（前回と同じ）は警告する。
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
      // 画像選択をリセット（モーダルを開くたびに白紙から選択させる）
      pcSelectedFile = null;
      if (els.pcImg) els.pcImg.value = '';
      if (els.pcImgName) els.pcImgName.textContent = '未選択（動画の元写真を添付）';
      if (els.pcImgClear) els.pcImgClear.style.display = 'none';
      if (els.pcImgPreview) { els.pcImgPreview.src = ''; els.pcImgPreview.style.display = 'none'; }
      updateWorkWarn();
      // 背後の入力欄のフォーカスを外してから表示（iOSでカーソル(キャレット)がモーダル上に
      // 浮いて見える・変な位置で点滅する問題の対策）。
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
        // 確定した作品URLを保存＆反映（記録・YT説明欄・プレビューの作品も揃う）。
        if (els.pcWorkUrl && els.workUrl) { var w = els.pcWorkUrl.value.trim(); els.workUrl.value = w; if (els.movieWorkUrl) els.movieWorkUrl.value = w; saveA('bsky_work_url', w); setLastPostedWork(w); paintWorkWarn(els.movieWorkWarn, w); updateMovieWorkLink(w); updateBskyWorkLink(w); }
        var v = els.pcText.value; cleanup(); resolve(v);
      }
      function cancel() { cleanup(); resolve(null); }
      els.pcOk.addEventListener('click', ok); els.pcCancel.addEventListener('click', cancel);
    });
  }

  // ---- 方法②：今すぐ投稿（単独） ----
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
      (f ? compressFile(f) : Promise.resolve(null))
        .then(function (blob) { return window.BlueskyCore.blueskyPostRaw({ identifier: c.handle, appPassword: c.appPw, text: text, imageBlob: blob, alt: alt }); })
        .then(function (res) { setPostStatus('✅ 投稿しました → <a href="' + res.postUrl + '" target="_blank" rel="noopener">投稿を開く</a>', true); notifyPosted(res, text, alt, postAcct, postMeta); })
        .catch(function (e) { setPostStatus('⚠️ 投稿に失敗：<br>' + friendlyLoginError(e && e.message ? e.message : e), true); })
        .then(function () { els.postNow.disabled = false; });
    });
  }

  // ---- 無人予約（Phase5）：GASへ送信し、時間トリガーが投稿（タブを閉じてもOK） ----
  function reserveUnattended(text, blob, ms, slotId, meta) {
    var gasUrl = (els.gasUrl.value || '').trim();
    if (!gasUrl) { setPostStatus('無人予約には⚙の「記録用URL（GAS）」設定が必要です。'); return; }
    var payload = { type: 'reserve', channel: (window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'), scheduled_at: new Date(ms).toISOString(), text: text, slot_id: slotId || '' };
    if (meta) payload.meta = meta; // 動画メタを中継＝GAS無人投稿でも videoId/カテゴリ/作品状態/リビルド元が記録される（D-1）
    function send() {
      setPostStatus('☁️ 無人予約を送信中…');
      fetch(gasUrl, { method: 'POST', body: JSON.stringify(payload) })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j && j.ok) setPostStatus('☁️ 無人予約しました：' + new Date(ms).toLocaleString('ja-JP') + '（タブを閉じてもOK）');
          else setPostStatus('予約に失敗：' + ((j && j.error) || '不明'));
        })
        .catch(function () { setPostStatus('予約送信に失敗（GAS URL・通信をご確認ください）。'); });
    }
    if (blob) { var fr = new FileReader(); fr.onload = function () { payload.image = fr.result; send(); }; fr.onerror = function () { send(); }; fr.readAsDataURL(blob); }
    else send();
  }

  // ---- 方法③：予約投稿（無人＝GAS／開いている間＝端末タイマー） ----
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
      if (unattended) {
        var _uMeta = captureMeta_(); // 予約時に動画メタを凍結（発火時UIに依存させない・D-1）
        (f ? compressFile(f) : Promise.resolve(null)).then(function (blob) { reserveUnattended(text, blob, ms, slotId, _uMeta); });
        return;
      }
      var c = creds();
      if (!c.handle || !c.appPw) { setPostStatus('⚙設定でハンドルとアプリパスワードを入れてください（無人予約ならGAS設定）。'); return; }
      if (!window.Scheduler) { setPostStatus('スケジューラ未読込。'); return; }
      var _mMeta = captureMeta_(); // 予約時のアカウント・メタを凍結（発火時のUI状態に依存させない）
      (f ? compressFile(f) : Promise.resolve(null)).then(function (blob) {
        window.Scheduler.reserve({ slotId: slotId, text: text, imageBlob: blob, scheduledAtMs: ms, alt: alt, handle: c.handle, appPw: c.appPw, account: acctId(), meta: _mMeta });
        setPostStatus('⏰ 予約しました：' + new Date(ms).toLocaleString('ja-JP') + '（このタブを開いている間に自動投稿）');
      });
    });
  }

  // ---- 方法①：動画作成後の自動投稿（編集できる確認） ----
  // ── 🔁リビルドの「Bluesky投稿引き継ぎ」 ──────────────────────────────
  // リビルド元と同じ作品なら、Blueskyへ再投稿せず前回の投稿（postUri/短縮URL/クリック計測）を
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
  // 引き継ぎ実行（履歴は「置き換え」＝旧アイテムはローカル履歴から消え、新アイテムがURL群を引き継ぐ。
  //   旧動画のクリック実績は rebuildBaseClicks として新アイテムに保存＝投稿履歴で「総合値(旧値)」表示。
  //   記録シートは videoId 別行なので旧行は残る＝分析はシートで可能・新行はリビルド元IDで系譜が追える）。
  function inheritRebuildPost_(old, ev) {
    var account = acctId(), meta = captureMeta_();
    var newVid = (ev && ev.detail && ev.detail.videoId) || currentVideoId || '';
    var title = (ev && ev.detail && ev.detail.title) || old.title || '';
    var baseClicks = null; // リビルド時点までのクリック数（括弧表示のスナップショット）
    try { if (window.Go5Clicks && old.shortUrl) baseClicks = window.Go5Clicks.of(old.shortUrl); } catch (e) {}
    histAdd({ account: account, meta: meta, title: title, shortUrl: old.shortUrl || '', shareUrl: old.shareUrl || old.shortUrl || '', postUrl: old.postUrl || '', postUri: old.postUri || '', videoId: newVid, rebuildBaseClicks: baseClicks });
    recordToSheet({ account: account, meta: meta, title: title, postUrl: old.postUrl || '', postUri: old.postUri || '', shortUrl: old.shortUrl || '', shareUrl: old.shareUrl || '', videoId: newVid });
    _skipNextYtReset = true; // 直後に走る video-created の説明欄リセット(INC-70)を1回スキップ（旧短縮URLを残す）
    setShareOutputs(old.shareUrl || old.shortUrl || '', old.postUrl || ''); // YT説明欄へも旧短縮URLを反映
    setBskyStatus('🔁 リビルド：Blueskyへは再投稿せず、前回の投稿を引き継ぎました（短縮URL・クリック計測は継続）。');
  }
  // 引き継ぎ条件を満たせば確認のうえ実行して true（自動投稿ON/OFFに関わらず video-created 直後に判定）。
  function maybeInheritRebuild_(ev) {
    try {
      if (!readRebuild()) return false;
      var rbVid = readRebuildTarget(); if (!rbVid) return false;
      var old = null; histLoad().forEach(function (x) { if (x.videoId === rbVid) old = x; });
      if (!old || (!old.postUri && !old.shortUrl)) return false; // 引き継げる投稿が無い
      if (!sameWorkCid_(old.workUrl, captureWorkUrl_())) return false; // 別作品なら通常フロー（新規投稿）
      if (!window.confirm('リビルド元と同じ作品です。\nBlueskyへは再投稿せず、前回の投稿（短縮URL・クリック計測）をこの動画に引き継ぎます。よろしいですか？\n\n（キャンセル＝通常どおりBlueskyへ新規投稿します）')) return false;
      inheritRebuildPost_(old, ev);
      return true;
    } catch (e) { return false; }
  }

  function handleVideoCreated(ev) {
    if (maybeInheritRebuild_(ev)) return; // 🔁同一作品のリビルド＝前回のBluesky投稿を引き継ぎ（再投稿しない）
    if (!els.enable || !els.enable.checked) return;
    var c = creds();
    if (!c.handle || !c.appPw) { setBskyStatus('「🦋 投稿」タブの⚙でハンドルとアプリパスワードを入れると自動投稿します（今回はスキップ）。'); return; }
    if (!window.BlueskyCore) { setBskyStatus('投稿モジュール未読込。'); return; }
    var composed = composePostText();
    if (!composed.trim()) { setBskyStatus('投稿本文が空です（「🦋 投稿」タブで入力）。'); return; }
    var alt = (ev && ev.detail && ev.detail.title) ? String(ev.detail.title) : (composed.split('\n')[0] || '');
    confirmEditable(composed, null).then(function (edited) {
      if (edited == null) { setBskyStatus('自動投稿をキャンセルしました。'); return; }
      if (!edited.trim()) { setBskyStatus('本文が空のため中止しました。'); return; }
      // 予約時刻チェック（movieSchedAt に値があれば即時投稿せず予約）
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
          notifyPosted(res, edited, alt, _postAcct, _postMeta);
          // 実際に添付した画像を Drive の同じ動画フォルダへ後追い保存（drive-upload.js が購読）。
          try {
            if (imgFile) document.dispatchEvent(new CustomEvent('bsky-image-posted', { detail: { file: imgFile, title: (ev && ev.detail && ev.detail.title) || '', videoId: (ev && ev.detail && ev.detail.videoId) || '' } }));
          } catch (e2) {}
        })
        .catch(function (e) { setBskyStatus('⚠️ 投稿に失敗しました：<br>' + friendlyLoginError(e && e.message ? e.message : e), true); });
    });
  }
  document.addEventListener('video-created', handleVideoCreated);
  // 自動投稿のON/OFFに関わらず、発番された安定動画IDは常に保持（投稿記録の背骨キー）。
  var _skipNextYtReset = false; // リビルド引き継ぎ時は説明欄の旧短縮URLを保持する（リセットを1回スキップ）
  document.addEventListener('video-created', function (e) {
    var d = (e && e.detail) || {};
    if (d.videoId) currentVideoId = d.videoId;
    if (_skipNextYtReset) { _skipNextYtReset = false; return; } // 引き継ぎ済み＝旧短縮URLが正
    resetYtDescShortLink_(); // 新作の動画＝前作の短縮リンクを説明欄から消す（この作品を投稿すると新リンクが入る・INC-70）
  });
  // ※旧「Bsky添付画像を自動ダウンロード」は廃止（iPhoneで毎回『ダウンロードしますか？』が
  //   出て邪魔＆Drive保存と干渉するため）。添付画像は投稿成功時に Drive へ保存する（drive-upload.js）。

  if (els.shortUrlCopy) els.shortUrlCopy.addEventListener('click', function () { if (lastShortUrl) copyText(lastShortUrl, els.shortUrlCopy); });
  if (els.ytCopy) els.ytCopy.addEventListener('click', function () { if (els.ytDesc) copyText(els.ytDesc.value, els.ytCopy); });
  if (els.ytInsert) els.ytInsert.addEventListener('click', function () { if (lastShortUrl) putUrlTop(lastShortUrl); });

  var lastTitle = '';
  var topEl = document.getElementById('top');
  var ytTagWarnEl = document.getElementById('ytTagWarn');
  // S-3: タグは3〜5個（#Shorts＋ジャンル語＋作品固有）が目安。タイトル上に表示されるのは上位3個のみ。
  //   公式仕様: 60個超で全タグ無視（「15個で無効」は二次ブログ由来の誤情報と判明・2026-07-05裏取り済
  //   https://support.google.com/youtube/answer/6390658）。※非破壊：ユーザーのタグは書き換えず注意表示のみ。
  function updateTagWarn(tags) {
    if (!ytTagWarnEl) return;
    var list = (tags.match(/#[^\s#]+/g) || []);
    var n = list.length;
    var hasShorts = list.some(function (t) { return /^#shorts$/i.test(t); });
    var msg = '', col = 'var(--sub)';
    if (n > 60) { msg = '⚠ タグが' + n + '個＝60個超はYouTubeが全タグを無視します（公式仕様）。3〜5個に絞ってください。'; col = '#e6a14e'; }
    else if (n === 0) { msg = 'ℹ タグ未設定。#Shorts＋ジャンル語で3〜5個入れるとフィードで有利です。'; col = 'var(--sub)'; }
    else if (n < 3) { msg = 'ℹ タグ' + n + '個。#Shorts＋ジャンル語＋作品固有で3〜5個が目安です。'; col = 'var(--sub)'; }
    else if (n > 5) { msg = 'ℹ タグ' + n + '個。表示されるのは上位3個だけ＝3〜5個に絞ると評価が集中します。' + (hasShorts ? '' : ' #Shorts も入れると◎。'); col = 'var(--sub)'; }
    else { msg = '✓ タグ' + n + '個（3〜5個）' + (hasShorts ? '' : '・#Shorts を足すと◎'); col = hasShorts ? '#7fb98a' : 'var(--sub)'; }
    ytTagWarnEl.textContent = msg;
    ytTagWarnEl.style.color = col;
  }
  function buildTitle() {
    if (!els.ytTitle) return;
    var comment = (topEl && topEl.value ? topEl.value.trim() : '');
    var tags = (els.ytTags && els.ytTags.value ? els.ytTags.value.trim() : '');
    var title = comment + (comment && tags ? ' ' : '') + tags;
    lastTitle = title;
    els.ytTitle.textContent = title || '（「動画作成」タブのコメントを入れると題名が出ます）';
    updateTagWarn(tags);
  }
  if (els.ytTags) els.ytTags.addEventListener('input', buildTitle);
  if (topEl) topEl.addEventListener('input', buildTitle);
  var tabPostBtn = document.getElementById('tabPost'); if (tabPostBtn) tabPostBtn.addEventListener('click', buildTitle);
  if (els.ytTitleCopy) els.ytTitleCopy.addEventListener('click', function () { if (lastTitle) copyText(lastTitle, els.ytTitleCopy); });
  buildTitle();

  // ---- ⏰ 予約して投稿（動画作成タブ） ----
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
})();
