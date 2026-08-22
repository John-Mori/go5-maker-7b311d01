/**
 * stock.js — 動画ドラフト管理。
 * 「📦 ドラフトで作成」で動画を生成してここへ保存し、投稿直前まで手元に置いておける。
 * 動画blob/サムネは Go5Idb(IndexedDB go5store/kv)、メタデータリストは localStorage。
 * 「⬇ 動画DL」で再DL、「🦋 投稿タブへ」で引き継ぎ、「✅ 投稿完了」でYouTube URL記録 + Drive UP。
 */
(function () {
  'use strict';

  var MAX = 20;
  var META_KEY = 'go5_stock_meta';
  // 作成履歴=投稿完了(③作成完了)でドラフト本体から外した項目を、復元できるように残す退避先(Chami指示④
  //   「消えてしまうのが怖いので作成履歴に残して復元できるように」)。動画/サムネのidb blobは消さず残すので
  //   復元すれば動画DL・再投稿まで丸ごと戻る。上限を超えた古い分だけ blob ごと本当に消える。
  var ARCHIVE_KEY = 'go5_stock_archive';
  var ARCHIVE_MAX = 30;
  var PH_URL_ = '(X投稿リンクを入力後、ここに短縮URLが入る)';

  // 動画の「存在」ではなく、最低限使える実体かを全保存境界で同じ規則にする。
  // core/video-integrity.js がキャッシュ不整合で未読込でも、空/極小Blobだけは必ず拒否する。
  function isUsableVideoBlob_(blob) {
    var vi = window.Go5VideoIntegrity;
    if (vi && vi.isUsableBlob) return vi.isUsableBlob(blob);
    return !!(blob && typeof blob.size === 'number' && blob.size >= 16 * 1024);
  }

  // 説明欄の短縮URLは「タップで実際に遷移できるリンク」だけで表示(Chami 2026-07-28指示=短縮URLのみの
  //   テキストボックスは不要・リンクだけでいい)。★短縮URLの実体はリンク要素の dataset.url に保持し、
  //   保存とコピーはそこから読む(readonlyボックスは撤去)。空なら隠す。リンク先頭は textarea の左縦線に揃える。
  // 自前短縮ドメイン(5mgl/yoz2)なら true。(link-workerが払い出す計測リンクだけ ?nc=1 を足す判定用)
  function isOurShort_(u) {
    try { var og = window.Go5Short; if (og && og.ourBase) return !!og.ourBase(u); } catch (e) {}
    return /\/\/(?:5mgl\.com|yoz2\.com)\//.test(String(u || ''));
  }
  // 説明欄アクション行(説明欄をコピー／動画DL／生成短縮URL)を必ず1行に収める(Chami依頼2026-08-03)。
  //   端末が狭い(iPhone16 等)と短縮URLが下段へ改行落ちしていた。ボタンは固定幅のまま、
  //   短縮URLの文字サイズだけを、行が溢れる間だけ段階的に縮めて1行へ収める(下限あり=可読性維持)。
  function fitDescRow_() {
    try {
      var row = $('draftDescRow'), lk = $('draftYtDescUrlLink');
      if (!row || !lk || lk.style.display === 'none') return;
      var px = 13, floor = 8, guard = 0; // 13px≒0.82rem を基準に、下限8pxまで縮める
      lk.style.fontSize = px + 'px';
      while (row.scrollWidth > row.clientWidth + 1 && px > floor && guard < 30) {
        px -= 0.5; lk.style.fontSize = px + 'px'; guard++;
      }
    } catch (e) {}
  }
  // 端末回転・幅変化でも1行維持を再計算(モーダルが無ければ fitDescRow_ 側で握りつぶす)。
  try { window.addEventListener('resize', fitDescRow_); } catch (e) {}
  function setDescUrlSlot_(url) {
    var lk = $('draftYtDescUrlLink');
    var ok = url && /^https?:\/\//.test(url);
    if (lk) {
      if (ok) {
        // ★アプリ内から自分の計測リンクをタップしても加算しない(Chami依頼2026-08-03③)。
        //   href(=このサイト内でのタップ先)にだけ ?nc=1 を付ける。初回タップで worker が go5nc Cookie を
        //   立て、以後この端末の同ドメインへのアクセスは全て除外される(link-ledger と同方式)。
        //   表示テキスト/コピー元(dataset.url)/概要欄本文は素のURLのまま=YouTube視聴者の実クリックは数える。
        var href = (isOurShort_(url) && !/[?&]nc=1(?:&|$)/.test(url)) ? (url + (url.indexOf('?') < 0 ? '?nc=1' : '&nc=1')) : url;
        lk.href = href; lk.textContent = url; lk.dataset.url = url; lk.style.display = 'inline-block';
      }
      else { lk.removeAttribute('href'); lk.textContent = ''; lk.dataset.url = ''; lk.style.display = 'none'; }
    }
    // ★短縮URLを概要欄テキストボックス(draftYtDescText)の最上段にも入れる(Chami指示2026-07-29)。
    //   既存の先頭URL行(+続く空行)を一旦剥がしてから入れ直す=貼り替えても重複しない。空なら剥がすだけ。
    //   ここ1箇所に集約=貼り付け時(applyXPostUrl_)もモーダル再表示時(openPostModal_)も同じ経路で最上段に乗る。
    var ta = $('draftYtDescText');
    if (ta) {
      var lines = String(ta.value || '').split('\n');
      if (lines.length && /^https?:\/\//.test((lines[0] || '').trim())) {
        lines.shift(); if (lines.length && lines[0].trim() === '') lines.shift();
      }
      var body = lines.join('\n');
      ta.value = ok ? (url + (body ? '\n\n' + body : '')) : body;
    }
    // レイアウト確定後に1行フィットを計算(表示直後は幅が未確定なため rAF で1フレーム待つ)。
    if (typeof requestAnimationFrame !== 'undefined') requestAnimationFrame(fitDescRow_); else fitDescRow_();
  }
  // 貼り付けたX投稿リンクを link-worker で短縮してスロットへ入れる(全滅時は生URL)。
  function applyXPostUrl_(raw, btn) {
    raw = (raw || '').trim();
    var xin = $('draftXPostUrl'); if (xin) xin.value = raw;
    if (!raw) { setDescUrlSlot_(''); saveDraftPost_(); return; }
    if (btn) btn.textContent = '短縮中...';
    var p = window.Go5MakeShort ? window.Go5MakeShort(raw) : Promise.resolve(null);
    p.then(function (r) {
      var shortUrl = (r && (r.shareUrl || r.shortUrl)) || raw;
      setDescUrlSlot_(shortUrl); saveDraftPost_();
      if (btn) { btn.textContent = '貼り付けました'; setTimeout(function () { btn.textContent = '貼り付け'; }, 2000); }
    }).catch(function () {
      setDescUrlSlot_(raw); saveDraftPost_();
      if (btn) btn.textContent = '貼り付け';
    });
  }

  // 保存済みの外部短縮(da.gd/tinyurl等・生X-URLが手元に無い旧レコード)を、ワーカーの /api/resolve で
  //   最終遷移先まで追い、それがX投稿URLなら applyXPostUrl_ で自前ドメイン短縮へ格上げする(=YouTube→Xの計測を取り戻す)。
  //   ★2026-08-04 恒久策(Chami「da.gdになってる、大問題」)。da.gdが落ちていれば resolve が失敗＝現状維持(悪化しない)。
  function healExternalXShort_(extShort) {
    try {
      var og = window.Go5Short;
      var base = (og && og.WORKER_URL || '').replace(/\/+$/, '');
      var sec = og && og.SHARED_SECRET;
      if (!base || !sec || !extShort) return;
      fetch(base + '/api/resolve?secret=' + encodeURIComponent(sec) + '&url=' + encodeURIComponent(extShort))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          var fin = (j && j.ok && j.final) || '';
          if (/^https?:\/\/(?:[^/]*\.)?(?:x\.com|twitter\.com)\//.test(fin)) applyXPostUrl_(fin, null);
        }).catch(function () {});
    } catch (e) {}
  }

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function fmtTs(ts) {
    try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); }
    catch (e) { return ''; }
  }

  function loadMeta() { try { return JSON.parse(localStorage.getItem(META_KEY) || '[]') || []; } catch (e) { return []; } }
  // ★localStorage逼迫でメタ書込みが無言失敗すると、commitPendingDraft_ の読み戻しが draft-meta-readback-failed で
  //   落ち、ドラフトが一覧に載らず遷移もしない(蓄積の多い月詠み=acc1で顕在化。実機の保留バナー内訳=
  //   手元:idb-timeout / 雲:draft-meta-readback-failed・Chami報告2026-08-16 msg1538578410564096130/第1弾計測で確証)。
  //   thumbDataUrl はメタ内で唯一の重い項目(≤160KB)で、IDB(stock_t_<id>)の複製=カードは resolveThumb_ が
  //   IDBからも引ける。枠が溢れたら古い順に thumbDataUrl を剥がして必ず書き切る(非破壊=サムネはIDBから復元)。
  //   ★元の meta オブジェクトは壊さず、localStorage へ落とす直列化用の複製だけを痩せさせる。
  function writeMetaResilient_(arr) {
    var full = (arr || []).slice(0, MAX);
    try { localStorage.setItem(META_KEY, JSON.stringify(full)); return true; } catch (e) {}
    var lean = full.map(function (m) { return m; }); // 永続化用の別列(要素は共有=剥がす時だけ複製へ差し替える)
    for (var i = lean.length - 1; i >= 0; i--) {      // 古い順(末尾から)にthumbDataUrlを剥がす=最新の今作ったドラフトは最後まで残す
      var m = lean[i];
      if (m && m.thumbDataUrl) {
        var c = {};
        for (var k in m) { if (Object.prototype.hasOwnProperty.call(m, k) && k !== 'thumbDataUrl') c[k] = m[k]; }
        lean[i] = c;
        try { localStorage.setItem(META_KEY, JSON.stringify(lean)); return true; } catch (e2) {}
      }
    }
    while (lean.length > 1) {                          // 全thumbを剥がしても入らない=古い件から件数を削り、最新は必ず残す
      lean.pop();
      try { localStorage.setItem(META_KEY, JSON.stringify(lean)); return true; } catch (e3) {}
    }
    return false;
  }
  // ★localStorage逼迫で「最新1件のlean metaすら入らない」時、再取得可能なキャッシュ(Go5Keys.isPurgeable)
  //   だけを緊急退避して1回だけ書き直す=最新ドラフトを必ず書き切る(draft-meta-readback-failed の根治・
  //   Fable5診断B-1・2026-08-18)。正本・唯一コピー(画像base64/履歴/手動宣言)は絶対に消さない。
  function purgeableSweep_() {
    if (!(window.Go5Keys && window.Go5Keys.isPurgeable)) return 0;
    var keys = [];
    try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (k && window.Go5Keys.isPurgeable(k)) keys.push(k); } } catch (e) {}
    var freed = 0;
    keys.forEach(function (k) { try { localStorage.removeItem(k); freed++; } catch (e) {} });
    return freed;
  }
  // ★戻り値=書けたか(bool)。書けた時だけ同期をkickする——書けていないのに kickSync すると、新ドラフトを
  //   含まない旧metaを雲へpushして「雲の台帳からも新ドラフトが消える」二重事故になる(旧コードのバグ)。
  function saveMeta(arr) {
    var ok = writeMetaResilient_(arr);
    if (!ok && purgeableSweep_() > 0) ok = writeMetaResilient_(arr);
    if (ok) kickSync_();
    return ok;
  }

  // ドラフトは「動画が手元または雲へ着地した後」にだけ一覧へ確定する二相コミット。
  // 失敗中のメタを先に go5_stock_meta へ入れると、黒いサムネ/DL不能の幽霊カードが残るため禁止する。
  var _pendingDraftMeta = {};
  var _pendingDraftCommit = {};
  function commitPendingDraft_(id) {
    var existing = loadMeta().filter(function (m) { return m && m.id === id; })[0];
    if (existing) return Promise.resolve(existing);
    if (_pendingDraftCommit[id]) return _pendingDraftCommit[id];
    var meta = _pendingDraftMeta[id];
    if (!meta) return Promise.reject(new Error('pending-draft-meta-missing'));
    var job = Promise.resolve().then(function () {
      var arr = loadMeta().filter(function (m) { return m && m.id !== id; });
      arr.unshift(meta);
      saveMeta(arr);
      var saved = loadMeta().filter(function (m) { return m && m.id === id; })[0];
      if (!saved) throw new Error('draft-meta-readback-failed');
      return saved;
    });
    _pendingDraftCommit[id] = job.then(function (saved) {
      delete _pendingDraftCommit[id]; delete _pendingDraftMeta[id]; return saved;
    }, function (err) {
      delete _pendingDraftCommit[id]; throw err;
    });
    return _pendingDraftCommit[id];
  }
  function loadArchive() { try { return JSON.parse(localStorage.getItem(ARCHIVE_KEY) || '[]') || []; } catch (e) { return []; } }
  // ★作成履歴(最大30件)は 1件ごとに thumbDataUrl(≤160KB)を抱える=最大約4.8MB。iOS Safariの約5MBの箱に
  //   張り付く「最後の要因」で、ここが埋まると saveMeta(下書き)も saveArchive 自身も無言失敗して
  //   「保存に失敗/遷移しない/画像が消える」を再燃させる(localStorage逼迫=①②③の共通根・Fable5診断2026-08-17)。
  //   旧 saveArchive は setItem 1発で、QuotaExceeded を握り潰して更新ごと失っていた=止血が無い。
  //   → writeMetaResilient_ と同型の段階縮退にする:①素で書く→②古い順に thumbDataUrl を剥がす(サムネは
  //   IDB stock_t_<id> / R2 stock:imgs から resolveThumb_ が復元=非破壊)→③それでも入らなければ古い件から
  //   件数を削り最新は必ず残す(作成履歴は id単位 union 同期=ローカルで落ちても他端末/雲から復活する非破壊)。
  //   ★元の meta オブジェクトは壊さず、直列化用の複製だけを痩せさせる(表示中カードのサムネを消さない)。
  //   ※これは「箱を溢れさせない止血」。同期越しに thumb が remote から union 復活する分の根治(PUSH payload
  //     サニタイズ)は別スライス(Fable5案2・寝る前Go候補)。ここは容量逼迫時に必ず書き切ることだけを保証する。
  function writeArchiveResilient_(arr) {
    var full = (arr || []).slice(0, ARCHIVE_MAX);
    try { localStorage.setItem(ARCHIVE_KEY, JSON.stringify(full)); return true; } catch (e) {}
    var lean = full.map(function (m) { return m; }); // 直列化用の別列(要素は共有=剥がす時だけ複製へ差し替える)
    for (var i = lean.length - 1; i >= 0; i--) {      // 古い順(末尾から)に thumbDataUrl を剥がす=最新は最後まで残す
      var m = lean[i];
      if (m && m.thumbDataUrl) {
        var c = {};
        for (var k in m) { if (Object.prototype.hasOwnProperty.call(m, k) && k !== 'thumbDataUrl') c[k] = m[k]; }
        lean[i] = c;
        try { localStorage.setItem(ARCHIVE_KEY, JSON.stringify(lean)); return true; } catch (e2) {}
      }
    }
    while (lean.length > 1) {                          // 全 thumb を剥がしても入らない=古い件から件数を削り最新は残す
      lean.pop();
      try { localStorage.setItem(ARCHIVE_KEY, JSON.stringify(lean)); return true; } catch (e3) {}
    }
    return false;
  }
  // ★S2=保存側の thumb detox。同期を待たずこの端末のLSを即痩せさせ、次の同期までの「肥大の窓」を潰す
  //   (窓の間の候補/下書き書込が容量で落ちる=再作成で画像が消える の残り火を断つ)。新しい keepN件だけ
  //   inline thumb を残し、古い分は剥がす(サムネは IDB stock_t_<id> / R2 stock:imgs から resolveThumb_ が復元=非破壊)。
  //   剥がすのは直列化する配列だけ=表示中カードの meta.thumbDataUrl は触らない(Go5Sync.slimStockArchive は複製を返す)。
  //   Go5Sync 未ロード/純関数無しの古いJSでは素通し(fail-open)=従来動作。雲越しの根治は core/sync.js の S3。
  function slimArchiveForWrite_(arr) {
    try {
      if (!(window.Go5Sync && typeof window.Go5Sync.slimStockArchive === 'function')) return arr;
      var slimStr = window.Go5Sync.slimStockArchive(JSON.stringify(arr || []), 3);
      var slim = JSON.parse(slimStr);
      return Array.isArray(slim) ? slim : arr;
    } catch (e) { return arr; }
  }
  function saveArchive(arr) {
    var lean = slimArchiveForWrite_(arr);
    var ok = writeArchiveResilient_(lean);
    if (!ok && purgeableSweep_() > 0) ok = writeArchiveResilient_(lean); // 再取得可能なキャッシュだけ緊急退避して再挑戦
    return ok;
  }
  // 全端末同期(Go5Sync)へ即時反映を促す。(未設定・未ロードなら何もしない)ドラフトを保存したら他端末へ運ぶ。
  // ドラフト作成/投稿完了/編集は頻度が低くユーザー操作＝即時push(flushSync)で相手端末へ渡す。
  //   これで相手は「今すぐ同期」を押さずとも、アプリを開いた時の自動pullだけで最新が出る(Chami依頼2026-08-03)。
  //   flushSync 未搭載の古いJSでも壊れないよう requestSync へフォールバック。
  // ★複数キーを続けて書く操作(投稿完了=墓標+meta+作成履歴の3書込)は、途中の kickSync を抑止して
  //   「全部書き終えてから1回だけ push」する。これをしないと最初の flushSync が走った瞬間の
  //   localStorage(=墓標だけ書けて meta/archive はまだ旧値)がスナップされ、作成履歴の反映が
  //   後続のデバウンス push 頼みになる=スマホを閉じると凍って相手端末に作成履歴が渡らない(Chami報告2026-08-04)。
  var _syncBatch = 0;
  function kickSync_() {
    if (_syncBatch) return; // バッチ中は溜めて、batchSync_ の末尾で1回だけ push する
    try {
      if (window.Go5Sync && window.Go5Sync.flushSync) window.Go5Sync.flushSync();
      else if (window.Go5Sync && window.Go5Sync.requestSync) window.Go5Sync.requestSync();
    } catch (e) {}
  }
  // fn 内の localStorage 書込を全て終えてから、揃った状態で1回だけ即時 push する。
  function batchSync_(fn) {
    _syncBatch++;
    try { fn(); } finally { _syncBatch--; }
    if (!_syncBatch) kickSync_();
  }
  // ドラフト削除の墓標。(id→削除ts)端末をまたいで「消したドラフトが union で復活する」のを防ぐ=候補の cand_del と同型。
  //   投稿完了・削除でドラフト本体から外す時に打つ。復元(restoreStock_)は addedAt=now を打って墓標を越える。
  function writeStockDel_(id) {
    try {
      var m = JSON.parse(localStorage.getItem('go5_stock_del') || '{}') || {};
      m[id] = Date.now();
      localStorage.setItem('go5_stock_del', JSON.stringify(m));
    } catch (e) {}
    kickSync_();
  }
  // 作成履歴の「完全削除(purge)」専用墓標。(id→削除ts)★ユーザーが明示削除した時だけ打つ=全端末で復活させない。
  //   作成履歴(go5_stock_archive)は「墓標なし・id単位union」で同期する設計(完了作品が2台目で消えない優先)。
  //   その裏返しで purgeArchived_ が墓標を打たないと、削除しても次の同期で他端末/雲から union 復活する
  //   =「削除を押しても消えない」(Chami報告2026-08-13②)。cand_del と同型の専用墓標で根治する。
  //   ★投稿完了(archiveStock_)・ARCHIVE_MAX溢れでは絶対に打たない=容量都合の消滅は2台目で復活してよい
  //     (2026-08-03「完了作品が消えない優先」を壊さないため)。適用は sync 側で completedTs>削除ts なら残す
  //     =purge後に作り直して再度投稿完了した正当な復活は許す(cand_del の addedAt 越えと同流儀)。
  var ARCH_DEL_TTL_MS = 180 * 24 * 3600 * 1000; // 180日で墓標をGC(archiveは30件で回転=復活源になる現実経路がほぼ無い)
  function writeArchDel_(id) {
    try {
      var m = JSON.parse(localStorage.getItem('go5_stock_arch_del') || '{}') || {};
      m[id] = Date.now();
      var cut = Date.now() - ARCH_DEL_TTL_MS;
      Object.keys(m).forEach(function (k) { if ((m[k] || 0) < cut) delete m[k]; }); // 追記のついでに古い墓標を掃除
      localStorage.setItem('go5_stock_arch_del', JSON.stringify(m));
    } catch (e) {}
    kickSync_();
  }
  function delBlobs_(id) {
    var store = idb();
    if (store) { store.del('stock_v_' + id).catch(function () {}); store.del('stock_t_' + id).catch(function () {}); store.del('stock_img_' + id).catch(function () {}); store.del('stock_prev_' + id).catch(function () {}); store.del('stock:imgs:' + id).catch(function () {}); }
    if (_thumbCache[id]) { try { URL.revokeObjectURL(_thumbCache[id]); } catch (e) {} delete _thumbCache[id]; }
  }

  // ── ①-B ドラフトの画像を全端末へ運ぶ(2026-07-31) ──
  //   サムネ/プレビュー/元画像を dataURL でまとめ stock:imgs:<id> に置く=Go5Syncの画像レール(R2 content-hash)に乗る。
  //   ★動画本体(stock_v_)は重いので載せない(②で on-demand 取り寄せにする)。実体はR2、同期台帳には参照だけ=積んでも軽い。
  function blobToDataUrlP_(blob) { return new Promise(function (res) { if (!blob) return res(''); blobToDataUrl_(blob, function (du) { res(du || ''); }); }); }
  // 画像blobを90px級サムネblobへ縮小する(失敗時 null)。canvasキャプチャが落ちた端末で「元画像フルをメタへ
  //   焼く→localStorage逼迫→draft-meta-readback-failed」を防ぐ最終保険(Fable5診断A-2・2026-08-18)。
  //   元画像そのものは stock_img_/go5src: に別途残す=喪失しない(このサムネはメタ/表示用の軽い複製)。
  function scaleBlobToThumb_(blob) {
    return new Promise(function (res) {
      try {
        if (!blob || !blob.size || typeof URL === 'undefined' || !URL.createObjectURL) return res(null);
        var url = URL.createObjectURL(blob), img = new Image();
        img.onload = function () {
          try {
            var iw = img.naturalWidth || img.width || 1, ih = img.naturalHeight || img.height || 1;
            var W = 90, H = Math.max(1, Math.round(90 * ih / iw));
            var c = document.createElement('canvas'); c.width = W; c.height = H;
            c.getContext('2d').drawImage(img, 0, 0, W, H);
            c.toBlob(function (b) { try { URL.revokeObjectURL(url); } catch (e) {} res(b || null); }, 'image/jpeg', 0.6);
          } catch (e) { try { URL.revokeObjectURL(url); } catch (_) {} res(null); }
        };
        img.onerror = function () { try { URL.revokeObjectURL(url); } catch (e) {} res(null); };
        img.src = url;
      } catch (e) { res(null); }
    });
  }
  // この端末が blob 実体を持つドラフトだけ、未作成ならミラーを1回作って雲へ送る(冪等)。既存ドラフトも開けば自動で運ばれる。
  var _blobMirrorBusy = {}; // 同じドラフトを render/定期sweep/保存直後から重複処理しない
  function ensureBlobMirror_(id) {
    var store = idb(); if (!store) return Promise.resolve();
    if (_blobMirrorBusy[id]) return _blobMirrorBusy[id];
    var job = store.get('stock:imgs:' + id).then(function (existing) {
      existing = existing || {};
      // ★既存ミラーに「欠けているフィールドだけ」を後追いで足す(非破壊・冪等)。
      //   以前は th さえ有れば skip していたため、プレビュー撮影(stock_prev_)より前に th だけで
      //   作られた古いミラーが永遠に .prev を持てず、2台目の投稿履歴に仕上がりプレビューが出なかった
      //   (Chami 2026-08-04「今までのGoogleドライブに入ってて表示していない履歴を反映して」)。
      var needTh = !existing.th, needPrev = !existing.prev, needSrc = !existing.src;
      if (!needTh && !needPrev && !needSrc) return; // 全部そろっている=触らない
      return Promise.all([
        needTh   ? store.get('stock_t_' + id)    : Promise.resolve(null),
        needPrev ? store.get('stock_prev_' + id) : Promise.resolve(null),
        needSrc  ? store.get('stock_img_' + id)  : Promise.resolve(null)
      ]).then(function (bs) {
        if (!bs[0] && !bs[1] && !bs[2]) return; // 足せる実体がこの端末に無い=同期で降ってくる側
        return Promise.all([blobToDataUrlP_(bs[0]), blobToDataUrlP_(bs[1]), blobToDataUrlP_(bs[2])]).then(function (du) {
          // 既存フィールドは温存し、欠けていたものだけ上書きせず追加する。
          var rec = {}; if (existing.th) rec.th = existing.th; if (existing.prev) rec.prev = existing.prev; if (existing.src) rec.src = existing.src;
          var added = false;
          if (needTh   && du[0]) { rec.th = du[0];   added = true; }
          if (needPrev && du[1]) { rec.prev = du[1]; added = true; }
          if (needSrc  && du[2]) { rec.src = du[2];  added = true; }
          if (added) return store.set('stock:imgs:' + id, rec).then(kickSync_);
        });
      });
    }).catch(function () {});
    _blobMirrorBusy[id] = job.then(function (v) { delete _blobMirrorBusy[id]; return v; }, function () { delete _blobMirrorBusy[id]; });
    return _blobMirrorBusy[id];
  }

  // ── ② 動画本体を全端末でDLできるようにする(2026-08-01・Chami依頼)──
  //   ★KV非依存の content-addressed 経路(2026-08-01 改訂)。
  //   旧: R2へ raw-bytes hash でPUT→hashを vidHash としてメタ(state同期=KV)に載せて2台目へ配る。
  //       →KVが日次制限で詰まると vidHash が2台目に届かず「永遠にDLできない」(Chami実測2026-07-31)。
  //   新: R2キー = sha256("go5vid:"+ドラフトID)。IDは既にメタ同期で両端末が持っている=
  //       2台目は自分でキーを算出して直接GETできる。ポインタをKVで配る必要が無い。
  //   実体を持つ端末だけが未アップ時に1回上げる(冪等)。手元マーカー(_vidUp)で二重PUTを避ける。
  var VIDNAME = function (id) { return 'go5vid:' + id; };
  var _vidUp = {}; // このセッションでアップ済みID(再PUT抑止・ローカルのみ)
  var _vidMirrorBusy = {}; // 保存直後と定期sweepが重なって同じ動画を二重PUTしない
  function ensureVideoMirror_(id, blobHint) {
    var store = idb();
    // 空/極小/画像BlobをR2へ上げて「雲に着地済み」と誤認しない。
    if (blobHint && !isUsableVideoBlob_(blobHint)) return Promise.resolve();
    if (_vidUp[id]) return Promise.resolve();
    if (_vidMirrorBusy[id]) return _vidMirrorBusy[id];
    if (!(window.Go5Sync && Go5Sync.configured && Go5Sync.configured() && Go5Sync.putBlobR2At)) return Promise.resolve();
    // ★作成直後は blobHint(メモリ上の動画)を直接R2へ上げる=手元IDB書き込み(stock_v_)の成否からミラーを切り離す。
    //   iOS Safari は idb-timeout 等で set が無言失敗しうる(idb-store.js:119 は set を意図的に reject)。その時
    //   IDBを読み直しても実体が無く、R2にもローカルにも動画が一切残らず「動画DL」が永久に落ちていた
    //   (Chami報告2026-08-13①「ドラフトで作成も動画DLできず」。v=757/758 は読み出し側のfail-openだけで、
    //   "書き込みが一度も成功していない=読む対象が存在しない" ケースは未対応だった)。blobHint 経由なら
    //   ローカル保存が死んでもR2に控えが残り、resolveVideoBlob_ が雲から取り寄せてDLできる(fail-open)。
    //   sweep(後追い)からは blobHint 無し=従来どおりIDBを読んで上げる。
    var pick = blobHint ? Promise.resolve(blobHint)
                        : (store ? store.get('stock_v_' + id) : Promise.resolve(null));
    var job = Promise.resolve(pick).then(function (blob) {
      if (!isUsableVideoBlob_(blob)) return; // 壊れたローカル実体は雲へ昇格させない
      return Go5Sync.putBlobR2At(VIDNAME(id), blob).then(function (key) {
        if (key) _vidUp[id] = 1; // 成功=このセッションでは再送しない。失敗時は次のsweepでまた試す(非破壊)
      });
    }).catch(function () {});
    _vidMirrorBusy[id] = job.then(function (v) { delete _vidMirrorBusy[id]; return v; }, function () { delete _vidMirrorBusy[id]; });
    return _vidMirrorBusy[id];
  }
  // ★save_job(サーバー側完走)を投げる前に「R2に動画実体が確実に在る」ことを保証する。
  //   ensureVideoMirror_ は IDB実体が消えていると"無言でスキップ"する=その後 queueSave を投げても Worker は
  //   R2に動画が無く r2_video_missing で約6秒後に黙って諦め、バッジが永遠に「保存中」のまま残る(炎上①の一因)。
  //   → 実体(IDB or 既にR2)を取り寄せてR2へ確実にPUTし、置けたら true。どこにも実体が無ければ false=save_jobは
  //   無駄撃ちなので呼び出し側は在ページ保存(legacy)へ倒し、"見える失敗"を出す(沈黙にしない・fail-open)。
  //   ★このセッションで作成直後に上げ済み(_vidUp)なら即 true=通常の投稿完了は追加コストゼロで従来と同一挙動。
  //   ★2026-08-18 Fable5診断で根本再設計: 旧実装は「このセッションでPUT成功(_vidUp)なら即true」だった=
  //   PUTが実は着地していない/別セッションでミラーが黙って失敗した端末で、R2に実体が無いのに true を返し、
  //   queueSave→Worker fetchが r2_video_missing で静死→「保存中のまま来ない」の主因。→ メモを信じず
  //   「今この瞬間 R2にHEADで実在するか」を毎回実測し、無ければ実体を取り寄せて再PUT→PUT後にもう一度HEADで
  //   着地確認してから true を返す(真に置けた時だけ save_job を撃つ)。HEADは本体を落とさず約100ms。
  //   hasBlobR2At が古いキャッシュのsync.jsに無い端末は従来の memo/PUT 経路へ安全に退避(fail-open)。
  function ensureVideoOnR2_(id) {
    if (!(window.Go5Sync && Go5Sync.putBlobR2At && Go5Sync.configured && Go5Sync.configured())) return Promise.resolve(false);
    var reput = function () {
      return Promise.resolve(resolveVideoBlob_(id)).then(function (blob) {
        if (!isUsableVideoBlob_(blob)) return false; // 実体がどこにも無い=queueSaveは死ぬ
        return Go5Sync.putBlobR2At(VIDNAME(id), blob).then(function (key) {
          if (!key) return false;
          // PUT成功後に「実際にGET/HEADで読める」ことをもう一度実測してから true(冪等PUTの200を鵜呑みにしない)
          if (!Go5Sync.hasBlobR2At) { _vidUp[id] = 1; return true; }
          return Go5Sync.hasBlobR2At(VIDNAME(id)).then(function (ok2) { if (ok2) { _vidUp[id] = 1; return true; } return false; });
        }).catch(function () { return false; });
      }).catch(function () { return false; });
    };
    if (!Go5Sync.hasBlobR2At) { // 旧sync.js(HEAD未実装)の端末=従来挙動へ退避
      if (_vidUp[id]) return Promise.resolve(true);
      return reput();
    }
    return Go5Sync.hasBlobR2At(VIDNAME(id)).then(function (present) {
      if (present) { _vidUp[id] = 1; return true; } // R2に実在を実測=追加コストなしで従来同等
      return reput();                                // 無い→実体を取り寄せて再PUT→再HEADで着地確認
    }).catch(function () { return reput(); });
  }
  // ★元画像(前景写真)も作成直後にメモリから直接R2へ控える(2026-08-17・Chami報告 msg1538754754824507473③
  //   「再作成を押すと使用した画像が消える」)。動画(ensureVideoMirror_)と違い、元画像はこれまで
  //   「IDBへ書く→IDBから mirror(stock:imgs:.src)を作る」経路しか無かった=iOS SafariがIDB書込みを黙って失敗、
  //   または後から容量都合でIDBを退避すると、元画像がどこにも残らず 再作成の復元(restoreRemakeForeground_)も
  //   Drive保存の元画像(go5src)も空になる。動画と同じく「作成時のメモリ実体(blobHint)」を go5src:<id> で
  //   R2へ直接上げる=IDBが死んでも元画像が雲に残り、再作成・Drive保存の両方で拾える(fail-open・冪等)。
  var SRCNAME = function (id) { return 'go5src:' + id; };
  var _srcUp = {}, _srcMirrorBusy = {};
  function ensureSrcMirror_(id, blobHint) {
    if (!blobHint || !blobHint.size) return Promise.resolve();
    if (_srcUp[id]) return Promise.resolve();
    if (_srcMirrorBusy[id]) return _srcMirrorBusy[id];
    if (!(window.Go5Sync && Go5Sync.configured && Go5Sync.configured() && Go5Sync.putBlobR2At)) return Promise.resolve();
    var job = Go5Sync.putBlobR2At(SRCNAME(id), blobHint).then(function (key) {
      if (key) _srcUp[id] = 1; // 成功=このセッションで再送しない。失敗時は次のsweepでまた試す(非破壊)
    }).catch(function () {});
    _srcMirrorBusy[id] = job.then(function (v) { delete _srcMirrorBusy[id]; return v; }, function () { delete _srcMirrorBusy[id]; });
    return _srcMirrorBusy[id];
  }
  // ★ドラフトタブを開かなくても、アプリが開いてさえいれば裏で全ドラフト/作成履歴の動画を雲へ上げる
  //   (Chami依頼2026-07-31「わざわざドラフトタブをタップしなくても雲に上がるように」)。
  var _mirrorSweepBusy = false, _mirrorSweepAgain = false;
  function sweepVideoMirror_() {
    // 旧実装は最大50件×(動画+画像)を同時発火していた。動画blob・dataURL変換が一瞬に重なると
    // iOS Safariがメモリ都合でページを丸ごと破棄するため、1件ずつ処理してイベントループへ返す。
    // 新規ドラフトは saveStock_ 直後にも即送信するので、ここは旧データ/失敗分の静かな後追い担当。
    if (document.hidden) return;
    if (_mirrorSweepBusy) { _mirrorSweepAgain = true; return; }
    var items = [];
    try { items = loadMeta().concat(loadArchive()); } catch (e) { return; }
    _mirrorSweepBusy = true;
    var i = 0;
    function finish_() {
      _mirrorSweepBusy = false;
      if (_mirrorSweepAgain) { _mirrorSweepAgain = false; setTimeout(sweepVideoMirror_, 5000); }
    }
    function next_() {
      if (document.hidden || i >= items.length) { finish_(); return; }
      var m = items[i++];
      if (!m || !m.id) { setTimeout(next_, 0); return; }
      Promise.resolve(ensureVideoMirror_(m.id))
        .then(function () { return ensureBlobMirror_(m.id); })
        .catch(function () {})
        .then(function () { setTimeout(next_, 80); }); // 1件ごとに描画/入力へ時間を返す
    }
    next_();
  }

  function idb() { return window.Go5Idb; }

  // 投稿履歴の「動画で使用した画像」は candidates.js の巨大な全画像ハイドレートを経由せず、
  // 必要な videoId の used:<id> だけをIDBから読む。ドラフト専用の軽量ページでも同じ正データを扱える。
  function usedImagesRead_(key) {
    if (!key) return Promise.resolve({ imgs: [], prev: 0 });
    var store = idb();
    if (store) return store.get('used:' + key).then(function (r) { return r || { imgs: [], prev: 0 }; }).catch(function () { return { imgs: [], prev: 0 }; });
    try { return Promise.resolve(JSON.parse(localStorage.getItem('hist_usedimg__' + key) || 'null') || { imgs: [], prev: 0 }); }
    catch (e) { return Promise.resolve({ imgs: [], prev: 0 }); }
  }
  function usedImagesSave_(key, imgs, prevCount) {
    if (!key) return Promise.resolve(false);
    imgs = (imgs || []).filter(Boolean);
    // 本体ページでは candidates.js のメモリキャッシュも同時更新。軽量ページではIDBへ直接保存する。
    if (window.Go5Cand && window.Go5Cand.usedImgSave) {
      try { return Promise.resolve(window.Go5Cand.usedImgSave(key, imgs, prevCount)); } catch (e) {}
    }
    var rec = { imgs: imgs, at: Date.now(), prev: prevCount | 0 };
    var store = idb();
    if (store) return store.set('used:' + key, rec).then(function () { try { kickSync_(); } catch (_) {} return true; }).catch(function () { return false; });
    try { localStorage.setItem('hist_usedimg__' + key, JSON.stringify(rec)); kickSync_(); return Promise.resolve(true); }
    catch (e) { return Promise.resolve(false); }
  }

  // ── サムネ取得(canvas最終フレームを小さいJPEGに) ──
  // ★canvas.toBlob は iOS Safari で「コールバックを一度も呼ばない」ことがある(メモリ逼迫・タブ非活性・
  //   巨大canvas等)。その時この Promise は永久に settle せず、saveStock_ も settle しない=生成後の
  //   .then(goDraft_) が発火せず「✅ドラフトを作成しました は出るのにドラフトタブへ遷移しない」に化ける
  //   (Chami報告2026-08-13・月詠みで再現。※アカウント分岐は無い=どのchでも起こりうる沈黙経路)。
  //   必ずタイムアウトで null に倒す=可用性は喋る側へ(§3 最悪の事故は沈黙)。サムネ/プレビューが取れない時は
  //   一覧・遷移を止めず、画像は mirror(雲)/backfill で後追いする(既存のfail-open設計と同じ握り)。
  function toBlobSafe_(canvas, type, quality, timeoutMs) {
    return new Promise(function (resolve) {
      var done = false;
      var finish = function (b) { if (done) return; done = true; resolve(b || null); };
      var timer = setTimeout(function () {
        try { if (window.console && console.warn) console.warn('[stock] canvas.toBlob がタイムアウト=nullで続行(遷移は止めない)'); } catch (_) {}
        finish(null);
      }, timeoutMs || 6000);
      try {
        canvas.toBlob(function (b) { clearTimeout(timer); finish(b); }, type, quality);
      } catch (e) { clearTimeout(timer); finish(null); }
    });
  }

  function captureThumb_() {
    try {
      var cv = $('cv');
      if (!cv) return Promise.resolve(null);
      var c = document.createElement('canvas');
      var W = 90, H = Math.round(90 * cv.height / cv.width);
      c.width = W; c.height = H;
      c.getContext('2d').drawImage(cv, 0, 0, W, H);
      // ★90pxと軽いので、まず同期の toDataURL でサムネを確実に得る=iOS Safari の canvas.toBlob
      //   コールバック不達で stock_t_ が保存されず「サムネが黒箱」になる沈黙経路を根絶(Chami報告2026-08-13①)。
      //   同一オリジン(背景mp4＋ユーザー画像)なので toDataURL は taint で投げない。取れなければ従来の toBlob へ。
      var durl = ''; try { durl = c.toDataURL('image/jpeg', 0.5); } catch (e) { durl = ''; }
      var b = durl ? durlToBlobSync_(durl) : null;
      if (b) return Promise.resolve(b);
      return toBlobSafe_(c, 'image/jpeg', 0.5, 6000);
    } catch (e) { return Promise.resolve(null); }
  }

  // ── 仕上がりプレビュー取得(canvas最終フレームを原寸JPEGで) ──
  //   これを投稿履歴の使用画像1ページ目＋Driveへ入れる(Chami依頼2026-07-30)。
  //   video-created の時点で #cv は最終フレームを保持している(captureThumb_ と同じ前提)。
  function capturePreview_() {
    try {
      var cv = $('cv');
      if (!cv || !cv.width) return Promise.resolve(null);
      // ★captureThumb_ と同じ握り(Chami報告2026-08-23「画像1枚しか保存されない」の真因)。
      //   仕上がりプレビューだけ async の canvas.toBlob(toBlobSafe_)に依存していたため、iOS Safari で
      //   toBlob のコールバックが不達だと prevBlob=null になり stock_prev_ が保存されず、投稿完了時に
      //   動画+元画像は入るのにプレビューだけ丸ごと欠ける沈黙経路になっていた(サムネ=captureThumb_ は
      //   2026-08-13① で toDataURL 同期化済みだったが、こちらは async のまま取り残されていた)。
      //   #cv は同一オリジン(背景mp4＋ユーザー画像)なので toDataURL は taint で投げない=まず同期で確実に得る。
      var durl = ''; try { durl = cv.toDataURL('image/jpeg', 0.85); } catch (e) { durl = ''; }
      var b = durl ? durlToBlobSync_(durl) : null;
      if (b) return Promise.resolve(b);
      return toBlobSafe_(cv, 'image/jpeg', 0.85, 6000); // 同期が取れなかった時だけ従来の async へ
    } catch (e) { return Promise.resolve(null); }
  }

  // ── 過去分プレビュー復元：動画blobを「再生し終えた画=末尾(約5秒)フレーム」でJPEGへ
  //   (Chami依頼2026-08-14「動画投稿プレビューは先頭の画像ではなく、再生して5秒後のシーンを」)。
  //   ★仕上がりプレビュー(動画作成タブの capturePreview_ が撮る #cv)は t=DURATION=5秒=ズーム完了後の絵。
  //   だから復元も先頭(0秒・ズーム前)ではなく末尾に寄せないと live と絵が食い違う(先頭だと引きの構図で別物)。
  //   iOS Safariの沈黙ハング(loadeddata/seeked が来ない・canvas.toBlobが呼ばれない等)に備え、8秒の番犬で
  //   必ず resolve(null) に倒す(toBlobSafe_ と同じ fail-open の作法。ここでは reject しない)。
  function videoEndFramePreview_(blob) {
    return new Promise(function (resolve) {
      if (!blob) { resolve(null); return; }
      var url = null;
      try { url = URL.createObjectURL(blob); } catch (e) { resolve(null); return; }
      var done = false;
      var timer = null;
      var durationFixed = false;   // ★実尺が確定済みか(MediaRecorder製webmは duration=Infinity のことがある)
      var finish = function (b) {
        if (done) return; done = true;
        clearTimeout(timer);
        try { URL.revokeObjectURL(url); } catch (e2) {}
        resolve(b || null);
      };
      timer = setTimeout(function () { finish(null); }, 8000);
      var v = document.createElement('video');
      v.muted = true; v.playsInline = true; v.preload = 'auto';
      var capture_ = function () {
        try {
          var c = document.createElement('canvas');
          c.width = v.videoWidth || 1080; c.height = v.videoHeight || 1920;
          if (!c.width || !c.height) { finish(null); return; }
          c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
          c.toBlob(function (b) { finish(b); }, 'image/jpeg', 0.85);
        } catch (e) { finish(null); }
      };
      var seekEnd_ = function () {
        var d = v.duration;
        // 末尾ちょうどは真っ黒/デコード未了になりやすいので数十ms手前を取る。
        //   実尺が取れなければ既定5秒-εへ(この動画は常に約5秒)。
        var target = (isFinite(d) && d > 0) ? Math.max(0, d - 0.05) : 4.95;
        try { v.currentTime = target; } catch (e) { capture_(); }
      };
      v.onloadeddata = function () {
        // ★MediaRecorder製のwebmは尺がヘッダに無く duration=Infinity のことがある。
        //   一度巨大値へシークさせると実尺が確定するので、その onseeked で末尾へ寄せ直す。
        if (!isFinite(v.duration) || v.duration <= 0) {
          durationFixed = false;
          try { v.currentTime = 1e101; } catch (e) { durationFixed = true; seekEnd_(); }
        } else {
          durationFixed = true;
          seekEnd_();
        }
      };
      v.onseeked = function () {
        if (!durationFixed) { durationFixed = true; seekEnd_(); return; } // 巨大値シークで実尺が入った直後
        capture_();
      };
      v.onerror = function () { finish(null); };
      try { v.src = url; v.load(); } catch (e) { finish(null); }
    });
  }
  function blobToDataUrl_(blob, cb) {
    try {
      var r = new FileReader();
      r.onload = function () { cb(r.result || ''); };
      r.onerror = function () { cb(''); };
      r.readAsDataURL(blob);
    } catch (e) { cb(''); }
  }
  // dataURL → Blob。同期ミラー(stock:imgs:)の .prev/.src は dataURL なので、Blobが要る経路
  //   (Drive アップロード等)へ渡す前にこれで実体へ戻す。取れなければ null。
  function durlToBlob_(durl) {
    if (!durl || typeof durl !== 'string' || durl.indexOf('data:') !== 0) return Promise.resolve(null);
    return fetch(durl).then(function (r) { return r.blob(); }).catch(function () { return null; });
  }
  // dataURL → Blob(同期・fetch非依存)。canvas.toDataURL の結果を非同期経路を一切通さずBlob化する
  //   =iOS Safari の toBlob/fetch の沈黙経路を避けてサムネを確実に得る(Chami報告2026-08-13①の根治)。
  function durlToBlobSync_(durl) {
    try {
      if (!durl || durl.indexOf('data:') !== 0) return null;
      var i = durl.indexOf(','); if (i < 0) return null;
      var head = durl.slice(0, i), body = durl.slice(i + 1);
      var mime = (head.match(/data:([^;]+)/) || [])[1] || 'image/jpeg';
      if (head.indexOf('base64') < 0) return null;
      var bin = atob(body), n = bin.length, u8 = new Uint8Array(n);
      for (var j = 0; j < n; j++) u8[j] = bin.charCodeAt(j);
      return new Blob([u8], { type: mime });
    } catch (e) { return null; }
  }

  // ── 保存 ──
  var _thumbCache = {}; // id → ObjectURL
  var _r2ThumbTried = {}; // id → 1(R2 go5srcサムネ取得を1回試した=null連打防止)

  // 動画作成タブのカテゴリ(ジャンル)チェックを読む。投稿完了時に投稿履歴へ引き継ぐ(Chami依頼2026-07-30)。
  //   これが無いと下書き→投稿完了で履歴にジャンルのチェックが渡らず、毎回手で入れ直しになる。
  // カテゴリの正本は core/categories.js(Go5Cats)。チェックボックスの要素IDは Go5Cats.elId(key)。
  function readMovieAttrs_() {
    var o = {};
    var cats = (window.Go5Cats && window.Go5Cats.visible()) || [];
    cats.forEach(function (c) { var el = $(window.Go5Cats.elId(c.key)); if (el && el.checked) o[c.key] = true; });
    return o;
  }

  // ★保存の「保留(hold)」バナー(I4)。動画が手元にも雲にも着地できなかった時、黙って遷移して
  //   全滅させず「この端末に残せていない=まだ手元に動画は生きている」を明示し、リトライを出す。
  //   遷移(location.href)で JSコンテキストを壊さない限りメモリ上の動画blobは生きている=救える。
  //   配色はアプリ(ティール#2bb3c0/ダーク面#0e1422)。紫・絵文字は使わない。
  function showSaveHold_(message, canRetry) {
    var box = document.getElementById('go5SaveHold');
    if (!box) {
      box = document.createElement('div');
      box.id = 'go5SaveHold';
      box.style.cssText = 'position:fixed;left:12px;right:12px;bottom:12px;z-index:99999;max-width:520px;margin:0 auto;background:#0e1422;border:1px solid #2bb3c0;border-radius:12px;padding:14px 16px;color:#e8f1f2;box-shadow:0 8px 24px rgba(0,0,0,.5);font-size:14px;line-height:1.55';
      var msg = document.createElement('div');
      msg.id = 'go5SaveHoldMsg';
      msg.style.cssText = 'margin-bottom:10px';
      var b1 = document.createElement('button');
      b1.id = 'go5SaveRetry';
      b1.textContent = 'もう一度保存';
      b1.style.cssText = 'background:#2bb3c0;color:#04222a;border:0;border-radius:8px;padding:8px 14px;font-weight:700;margin-right:8px;cursor:pointer';
      b1.onclick = function () { if (typeof window.__go5RetrySave === 'function') window.__go5RetrySave(); };
      var b2 = document.createElement('button');
      b2.textContent = 'このまま履歴へ';
      b2.style.cssText = 'background:transparent;color:#9fb3b8;border:1px solid #35505a;border-radius:8px;padding:8px 14px;cursor:pointer';
      // ★遷移はユーザーの明示選択でのみ=黙って全滅させない(自動経路は決して未着地で遷移しない)。
      b2.onclick = function () { hideSaveHold_(); if (typeof window.__go5HoldGoDraft === 'function') window.__go5HoldGoDraft(); };
      box.appendChild(msg); box.appendChild(b1); box.appendChild(b2);
      document.body.appendChild(box);
    }
    var msgEl = document.getElementById('go5SaveHoldMsg');
    if (msgEl) msgEl.textContent = message || '動画をこの端末に保存できませんでした(通信が不安定な可能性があります)。動画はまだ手元に残っています。もう一度保存すると消えずに済みます。';
    var retryEl = document.getElementById('go5SaveRetry');
    if (retryEl) retryEl.style.display = canRetry === false ? 'none' : 'inline-block';
    box.style.display = 'block';
  }
  function hideSaveHold_() { var box = document.getElementById('go5SaveHold'); if (box) box.style.display = 'none'; }

  // ★保存の「進捗」トースト(P2・Fable5診断2026-08-17)。hold と違い判定に一切関与しない表示だけ=ボタン無し。
  //   z-index は hold(99999)より下=万一同時表示でも hold が勝つ。配色はアプリ準拠(紫不使用・ティール系)。
  //   飛行中のレーンを「失敗」に見せず「保存中」と正しく伝える=①「自動遷移しない(実は保存成功中)」の体感を治す。
  function showSaveWait_(message) {
    var box = document.getElementById('go5SaveWait');
    if (!box) {
      box = document.createElement('div');
      box.id = 'go5SaveWait';
      box.style.cssText = 'position:fixed;left:12px;right:12px;bottom:12px;z-index:99998;max-width:520px;margin:0 auto;background:#0e1422;border:1px solid #35505a;border-radius:12px;padding:12px 16px;color:#e8f1f2;box-shadow:0 8px 24px rgba(0,0,0,.5);font-size:14px;line-height:1.55';
      document.body.appendChild(box);
    }
    box.textContent = message || '動画を保存中です…';
    box.style.display = 'block';
  }
  function hideSaveWait_() { var box = document.getElementById('go5SaveWait'); if (box) box.style.display = 'none'; }

  // ★着地失敗の実因を貫通させる小道具(Fable5診断2026-08-16・沈黙経路の根治=第1弾)。
  //   従来は verify/commit の reject が全て function(){} に吸われ、hold文面は原因に関わらず
  //   「動画を端末にも雲にも確認できませんでした」と“動画のせい”に見せていた(実際は localStorage逼迫の
  //   メタ書込み失敗=draft-meta-readback-failed でも同じ文面)。「月詠み(acc1)だけ遷移もドラフト確定もしない」の
  //   芯が acc分岐の無いコードのどこで落ちているかを、次の再現1回で確定させる=表示と記録のみ。
  //   ★遷移/ドラフト確定の判定は一切変えない(8/15の全滅回帰を招く gate ロジックには触れない)。
  function errMsg_(e) {
    if (!e) return '';
    var m = (e && (e.message || e.name)) || String(e);
    return String(m).slice(0, 80);
  }
  function logLanding_(id, account, kind, extra) {
    try {
      var arr = JSON.parse(localStorage.getItem('go5_landing_log') || '[]') || [];
      var rec = { ts: Date.now(), id: id || '', account: account || '', kind: kind || '' };
      if (extra) { rec.local = extra.local || ''; rec.cloud = extra.cloud || ''; rec.videoBytes = extra.videoBytes || 0; }
      arr.unshift(rec);
      localStorage.setItem('go5_landing_log', JSON.stringify(arr.slice(0, 12)));
    } catch (e) {}
  }

  // IDBの set() 解決だけでは成功扱いにしない。同じキーを読み戻し、使える動画Blobであることまで確認する。
  function verifyLocalVideoWrite_(id, blob) {
    var store = idb();
    if (!store || !isUsableVideoBlob_(blob)) return Promise.reject(new Error('local-video-unavailable'));
    return store.set('stock_v_' + id, blob).then(function () {
      return store.get('stock_v_' + id);
    }).then(function (saved) {
      if (!isUsableVideoBlob_(saved)) throw new Error('local-video-readback-invalid');
      return 'local';
    });
  }
  function verifyCloudVideoWrite_(id, blob) {
    if (!isUsableVideoBlob_(blob)) return Promise.reject(new Error('cloud-video-invalid'));
    return ensureVideoMirror_(id, blob).then(function () {
      if (!_vidUp[id]) throw new Error('cloud-video-not-landed');
      return 'cloud';
    });
  }
  function firstVideoLanding_(id, blob) {
    var attempts = [verifyLocalVideoWrite_(id, blob), verifyCloudVideoWrite_(id, blob)];
    return new Promise(function (resolve, reject) {
      var left = attempts.length, errors = [];
      attempts.forEach(function (p) {
        Promise.resolve(p).then(resolve, function (err) {
          errors.push(err); left--;
          if (!left) reject(errors[0] || new Error('video-not-landed'));
        });
      });
    });
  }

  function saveStock_(evDetail, hooks) {
    hooks = hooks || {}; // {onStart(id), onLocal(id), onCloud(id), onBothFailed(id)} — 検証済みシグナルだけを配る
    var ts = Date.now();
    var id = 'stk' + ts;
    var title = evDetail.title || '';
    var meta = {
      id: id, ts: ts,
      addedAt: ts,
      account: evDetail.account || 'acc1',
      label: title.length > 22 ? title.slice(0, 22) + '…' : (title || '(無題)'),
      title: title,
      author: ($('author') || {}).value || '',
      bskyText: ($('bskyText') || {}).value || '',
      affiliateUrl: ($('movieWorkAffi') || {}).value || '',
      workUrl: ($('movieWorkUrl') || {}).value || '',
      videoName: evDetail.name || (title.replace(/[\\/:"*?<>|]/g, '_') + '.mp4'),
      videoId: evDetail.videoId || '',
      attrs: readMovieAttrs_(),
      goal: ($('movieGoal') || {}).value || '',
      cmtType: ($('movieCmtType') || {}).value || '',
      priceInfo: livePriceInfo_(($('movieWorkUrl') || {}).value || ($('movieWorkAffi') || {}).value || ''),
      youtubeUrl: ''
    };

    // Phase 0: メタはメモリ上の pending に置くだけ。一覧へは動画の着地検証後に commitPendingDraft_ が確定する。
    _pendingDraftMeta[id] = meta;
    if (hooks.onStart) hooks.onStart(id); // タイムアウトより前から、保留リトライが同じpending IDを指せるようにする

    // サムネ/プレビューは今の最終Canvasに依存するため、画面遷移より前に取得する。
    var capP = Promise.all([captureThumb_(), capturePreview_()]).catch(function () { return [null, null]; });
    return capP.then(function (caps) {
      var thumbBlob = caps[0], prevBlob = caps[1];
      // Canvas取得が失敗しても、元画像を端末側サムネの最終保険にする。★ただし元画像フルをそのままメタへ
      //   焼くと localStorage を逼迫させ draft-meta-readback-failed の主因になる(Fable5診断A-2)。90px級へ縮小し、
      //   縮小できなかった時だけ raw を保険に使う(その場合はメタ同梱上限を厳しくする=下の thumbMetaCap)。
      var usedRawSource = false;
      var thumbReadyP = thumbBlob
        ? Promise.resolve(thumbBlob)
        : (evDetail.sourceImageFile
          ? scaleBlobToThumb_(evDetail.sourceImageFile).then(function (t) { if (t) return t; usedRawSource = true; return evDetail.sourceImageFile; })
          : Promise.resolve(null));
      return thumbReadyP.then(function (tb) {
      thumbBlob = tb;

      // 90pxサムネはメタにも小さなdataURLとして同梱する。IDBが丸ごと死んでR2動画だけが着地した場合でも、
      // ドラフトカードが黒い無言箱にならない。縮小済みサムネは小さい=同梱してよいが、縮小不能で元画像フルに
      // 落ちた時は24KB以下でだけ同梱する(逼迫防止・Fable5診断A-2)。
      var thumbMetaCap = usedRawSource ? 24 * 1024 : 160 * 1024;
      var thumbMetaP = (thumbBlob && thumbBlob.size > 0 && thumbBlob.size <= thumbMetaCap)
        ? blobToDataUrlP_(thumbBlob)
        : Promise.resolve('');
      return thumbMetaP.then(function (thumbDataUrl) {
        if (/^data:image\//.test(thumbDataUrl || '')) meta.thumbDataUrl = thumbDataUrl;
        meta.videoBytes = evDetail.blob && evDetail.blob.size || 0;

        var store = idb();
        var auxOps = [];
        if (store) {
          if (thumbBlob) auxOps.push(store.set('stock_t_' + id, thumbBlob));
          if (evDetail.sourceImageFile) auxOps.push(store.set('stock_img_' + id, evDetail.sourceImageFile));
          if (prevBlob) auxOps.push(store.set('stock_prev_' + id, prevBlob));
        }
        // 補助画像の失敗は動画の着地判定と分離する。成功分はIDBへ残し、後続sweepで同期ミラー化する。
        var auxDone = (typeof Promise.allSettled === 'function')
          ? Promise.allSettled(auxOps)
          : Promise.all(auxOps.map(function (p) { return Promise.resolve(p).catch(function () {}); }));
        auxDone.then(function () { ensureBlobMirror_(id); }).catch(function () {});
        // ★元画像はIDBの成否と無関係に、メモリ実体から直接R2へ控える(2026-08-17③)。IDB書込み(stock_img_)が
        //   iOSで黙って失敗/後で退避されても、go5src:<id> がR2に残る=再作成・Drive保存が空にならない。
        //   ★ただし作成直後は動画のR2 PUT(ensureVideoMirror_)が上り帯域を使い、iPhoneの細い回線では同時PUTが
        //     動画の着地を遅らせ「ドラフトへ自動遷移しない/DL準備中」を悪化させうる(Fable5診断2026-08-17)。
        //     →元画像PUTは数秒遅らせ、動画の着地を先に通す(IDB退避は分〜日単位=数秒の遅延はdurabilityに無害)。
        if (evDetail.sourceImageFile) {
          var _srcHint = evDetail.sourceImageFile;
          setTimeout(function () { try { ensureSrcMirror_(id, _srcHint); } catch (e) {} }, 6000);
        }

        // Phase 1: 動画を手元/雲へ並列着地。手元は set 解決ではなく、同じキーの読み戻しまで検証する。
        //   ★各レーンの reject 理由(idb-timeout / QuotaExceeded / draft-meta-readback-failed=localStorage逼迫 /
        //     cloud-video-not-landed=Go5Sync未設定 等)を握り潰さず errL/errC に保持=hold文面と go5_landing_log へ
        //     実因を通す(Fable5診断2026-08-16・沈黙経路の根治)。判定(landed/onBothFailed)は従来どおり。
        var errL = null, errC = null;
        var localLand = verifyLocalVideoWrite_(id, evDetail.blob).then(function () {
          meta.videoReadyAt = Date.now();
          return commitPendingDraft_(id);
        }).then(function () {
          if (hooks.onLocal) hooks.onLocal(id);
          return 'local';
        }, function (e) { errL = e; throw e; });
        var cloudLand = verifyCloudVideoWrite_(id, evDetail.blob).then(function () {
          meta.videoReadyAt = Date.now();
          return commitPendingDraft_(id);
        }).then(function () {
          if (hooks.onCloud) hooks.onCloud(id);
          return 'cloud';
        }, function (e) { errC = e; throw e; });

        // Phase 2: どちらかが着地し、メタの書込み/読み戻しも成功して初めて正常ドラフトとして完了する。
        return new Promise(function (resolve) {
          var resolved = false, localOk = false, cloudOk = false;
          function landed(kind) {
            if (kind === 'local') localOk = true; else cloudOk = true;
            logLanding_(id, meta.account, 'landed:' + kind, null);
            if (!resolved) { resolved = true; resolve(id); }
          }
          localLand.then(landed, function () {});
          cloudLand.then(landed, function () {});
          var bothDone = (typeof Promise.allSettled === 'function')
            ? Promise.allSettled([localLand, cloudLand])
            : Promise.all([localLand.catch(function () {}), cloudLand.catch(function () {})]);
          bothDone.then(function () {
            if (!localOk && !cloudOk) {
              var reasons = { local: errMsg_(errL), cloud: errMsg_(errC), account: meta.account, videoBytes: meta.videoBytes || 0 };
              logLanding_(id, meta.account, 'both-failed', reasons);
              if (hooks.onBothFailed) hooks.onBothFailed(id, reasons);
              if (!resolved) { resolved = true; resolve(id); }
            }
          });
        });
      });
      });
    });
  }
  // ── 削除 ──
  function deleteStock_(id) {
    writeStockDel_(id); // 墓標＝他端末でも消す(復活防止)
    saveMeta(loadMeta().filter(function (m) { return m.id !== id; }));
    try { localStorage.removeItem('go5_draft_post_' + id); } catch (e) {} // 投稿編集も掃除(同期で削除が伝播)
    delBlobs_(id);
  }

  // ── 投稿履歴ミラー(product-scout daily_pick 用・2026-08-16) ──
  //   投稿完了した作品の cid×チャンネル別 最終投稿日を fanza-worker(D1 posted_log)へ1件POST。
  //   fire-and-forget=失敗しても投稿完了は成功のまま(fail-open)。URL/鍵は他フロントAPIと同じlocalStorageキー。
  function postedWorkerCfg_() {
    var u = '', s = '';
    try { u = (localStorage.getItem('fanza_worker_url') || '').trim(); s = (localStorage.getItem('fanza_shared_secret') || '').trim(); } catch (e) {}
    return { url: u.replace(/\/+$/, ''), secret: s };
  }
  // meta の作品URL(workUrl優先→affiliateUrl)から cid= を取り出す(render の cidm 抽出式と同一)。
  function cidFromMeta_(meta) {
    var m = String((meta && (meta.workUrl || meta.affiliateUrl)) || '').match(/cid=([^/?&\s]+)/);
    var cid = m ? m[1] : '';
    return /^[0-9A-Za-z_-]{1,64}$/.test(cid) ? cid : '';
  }
  function mirrorPostedLog_(meta) {
    try {
      if (!meta) return;
      var cid = cidFromMeta_(meta);
      if (!cid) return; // cidが取れない=daily_pickが引けるキーが無いので送らない
      var cfg = postedWorkerCfg_();
      if (!cfg.url) return; // Worker未設定=送らない(投稿完了は成功のまま)
      var ch = (meta.account === 'acc2') ? 'acc2' : 'acc1';
      var postedAt = new Date(meta.completedTs || meta.ts || Date.now()).toISOString();
      fetch(cfg.url + '/posted', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': cfg.secret },
        body: JSON.stringify({ cid: cid, channel: ch, posted_at: postedAt, yt_url: meta.youtubeUrl || '' })
      }).catch(function () {}); // fail-open: 通信失敗でも投稿完了は成功のまま
    } catch (e) {}
  }
  // 一度きりのバックフィル：既存 go5_stock_archive の完了作品を posted_log へ流す(cid or ytUrl 無しはスキップ)。
  //   localStorageフラグ go5_posted_log_backfilled で二重送信防止。fire-and-forget=失敗は次回に持ち越す。
  function backfillPostedLog_() {
    try {
      if (localStorage.getItem('go5_posted_log_backfilled') === '1') return;
      var cfg = postedWorkerCfg_();
      if (!cfg.url) return; // Worker未設定=フラグを立てず次回起動へ持ち越す
      loadArchive().forEach(function (meta) {
        if (!meta) return;
        if (!cidFromMeta_(meta) || !meta.youtubeUrl) return; // cid or ytUrl が無い要素はスキップ
        mirrorPostedLog_(meta);
      });
      localStorage.setItem('go5_posted_log_backfilled', '1');
    } catch (e) {}
  }

  // ③投稿完了=作成完了 → ドラフト本体から外して作成履歴へ退避(④復元できるよう blob は残す)。
  //   上限を超えて作成履歴から溢れた古い分だけ、blob ごと本当に削除する。
  function archiveStock_(id) {
    var metas = loadMeta();
    var meta = metas.filter(function (m) { return m.id === id; })[0];
    if (!meta) return;
    meta.completedTs = Date.now();
    // 墓標+meta+作成履歴の3書込を1トランザクションにして、揃った状態で1回だけ即時 push する
    //   (途中 push だと作成履歴が旧値のまま送られ、相手端末で完了作品が並ばない・Chami報告2026-08-04)。
    batchSync_(function () {
      writeStockDel_(id); // 投稿完了＝ドラフト本体から外す。他端末のドラフト一覧からも消す(復活防止)
      saveMeta(metas.filter(function (m) { return m.id !== id; }));
      var arch = loadArchive().filter(function (m) { return m.id !== id; }); // 二重退避を防ぐ
      arch.unshift(meta);
      var dropped = arch.slice(ARCHIVE_MAX); // 上限超過分=保持できないので blob を掃除
      dropped.forEach(function (m) { delBlobs_(m.id); });
      saveArchive(arch);
    });
    // 投稿履歴ミラー(product-scout daily_pick 用)へ1件POST。fire-and-forget=失敗しても投稿完了は成功のまま。
    mirrorPostedLog_(meta);
  }

  // ④作成履歴からドラフト本体へ戻す。ドラフトが満杯なら溢れる最古の1件は作成履歴へ送り返す(=消さない)。
  function restoreStock_(id) {
    var arch = loadArchive();
    var meta = arch.filter(function (m) { return m.id === id; })[0];
    if (!meta) return;
    delete meta.completedTs;
    meta.addedAt = Date.now(); // ★墓標(投稿完了/削除で打たれた)を越えて復活させる=全端末で戻る
    arch = arch.filter(function (m) { return m.id !== id; });
    var metas = loadMeta().filter(function (m) { return m.id !== id; });
    metas.unshift(meta);
    if (metas.length > MAX) {
      var overflow = metas.slice(MAX); // ドラフト満杯で溢れる最古=消さずに作成履歴へ戻す
      metas = metas.slice(0, MAX);
      overflow.forEach(function (m) { if (!arch.some(function (a) { return a.id === m.id; })) arch.unshift(m); });
    }
    saveMeta(metas);
    saveArchive(arch);
  }

  // 作成履歴から完全に削除(復元不可)。blob も消す。
  //   ★墓標(go5_stock_arch_del)+作成履歴の書換を1トランザクションにして、揃った状態で1回だけ即時 push する
  //     (archiveStock_ と同型。途中 push だと墓標だけ or archive だけ渡り、相手端末で復活/消失が割れる)。
  //     これで「削除しても同期unionで復活する」を根治(Chami報告2026-08-13②)。
  function purgeArchived_(id) {
    batchSync_(function () {
      writeArchDel_(id); // purge専用墓標=全端末で復活させない(cand_del と同型)
      saveArchive(loadArchive().filter(function (m) { return m.id !== id; }));
      delBlobs_(id);
    });
  }

  // ── 動画本体の取得(実体が手元に無い2台目は ID→R2キー算出で取り寄せ・②2026-08-01)──
  //   DL・投稿完了(Driveアップロード)の両方がこれを通す=片方だけ直して片方が「動画が見つかりません」で
  //   止まる事故を防ぐ(Chami指摘2026-07-31: 2台目で投稿完了が動画未検出で失敗)。
  // ★手元(IDB)に無い動画本体を、キーを ID から算出して R2 から直接取り寄せる(vidHash不要=KV非依存)。
  //   R2取り寄せが無応答だと、これを await する Drive保存/DL が永久に返らず「☁️ 保存中…」が固まる
  //   (Chami報告2026-08-11①「いつまで経っても保存中」)。45秒で null に倒す=fail-open。取れなければ
  //   「見つかりません」で終える方が、黙って固まるより良い(§3 可用性は喋る側へ倒す)。
  // ★動画のセッション内メモリ層(②即DL・Fable5設計2026-08-17)。iOSはIDBが数MBの動画を持続保存できず
  //   退避しがちで、DLのたびにR2から十数秒かけて取り寄せていた。その十数秒の非同期の間に navigator.share の
  //   ユーザー操作有効期限(transient activation)が切れ、共有シートが無言で拒否される(=「準備中→無反応」)。
  //   作成直後/一度取得後の動画をメモリに持てば、DLはタップ即応=activation内でshareが確実に出る。最大2件。
  var _vidMem = {};
  var _vidMemOrder = [];
  var _persisted = null; // navigator.storage.persisted() の実値(C-1・DL診断へ載せる)
  function putVidMem_(id, blob) {
    if (!id || !isUsableVideoBlob_(blob)) return;
    if (!_vidMem[id]) _vidMemOrder.push(id);
    _vidMem[id] = blob;
    while (_vidMemOrder.length > 2) {
      var drop = _vidMemOrder.shift();
      if (drop !== id) { delete _vidMem[drop]; }
    }
  }
  function resolveVideoFromR2_(id) {
    if (!(window.Go5Sync && Go5Sync.fetchBlobR2At)) return Promise.resolve(null);
    var store = idb();
    var fetchP = Go5Sync.fetchBlobR2At('go5vid:' + id).then(function (b) {
      if (!isUsableVideoBlob_(b)) return null; // R2に空/破損実体があっても正常動画として返さない
      if (store) { try { store.set('stock_v_' + id, b); } catch (e) {} } // 取り寄せた実体は手元にも保存=次回は即使える
      putVidMem_(id, b); // メモリにも置く=IDBが持続しない端末でも「次のタップ」は即
      return b;
    }).catch(function () { return null; });
    var toP = new Promise(function (res) { setTimeout(function () { res(null); }, 45000); });
    return Promise.race([fetchP, toP]);
  }
  function resolveVideoBlob_(id) {
    if (_vidMem[id] && isUsableVideoBlob_(_vidMem[id])) return Promise.resolve(_vidMem[id]); // 第1層=メモリ(IDB非依存)
    var store = idb();
    if (!store) return resolveVideoFromR2_(id);
    return store.get('stock_v_' + id).then(function (blob) {
      if (isUsableVideoBlob_(blob)) { putVidMem_(id, blob); return blob; }
      // オブジェクト自体がtruthyでも空/破損なら手元成功にしない。雲の正常な控えへフォールバックする。
      return resolveVideoFromR2_(id);
    }, function () {
      // ★IDB get が iOS Safari で idb-timeout / idb-open-timeout 等で reject した時も R2 へ倒す(2026-08-13)。
      //   従来は reject が .then を素通りして downloadStock_ の catch(「動画データの取得に失敗しました」)へ
      //   直行し、作成直後に ensureVideoMirror_ で R2 へ上げた実体があっても一切取りに行けなかった
      //   (Chami報告2026-08-12①「動画データの取得に失敗。3回くらい出た」の根治)。拒否=手元が無応答なので
      //   雲の控えを見に行く=これが可用性を喋る側へ倒す fail-open。
      return resolveVideoFromR2_(id);
    });
  }

  // ★最新ドラフトの動画を先読み(②即DL・Fable5診断2026-08-17)。手元IDBに実体が有ればそのまま=何もしない。
  //   IDBが病んで実体が無い時だけR2から取り寄せ、resolveVideoFromR2_ が取得後にIDBへ書き戻す(stock.js内)
  //   =次のDLタップは手元から即出る。最新2件のみ・逐次・非表示タブでは動かない(iOSメモリ/帯域の配慮)。
  //   失敗しても何も起きない(fail-open)。遷移/ゲートには一切触れない=純粋な追加。
  var _dlWarm = {};
  function warmNewestVideos_() {
    if (document.hidden) return;
    var store = idb(); if (!store) return;
    var metas = []; try { metas = loadMeta().slice(0, 2); } catch (e) { return; }
    var chain = Promise.resolve();
    metas.forEach(function (m) {
      if (!m || !m.id || _dlWarm[m.id]) return;
      _dlWarm[m.id] = 1;
      chain = chain.then(function () {
        return store.get('stock_v_' + m.id).then(function (b) {
          if (isUsableVideoBlob_(b)) { putVidMem_(m.id, b); return; } // 手元に有る=メモリへ載せて先読み完了
          return resolveVideoFromR2_(m.id);   // 無い時だけR2→取得後にIDB+メモリへ
        }).catch(function () {});
      });
    });
  }

  // ── 動画DL ──
  //   ★押した瞬間に反応が要る(Chami報告2026-08-16「押してからすぐではなく5秒くらい時差があって反応がある」)。
  //   時差の芯＝動画blobの取り寄せが非同期(手元IDBのread、手元に無ければR2からネット取得=数秒)で、その間ボタンが
  //   無反応=死んで見える。core/operation-gate.js の armButton で「押した瞬間から」処理中表示に切り替え、共有シートを
  //   出す/取得失敗の瞬間に戻す=手元に有る動画は即・雲から取り寄せる動画も「準備中…」で反応が返る(stk-driveと同型)。
  function downloadStock_(id, videoName, btn) {
    var store = idb();
    // ボタンの素のラベルを1度だけ退避=再タップ後もボタンが正しい表記へ戻る(Fable5設計2026-08-17)。
    if (btn && !btn.getAttribute('data-dl-label')) btn.setAttribute('data-dl-label', btn.textContent || '⬇ 動画DL');
    var _op = (btn && window.Go5OperationGate && window.Go5OperationGate.armButton)
      ? window.Go5OperationGate.armButton(btn, {
          originalLabel: (btn && btn.getAttribute('data-dl-label')) || '⬇ 動画DL',
          pendingLabel: '⬇ 準備中…', timeoutLabel: '⏱ 再試行', timeoutMs: 60000
        })
      : null;
    function settle(ok, label) { if (_op) _op.finish(ok, label); }
    if (!store && !(_vidMem[id] && isUsableVideoBlob_(_vidMem[id]))) { settle(false); alert('IndexedDB未対応のため再DLできません。'); return; }
    var tapTs = Date.now();
    resolveVideoBlob_(id).then(function (blob) {
      if (!blob) {
        // 手元にも雲にも無い=作った端末からまだ上がっていない(その端末でアプリを開けば数十秒で上がる)。
        settle(false);
        // ★このalertを診断に変える(2026-08-17・Fable5診断)。次の1枚のスクショで「雲同期の設定状態」と
        //   「この動画が作成時に着地したか(go5_landing_log)」が読める=再発の芯(雲PUT失敗かIDB退避か)を切り分ける。
        var diag = '';
        try {
          var cfgd = !!(window.Go5Sync && Go5Sync.configured && Go5Sync.configured());
          var log = JSON.parse(localStorage.getItem('go5_landing_log') || '[]') || [];
          var ent = null; for (var li = 0; li < log.length; li++) { if (log[li] && log[li].id === id) { ent = log[li]; break; } }
          diag = '\n\n[診断] 雲同期=' + (cfgd ? '設定済' : '未設定') +
                 ' / 永続化=' + (_persisted || '未取得') +
                 (ent ? (' / 作成時の着地=' + (ent.kind || '?') + (ent.local ? ' 手元:' + ent.local : '') + (ent.cloud ? ' 雲:' + ent.cloud : '')) : ' / 着地記録なし') +
                 '\nid=' + id;
        } catch (_) {}
        alert('動画がまだ雲に届いていません。動画を作成した端末でこのアプリを開いていれば数十秒で自動的に上がります。少し待ってもう一度お試しください。' + diag);
        return;
      }
      putVidMem_(id, blob); // 次のタップは通信なしで即(再タップ経路の要)
      var name = videoName || 'video.mp4';
      // ★iPhoneはカメラロール(アルバム)へ直接入れたい(Chami指示2026-07-29)。<a download>だと「ファイル」アプリ止まりで
      //   写真アルバムに入らない。Web共有シート(navigator.share)には「ビデオを保存」があり、そこからアルバムへ入る=
      //   本体タブの保存ボタン(app.js saveBtn)と同じ経路。共有が使えない/断られた時だけ従来の<a download>へ落とす。
      var file = null;
      try { file = new File([blob], name, { type: blob.type || 'video/mp4' }); } catch (e) {}
      if (file && navigator.canShare && navigator.canShare({ files: [file] })) {
        // ★navigator.share は「直近のユーザー操作(transient activation)」が生きている間しか許されない。
        //   タップから blob 取得に時間がかかると(R2から十数秒)activationが切れ、share() は NotAllowedError で
        //   無言拒否される=「準備中→何も起きずポップアップも無し」の芯(Fable5診断2026-08-17・確定)。
        //   →取得が速かった(≒activation内)時だけ即share。遅かった時は share を呼ばず「もう一度タップ」へ倒し、
        //     メモリ層(putVidMem_)から2度目のタップを即応させる=activation内で確実に共有シートが出る。
        var elapsed = Date.now() - tapTs;
        if (elapsed <= 3000) {
          settle(true); // 共有シートを出す=ボタンは操作可能へ戻す
          navigator.share({ files: [file], title: name }).catch(function (err) {
            // ★共有シートを出せたらキャンセル/完了に関わらずここで完結する。<a download>へ落とすと
            //   iOSで共有シートの後に「ダウンロードしますか?」が二重に出て邪魔(Chami指摘2026-07-29・スクショ実物)。
            if (err && err.name === 'AbortError') return; // ユーザーが共有シートを閉じた=無言でよい(現行維持)
            // activation切れ等でシートが出せなかった=無言にせず、もう一度タップで確実に出せるよう案内する。
            if (btn) { try { btn.textContent = '⬇ もう一度タップで保存'; } catch (_) {} }
          });
          return;
        }
        // 取得に時間がかかった=activationは切れている。share を呼ばず「準備完了→再タップ」で無言終了を断つ。
        settle(true, '✅ 準備完了→もう一度タップで保存');
        return;
      }
      settle(true);
      anchorDownload_(blob, name);
    }).catch(function () { settle(false); alert('動画データの取得に失敗しました。'); });
  }
  // 共有が使えない/キャンセル時のフォールバック=従来の <a download>(PC・非対応ブラウザはこちら)。
  function anchorDownload_(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name || 'video.mp4';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 3000);
  }

  // ── 投稿完了処理 ──
  function handleCompleteOk_(id, ytUrl, shortUrl) {
    var store = idb();
    if (!store) { alert('IndexedDB未対応のため動画データを取得できません。'); return false; }
    var metas = loadMeta();
    var meta = metas.filter(function (m) { return m.id === id; })[0];
    // ★メタが loadMeta()(localStorage META_KEY)に無い経路の無言取りこぼしを断つ(Chami報告2026-08-22
    //   宵桜艶帖「ドン引きされた願いのドラフトが、投稿完了で保存中が一瞬走って元に戻り無視される」)。
    //   真因=容量逼迫でメタ書込みが無言失敗する(上の writeMetaResilient_ / draft-meta-readback-failed・
    //   蓄積の多いacc1で顕在化だがacc2でも起きる)と、ドラフトは pending/IDBサムネ由来で一覧に出るのに
    //   loadMeta()には居ない=従来はここで黙って false を返し、ダイアログも出さずモーダルも閉じず
    //   「投稿完了が無視される」になっていた(=Drive保存はそもそも一度も走らない)。復元元を
    //   作成履歴(loadArchive)→保存中pending(_pendingDraftMeta)→今開いているモーダルのmeta(_modalMeta)の
    //   順で辿り、拾えたら metas へ載せて以降の saveMeta で確定する(記録・Drive保存は在メモリのmetaで進む)。
    if (!meta) {
      meta = loadArchive().filter(function (m) { return m && m.id === id; })[0]
          || _pendingDraftMeta[id]
          || (_modalMeta && _modalMeta.id === id ? _modalMeta : null);
      if (meta) metas.push(meta); // 下流の videoId発番/youtubeUrl更新の saveMeta(metas) で永続化を試みる
    }
    // それでも実体が無い=この端末にメタが残っていない。黙って捨てず正直に伝える(沈黙が最悪の事故)。
    if (!meta) { alert('このドラフトのデータをこの端末で見つけられませんでした。\nメタ情報の保存が容量都合で失敗した可能性があります。端末の空き容量を確保し、ページを再読み込みしてからもう一度「投稿完了」を押してください。\n(ドラフトは残してあります)'); return false; }
    // ★背骨ID(videoId)が無いドラフト(idgen導入前 or 作成時に未スナップ)は、投稿完了の時点で必ず発番して
    //   meta へ保存する。これが無いと addCompletedPost のガードに落ちて投稿履歴の一覧に載らず作成履歴だけ
    //   残り、さらに下の使用画像プレビュー紐付け(usedImgSave は meta.videoId をキーにする)も効かない
    //   (Chami報告2026-08-08 即時投稿が一覧に出ず作成履歴のみ)。metas は meta を参照で含むので saveMeta で確定。
    if (!meta.videoId) {
      var _vid = '';
      try { if (window.IdGen && window.IdGen.makeVideoId) _vid = window.IdGen.makeVideoId(meta.account || 'acc1', new Date(), {}); } catch (e0) {}
      if (_vid) { meta.videoId = _vid; saveMeta(metas); }
    }
    // ★X短縮URLが引数で来なかった時(短縮生成前・スロット読み取り失敗)でも、保存済みドラフトデータ
    //   (saveDraftPost_ が xShortUrl として都度保存)から補って投稿履歴へ渡す。これが無いと投稿履歴の
    //   「投稿URL(計測用の短縮URL)」欄が空になり毎回手入力になる(Chami指摘2026-07-29)。
    if (!shortUrl) {
      try { var sv = JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}'); shortUrl = (sv.xShortUrl || '').trim(); } catch (e) {}
    }
    // ★投稿履歴への記録は「動画blobの有無」から完全に切り離す(Chami報告2026-08-08: 作成履歴から復元→
    //   即時投稿で投稿完了しても投稿履歴に載らない/Fable5工数で真因追跡の指示)。真因=記録(addCompletedPost)・
    //   URL保存・枠書き戻し・作成履歴退避・再描画が resolveVideoBlob_().then の中に入れ子で、動画blobが
    //   保存期限切れ/未検出だと先頭の `if(!blob) return` で"記録ごと"素通りしていた。復元したドラフトは
    //   metaは戻るが動画blobは期限切れのことがあり、そこで完了しても履歴に一切載らなかった(根治)。
    //   記録系は blob に依存しないので下で"先に同期実行"する。archiveStock_ は当該idのblobを消さない
    //   (復元用に保持)ので、後段の Drive アップロード(blob依存)より前に呼んでも動画/画像UPは壊れない。
    if (ytUrl) {
      metas.forEach(function (m) { if (m.id === id) m.youtubeUrl = ytUrl; });
      saveMeta(metas);
    }
    // ★投稿完了の時点で拾い直す：作成時スナップ(meta)が空でも、動画作成タブのライブ値から
    //   ジャンル・作品URLを補う(Chami指摘2026-07-31 msg1532858293440090163)。meta優先・空の時だけライブ補完。
    var liveAttrs = readMovieAttrs_();
    var histAttrs = (meta.attrs && Object.keys(meta.attrs).length) ? meta.attrs
      : (Object.keys(liveAttrs).length ? liveAttrs : null);
    var liveWorkUrl = (($('movieWorkUrl') || {}).value || '').trim();
    var liveAffi = (($('movieWorkAffi') || {}).value || '').trim();
    var histWorkUrl = meta.workUrl || meta.affiliateUrl || liveWorkUrl || liveAffi || '';
    // 公開設定(即時/予約)＋選んだカレンダー公開枠を1回読む(履歴へ渡す予定時刻＆枠書き戻しの両方で使う)。
    var pd = {}; try { pd = JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}'); } catch (e2) {}
    var ps = pd.pubSlot;
    // 予約投稿でカレンダー枠を選んでいたら、その枠の公開予定時刻を投稿履歴の「投稿予定」時刻として渡す(DEF#4)。
    var plannedAt = (pd.pubMode === 'scheduled' && ps && ps.scheduled_at) ? String(ps.scheduled_at).replace(' ', 'T') : '';
    // ①投稿完了 → 投稿履歴へ1件記録(既存の投稿履歴機構=Go5History)。blobの有無に関わらず必ず実行。
    //   ★戻り値を"正"にする(2026-08-12)。以前は戻り値を捨て、verify_manual を videoId 完全一致で読み直して
    //     診断していたため、videoId無し既存行にYouTube/短縮URL一致で当たった重複を「記録が全て空で拒否」と
    //     誤報していた(Chami報告2026-08-11・スクショはURL埋まりなのに"全て空"表示)。addCompletedPost が
    //     測った理由(ok/dupe/no-id/例外)だけを出す＝でっち上げない・黙って落とさない(fail-open)。
    var _res = null;
    // ★addCompletedPost へ渡す引数は1つの変数にまとめる=dupe時に forceNew を足して"同じ引数で"再挿入できるように
    //   する(下の確認ダイアログ経路)。
    var _hpOpts = {
      account: meta.account || 'acc1',
      ytUrl: ytUrl || '',
      shortUrl: shortUrl || '',
      title: meta.title || '',
      workUrl: histWorkUrl, // 導線2の自動短縮はこのworkUrlから発火する(addCompletedPost内)
      // ★投稿モーダルで既に発行・保存済みの導線2短縮URL(X本文に実際に貼ったコード)を"値として"渡す。
      //   これで完了時の非同期再発行(離脱で消える)に頼らず一発で欄が埋まる=空欄の恒久対策(REQ-65c7897f2f他)。
      workShortUrl: (pd.workShortUrl || '').trim(),
      workShareUrl: (pd.workShareUrl || '').trim(),
      videoId: meta.videoId || '',
      scheduledAt: plannedAt, // カレンダー公開枠の予定時刻(予約投稿時のみ・任意)
      attrs: histAttrs // ジャンルのチェックを引き継ぐ(Chami依頼2026-07-30・空なら投稿完了時のライブ値で補完)
    };
    try {
      if (window.Go5History && typeof window.Go5History.addCompletedPost === 'function') {
        _res = window.Go5History.addCompletedPost(_hpOpts);
      } else {
        // ドラフト専用ページで履歴モジュールが未起動でも、完了扱いにしてドラフトだけ消してはいけない。
        _res = { ok: false, reason: 'unavailable' };
      }
    } catch (e) { _res = { ok: false, reason: 'exception', message: (e && e.message) || String(e) }; }
    // ★測った理由だけを出す。成功=無言(従来どおり)。dupe=エラーでなく「既に載っています」の情報表示。
    try {
      var _dacc2 = meta.account || 'acc1';
      if (_res && _res.ok === false) {
        if (_res.reason === 'dupe') {
          // ★黙って弾かない。「何と重複扱いされたか(既存の題名・背骨ID・そのYouTube URL)」を実物で見せ、
          //   別の新規作品なら forceNew で投稿履歴へ新規追加できる逃げ道を出す(明示操作を黙って捨てない
          //   =沈黙が最悪の事故。REQ 2026-08-15「新規なのにYouTube URL一致で弾かれ履歴に載らない」の恒久対策)。
          var _byJa = _res.matchedBy === 'ytUrl' ? 'YouTube URL一致' : _res.matchedBy === 'shortUrl' ? '短縮URL一致' : '同じ動画ID';
          var _ex = _res.existing || {};
          var _exLines = '既存: ' + (_ex.title || '(題名なし)')
            + (_ex.videoId ? '\n背骨ID: ' + _ex.videoId : '')
            + (_ex.ytUrl ? '\nそのYouTube URL: ' + _ex.ytUrl : '');
          var _proceed = confirm('この動画は投稿履歴の別の1件と同じ動画として弾かれました(' + _byJa + ')。\nこのままでは投稿履歴に載りません。\n\n' + _exLines + '\n\n別の新規作品なら「OK」で投稿履歴へ新規追加します。\n同じ動画なら「キャンセル」。');
          if (_proceed) {
            try {
              _hpOpts.forceNew = true; // 重複判定を飛ばして必ず新規挿入
              _res = window.Go5History.addCompletedPost(_hpOpts);
            } catch (e6) { _res = { ok: false, reason: 'exception', message: (e6 && e6.message) || String(e6) }; }
            if (_res && _res.ok === false && _res.reason && _res.reason !== 'dupe') {
              alert('新規追加もできませんでした(理由=' + _res.reason + (_res.message ? ' / ' + _res.message : '') + ')。\nドラフトは残してあります。');
            }
          }
        } else if (_res.reason === 'no-id') {
          alert('投稿履歴に載せられませんでした。\n理由=この動画に識別ID(背骨ID)が無く、YouTube URL・短縮URLも空でした。\n(videoId=' + (meta.videoId || 'なし') + ' / チャンネル=' + _dacc2 + ')');
        } else if (_res.reason === 'unavailable') {
          alert('投稿履歴の登録機能を読み込めませんでした。\nドラフトは残してあるので、ページを再読み込みしてもう一度「投稿完了」を押してください。');
        } else if (_res.reason === 'persist-failed') {
          alert('投稿履歴をこの端末へ保存できませんでした。\nドラフトは残してあります。空き容量を確認してから、もう一度「投稿完了」を押してください。');
        } else if (_res.reason === 'exception') {
          alert('投稿履歴への記録で問題が起きました。\n' + (_res.message || '(詳細不明)') + '\n(videoId=' + (meta.videoId || 'なし') + ' / チャンネル=' + _dacc2 + ')');
        }
      }
    } catch (e5) {}
    // ★persist-pending＝端末のlocalStorageは満杯だが履歴の正本(IDB)へ書込中(hist-store)。IDB着地を待って
    //   から完了可否を決める＝満杯でも投稿完了が「いつまでも保存中」で止まらない(炎上①の恒久対策)。
    //   handleCompleteOk_ は同期 true/false 契約(呼び元が closeModal_ を判断)なので、ここでは false を返し、
    //   着地後の完了処理とモーダル閉じは wait の continuation 側で行う(_res は差し替え済＝二重完了しない)。
    if (_res && _res.ok === false && _res.reason === 'persist-pending' && _res.wait && typeof _res.wait.then === 'function') {
      var _pfMsg = '投稿履歴をこの端末へ保存できませんでした。\nドラフトは残してあります。空き容量を確認してから、もう一度「投稿完了」を押してください。';
      _res.wait.then(function (r) {
        if (r && (r.ok || r.reason === 'dupe')) { finishComplete_(id, meta, ytUrl, shortUrl, ps, pd); try { closeModal_(); } catch (e7) {} }
        else { try { alert(_pfMsg); } catch (e8) {} }
      }, function () { try { alert(_pfMsg); } catch (e9) {} });
      return false; // 同期経路では未確定＝モーダルは閉じない(着地後に continuation が閉じる)
    }
    // 投稿履歴へ「新規保存できた」または「既に載っている」と確認できた時だけ完了を進める。
    // API未起動/識別不能/保存失敗/例外でドラフトを作成履歴へ移すと再試行手段を失うため、ここで止める。
    if (!_res || (_res.ok === false && _res.reason !== 'dupe')) return false;
    finishComplete_(id, meta, ytUrl, shortUrl, ps, pd);
    return true;
  }

  // 投稿完了の"後半"(枠書き戻し→作成履歴退避→再描画→Drive保存)。同期で載った時も、persist-pending の
  //   IDB着地後も同じ処理を通す。★closeModal_ はここでは呼ばない=同期経路は呼び元が返り値 true で閉じる。
  function finishComplete_(id, meta, ytUrl, shortUrl, ps, pd) {
    // 公開設定＝予約投稿でカレンダー公開枠を選んでいたら、その枠へ書き戻す(投稿履歴/カレンダー/予約を結ぶ)。
    try {
      if (ps && ps.id) {
        if (pd.pubMode === 'scheduled') {
          document.dispatchEvent(new CustomEvent('bluesky-reserved', { detail: { slotId: ps.id, account: meta.account || 'acc1' } }));
        } else {
          document.dispatchEvent(new CustomEvent('bluesky-posted', { detail: { slotId: ps.id, account: meta.account || 'acc1', post_url: ytUrl || '', short_url: shortUrl || '' } }));
        }
      }
    } catch (e) {}
    // ③投稿完了=作成完了 → ドラフト本体から外し、④作成履歴へ退避(復元可)。記録の後に行う(blob非依存)。
    archiveStock_(id);
    render();
    // ── Drive 保存。動画作成時に即保存済みならプレビューだけ追記、未保存の旧ドラフト等はフル保存にフォールバック ──
    driveSaveForCompleted_(meta, { silent: false });
  }

  // 動画に使った元画像のBlobを解決する。手元Blob(stock_img_)優先、無ければ同期ミラー(stock:imgs:.src)の
  //   dataURLから実体へ戻す(別端末で作った分)。どちらも無ければ null(=元画像はスキップ・非致命)。
  function resolveSrcImageBlob_(id) {
    var store = idb();
    if (!store) return Promise.resolve(null);
    return Promise.all([
      store.get('stock_img_' + id).catch(function () { return null; }),
      store.get('stock:imgs:' + id).catch(function () { return null; })
    ]).then(function (r) {
      var img = r[0], mirror = r[1] || {};
      if (img) return img;
      if (mirror.src) return durlToBlob_(mirror.src); // .then が Promise を自動で解く
      // ★手元IDBにも同期ミラーにも無い=作成直後にR2へ控えた元画像 go5src:<id> を取り寄せる(2026-08-17③)。
      //   これでIDB退避後でもDrive保存の「元画像」が空にならない。
      if (window.Go5Sync && Go5Sync.fetchBlobR2At) {
        return Go5Sync.fetchBlobR2At('go5src:' + id).then(function (b) { return (b && b.size) ? b : null; }).catch(function () { return null; });
      }
      return null;
    }, function () { return null; });
  }

  // 投稿完了(または作成履歴カードの「☁️ Drive保存」)から呼ぶDrive保存。
  //   ★動画作成の瞬間に即保存済み(drive_up_<videoId>あり)なら、動画/元画像は上げ直さず仕上がりプレビューだけ追記する。
  //     iOSがIDBの動画blobを容量都合で捨てた後でも、作成時に上げてあるのでDriveには残る=「履歴に載るのにDriveに無い」の根治。
  //   ★未保存(旧ドラフト・作成時の即保存に失敗・サブ端末完了)なら従来どおり動画blobを取り直してフル保存する。
  //   仕上がりプレビューは Driveの有無に関わらず「使用画像1ページ目」へ差し込む(REQ-716a4bf46f・冪等)。
  //   opts.silent=true のときは成否のalertを出さない(裏経路/一括保存用)。
  function driveSaveForCompleted_(meta, opts) {
    opts = opts || {};
    // ★手押し(作成履歴カードの☁️ Drive保存)は「押したのに何も起きない」に見えないよう、
    //   終着点で必ず onDone(ok,msg) を呼ぶ。作成時に即保存済み(folderIdあり)だと従来は無反応で返っていた=
    //   これが Chami 報告「drive保存のボタンが押せない」の正体(2026-08-12)。
    var done = function (ok, msg) { if (opts.onDone) { try { opts.onDone(ok, msg); } catch (_) {} } };
    if (!meta || !meta.id) { done(false, 'メタ情報がありません'); return; }
    var store = idb();
    if (!store) { if (!opts.silent) alert('IndexedDB未対応のためDrive保存できません。(投稿履歴には記録済み)'); done(false, 'IDB未対応'); return; }
    if (!(window.Go5Drive && typeof window.Go5Drive.upload === 'function')) {
      if (!opts.silent) alert('Drive連携が未設定です。動画作成タブのDriveStatus欄を確認してください。(投稿履歴には記録済み)');
      done(false, 'Drive未設定');
      return;
    }
    var id = meta.id;
    // ── ★最後の砦=「動画生成で使用した画像」(used:<videoId>)から素材を拾う ─────────────────
    //   Chami報告2026-08-18 msg1539277864371748965「全部データが見つからないと出たが、投稿履歴にちゃんと二つ
    //   画像データがあるやないか」。原因=退避/再生成は素材を stock_*(ドラフト由来)と R2 からしか探していなかった。
    //   だが投稿履歴の「動画生成で使用した画像」は別の器 used:<videoId> に在る(Go5Cand のhydrateメモリ／IDB)。
    //   iOSがドラフト側blobを捨てても、投稿履歴表示のため used: は生きている=モーダルには映るのに退避は空、が起きる。
    //   ここでモーダルと同じ源(Go5Cand.usedImgs=メモリ)を最優先で読み、無ければ usedImagesRead_(IDB)へ倒す。
    //   used レコード= { imgs:[仕上がりプレビュー×prev枚, 元画像…], prev }。先頭prev枚がプレビュー・残りが元画像。
    function usedRec_() {
      var vids = [];
      if (meta.videoId) vids.push(meta.videoId);
      if (meta.id && meta.id !== meta.videoId) vids.push(meta.id);
      // ① 投稿履歴モーダルと同一の源(Go5Cand のメモリ)。IDBに used: が無くてもR2/シート由来でここには居る事がある。
      for (var i = 0; i < vids.length; i++) {
        var key = vids[i];
        if (window.Go5Cand && typeof window.Go5Cand.usedImgs === 'function') {
          var imgs = window.Go5Cand.usedImgs(key) || [];
          if (imgs.length) {
            var pn = (typeof window.Go5Cand.usedPrevCount === 'function') ? (window.Go5Cand.usedPrevCount(key) || 0) : 0;
            return Promise.resolve({ imgs: imgs.filter(Boolean), prev: pn | 0 });
          }
        }
      }
      // ② IDB直読み(軽量ページ/メモリ未hydrate時)。videoId→id の順で最初に中身のある方を採る。
      var chain = Promise.resolve({ imgs: [], prev: 0 });
      vids.forEach(function (key) {
        chain = chain.then(function (acc) {
          if (acc.imgs && acc.imgs.length) return acc;
          return usedImagesRead_(key).then(function (r) {
            return (r && r.imgs && r.imgs.length) ? { imgs: r.imgs.filter(Boolean), prev: (r.prev | 0) } : acc;
          }).catch(function () { return acc; });
        });
      });
      return chain;
    }
    // used: の先頭prev枚=仕上がりプレビュー。その次(prev番目)以降=元画像(生の写真)。dataURL→Blob化して返す。
    function usedPrevBlob_() {
      return usedRec_().then(function (r) {
        var imgs = (r && r.imgs) || [], prev = (r && r.prev) | 0;
        if (prev >= 1 && imgs[0]) return durlToBlob_(imgs[0]);
        return null;
      }).catch(function () { return null; });
    }
    function usedSrcBlob_() {
      return usedRec_().then(function (r) {
        var imgs = (r && r.imgs) || [], prev = (r && r.prev) | 0;
        var idx = (imgs.length > prev) ? prev : (imgs.length ? 0 : -1); // 先頭prev枚を飛ばした最初の元画像
        if (idx >= 0 && imgs[idx]) return durlToBlob_(imgs[idx]);
        return null;
      }).catch(function () { return null; });
    }
    // 元画像の解決を used: まで延長(ドラフト由来 stock_img_/同期ミラー/R2 で取れなければ used: の元画像へ倒す)。
    function resolveSrcImageBlob2_() {
      return resolveSrcImageBlob_(id).then(function (b) { return b || usedSrcBlob_(); }).catch(function () { return usedSrcBlob_(); });
    }
    // 仕上がりプレビューを「使用画像1ページ目」へ差し込む(videoIdで紐付く・Chami依頼2026-07-30・冪等)。
    var applyPreview = function (prevB) {
      if (!prevB || !meta.videoId) return;
      blobToDataUrl_(prevB, function (durl) {
        if (!durl) return;
        usedImagesRead_(meta.videoId).then(function (rec) {
          var cur = (rec && Array.isArray(rec.imgs)) ? rec.imgs.filter(Boolean) : [];
          if (cur[0] === durl) return; // 再投稿完了で二重差し込みしない(冪等)
          usedImagesSave_(meta.videoId, [durl].concat(cur.filter(function (u) { return u !== durl; })), 1);
        });
      });
    };
    // ★symptom恒久対策(Chami報告2026-08-15「それに伴って投稿履歴の画像もあるべき画像が設定されていない」)：
    //   投稿履歴1ページ目のプレビュー差し込みを「動画blobの有無」から完全に切り離す。従来は下の
    //   resolveVideoBlob_().then の中(=blobが取れた時だけ)で applyPreview を呼んでいたため、iOSがIDBの動画blobを
    //   捨て R2ミラーも未着だと『Driveに動画が来ない』と『投稿履歴の画像が設定されない』が"一緒に"起きていた。
    //   プレビュー実体は stock_prev_(Blob)/ 同期ミラー stock:imgs:.prev(dataURL)から取れる=動画に一切依存しない。
    //   ここで先に確定させ、下のDrive保存(blob依存)の成否に関わらず投稿履歴へは必ず入る。
    var previewReady = Promise.all([
      store.get('stock_prev_' + id).catch(function () { return null; }),
      store.get('stock:imgs:' + id).catch(function () { return null; })
    ]).then(function (r) {
      var prev = r[0], mirror = r[1] || {};
      return prev ? prev : durlToBlob_(mirror.prev); // .then が Promise を自動で解く
    }).then(function (prevB) {
      if (prevB) return prevB;
      // ★手元にプレビュー実体が無い(別端末で作った投稿履歴の回復・編集モーダルからの再生成)＝Driveに既にある
      //   仕上がりプレビューを取り寄せて使う。無ければ null のまま(何も壊さない)。これで yt-clicks.js の旧
      //   regenRecordData_(分岐コピー)が持っていた「Drive既存プレビューで回復」を driveSaveForCompleted_ 一本へ
      //   畳み込む=データ再生成の経路を1つに保つ(Chami依頼2026-08-18・単一化)。
      if (window.Go5Drive && Go5Drive.fetchPreview && (meta.account === 'acc1' || meta.account === 'acc2') && meta.title)
        return Go5Drive.fetchPreview(meta.account, meta.title).then(function (du) { return du ? durlToBlob_(du) : null; }, function () { return null; });
      return null;
    }).then(function (prevB) {
      // ★ドラフト側にもDriveにも無い時の最後の砦=投稿履歴が表示している仕上がりプレビュー(used:<videoId>)。
      //   これで「モーダルには映るのに再生成すると全部見つからない」(Chami報告2026-08-18)を塞ぐ。
      if (prevB) return prevB;
      return usedPrevBlob_();
    }).then(function (prevB) { applyPreview(prevB); return prevB; }, function () { return null; });

    var folderId = window.Go5Drive.folderIdFor ? window.Go5Drive.folderIdFor(meta.videoId) : '';
    // ── 控えフォルダ(drive_up_<videoId>)が在っても「実際に動画が在るか」を必ず確かめてから信じる。
    //   ★静かな取りこぼしの根治(Chami報告2026-08-16「Driveに投稿保存しても動画が保存されない」)。従来は控えが
    //   在るだけで「動画は保存済み」と決めつけ、仕上がりプレビューだけ追記して動画本体を一切上げなかった。だが
    //   この控えは今日足したDriveアイコンの解決(resolveFolderUrl_)でも題名一致で書かれる=空/プレビューだけの
    //   フォルダを"保存済み"と誤認しうる。checkSaved(read-only)で[題名]フォルダに動画実体が在る時だけプレビュー
    //   追記で済ませ、無ければ本当の保存(realSaveNow_)へ倒す(判定不能も保存側へ倒す=fail-open・沈黙より保存)。
    //   ★控えが端末に無くても、Driveに既に動画が在るなら フォルダIDを引き当てて「プレビュー追記だけ」で済ませる
    //     =別端末で作成/保存済みの投稿履歴を編集モーダルから再生成しても動画を上げ直さない(gap-fill・Chami
    //     依頼2026-08-18「既に作られてたら再作成の必要はない・足りてないものだけ」)。read-onlyの照会のみ・非破壊。
    function resolveOkFolder_() {
      if (folderId)
        return Go5Drive.checkSaved(meta.account, meta.title).then(function (saved) { return saved ? folderId : ''; }, function () { return ''; });
      if (!(Go5Drive.checkSaved && Go5Drive.resolveFolderUrl && (meta.account === 'acc1' || meta.account === 'acc2') && meta.title))
        return Promise.resolve('');
      return Go5Drive.checkSaved(meta.account, meta.title).then(function (saved) {
        if (!saved) return ''; // Driveに動画がまだ無い＝本当の保存(全部)へ倒す
        return Go5Drive.resolveFolderUrl(meta.account, meta.title, meta.videoId).then(function () {
          return (window.Go5Drive.folderIdFor && meta.videoId) ? window.Go5Drive.folderIdFor(meta.videoId) : '';
        }, function () { return ''; });
      }, function () { return ''; });
    }
    // ★正常化(opts.normalize=手動の明示「名前を正しく保存し直す」)は、Driveに既に動画が在っても「追記だけ」の近道
    //   (okFolder枝)を通さず、必ず本当の作り直し(realSaveNow_→queueSaveにnormalize:true)へ倒す。古いフォルダは
    //   candidate.jpg 等の誤名で作られたレガシー=正しい名前で一式を作り直し、古いのはWorkerが新規保存の"後"にゴミ箱送り。
    var verifyFolder = opts.normalize ? Promise.resolve('') : resolveOkFolder_();
    verifyFolder.then(function (okFolderId) {
      if (okFolderId) {
        setDriveSavedState_(id, 'verified', meta); try { render(); } catch (e) {} // checkSavedで実物確認済み＝verified
        // ★重複生成の根治(Chami報告2026-08-18 msg1539252539571052544「元画像だけがない場合でデータ再生成しても
        //   プレビューがもう一つできるだけ。意味なし」)。動画は既にDriveに在る(=okFolderId)。従来はここで有無を見ずに
        //   appendImage(プレビュー)を毎回打っていた=Driveに「_プレビュー」が増殖。folder_state(read-only)で
        //   動画/プレビュー/元画像の有無を1回で引き、"Driveに無いものだけ補う"。既にあるものは上げ直さない(冪等)。
        var stateP = (window.Go5Drive.folderState)
          ? window.Go5Drive.folderState(meta.account, meta.title).catch(function () { return null; })
          : Promise.resolve(null);
        Promise.all([previewReady, stateP]).then(function (arr) {
          var prevB = arr[0], st = arr[1];
          // 状態不明(st===null)は「在る」とみなす=重複防止側へ倒す(余計に作らない)。
          var hasPrev = st ? !!st.hasPreview : true;
          var hasSrc  = st ? !!st.hasSrc     : true;
          var added = [];
          // プレビュー: Driveに無い時だけ追記(冪等)。
          if (prevB && !hasPrev && window.Go5Drive.appendImage) {
            window.Go5Drive.appendImage(meta.account, meta.title, okFolderId, prevB, null);
            added.push('プレビュー');
          }
          var finish = function (srcB) {
            // 元画像: Driveに無く、この端末(またはR2/同期ミラー)に元画像が残っている時だけ復元。
            //   命名は投稿完了時と同じ "題名_元画像.拡張子"(Worker findSrcImageFile と一致)。
            if (!hasSrc && srcB && window.Go5Drive.appendImage) {
              var ext = (srcB.type && srcB.type.indexOf('png') >= 0) ? 'png' : 'jpg';
              var sname = String(meta.title || '動画').replace(/[\\/:"*?<>|]/g, '_') + '_元画像.' + ext;
              window.Go5Drive.appendImage(meta.account, meta.title, okFolderId, srcB, sname);
              added.push('元画像');
            }
            var msg;
            if (added.length) {
              msg = 'Driveへ ' + added.join('・') + ' を補いました(動画は既に保存済み)';
            } else if (st === null) {
              msg = '既にDriveへ保存済みの作品です。状態を確認できなかったため、重複を避けて今回は追記していません。';
            } else if (!hasSrc) {
              // ★正直に(Chami「素直にギブアップとか言ってくれ」)。元画像は"元の写真そのもの"＝この端末に残っていなければ復元不能。
              msg = '動画と仕上がりプレビューは既にDriveにあります。足りないのは元画像だけで、これは元の写真そのものなので、この端末に残っていないと自動では復元できません。元画像だけGoogleドライブへ手動で追加してください。';
            } else {
              msg = 'すでに動画・元画像・プレビューが揃っています(新たに補うものはありません)。';
            }
            done(true, msg);
          };
          // 元画像がDriveに在るなら読む必要なし(無駄なR2取り寄せとハングを避ける)。無い時だけ手元素材を探す=
          //   12秒で切り上げて null(＝復元不能扱い=正直に手動追加を案内)。
          if (hasSrc) { finish(null); return; }
          var timed = new Promise(function (res) { setTimeout(function () { res(null); }, 12000); });
          Promise.race([resolveSrcImageBlob2_().catch(function () { return null; }), timed]).then(finish);
        });
        return;
      }
      realSaveNow_(); // 控えが在っても動画が無い/確かめられない=本当に保存する
    });
    return;

    // ── ★退避保存(Chami依頼2026-08-18 msg1539252929222017124「動画がないとつくれないなら仕方ない。にしても
    //   フォルダくらい作ってくれ、あとプレビュー画像や元画像はあるならそれを取得して名前変えて保存すればいいだろ」)。
    //   動画本体がこの端末にもR2にも無く復元不能な時、従来は「動画データが見つかりません」で全部あきらめていた=
    //   フォルダも作られず、手元にあるプレビュー/元画像すら保存されなかった。ここで全か無かをやめる=フォルダを確保し、
    //   手元にあるプレビュー/元画像だけ Worker(ensure_folder) で退避保存する。動画は正直に「見つからず保存できない・
    //   手動で追加して」と返す(素直にギブアップ)。Driveに既に在るものは上げ直さない(冪等・重複プレビューを再演しない)。
    function salvageWithoutVideo_() {
      if (!(window.Go5Drive && typeof window.Go5Drive.ensureFolder === 'function') || (meta.account !== 'acc1' && meta.account !== 'acc2') || !meta.title) {
        if (!opts.silent) alert('動画データが見つかりません(保存期間が過ぎたか削除されました)。投稿履歴には記録済み・使用画像のプレビューも設定済みです。Google Driveへの動画保存だけスキップしました。');
        done(false, '動画データ無し(プレビューは設定済み)');
        return;
      }
      // Driveの現状(プレビュー/元画像の有無)。判定不能(null)は「無い」とみなす=退避を試みる側へ倒す
      //   (Worker側が役割ごとに冪等なので、実際に既にあれば skipped になり二重にはならない)。
      var stateP = window.Go5Drive.folderState
        ? window.Go5Drive.folderState(meta.account, meta.title).catch(function () { return null; })
        : Promise.resolve(null);
      // 元画像は"元の写真そのもの"=手元(IDB/同期ミラー/R2)に残っていれば拾う。12秒で切り上げ(ハング防止)。
      var srcTimed = new Promise(function (res) { setTimeout(function () { res(null); }, 12000); });
      var srcP = Promise.race([resolveSrcImageBlob2_().catch(function () { return null; }), srcTimed]);
      Promise.all([previewReady, srcP, stateP]).then(function (arr) {
        var prevB = arr[0], srcB = arr[1], st = arr[2];
        var hasPrev = st ? !!st.hasPreview : false;
        var hasSrc  = st ? !!st.hasSrc     : false;
        var imgs = [];
        if (prevB && !hasPrev) imgs.push({ blob: prevB, role: 'preview' });
        if (srcB && !hasSrc)   imgs.push({ blob: srcB, role: 'src' });
        window.Go5Drive.ensureFolder(meta.account, meta.title, imgs).then(function (res) {
          if (!(res && res.ok)) {
            if (!opts.silent) alert('動画データが見つからず、フォルダの用意にも失敗しました(投稿履歴には記録済み)。通信状況を変えてもう一度お試しください。');
            done(false, 'フォルダ確保に失敗(動画も無し)');
            return;
          }
          var saved = res.added || [];
          var savedPrev = saved.some(function (n) { return String(n).indexOf('プレビュー') >= 0; });
          var savedSrc  = saved.some(function (n) { return String(n).indexOf('元画像') >= 0; });
          var parts = [];
          if (savedPrev) parts.push('プレビュー');
          if (savedSrc)  parts.push('元画像');
          var msg;
          if (parts.length) {
            msg = '動画は元データが見つからず保存できませんでしたが、フォルダを作成し ' + parts.join('・') + ' を保存しました。動画だけ手動でGoogleドライブへ追加してください。';
          } else if (hasPrev || hasSrc) {
            msg = '動画は元データが見つからず保存できません。フォルダは用意済みで、プレビュー/元画像は既にDriveにあります。動画だけ手動で追加してください。';
          } else {
            msg = '動画は元データが見つからず保存できません。フォルダは作成しましたが、プレビューも元画像もこの端末に残っていないため入れられませんでした。動画を手動でGoogleドライブへ追加してください。';
          }
          done(true, msg);
        });
      });
    }
    // ── 本当のDrive保存(動画本体を上げる)。控えフォルダに動画実体が無い時/控えが無い時に呼ぶ。
    function realSaveNow_() {
      // ★ここから先は実際に保存を試みる=カードに「確認中…」を出し、実物確認ループを起動する(queueSave/レガシー両経路を1箇所で被覆)。
      setDriveSavedState_(id, 'pending', meta); try { render(); } catch (e) {}
      verifyDriveLanded_(id);
    // ── ★フォールバック：作成時にDrive未保存 → サーバー側完走ジョブ(2026-08-16 Chami「途中で閉じても裏で完結」)。
    //   従来はここでこのページ内で動画をフルアップロードしていた=スマホ回線で数秒〜十数秒。その最中にSafariが
    //   タブをbg破棄/閉じるとfetchが切れて中断し、積み直す永続キューも無く「黙って消える」(Chami再発報告
    //   2026-08-16「月詠みの2本がDriveに保存されていない」)。動画は作成直後にR2へ控えてある(ensureVideoMirror_)ので、
    //   その在り処(videoKey)だけを軽く渡し→Workerが即202→R2→Driveをサーバー側で完走させる=閉じても続く。
    //   届かなかった場合に備え localStorage(go5_drive_savejob_<id>)へpendingを記録し、次回起動のsweepで再送(冪等)。
    if (window.Go5Drive && typeof window.Go5Drive.queueSave === 'function' && meta.account) {
      // ★save_jobを投げる前にR2へ動画実体を確実に置く。置けない(実体喪失)なら在ページ保存(legacy)へ倒す=
      //   Workerが r2_video_missing で黙って諦めて「永遠に保存中」になる沈黙経路を封じる(炎上①・B-1)。
      ensureVideoOnR2_(id).then(function (onR2) {
        if (!onR2) { legacyRealSave_(); return; } // R2に動画が無い=save_jobは無駄撃ち→在ページ保存で救うか"見える失敗"を出す
        // ★動画のsave_job(サーバー側完走)を「任意の付随画像(プレビュー/元画像)の解決・R2ミラー」に絶対ブロック
        //   させない(Chami報告2026-08-18 msg1539278578913509416「投稿完了しても結局Googleドライブに保存できてない」)。
        //   真因=このブロックの前段が3つとも網へ伸びる無時限待ち: previewReady(手元に無いと fetchPreview=網)/
        //   resolveSrcImageBlob2_(R2取り寄せ)/ putBlobR2At(プレビュー・元画像のR2ミラー)。iOS Safariでどれか1つが
        //   返らないと queueSave が発火せず、動画本体が一度も送られないまま「確認中…」で固まる=投稿完了したのに
        //   Driveに動画が来ない、が起きる。動画実体は既にR2に在る(直上の ensureVideoOnR2_=true)ので、付随画像は
        //   12秒だけ待って"取れた分のkeyだけ"添え、必ず save_job を投げる(動画が最優先。プレビューは used:1ページ目
        //   への差し込みと、次回開いた時の okFolder/salvage の gap-fill でも後から揃う=取りこぼしゼロ)。
        //   okFolder枝・salvage枝が既に使っている12秒Promise.raceと同じ型に揃える(この主経路だけ無防備だった)。
        var enrich = Promise.all([
          Promise.resolve(previewReady).catch(function () { return null; }),
          resolveSrcImageBlob2_().catch(function () { return null; })
        ]).then(function (bs) {
          var prevB = bs[0], srcB = bs[1];
          // 仕上がりプレビュー・元画像も小さくR2へ控えてkeyを添える(Workerが同フォルダへ保存)。任意=失敗しても続行。
          //   ★元画像を渡すのは「投稿完了と同じ一式(動画+元画像+プレビュー)」を揃えるため(Chami 2026-08-17)。
          var mirrorPrev = (prevB && window.Go5Sync && Go5Sync.putBlobR2At)
            ? Go5Sync.putBlobR2At('go5prev:' + id, prevB).catch(function () { return ''; })
            : Promise.resolve('');
          var mirrorSrc = (srcB && window.Go5Sync && Go5Sync.putBlobR2At)
            ? Go5Sync.putBlobR2At('go5src:' + id, srcB).catch(function () { return ''; })
            : Promise.resolve('');
          return Promise.all([mirrorPrev, mirrorSrc]);
        }).catch(function () { return ['', '']; });
        var enrichTimed = new Promise(function (res) { setTimeout(function () { res(['', '']); }, 12000); });
        Promise.race([enrich, enrichTimed]).then(function (keys) {
          recordSaveJobPending_(id, meta);
          return window.Go5Drive.queueSave({ videoId: id, title: meta.title, channel: meta.account, previewKey: keys[0] || '', srcKey: keys[1] || '', overwrite: true, normalize: !!opts.normalize });
        })
          .then(function (res) {
            var ok = !!(res && res.ok);
            done(ok, ok ? 'Driveへ保存(裏で完走)' : '今は送れず・次回起動で自動再送(投稿履歴は記録済み)');
          })
          .catch(function () { done(false, '保存予約に失敗・次回起動で自動再送(投稿履歴は記録済み)'); });
      });
      return;
    }
    legacyRealSave_();
    // ── 最後の砦：queueSave が使えない旧環境 / R2に実体が無い時のみ、従来のこのページ内フル保存(動画+元画像+プレビュー)。
    function legacyRealSave_() {
    // ★この直アップロード経路も pending を記録する(2026-08-18 Fable5診断)。送信がiOS背景化で黙って死んでも、
    //   次回起動の sweepSaveJobs_ が「Driveに在るか」を実測し、無ければ実体を取り寄せて再送=直アップロードの
    //   取りこぼしも自己修復させる(旧実装はlegacyだけpending未記録=一度死ぬと二度と拾えなかった)。
    recordSaveJobPending_(id, meta);
    resolveVideoBlob_(id).then(function (blob) {
      if (!blob) {
        // ★動画は取れなくても、上の previewReady が投稿履歴1ページ目のプレビューを既に設定済み。
        //   さらに「動画が無いなら仕方ない、でもフォルダくらい作って・プレビュー/元画像はあるなら名前変えて保存して」
        //   (Chami依頼2026-08-18 msg1539252929222017124)へ応える=全か無かにせず、フォルダを作り手元の画像だけ退避する。
        salvageWithoutVideo_();
        return;
      }
      Promise.all([
        store.get('stock_img_' + id).catch(function () { return null; }),
        store.get('stock:imgs:' + id).catch(function () { return null; }) // 同期ミラー(別端末で作った動画の画像)
      ]).then(function (r) {
        var img = r[0], mirror = r[1] || {};
        // ★サブ端末では stock_img_(Blob)が無いので、同期ミラー stock:imgs: の dataURL から実体へ戻す
        //   (Chami 2026-08-04「サブ端末で投稿すると投稿履歴の画像に動画投稿プレビューが表示されない」)。
        var imgP  = img  ? Promise.resolve(img)  : durlToBlob_(mirror.src);
        Promise.all([imgP, previewReady]).then(function (bs) {
          var imgB = bs[0], prevB = bs[1];
          window.Go5Drive.upload(blob, meta.videoName, meta.title, meta.account, meta.id, imgB ? [imgB] : [], prevB || null, { normalize: !!opts.normalize });
          done(true, 'Driveへ保存開始');
        });
      }).catch(function () {
        window.Go5Drive.upload(blob, meta.videoName, meta.title, meta.account, meta.id, [], null, { normalize: !!opts.normalize });
        done(true, 'Driveへ保存開始');
      });
    }).catch(function (err) {
      if (!opts.silent) alert('動画データの取得に失敗しました(投稿履歴には記録済み): ' + (err ? err.message || String(err) : '不明'));
      done(false, '取得失敗');
    });
    } // legacyRealSave_
    } // realSaveNow_
  }

  // ── 編集モーダル(ドラフト履歴/投稿履歴)からの「データ再生成」(Chami依頼2026-08-18) ──────────────
  //   一連のデータ(動画・元画像・仕上がりプレビュー)を"投稿完了と同じ"経路=driveSaveForCompleted_ で作り直す。
  //   ★この一本に集約=「同じデータを作れる」の担保。冪等/gap-fill：Driveに既に在れば動画は上げ直さずプレビュー
  //     追記のみ、投稿履歴1ページ目のプレビューも重複差し込みしない(既にあれば作り直さない・足りないものだけ)。
  //   yt-clicks.js の旧regenRecordData_(分岐コピー)もこの経路へ寄せた=データ再生成のロジックは1つ(単一化)。
  //   locator = 完全なmeta(.id あり) か {videoId,title,account}(後者は手元metas/archiveから実metaを引く)。
  function regenDataset_(locator, opts) {
    opts = opts || {};
    var done = function (ok, msg) { if (opts.onDone) { try { opts.onDone(ok, msg); } catch (_) {} } };
    var meta = null;
    if (locator && locator.id) {
      meta = locator; // ドラフトモーダル=openPostModal_ が持つ実meta(id/videoId/IDB素材あり)
    } else if (locator && (locator.videoId || locator.title)) {
      // 投稿履歴モーダル=click-listの it から locator が来る。手元のドラフト/作成履歴に実metaが在れば引く
      //   (=正しい id/videoName/IDBキーで素材を読める)。
      var all = loadMeta().concat(loadArchive());
      for (var i = 0; i < all.length; i++) {
        if (!all[i]) continue;
        if (locator.videoId && all[i].videoId === locator.videoId) { meta = all[i]; break; }
        if (!locator.videoId && locator.title && all[i].title === locator.title) { meta = all[i]; break; }
      }
      // 手元に無い(別端末で作成した投稿履歴)＝背骨IDを id として合成。IDBに素材が無くても driveSaveForCompleted_
      //   側が Driveの既存プレビュー(fetchPreview)を取り寄せて回復し、動画がDriveに在れば追記だけで済ませる。
      if (!meta) meta = { id: locator.videoId || '', videoId: locator.videoId || '', title: locator.title || '', account: locator.account || '', videoName: '' };
    }
    if (!meta || !meta.id) { done(false, 'この履歴のデータを特定できませんでした(背骨IDが空=Drive保存が始まる前の古い投稿)'); return; }
    // ★成否の真の基準は「投稿履歴1ページ目に仕上がりプレビューが入ったか」(Chami「戻すだけ・前はプレビューが入ってた」
    //   2026-08-18)。driveSaveForCompleted_ は動画がDriveに在るだけで done(true,'プレビュー追記') と返しうる=
    //   プレビュー素材がどこにも無ければ実際は1ページ目に何も入らないのに「生成しました」と出る("結局できてない"の真因)。
    //   → 完了時に usedImagesRead_ で1ページ目プレビューの実在を確かめ、入った時だけ成功と報告する。素材が無い時は
    //     「動画は在るがプレビュー素材がこの端末にもDriveにも無い=生成不可(元動画/プレビューを手動で入れて)」と正直に返す。
    var vid = meta.videoId || '';
    var settled = false;
    var wrapped = function (ok, msg) {
      if (settled) return; settled = true;
      if (wd) { clearTimeout(wd); wd = 0; }
      done(ok, msg);
    };
    // ★ウォッチドッグ：どの経路が固まっても40秒で必ず一度だけ結着させる=ボタンが「再生成中…」のまま
    //   永久に固まらない(Chami報告2026-08-18「再生成中から待たされる」)。この時点の1ページ目プレビューで判定。
    var wd = setTimeout(function () {
      if (settled) return;
      if (!vid) { wrapped(false, '時間内に完了できませんでした(通信が返りません)。もう一度お試しください'); return; }
      usedImagesRead_(vid).then(function (rec) {
        var prevN = (rec && rec.prev) ? (rec.prev | 0) : 0;
        wrapped(prevN > 0, prevN > 0 ? 'プレビューを1ページ目へ反映(保存は裏で継続)' : '時間内に完了できませんでした。通信状況を変えてもう一度お試しください');
      }).catch(function () { wrapped(false, '時間内に完了できませんでした。もう一度お試しください'); });
    }, 40000);
    driveSaveForCompleted_(meta, {
      silent: opts.silent,
      normalize: !!opts.normalize, // ★正常化(名前を正しく保存し直す)の明示intentを保存本体へ引き継ぐ
      onDone: function (ok, msg) {
        if (settled) return;
        if (!vid) { wrapped(ok, msg); return; } // videoId無し=1ページ目の紐付けキーが無い(旧投稿)=素の結果を返す
        // 実在確認：1ページ目にプレビューが入っていれば成功。入っていなければ、動画保存は進んでいても「生成」としては未達。
        //   ★applyPreview の書き込みは fire-and-forget(driveSaveForCompleted_ は待たずに done する)ので、読むのが
        //     早すぎると未反映=偽の失敗になる。1度だけ1.2秒待って読み直してから正直な結論を出す。
        var verdict = function () {
          usedImagesRead_(vid).then(function (rec) {
            var prevN = (rec && rec.prev) ? (rec.prev | 0) : 0;
            if (prevN > 0) { wrapped(true, msg || 'プレビューを1ページ目へ反映'); return; }
            setTimeout(function () {
              if (settled) return;
              usedImagesRead_(vid).then(function (rec2) {
                var p2 = (rec2 && rec2.prev) ? (rec2.prev | 0) : 0;
                wrapped(p2 > 0, p2 > 0 ? (msg || 'プレビューを1ページ目へ反映')
                  : 'この作品の仕上がりプレビュー素材が、この端末にもGoogleドライブにも見つかりませんでした。動画(または仕上がりプレビュー画像)を手動で入れると1ページ目に反映できます。');
              }).catch(function () { wrapped(false, 'この作品の仕上がりプレビュー素材が見つかりませんでした。動画を手動で入れてお試しください。'); });
            }, 1200);
          }).catch(function () { wrapped(ok, msg); });
        };
        verdict();
      }
    });
  }

  // ── ★save_job 永続pending(2026-08-16 Chami「途中で閉じても裏で完結」の取りこぼし対策)──
  //   投稿完了で queueSave を投げた瞬間に pending を記録する。keepalive送信が届かなかった(オフライン/
  //   送信途中でタブ破棄)場合でも、次回アプリ起動の sweep が「Driveにもう在るか」を照会(read-only)し、
  //   無ければ動画をR2へ上げ直して save_job を再送する。Worker側は冪等=再送で二重フォルダにならない。
  var SAVEJOB_PENDING_PREFIX = 'go5_drive_savejob_';
  var SAVEJOB_MAX_TRIES = 12; // R2に実体が在る前提での「再送」上限。超えても記録は残しcheckSavedは継続(嘘の完了にしない)
  function recordSaveJobPending_(id, meta) {
    try {
      var prev = JSON.parse(localStorage.getItem(SAVEJOB_PENDING_PREFIX + id) || 'null') || {};
      localStorage.setItem(SAVEJOB_PENDING_PREFIX + id, JSON.stringify({
        id: id, title: meta.title, channel: meta.account, ts: prev.ts || Date.now(), tries: (prev.tries | 0)
      }));
    } catch (e) {}
  }
  var _saveJobSweepBusy = false;
  function sweepSaveJobs_() {
    if (document.hidden || _saveJobSweepBusy) return;
    if (!(window.Go5Drive && Go5Drive.queueSave && Go5Drive.checkSaved)) return;
    var keys = [];
    try { for (var i = 0; i < localStorage.length; i++) { var k = localStorage.key(i); if (k && k.indexOf(SAVEJOB_PENDING_PREFIX) === 0) keys.push(k); } } catch (e) { return; }
    if (!keys.length) return;
    _saveJobSweepBusy = true;
    var idx = 0;
    function done_() { _saveJobSweepBusy = false; }
    function nextK() {
      if (document.hidden || idx >= keys.length) { done_(); return; }
      var k = keys[idx++], rec = null;
      try { rec = JSON.parse(localStorage.getItem(k) || 'null'); } catch (e) { rec = null; }
      if (!rec || !rec.id || !rec.title || !rec.channel) { try { localStorage.removeItem(k); } catch (e) {} setTimeout(nextK, 0); return; }
      Go5Drive.checkSaved(rec.channel, rec.title).then(function (saved) {
        if (saved) { // 確認できた=畳む。saved後にnovideo等の暫定失敗表示が残っていたら実物確認へ格上げ
          try { localStorage.removeItem(k); } catch (e) {}
          var _ds = driveSavedState_(rec.id);
          if (_ds && _ds.state !== 'verified') { setDriveSavedState_(rec.id, 'verified', { title: rec.title, account: rec.channel }); try { render(); } catch (e) {} }
          setTimeout(nextK, 40); return;
        }
        // ★まだDriveに無い→「R2に動画実体が今この瞬間 在るか」をHEADで実測してから撃つ(ensureVideoMirror_=IDB直読み
        //   だけの旧処置は、IDBを退役した端末で毎回無言スキップ→r2_video_missingの保証された失敗を8回撃って諦めていた。
        //   Fable5診断・2026-08-18)。実体がどこにも無い時はsave_jobは無駄撃ち=沈黙で終わらせず「見える失敗(novideo)」にする。
        Promise.resolve(ensureVideoOnR2_(rec.id)).then(function (onR2) {
          if (!onR2) {
            // 動画がこの端末にもクラウドにも無い=save_jobを投げても静死するだけ。カードに見える失敗を出す(沈黙ゼロ)。
            setDriveSavedState_(rec.id, 'novideo', { title: rec.title, account: rec.channel });
            try { render(); } catch (e) {}
            var ageMs = Date.now() - (rec.ts || Date.now());
            if (ageMs > 14 * 24 * 3600 * 1000) { try { localStorage.removeItem(k); } catch (e) {} } // 14日粘っても実体が戻らなければ記録は掃除(表示は残る)
            setTimeout(nextK, 60); return;
          }
          if ((rec.tries | 0) >= SAVEJOB_MAX_TRIES) { setTimeout(nextK, 40); return; } // 再送は打ち切るが記録は残す=次回以降もcheckSavedで確認は続ける
          rec.tries = (rec.tries | 0) + 1;
          try { localStorage.setItem(k, JSON.stringify(rec)); } catch (e) {}
          Go5Drive.queueSave({ videoId: rec.id, title: rec.title, channel: rec.channel, overwrite: true })
            .catch(function () {}).then(function () { setTimeout(nextK, 150); });
        }).catch(function () { setTimeout(nextK, 150); });
      }).catch(function () { setTimeout(nextK, 150); });
    }
    nextK();
  }

  // ── ★Drive保存の「実物確認」状態(2026-08-17 オタコン)──
  //   投稿完了/手押しでDrive保存に入ったら go5_drive_saved_<id> に pending を記録し、Go5Drive.checkSaved
  //   ([題名]フォルダに動画実体が在るか＝read-only)で実物を確認できた時だけ verified へ上げる。Workerの202受理を
  //   成功と読み替えない=「裏で完走と出るのにDriveに動画が来ない」の沈黙を、カードで見える状態(確認中/実物確認)に変える。
  var DRIVE_SAVED_PREFIX = 'go5_drive_saved_';
  function driveSavedState_(id) {
    try { return JSON.parse(localStorage.getItem(DRIVE_SAVED_PREFIX + id) || 'null'); } catch (e) { return null; }
  }
  function setDriveSavedState_(id, state, meta) {
    try {
      var prev = driveSavedState_(id) || {};
      localStorage.setItem(DRIVE_SAVED_PREFIX + id, JSON.stringify({
        state: state, ts: Date.now(),
        title: (meta && meta.title) || prev.title || '',
        channel: (meta && meta.account) || prev.channel || '',
        videoId: (meta && meta.videoId) || prev.videoId || ''
      }));
    } catch (e) {}
  }
  var _driveVerifyBusy = {};
  function verifyDriveLanded_(id) {
    if (_driveVerifyBusy[id]) return;
    var st = driveSavedState_(id);
    if (!st || st.state === 'verified') return;
    if (!(window.Go5Drive && Go5Drive.checkSaved) || !st.channel || !st.title) return;
    _driveVerifyBusy[id] = true;
    var delays = [4000, 20000, 60000, 180000]; // 4秒→20秒→60秒→180秒(初回を4秒に=既にDrive着地済み/軽い保存は数秒で「実物確認」へ上がる。Chami「押して30秒無反応」2026-08-18)
    var i = 0;
    function schedule() {
      if (i >= delays.length) { _driveVerifyBusy[id] = false; return; } // 打ち切り=pendingのまま(嘘をつかない・次回起動で再照会)
      setTimeout(tryOnce, delays[i++]);
    }
    function tryOnce() {
      if (document.hidden) { schedule(); return; } // 隠れている間は数えず復帰で再試行
      Go5Drive.checkSaved(st.channel, st.title).then(function (saved) {
        if (saved) { setDriveSavedState_(id, 'verified', null); _driveVerifyBusy[id] = false; try { render(); } catch (e) {} return; }
        schedule();
      }).catch(function () { schedule(); });
    }
    schedule();
  }

  // ── 再作成(ドラフトデータを動画作成タブに復元) ──
  var REMAKE_PENDING_KEY = 'go5_stock_remake_pending';
  function remakeStock_(meta) {
    // ドラフト専用ページには動画作成DOMを積まない。IDだけsessionStorageへ渡し、本体で同じ関数を再開する。
    // ここでは元ドラフトを消さない=遷移失敗/タブ破棄があってもデータを失わない。本体で復元完了後にだけ削除する。
    if (!$('author')) {
      try { sessionStorage.setItem(REMAKE_PENDING_KEY, meta && meta.id || ''); localStorage.setItem('go5_active_tab', 'tabMovie'); } catch (e) {}
      location.href = 'index.html';
      return;
    }
    var a = $('author');
    if (a) { a.value = meta.author || ''; a.dispatchEvent(new Event('input')); }
    var t = $('top');
    if (t) { t.value = meta.title || ''; t.dispatchEvent(new Event('input')); }
    var b = $('bskyText');
    if (b) b.value = meta.bskyText || '';
    var w = $('movieWorkUrl');
    if (w) { w.value = meta.workUrl || ''; w.dispatchEvent(new Event('input')); }
    // ★狙い・コメント型を復元する。無いと make()(app.js)の必須ガードで弾かれ、作り直し直後の
    //   「ドラフトで作成」が毎回『狙い/コメント型が未選択です』で止まる(Chami 2026-08-14②)。
    //   ※これより前に保存された下書き(meta.goal 無し)は''のまま=その1件だけ再選択が要る(移行の宿命)。
    var g = $('movieGoal'); if (g) { g.value = meta.goal || ''; try { g.dispatchEvent(new Event('change')); } catch (e) {} }
    var ct = $('movieCmtType'); if (ct) { ct.value = meta.cmtType || ''; try { ct.dispatchEvent(new Event('change')); } catch (e) {} }
    // ①作成時にスナップしたカテゴリ(ジャンル)チェックを復元する(Chami依頼2026-08-06①)。
    //   作品URLのinputで走る非同期のFANZA再取得(autoApplyAttrsFromInfo_)が後から上書きしないよう、
    //   この作品のcidを「適用済み」に印してから復元する=再作成では手元の下書きの選択を正とする。
    try {
      var attrs = meta.attrs || {};
      var cidm = String(meta.workUrl || '').match(/cid=([^/?&\s]+)/);
      if (cidm && cidm[1]) { try { localStorage.setItem('movie_auto_attrs_cid', cidm[1]); } catch (e) {} }
      var cats = (window.Go5Cats && window.Go5Cats.visible && window.Go5Cats.visible()) || [];
      cats.forEach(function (c) { var el = $(window.Go5Cats.elId(c.key)); if (el) el.checked = !!attrs[c.key]; });
    } catch (e) {}
    // ③テストモード(記録スキップの危険フラグ)は再作成では必ずOFFへ倒す(Chami依頼2026-08-06③)。
    try { var tm = $('testMode'); if (tm && tm.checked) tm.checked = false; } catch (e) {}
    var tab = $('tabMovie');
    if (tab) tab.click();
    // ★前景画像の復元(Chami依頼2026-08-16②「作り直しを選ぶと画像が消えている・作った時と同じ状態に戻して」)。
    //   従来はテキスト系(作者/コメント/作品URL/狙い/カテゴリ)だけ戻し、肝心の前景画像を戻していなかった=
    //   作り直すたびに写真だけ空欄になっていた。候補→動画作成と同じ実績のある経路 window.Go5SetForegroundFile で
    //   #photo へ流し込む。手元Blob(stock_img_)優先、無ければ同期ミラー(stock:imgs:.src)から復元。
    //   ★元ドラフトの一覧からの除去(deleteStock_)は delBlobs_ で画像も消すため、画像の読み取りが終わってから行う
    //     (先に消すと復元用のBlobを取りこぼす)。読み取りに失敗しても除去は必ず走らせる。
    restoreRemakeForeground_(meta).catch(function () {}).then(function () {
      // ②再作成したらこのドラフトはドラフト一覧から外す(Chami依頼2026-08-06②)。作り直しの起点なので
      //   元の下書きは残さない=消し忘れによる二重ドラフトを防ぐ(墓標で他端末のドラフトからも消える)。
      try { deleteStock_(meta.id); render(); } catch (e) {}
    });
  }
  // 作り直し時に、作成に使った前景画像を動画作成タブ(#photo)へ戻す。常に解決するPromiseを返す(呼び出し側が
  //   これを待ってから元ドラフトを消せるように)。画像が取れなくても投げない=deleteStock_ は必ず走る。
  function restoreRemakeForeground_(meta) {
    var store = idb();
    if (!store || !meta || !meta.id || !window.Go5SetForegroundFile) return Promise.resolve();
    var setFg = function (blob) {
      if (!blob) return;
      try {
        var name = (meta.title || 'photo').replace(/[\\/:"*?<>|]/g, '_') + '.jpg';
        var f = (blob instanceof File) ? blob : new File([blob], name, { type: blob.type || 'image/jpeg' });
        window.Go5SetForegroundFile(f);
      } catch (e) {}
    };
    return Promise.all([
      store.get('stock_img_' + meta.id).catch(function () { return null; }),
      store.get('stock:imgs:' + meta.id).catch(function () { return null; })
    ]).then(function (r) {
      var img = r[0], mirror = r[1] || {};
      if (img) { setFg(img); return; }
      if (mirror.src) return durlToBlob_(mirror.src).then(setFg); // サブ端末で作った=同期ミラーから戻す
      // ★手元IDBにも同期ミラーにも無い(iOSがIDBを退避した等)=作成直後にR2へ控えた元画像 go5src:<id> から
      //   最後の復元(2026-08-17③)。これが無いと「再作成で画像が消える」が残る。
      if (window.Go5Sync && Go5Sync.fetchBlobR2At) {
        return Go5Sync.fetchBlobR2At('go5src:' + meta.id).then(function (b) { if (b && b.size) setFg(b); }).catch(function () {});
      }
    }).catch(function () {});
  }

  // ── レンダリング ──
  function renderItem_(meta, thumbUrl) {
    var id = meta.id;
    var acctLabel = meta.account === 'acc2' ? '宵桜艶帖' : '月詠み';
    var bskyPre = (meta.bskyText || '').replace(/\n/g, ' ');
    if (bskyPre.length > 40) bskyPre = bskyPre.slice(0, 40) + '…';
    var hasYt = !!(meta.youtubeUrl);
    var btnBase = 'width:auto;margin:0;padding:5px 10px;font-size:.76rem;border-radius:6px;cursor:pointer;white-space:nowrap;';
    return '<div data-item-id="' + esc(id) + '" style="display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid #2a3346;">' +
      (thumbUrl ? '<img src="' + esc(thumbUrl) + '" alt="" style="width:48px;height:85px;object-fit:cover;border-radius:5px;flex:0 0 auto;">'
                : '<div title="サムネイル未取得" style="width:48px;height:85px;border-radius:5px;background:linear-gradient(160deg,#17243a,#0e1422);border:1px solid #31405a;display:flex;align-items:center;justify-content:center;color:#7a8fa3;font-size:.6rem;line-height:1.2;text-align:center;flex:0 0 auto;">確認中</div>') +
      '<div style="flex:1 1 0;min-width:0;">' +
        '<div style="font-size:.86rem;font-weight:700;color:#eef2f7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(meta.label) + '</div>' +
        '<div style="font-size:.74rem;color:#7a8fa3;margin-top:1px;">' + esc(acctLabel) + ' · ' + esc(fmtTs(meta.ts)) + '</div>' +
        (bskyPre ? '<div style="font-size:.74rem;color:#9fb0c3;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(bskyPre) + '</div>' : '') +
        (meta.affiliateUrl ? '<div style="font-size:.71rem;color:#4a7060;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">🔗 ' + esc(meta.affiliateUrl.replace(/^https?:\/\//, '').slice(0, 44)) + '</div>' : '') +
        (hasYt ? '<div style="font-size:.71rem;color:var(--accent);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">✅ <a href="' + esc(meta.youtubeUrl) + '" target="_blank" rel="noopener" style="color:var(--accent);">' + esc((meta.youtubeUrl).replace(/^https?:\/\//, '').slice(0, 44)) + '</a></div>' : '') +
        '<div style="display:flex;gap:5px;margin-top:7px;flex-wrap:wrap;">' +
          '<button type="button" class="stk-dl" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #3a4a5e;background:transparent;color:#ccc;">⬇ 動画DL</button>' +
          '<button type="button" class="stk-mode" data-id="' + esc(id) + '" style="' + btnBase + (hasYt ? 'border:1px solid var(--accent);background:transparent;color:var(--accent);' : 'border:none;background:linear-gradient(180deg,var(--cta-from,var(--accent)),var(--cta-to,var(--accent)));color:var(--cta-ink,#04222a);') + 'font-weight:700;">投稿モード</button>' +
          '<button type="button" class="stk-remake" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #3a4a5e;background:transparent;color:#9fb0c3;">再作成</button>' +
          '<button type="button" class="stk-del" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #3a4a5e;background:transparent;color:#666;padding:5px 8px;">🗑</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  // ★保存中(未着地)ドラフトの1行。着地までのページ内表示(B・Fable5設計2026-08-17)用。
  //   まだ手元/雲に着地していない=操作ボタンは出さない(DL/投稿は着地後の通常カードで)。
  function renderPendingItem_(meta) {
    var acctLabel = meta.account === 'acc2' ? '宵桜艶帖' : '月詠み';
    var thumbUrl = meta.thumbDataUrl || '';
    var status = meta._failed
      ? '<span style="color:#e6a23c;font-weight:700;">⚠ 保存に失敗。下の「もう一度保存」で再確認できます</span>'
      : '<span style="color:var(--accent);">⏳ 保存中…(この端末と雲へ確認しています)</span>';
    return '<div style="display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid #2a3346;opacity:.92;">' +
      (thumbUrl ? '<img src="' + esc(thumbUrl) + '" alt="" style="width:48px;height:85px;object-fit:cover;border-radius:5px;flex:0 0 auto;">'
                : '<div style="width:48px;height:85px;border-radius:5px;background:linear-gradient(160deg,#17243a,#0e1422);border:1px solid #31405a;display:flex;align-items:center;justify-content:center;color:#7a8fa3;font-size:.6rem;text-align:center;flex:0 0 auto;">保存中</div>') +
      '<div style="flex:1 1 0;min-width:0;">' +
        '<div style="font-size:.86rem;font-weight:700;color:#eef2f7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(meta.label) + '</div>' +
        '<div style="font-size:.74rem;color:#7a8fa3;margin-top:1px;">' + esc(acctLabel) + ' · ' + esc(fmtTs(meta.ts)) + '</div>' +
        '<div style="font-size:.74rem;margin-top:4px;">' + status + '</div>' +
      '</div>' +
    '</div>';
  }

  // 作成履歴(退避済み)の1行。復元・動画DL(blobは残してある)・完全削除。
  function renderArchItem_(meta, thumbUrl) {
    var id = meta.id;
    var acctLabel = meta.account === 'acc2' ? '宵桜艶帖' : '月詠み';
    var hasYt = !!(meta.youtubeUrl);
    // ★Drive保存の実物確認状態を1行で見せる(ボタンではなくテキスト行=幅レイアウトに触れない)。
    var _dsv = driveSavedState_(id);
    var driveLine = '';
    if (_dsv && _dsv.state === 'verified') {
      var _durl = (window.Go5Drive && Go5Drive.folderUrl) ? Go5Drive.folderUrl(meta.account, meta.title, meta.videoId) : '';
      driveLine = '<div style="font-size:.71rem;color:var(--accent);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">☁️ Drive保存済み(実物確認)' +
        (_durl ? ' · <a href="' + esc(_durl) + '" target="_blank" rel="noopener" style="color:var(--accent);">Driveで開く</a>' : '') + '</div>';
    } else if (_dsv && _dsv.state === 'pending') {
      // ★確認できるまでは「確認中…」。ただし実物照会ループ(20→60→180秒)を尽くしても着地を確認できない時、
      //   いつまでも「確認中…」のままだと「保存中が終わらない」に見える(DEF-8f75「いつまで経っても保存中」の真因)。
      //   → verify窓(約5分)を過ぎても未確認なら「確認できず・再試行」へ切替え、下の「☁️ Drive保存」で押し直せると示す
      //   (次回アプリ起動時の再照会=1846行 でも自動で確認中→実物確認へ上がる)。
      var _stuck = _dsv.ts && (Date.now() - _dsv.ts) > 5 * 60 * 1000;
      // ★どちらも「失敗宣告」に読ませない(Chami報告2026-08-18「何も押してないのに勝手にエラーが出てる」)。
      //   実態=開いている間は毎描画で自動再照会(1846行)・180秒毎にsweepSaveJobs_が自動再送する=裏で粘っている。
      //   だから「確認中/確認できていないだけ・自動で粘っている・急ぐなら手動でも押せる」と読める中立表現にする。
      //   押下直後もこの状態行が受領を語る(realSaveNow_のrender()でボタン自体は作り直されて押下感が消えるため)。
      driveLine = _stuck
        ? '<div style="font-size:.71rem;color:#7a8fa3;margin-top:2px;white-space:normal;">☁️ まだDrive保存を確認できていません(開いている間は自動で再確認を続けます) · 急ぐ場合は下の「☁️ Drive保存」で再試行</div>'
        : '<div style="font-size:.71rem;color:#7a8fa3;margin-top:2px;">☁️ 保存を受け付けました · 実物を確認中…(ふつうは数秒・最大3分)</div>';
    } else if (_dsv && _dsv.state === 'novideo') {
      // ★動画の実体がこの端末にもクラウド(R2)にも見つからず、Driveへ保存できない=沈黙で諦めず「見える失敗」にする
      //   (Fable5診断2026-08-18。旧実装は無言で8回再送して静かに諦めていた)。「復元」して作り直すか手動投入を促す。
      driveLine = '<div style="font-size:.71rem;color:#e6a23c;margin-top:2px;white-space:normal;">⚠ 動画の元データがこの端末にもクラウドにも見つからず、Driveへ保存できません · 「復元」で作り直すか、動画を手動で入れてください</div>';
    }
    // ★4ボタン(復元/動画DL/Drive保存/削除)を折り返さず一列に収める(Chami依頼2026-08-12)。
    //   ★横スクロールをやめ「収まらなければ縮小して収める」方式へ(Chami依頼2026-08-11 msg1536769222108119050)。
    //   ★横幅は前のサイズ(中身なり=padding:4px 8px/.72rem)を維持し、引き伸ばさない(Chami指摘2026-08-11 msg1536774712519163914)。
    //   flex:0 0 auto=各ボタンは常に中身なりの幅(文字量で可変)。伸ばさない(旧flex:1 1 0)し、縮ませもしない。
    //     ★縮み(旧flex:0 1 auto)をやめた理由=収まらない時に短い復元/削除まで縮んで横幅を食い合い「文字量なり」に見えない(Chami指摘 msg1536781919541399602)。
    //     収まらない時は縮小でなく折り返す(下の flex-wrap:wrap)=各ボタンは文字ぶんの幅を保つ。
    //   inline-flex+justify-content:center=絵文字+文字を枠の中央に置く(Drive保存の中央揃えズレ=msg1536776216986779729③の根治)。
    //   ★★width:auto が必須=グローバル button{width:100%}(style.css:846)を打ち消す。これが無いと flex-basis:auto が
    //     width:100% を読み、flex:0 0 auto+wrap で各ボタンが全幅→縦積みになる(Chami msg1536784731872698439「余計に悪くなってる」の真因)。
    //     ドラフト側btnBase(703行)や draftPostModal(1206行コメント)と同じ既知の罠=INC-47系。ここが幅騒動の元凶だった。
    var btnBase = 'width:auto;margin:0;padding:4px 8px;font-size:.72rem;border-radius:6px;cursor:pointer;white-space:nowrap;flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;gap:3px;';
    return '<div data-item-id="' + esc(id) + '" style="display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid #2a3346;opacity:.92;">' +
      (thumbUrl ? '<img src="' + esc(thumbUrl) + '" alt="" style="width:40px;height:71px;object-fit:cover;border-radius:5px;flex:0 0 auto;">'
                : '<div style="width:40px;height:71px;border-radius:5px;background:#0e1422;flex:0 0 auto;"></div>') +
      '<div style="flex:1 1 0;min-width:0;">' +
        '<div style="font-size:.84rem;font-weight:700;color:#cbd5e3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(meta.label) + '</div>' +
        '<div style="font-size:.72rem;color:#7a8fa3;margin-top:1px;">' + esc(acctLabel) + ' · 完了 ' + esc(fmtTs(meta.completedTs || meta.ts)) + '</div>' +
        (hasYt ? '<div style="font-size:.71rem;color:var(--accent);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">✅ <a href="' + esc(meta.youtubeUrl) + '" target="_blank" rel="noopener" style="color:var(--accent);">' + esc((meta.youtubeUrl).replace(/^https?:\/\//, '').slice(0, 44)) + '</a></div>' : '') +
        driveLine +
        '<div style="display:flex;gap:6px;margin-top:7px;flex-wrap:wrap;">' +
          '<button type="button" class="stk-restore" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid var(--accent);background:transparent;color:var(--accent);font-weight:700;">↩ 復元</button>' +
          '<button type="button" class="stk-dl" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #46586e;background:#151d2c;color:#dfe6ef;">⬇ 動画DL</button>' +
          '<button type="button" class="stk-drive" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #46586e;background:#151d2c;color:#dfe6ef;">☁️ Drive保存</button>' +
          '<button type="button" class="stk-arch-del" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #5a2a2a;background:transparent;color:#c77;">削除</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  // ★既に投稿完了したぶんの遡及補完(Chami 2026-08-04)。
  //   サブ端末で投稿完了した過去分は、投稿履歴の使用画像1ページ目に仕上がりプレビューが入っていない
  //   (完了時に stock_prev_ が無くガードで弾かれたため)。同期ミラー stock:imgs:<id> の .prev(dataURL)が
  //   届いている今なら後から差し込める。videoId単位・プレビュー未挿入のものだけ・冪等。
  var _prevBackfilled = {}; // このセッションで補完済み/確認済みの videoId(再走査を抑える)
  var _prevBackfillBusy = false;
  function backfillUsedPreview_() {
    var store = idb(); if (!store || _prevBackfillBusy) return;
    var items = loadMeta().concat(loadArchive()).filter(function (m) { return m && m.id && m.videoId && !_prevBackfilled[m.videoId]; });
    _prevBackfillBusy = true;
    var i = 0;
    function done_() { _prevBackfillBusy = false; }
    function next_() {
      if (i >= items.length) { done_(); return; }
      var m = items[i++];
      usedImagesRead_(m.videoId).then(function (rec) {
        var cur = (rec && Array.isArray(rec.imgs)) ? rec.imgs.filter(Boolean) : [];
        var prevN = (rec && rec.prev) ? (rec.prev | 0) : 0;
        if (prevN > 0) { _prevBackfilled[m.videoId] = 1; return null; }
        return store.get('stock:imgs:' + m.id).then(function (mir) {
          var du = mir && mir.prev;
          if (!du) return; // ミラーがまだ来ていない=次の同期機会に再試行
          _prevBackfilled[m.videoId] = 1;
          if (cur[0] === du) return;
          return usedImagesSave_(m.videoId, [du].concat(cur.filter(function (u) { return u !== du; })), 1).then(function () {
            try { if (window.YtRank && window.YtRank.renderRank && $('pageRank') && !$('pageRank').hidden) window.YtRank.renderRank(); } catch (e) {}
          });
        });
      }).catch(function () {}).then(function () { setTimeout(next_, 30); });
    }
    next_();
  }

  // ── 投稿履歴からの過去分プレビュー生成に使う公開API(Chami依頼2026-08-13「投稿履歴の🔁ボタンに統合」)。
  //   videoId(投稿履歴のキー)→ 対応するドラフト/作成履歴の stock id を引き、動画(手元 or R2の控え)の
  //   末尾(約5秒)フレームで仕上がりプレビューを起こして dataURL を返す。呼び出し側(yt-clicks.js)が投稿履歴の
  //   使用画像1ページ目へ挿入する。動画の在りかを引けない(この端末に stock 記録が無い)/動画が手元にも
  //   雲にも無い時は null(=この端末では生成不可)。生成できたら端末内 stock_prev_ にも控える(次回は速い)。
  function previewForVideoId_(videoId) {
    if (!videoId) return Promise.resolve(null);
    var all = loadMeta().concat(loadArchive());
    var m = null;
    for (var i = 0; i < all.length; i++) { if (all[i] && all[i].videoId === videoId) { m = all[i]; break; } }
    if (!m) return Promise.resolve(null); // この端末に stock 記録が無い=動画の在りかを引けない
    var store = idb();
    var existP = store ? store.get('stock_prev_' + m.id).catch(function () { return null; }) : Promise.resolve(null);
    return existP.then(function (pb) {
      if (pb) return blobToDataUrlP_(pb); // 既にローカルに控えがある=動画デコードを省く
      return resolveVideoBlob_(m.id).then(function (vBlob) {
        if (!vBlob) return null;                       // 手元にも雲(R2)にも動画が無い=復元不可
        return videoEndFramePreview_(vBlob).then(function (prevBlob) {
          if (!prevBlob) return null;
          try { if (store) store.set('stock_prev_' + m.id, prevBlob).catch(function () {}); } catch (e) {} // 次回のために控える(冪等)
          return blobToDataUrlP_(prevBlob);
        });
      });
    }).catch(function () { return null; });
  }

  // 動画Blob(Driveから取り寄せた別端末作成分など)→末尾(約5秒)フレームで仕上がりプレビューを起こし dataURL を返す。
  //   stock記録に依らない=videoIdが引けない投稿でも、動画さえ渡されれば生成できる(Chami指摘2026-08-14)。
  function previewFromVideoBlob_(vBlob) {
    if (!vBlob) return Promise.resolve(null);
    return videoEndFramePreview_(vBlob).then(function (prevBlob) {
      if (!prevBlob) return null;
      return blobToDataUrlP_(prevBlob);
    }).catch(function () { return null; });
  }
  // videoId→この端末(IDB)or 雲(R2)の動画Blobを取り寄せる。無ければ null。
  //   ★投稿履歴の「データ再作成」(yt-clicks.js)がDriveへ一式保存し直す時、端末側の動画本体が要るため公開する
  //   (Driveからも取れるが、端末に生きていれば再ダウンロード不要=こちらを先に試す・Chami依頼2026-08-15)。
  function videoBlobForId_(videoId) {
    if (!videoId) return Promise.resolve(null);
    var all = loadMeta().concat(loadArchive());
    var m = null;
    for (var i = 0; i < all.length; i++) { if (all[i] && all[i].videoId === videoId) { m = all[i]; break; } }
    if (!m) return Promise.resolve(null); // この端末に stock 記録が無い=動画の在りかを引けない
    return resolveVideoBlob_(m.id).catch(function () { return null; });
  }

  var _renderSeq = 0, _lastRenderedStockSig = '', _missingThumbs = {}, _stockBgPending = false;
  // 作成履歴(details)の開閉状態を再描画をまたいで保持する。render毎に<details>を作り直すと
  //   open属性が消えて閉じる=「削除を押すと作成履歴が閉じる」の真因(Chami報告2026-08-13③)。
  var _archOpen = false;
  function stockViewSig_(acct) {
    try {
      var m = loadMeta().filter(function (x) { return (x.account || 'acc1') === acct; });
      var a = loadArchive().filter(function (x) { return (x.account || 'acc1') === acct; });
      return JSON.stringify([m, a]);
    } catch (e) { return ''; }
  }
  function render() {
    var page = $('pageStock');
    if (!page || page.hidden) return;
    _stockBgPending = false;
    var curAcct = (window.Go5Acct && Go5Acct.current && Go5Acct.current()) || 'acc1';
    var metas = loadMeta().filter(function (m) { return (m.account || 'acc1') === curAcct; });
    // ★表示順=日付が昔(古い)を一番上へ(Chami依頼2026-08-19「ドラフトの履歴は日付が昔が一番上に来るように」)。
    //   これは表示専用の並べ替え=metasはloadMeta()のフィルタ済みコピーなので、保存側(unshiftで新しい順・MAX_DRAFTS間引き)は不変。
    metas.sort(function (a, b) { return (a.ts || 0) - (b.ts || 0); });
    var arch = loadArchive().filter(function (m) { return (m.account || 'acc1') === curAcct; });
    // ★作成履歴(🗂投稿完了ぶん)も同じく日付が昔(古い)を一番上へ(Chami依頼2026-08-19「ドラフトの作成履歴も！」)。
    //   並べる鍵はカードに出している「完了」日時(completedTs)＝見えている日付と一致させる(無ければ ts)。
    //   これも表示専用=archはloadArchive()のフィルタ済みコピーなので、保存側(unshiftで新しい順・ARCHIVE_MAX間引き・id単位union同期)は不変。
    arch.sort(function (a, b) { return ((a.completedTs || a.ts || 0) - (b.completedTs || b.ts || 0)); });
    // ★保存中(未着地)ドラフト=メモリ上の pending だけ。着地(commitPendingDraft_)で metas 側へ移るので、
    //   既に metas に居る id は除外して重複を防ぐ(B・Fable5設計2026-08-17)。
    var _metaIds = {}; metas.forEach(function (m) { _metaIds[m.id] = 1; });
    var pendingList = Object.keys(_pendingDraftMeta).map(function (k) { return _pendingDraftMeta[k]; })
      .filter(function (m) { return m && (m.account || 'acc1') === curAcct && !_metaIds[m.id]; });
    var sig = stockViewSig_(curAcct), seq = ++_renderSeq;

    var store = idb();
    var all = metas.concat(arch);
    // ★保存中(pending)のDrive保存は、この端末が開くたびに実物照会を再起動する=前回タブを閉じた後に着地した分も拾って確認中→実物確認へ上げる。
    all.forEach(function (m) { if (m && m.id) { var _ds = driveSavedState_(m.id); if (_ds && _ds.state === 'pending') verifyDriveLanded_(m.id); } });

    // 一覧HTMLを thumbFor(id→サムネURL/null)から組み立てて描画する。(サムネの有無に依らず同じ骨格)
    function paint_(thumbFor) {
      if (seq !== _renderSeq || page.hidden) return;
      // ★過去分プレビューの一括復元は「投稿履歴の🔁ボタン」へ統合した(Chami依頼2026-08-13)。
      //   ドラフトタブのこのボタンは撤去(Chami「ドラフトタブにそのボタンは不要・削除で」)。
      var html = '';
      // ★保存中カード(ページ内表示中に生成直後のドラフトを「保存中…」で先頭表示・B)。
      if (pendingList.length) {
        html += '<div class="card" style="border:1px solid var(--accent);">' +
          '<div style="font-size:.95rem;font-weight:700;color:var(--accent);margin-bottom:10px;">⏳ 保存中(' + pendingList.length + '件)</div>' +
          pendingList.map(function (m) { return renderPendingItem_(m); }).join('') +
        '</div>';
      }
      html += '<div class="card">';
      if (metas.length) {
        html += '<div style="font-size:.95rem;font-weight:700;color:var(--accent);margin-bottom:10px;">📦 ドラフト(' + metas.length + '件)</div>' +
          metas.map(function (m) { return renderItem_(m, thumbFor[m.id]); }).join('');
      } else {
        html += '<div style="color:var(--sub);text-align:center;padding:28px 16px;font-size:.9rem;">' +
          'このアカウントのドラフトはまだありません。<br>動画作成タブの「📦 ドラフトで作成」で動画をここへ貯められます。</div>';
      }
      html += '</div>';
      // ④作成履歴=投稿完了ぶんの退避リスト。ドラフト本体の下に折りたたみで置く(初期は閉じ・タップで開く)。
      if (arch.length) {
        html += '<details id="stkArchDetails"' + (_archOpen ? ' open' : '') + ' style="margin-top:12px;">' +
          '<summary style="cursor:pointer;font-size:.86rem;font-weight:700;color:var(--sub);padding:11px 14px;background:var(--card);border:1px solid var(--line);border-radius:12px;">🗂 作成履歴(投稿完了ぶん・' + arch.length + '件) — タップで開く/復元</summary>' +
          '<div class="card" style="margin-top:8px;">' +
          arch.map(function (m) { return renderArchItem_(m, thumbFor[m.id]); }).join('') +
          '</div></details>';
      }
      page.innerHTML = html;
      _lastRenderedStockSig = sig;
    }

    // ★まず同期で即描画する=IDBサムネ読込を待たずに一覧の文字(件数/空メッセージ/作成履歴)を必ず出す。
    //   従来は Promise.all(thumbPs) の解決を待って初めて innerHTML を入れていたため、iOS SafariでIDB get が
    //   無言ハングすると Promise が永久に未解決=ページが真っ白のまま(リロードでたまたま復帰)。=「8割
    //   何も表示されない/リロードで直る」の根治(Chami報告2026-08-12)。サムネはキャッシュ分だけ即出し、
    //   残りは下の非同期取り込みで差し替える。
    var cachedFor = {}; _missingThumbs = {};
    all.forEach(function (m) { var u = _thumbCache[m.id] || m.thumbDataUrl || null; cachedFor[m.id] = u; if (!u) _missingThumbs[m.id] = 1; });
    paint_(cachedFor);

    var thumbPs = all.map(function (m) {
      if (_thumbCache[m.id]) return Promise.resolve(_thumbCache[m.id]);
      if (m.thumbDataUrl) return Promise.resolve(m.thumbDataUrl);
      if (!store) return Promise.resolve(null);
      return store.get('stock_t_' + m.id).then(function (blob) {
        if (blob) {
          _thumbCache[m.id] = URL.createObjectURL(blob);
          return _thumbCache[m.id];
        }
        // 実体が無い端末(2台目)=同期で来た stock:imgs ミラーの dataURL からサムネを出す(①-B)
        return store.get('stock:imgs:' + m.id).then(function (mir) {
          var du = mir && (mir.th || mir.prev || mir.src);
          if (du) { _thumbCache[m.id] = du; return du; }
          // ★サムネ(stock_t_)もミラーも無い=過去に toBlob 不達で黒箱になったカードを、
          //   仕上がりプレビュー→元画像 の順に拾って救う(既存の黒箱も開くだけで埋まる・Chami報告2026-08-13①)。
          return store.get('stock_prev_' + m.id).then(function (pb) {
            if (pb) { _thumbCache[m.id] = URL.createObjectURL(pb); return _thumbCache[m.id]; }
            return store.get('stock_img_' + m.id).then(function (ib) {
              if (ib) { _thumbCache[m.id] = URL.createObjectURL(ib); return _thumbCache[m.id]; }
              // ★手元のサムネ系が全滅(iOSがIDBを退避)=作成時にR2へ控えた元画像 go5src:<id> をサムネ代わりに
              //   「1回だけ」取り寄せて「確認中」を絵に戻す(2026-08-17・Fable5診断P3)。null時は _r2ThumbTried で
              //   再取得を止め、毎描画のfetch連打を防ぐ。
              if (!_r2ThumbTried[m.id] && window.Go5Sync && Go5Sync.fetchBlobR2At) {
                _r2ThumbTried[m.id] = 1;
                return Go5Sync.fetchBlobR2At('go5src:' + m.id).then(function (rb) {
                  if (rb && rb.size) { _thumbCache[m.id] = URL.createObjectURL(rb); return _thumbCache[m.id]; }
                  return null;
                }).catch(function () { return null; });
              }
              return null;
            }).catch(function () { return null; });
          }).catch(function () { return null; });
        }).catch(function () { return null; });
      }).catch(function () { return null; });
    });

    // ★サムネは「解決したカードから1枚ずつ即差し替え」る(2026-08-18 Fable5診断/Chami「サムネが遅すぎる」)。
    //   旧実装は Promise.all(thumbPs) で全カードの解決を待ってから一括 paint_ していたため、iOS SafariでIDB read が
    //   1件でも数秒ハングすると、既に揃っている他カードまで最遅の1件に道連れで待たされた=「全員が確認中のまま遅い」。
    //   個別差し替えなら最遅1件は自分のカードだけを待つ。全innerHTML交換をしないので開いている作成履歴も閉じない。
    function _stillCurrent_() {
      var nowAcct = (window.Go5Acct && Go5Acct.current && Go5Acct.current()) || 'acc1';
      return !(seq !== _renderSeq || page.hidden || nowAcct !== curAcct || stockViewSig_(curAcct) !== sig);
    }
    thumbPs.forEach(function (p, idx) {
      var m = all[idx];
      p.then(function (url) {
        if (!url || !_stillCurrent_()) return;
        var sel = (window.CSS && CSS.escape) ? CSS.escape(m.id) : m.id;
        var card = page.querySelector('[data-item-id="' + sel + '"]');
        if (!card) return;
        var cur = card.firstElementChild; // カードの先頭要素=サムネ(img)or プレースホルダ(div)
        if (!cur) return;
        if (cur.tagName === 'IMG' && cur.getAttribute('src') === url) return; // 既に同じ絵=何もしない
        var img = document.createElement('img');
        img.src = url; img.alt = '';
        img.style.cssText = 'width:40px;height:71px;object-fit:cover;border-radius:5px;flex:0 0 auto;';
        card.replaceChild(img, cur);
        delete _missingThumbs[m.id];
      }).catch(function () {});
    });
    // 古い描画(アカウント/同期切替)の後始末だけは全解決後に一度。ここでは全交換paintをしない(個別差し替え済み)。
    Promise.all(thumbPs).then(function (thumbUrls) {
      if (!_stillCurrent_()) {
        if (!page.hidden && !modalIsOpen_()) setTimeout(render, 0);
        return;
      }
      _missingThumbs = {};
      all.forEach(function (m, i) { if (!thumbUrls[i]) _missingThumbs[m.id] = 1; });
    });
  }

  // ★ページ内でドラフト一覧を前面に出す(B・Fable5設計2026-08-17)。破壊遷移(location.href='Stock.html')を
  //   使わず #pageStock を表示=生成直後に一覧が出て「自動遷移が遅い/手動タブの方が速い」を解消し、かつ
  //   手動タブの全消し窓(8/15の全滅=着地前に location.href でblobを殺す)も塞ぐ。保存窓の間だけ有効
  //   (__go5SaveInFlight=true)。affiliate.js の showTab を単一の切替権威として使い、その tabStock 早期return
  //   (Stock.htmlへ)は __go5SaveInFlight で無効化される=一覧表示+render() は showTab 側が担う。
  function showStockInline_() {
    window.__go5SaveInFlight = true;
    if (typeof window.showTab === 'function') { try { window.showTab('tabStock'); return; } catch (e) {} }
    // フォールバック(affiliate.js 未ロード時のみ): 手動で #pageStock を前面へ。
    try {
      var secs = document.querySelectorAll('section[id^="page"]');
      for (var i = 0; i < secs.length; i++) secs[i].hidden = (secs[i].id !== 'pageStock');
      var ps = $('pageStock'); if (ps) ps.hidden = false;
      document.documentElement.setAttribute('data-tab', 'tabStock');
      try { localStorage.setItem('go5_active_tab', 'tabStock'); } catch (e2) {}
    } catch (e3) {}
    render();
  }

  // ── 投稿モード モーダル ──
  var _modalMeta = null;
  var _ytTitleDirty = false; // ユーザーが題名を手編集したかどうか(trueの間はタグ変更で上書きしない)
  var _pickedSlot = null;    // 予約投稿で選んだカレンダーの公開枠(slot-picked で受ける){id,date,time,role,genre,scheduled_at}
  // ★投稿モードを開いている間だけ、開いているドラフトidをタブセッションに覚える(Chami報告2026-08-08)。
  //   iOS SafariはX/YouTubeアプリへ切り替えて戻ると、メモリ都合でこのタブのページを丸ごと捨てて
  //   再読込することがある(=戻ると「リロード」に見える。JS側のlocation.reloadは存在しない=OS判断)。
  //   sessionStorageはタブが生きている限り再読込を跨いで残る=戻ってきた瞬間に同じドラフトの投稿モードを
  //   開き直せば、途中だった作業を失わずリロードが実質見えなくなる。ページを閉じれば消える(勝手には開かない)。
  var OPEN_MODAL_KEY = 'go5_open_post_modal';
  function rememberOpenModal_(id) { try { sessionStorage.setItem(OPEN_MODAL_KEY, id || ''); } catch (e) {} }
  function forgetOpenModal_() { try { sessionStorage.removeItem(OPEN_MODAL_KEY); } catch (e) {} }
  function modalIsOpen_() { var m = $('draftPostModal'); return !!(m && m.style.display !== 'none'); }
  function closeModal_() { var m = $('draftPostModal'); if (m) m.style.display = 'none'; _modalMeta = null; forgetOpenModal_(); if (_stockBgPending) setTimeout(render, 0); }

  function copyText_(text, btn) {
    function flash() { var o = btn.textContent; btn.textContent = 'コピーしました'; setTimeout(function () { btn.textContent = o; }, 2000); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(flash).catch(function () { fallback_(); });
    } else { fallback_(); }
    function fallback_() {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.cssText = 'position:fixed;top:0;opacity:0;';
      document.body.appendChild(ta); ta.focus(); ta.select();
      try { document.execCommand('copy'); flash(); } catch (e) {}
      document.body.removeChild(ta);
    }
  }

  function buildModalYtTitle_() {
    var el = $('draftYtTitleText');
    if (!el || !_modalMeta) return;
    var title = (_modalMeta.title || '').replace(/\n+/g, '');
    var tags = ($('draftYtTagsInput') || {}).value || '';
    el.value = title + (title && tags.trim() ? ' ' : '') + tags.trim();
  }

  // ---- 公開設定(即時/予約)＋公開枠ピッカー ----
  function curPubMode_() { var r = $('draftPubSched'); return (r && r.checked) ? 'scheduled' : 'now'; }
  // ラジオの状態に合わせて「公開枠を選ぶ」行の表示/非表示を切り替える。
  function syncPubModeUI_() {
    var row = $('draftSchedRow'); if (row) row.style.display = (curPubMode_() === 'scheduled') ? 'block' : 'none';
    renderPickedSlot_();
  }
  // 選んだ枠のラベル表示。未選択なら「解除」を隠す。
  function renderPickedSlot_() {
    var lab = $('draftPickedSlot'), clr = $('draftClearSlot');
    if (!lab) return;
    if (_pickedSlot && _pickedSlot.date) {
      lab.textContent = '選択中：' + _pickedSlot.date + (_pickedSlot.time ? ' ' + _pickedSlot.time : '') + (_pickedSlot.role ? '／' + _pickedSlot.role : '');
      if (clr) clr.style.display = '';
    } else {
      lab.textContent = '(枠は未選択)';
      if (clr) clr.style.display = 'none';
    }
  }
  // カレンダーを上から降ろす。schedule/ を pick=1 で埋め込み、枠タップ→slot-picked を受ける。
  function openSlotPicker_() {
    // ドラフトの投稿先チャンネルを渡す=ピッカーはそのchの枠だけを表示する(Chami依頼2026-08-05)。
    var acc = (_modalMeta && _modalMeta.account) || (window.Go5Acct && Go5Acct.current && Go5Acct.current()) || 'acc1';
    var pk = $('draftSlotPicker');
    if (!pk) {
      pk = document.createElement('div');
      pk.id = 'draftSlotPicker';
      // 上から降りてくる=固定オーバーレイ＋transformでスライドイン。z-indexは投稿モーダル(9999)より上。
      // ★背景は必ず不透明にする(--card はアカウントテーマ下で rgba(...,.06)=透けるため使わない・Chami「透明にしない」2026-08-05)。
      pk.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:10000;background:var(--app-bg,#0e1422);border-bottom:1px solid var(--line);' +
        'box-shadow:0 12px 32px rgba(0,0,0,.5);transform:translateY(-100%);transition:transform .28s ease;' +
        'display:flex;flex-direction:column;max-height:82vh;';
      pk.innerHTML =
        '<div style="padding:11px 14px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px;background:var(--app-bg,#0e1422);">' +
          '<div style="font-size:.9rem;font-weight:800;color:var(--accent);flex:1;">公開枠を選ぶ</div>' +
          '<div style="font-size:.74rem;color:var(--sub);">枠をタップ→「この枠を公開枠に選ぶ」</div>' +
          '<button type="button" id="draftPickerClose" style="background:none;border:none;color:var(--sub);font-size:1.2rem;cursor:pointer;padding:2px 8px;line-height:1;width:auto;margin:0;">✕</button>' +
        '</div>' +
        '<iframe id="draftPickerFrame" title="公開枠カレンダー" style="border:0;width:100%;flex:1;min-height:60vh;background:var(--bg,#0e1422);"></iframe>';
      document.body.appendChild(pk);
      $('draftPickerClose').addEventListener('click', closeSlotPicker_);
    }
    var f = $('draftPickerFrame');
    if (f && !f.getAttribute('src')) f.setAttribute('src', 'schedule/index.html?pick=1&acc=' + acc + '&v=37');
    // 表示→次フレームでスライドイン。iframe読込後に enter-pick を送る(未読込なら onload で)。
    pk.style.display = 'flex';
    requestAnimationFrame(function () { pk.style.transform = 'translateY(0)'; });
    var send = function () { try { f.contentWindow.postMessage({ target: 'sch-calendar', type: 'enter-pick', acc: acc }, '*'); } catch (e) {} };
    if (f.contentWindow && f.dataset.loaded === '1') send();
    else { f.addEventListener('load', function () { f.dataset.loaded = '1'; send(); }, { once: true }); }
  }
  function closeSlotPicker_() {
    var pk = $('draftSlotPicker'); if (!pk) return;
    var f = $('draftPickerFrame');
    if (f && f.contentWindow) { try { f.contentWindow.postMessage({ target: 'sch-calendar', type: 'exit-pick' }, '*'); } catch (e) {} }
    pk.style.transform = 'translateY(-100%)';
    setTimeout(function () { pk.style.display = 'none'; }, 280);
  }
  // カレンダーiframe(pick=1)からの枠選択を受ける。投稿モーダルが開いている時だけ取り込む。
  window.addEventListener('message', function (ev) {
    var d = ev.data;
    if (!d || d.source !== 'sch-calendar' || d.type !== 'slot-picked' || !d.slot) return;
    var s = d.slot;
    _pickedSlot = { id: s.id || '', date: s.date || '', time: s.time || '', role: s.role || '', genre: s.genre || '', scheduled_at: s.scheduled_at || '' };
    // 予約が選ばれた=ラジオも予約へ寄せる(即時のまま枠だけ持つ矛盾を避ける)。
    var r = $('draftPubSched'); if (r) { r.checked = true; syncPubModeUI_(); }
    renderPickedSlot_();
    saveDraftPost_();
    closeSlotPicker_();
  });

  function saveDraftPost_() {
    if (!_modalMeta) return;
    var slotEl = $('draftYtDescUrlLink');
    var data = {
      xText:   ($('draftXText')       || {}).value || '',
      ytTitle: ($('draftYtTitleText') || {}).value || '',
      ytTags:  ($('draftYtTagsInput') || {}).value || '',
      ytUrl:   ($('draftYtUrl')       || {}).value || '',
      ytDesc:  ($('draftYtDescText')  || {}).value || '',
      xPostUrl:  ($('draftXPostUrl')  || {}).value || '',
      xShortUrl: (slotEl && slotEl.dataset.url) || '',
      pubMode:   curPubMode_(),          // 'now' | 'scheduled'(YouTube公開のタイミング)
      pubSlot:   _pickedSlot || null,    // 予約投稿で選んだカレンダー公開枠(任意)
    };
    // ★導線2の計測用短縮URL(mintDraftWorkShort_ が発行して残す正本フィールド)は、この本文保存で
    //   握り潰さないよう既存レコードから引き継ぐ(dataに項目が無いとJSON全置換で消える=空欄再発の穴)。
    try {
      var _ex0 = JSON.parse(localStorage.getItem('go5_draft_post_' + _modalMeta.id) || '{}') || {};
      ['workShortUrl', 'workShareUrl', 'workShortFor'].forEach(function (f) { if (_ex0[f] && !data[f]) data[f] = _ex0[f]; });
    } catch (e) {}
    try { localStorage.setItem('go5_draft_post_' + _modalMeta.id, JSON.stringify(data)); } catch (e) {}
    kickSync_(); // 投稿編集も全端末へ運ぶ
  }

  // 導線2(作品クリック計測用短縮URL)の発行結果だけを go5_draft_post_ へ非破壊マージ保存する。
  //   ★saveDraftPost_ は呼ばない=モーダルDOM全体を読み直して未編集の xText='' で上書きし「空=未編集」
  //   ロジックを壊すため。この専用ヘルパで該当3フィールドだけ書き、既存の本文編集には触れない。
  function saveDraftWorkShortField_(id, obj) {
    try {
      var k = 'go5_draft_post_' + id;
      var sv = JSON.parse(localStorage.getItem(k) || '{}') || {};
      var changed = false;
      ['workShortUrl', 'workShareUrl', 'workShortFor'].forEach(function (f) {
        if (obj[f] && sv[f] !== obj[f]) { sv[f] = obj[f]; changed = true; }
      });
      if (changed) { localStorage.setItem(k, JSON.stringify(sv)); kickSync_(); }
    } catch (e) {}
  }

  // 投稿完了の直前に、導線2「作品計測用短縮URL」の非同期発番(openPostModal_ が蹴った mintDraftWorkShort_)が
  //   go5_draft_post_ へ着地するのを短時間だけ待ってから done() を呼ぶ。着地済み/発番対象なし/上限到達なら即 done()。
  //   ★これで「発番が終わる前に投稿完了を押す→履歴の計測URL欄が空」の競合を塞ぐ(REQ-65c7897f2f 恒久対策の穴埋め)。
  //   非破壊：待っても取れなければ従来どおり進む=投稿完了は決してブロックしない。判定は workshort-gate-core.js。
  function waitWorkShortSettle_(id, maxMs, done) {
    var gate = (window.Go5WorkShortGate && window.Go5WorkShortGate.step)
      || function () { return 'record'; }; // coreが未ロードでも完了は止めない(従来=待たず記録)
    var meta = null;
    try { meta = loadMeta().filter(function (m) { return m.id === id; })[0] || null; } catch (e) {}
    function sv_() { try { return JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}') || {}; } catch (e) { return {}; } }
    var t0 = Date.now();
    (function tick_() {
      if (gate(sv_(), meta, Date.now() - t0, maxMs) === 'record') { done(); return; }
      setTimeout(tick_, 200);
    })();
  }

  // ★投稿本文の「正」= 投稿タブのテキストボックス(テンプレ帳の本文・アカウント別)。Chami指定2026-07-31:
  //   「今までどれが正かわからなかった」→ 投稿モードもここを参照し、この本文が唯一の正となる。
  //   ・同一アカウントなら未保存の編集も反映するため生のテキストボックスを優先。
  //   ・別アカウントの投稿を開いた時は、そのアカウントの保存済みマスター(bsky_text__accN)を読む。
  //   ・どちらも取れなければ、その投稿の当時のスナップショット(meta.bskyText)にフォールバック。
  function masterBody_(meta) {
    var acc = (meta && meta.account) || (window.Go5Acct && Go5Acct.current && Go5Acct.current()) || 'acc1';
    try {
      var cur = (window.Go5Acct && Go5Acct.current && Go5Acct.current()) || 'acc1';
      var b = $('bskyText');
      // Stock.htmlの#bskyTextは共通短縮モジュールを起動する非表示ホストであり、
      // 投稿本文の入力欄ではない。非表示ホストの既定文でドラフト当時の本文を上書きしない。
      if (b && !b.hidden && cur === acc && b.value) return b.value;
    } catch (e) {}
    try {
      var k = (window.Go5Acct && Go5Acct.key) ? Go5Acct.key('bsky_text', acc) : ('bsky_text__' + acc);
      var v = localStorage.getItem(k);
      if (v != null && v !== '') return v;
    } catch (e) {}
    return (meta && meta.bskyText) || '';
  }

  // 販促テンプレの解決に必要な値(タグ種別/割引率/実価格)を、手元のキャッシュだけで集める(ネット不使用)。
  //   ・Go5WorkInfo(取得済みキャッシュ)→ fanza_title_cache(スナップ) の順。取れなければ null(=Nのまま=誤値を貼らない)。
  // 手元の生キャッシュ(取得済みFANZA情報→スナップ)から価格/割引率だけを引く(ネット不使用)。取れなければ null。
  function livePriceInfo_(url) {
    var price = null, pct = null;
    try { var info = (url && window.Go5WorkInfo) ? window.Go5WorkInfo(url) : null; if (info) { if (info.price != null) price = info.price; if (info.discountPct != null) pct = info.discountPct; } } catch (e) {}
    if (price == null || pct == null) {
      try {
        var fc = (JSON.parse(localStorage.getItem('fanza_title_cache') || '{}') || {})[url];
        if (fc && fc.priceInfo) { if (price == null && fc.priceInfo.price != null) price = fc.priceInfo.price; if (pct == null && fc.priceInfo.discountPct != null) pct = fc.priceInfo.discountPct; }
      } catch (e) {}
    }
    return { price: price, pct: pct };
  }
  function promoInfo_(meta) {
    var type = 'discount';
    try { type = (localStorage.getItem('promo_label_type') === 'price') ? 'price' : 'discount'; } catch (e) {}
    var url = (meta && (meta.workUrl || meta.affiliateUrl)) || '';
    var live = livePriceInfo_(url);
    var price = live.price, pct = live.pct;
    // ★生キャッシュが失効/未取得でも、ドラフト作成時に焼いたスナップ(meta.priceInfo)へフォールバック
    //   =再作成の往復・別端末・キャッシュ失効でも投稿モードの割引%が「N%」に落ちない(Chami依頼2026-08-06④)。
    if (meta && meta.priceInfo) {
      if (price == null && meta.priceInfo.price != null) price = meta.priceInfo.price;
      if (pct == null && meta.priceInfo.pct != null) pct = meta.priceInfo.pct;
    }
    return { type: type, price: price, pct: pct };
  }
  // 販促テンプレ(%:/¥: 候補行・N%/N円/¥N・%表示時の価格行削除)を解決する。純粋関数は bluesky-core 側。(Chami依頼2026-08-03①②)
  function applyPromo_(text, meta) {
    if (window.BlueskyCore && window.BlueskyCore.resolvePromoTemplate) return window.BlueskyCore.resolvePromoTemplate(text, promoInfo_(meta));
    return String(text || '');
  }
  // 投稿モードのX本文を組む＝bluesky側の合成(短縮URL置換等)→販促テンプレ解決 の順で通す。
  function composeXForModal_(meta) {
    var base;
    // ★作品リンクは affiliateUrl を第一に、空なら workUrl へ倒す(mintDraftWorkShort_ の meta.affiliateUrl||meta.workUrl と揃える)。
    //   これが affiliateUrl だけだと、affiliateUrl 未設定のドラフトで作品プレースホルダ「(商品紹介短縮URL)」が
    //   置換対象リンクを得られず literal のまま残っていた(Chami報告2026-08-13「短縮URLが反映されない」)。
    if (window.__go5ComposeXTextForBskyText) base = window.__go5ComposeXTextForBskyText(masterBody_(meta), (meta && (meta.affiliateUrl || meta.workUrl)) || '');
    else base = masterBody_(meta);
    return applyPromo_(base, meta);
  }
  // 後方互換(呼び出し元が残っていても壊さない)。YouTube説明欄も同じ販促解決を通す。
  function resolveYtDescYen_(text, meta) { return applyPromo_(text, meta); }

  // ①短縮URL置換：このドラフトの作品アフィリンクの短縮を発番し、X本文の生リンク/プレースホルダを短縮へ差し替える。
  //   ・発番は非同期(Go5MakeShort=makeShortAndShare)。302素通しでaf_idは保持=クリック計測は壊れない。
  //   ・モーダルが別作品へ切り替わっていたら書かない(_modalMeta !== meta)。失敗時は生リンク/プレースホルダのまま(何も壊さない)。
  var _shortMintCache = {}; // aff → { shortUrl(r2・計測用), shareUrl(表示用) }(同一作品の二重発番を避ける)
  function mintDraftWorkShort_(meta) {
    var aff = (meta && (meta.affiliateUrl || meta.workUrl) || '').trim();
    if (!aff || !window.Go5MakeShort) return;
    // ★発行結果(r2)を go5_draft_post_ の正本フィールドとして残す=これが導線2空欄の恒久対策の核心。
    //   従来は短縮URLをX本文とメモリ内キャッシュにしか書かず、投稿完了時はyt-clicks側の"投げっぱなし再発行"
    //   だけが頼りで、ページ離脱/一過性失敗で無言に落ちると欄が永久に空になっていた(REQ-65c7897f2f他)。
    //   ここでX本文に実際に貼るコードそのものを保存する=完了時に値として渡り、本文/履歴/シートが三点一致する。
    function persistWorkShort_(res) {
      if (_modalMeta !== meta || !res) return;
      var go5 = window.Go5Short || {};
      if (!(go5.ourBase && res.shortUrl && go5.ourBase(res.shortUrl))) return; // 計測キー(r2)のみ永続化。fallbackは完了時mint(リトライ付)へ委ねる
      saveDraftWorkShortField_(meta.id, { workShortUrl: res.shortUrl, workShareUrl: res.shareUrl || res.shortUrl, workShortFor: aff });
    }
    function applyShare_(res) {
      persistWorkShort_(res);
      var share = (res && (res.shareUrl || res.shortUrl)) || '';
      if (!share || _modalMeta !== meta) return;
      var el = $('draftXText'); if (!el) return;
      var v = el.value, nv = v;
      if (v.indexOf(aff) >= 0) nv = v.split(aff).join(share); // 生アフィリンクを短縮へ
      else if (window.BlueskyCore && window.BlueskyCore.hasWorkLinkPlaceholder && window.BlueskyCore.hasWorkLinkPlaceholder(v)) {
        nv = window.BlueskyCore.fillWorkLinkPlaceholder(v, share, ''); // プレースホルダを短縮で埋める
      }
      if (nv !== v) {
        el.value = nv; // 表示だけ更新(未編集なら手編集扱いにしない=saveDraftPost_は呼ばない)
        // ★保存済みの投稿編集(saved.xText)が生アフィリンクのまま凍結されているのを短縮版へ更新する。
        //   これが無いと復元→再度開くたびに生リンクへ戻る(Chami報告2026-08-11「復活させたら短縮化されてない」)。
        //   saved.xText が無い(未編集)場合は保存しない=「空=未編集」ロジック(openPostModal_)を壊さない。
        try {
          var _sv = JSON.parse(localStorage.getItem('go5_draft_post_' + meta.id) || '{}');
          if (_sv && _sv.xText) saveDraftPost_();
        } catch (e) {}
      }
    }
    if (_shortMintCache[aff]) { applyShare_(_shortMintCache[aff]); return; }
    // ★短縮発番(link-worker=Go5MakeShort)が一度失敗すると、以前は無言catchで諦め「(商品紹介短縮URL)」が
    //   埋まらないまま固まった(Chami報告2026-08-13②)。一過性の失敗を数回リトライ(指数バックオフ)して自己回復する。
    //   別作品へ切り替わったら止める。3回で諦める。account=そのドラフトのchドメインで発行(取り違え防止)。
    var tries = 0;
    (function attempt_() {
      if (_modalMeta !== meta) return;
      tries++;
      var retry_ = function () { if (tries < 3 && _modalMeta === meta) setTimeout(attempt_, tries * 1500); };
      try {
        window.Go5MakeShort(aff, { account: meta.account }).then(function (r) {
          // ★成功=計測キー(r2/独自ドメイン)が取れた時だけ。2026-08-13の da.gd 全廃以降、makeShortAndShare は
          //   worker瞬断時に"生アフィリンク"を shortUrl/shareUrl として返す(bluesky.js:1950)。生URLを成功と
          //   誤認すると①_shortMintCache が汚れてリトライが二度と走らず欄が永久に空(REQ-28ef251ba4/65c7897f2f)
          //   ②X本文プレースホルダへ生アフィリンクが充填される(§6.1のP0作法違反)。r2以外はキャッシュせずリトライへ。
          var go5 = window.Go5Short || {};
          if (r && r.shortUrl && go5.ourBase && go5.ourBase(r.shortUrl)) {
            _shortMintCache[aff] = { shortUrl: r.shortUrl, shareUrl: (r.shareUrl || r.shortUrl) };
            applyShare_(_shortMintCache[aff]); return;
          }
          retry_();
        }).catch(retry_);
      } catch (e) {}
    })();
  }

  // ①-B セール短縮URL置換：X本文の「(セール紹介短縮用URL)」を短縮セールリンクへ“その場で”埋める。
  //   ★作品側 mintDraftWorkShort_ と対。openPostModal_ の saved.xText 分岐は composeXForModal_ を通らないため、
  //     セール側だけが日本語プレースホルダのまま凍結して残っていた(Chami報告2026-08-13「まだ短縮URLリンクが置換されない」)。
  //   本文全体は作り直さない(＝手編集を壊さない)。別作品へ切り替わっていたら書かない。未発番なら発番完了後に差し替える。
  function mintDraftSaleShort_(meta) {
    if (!window.__go5FillSalePlaceholderInText) return;
    var el = $('draftXText'); if (!el) return;
    var applySale_ = function (nv) {
      if (_modalMeta !== meta) return;
      var cur = $('draftXText'); if (!cur || !nv || nv === cur.value) return;
      var saleLink = arguments[1] || '';
      // 非同期発番の間に作品URL側が先に置換されることがある。nvは開始時点の古い本文なので、
      // 発番済みURLだけを「今の本文」へ適用し、2処理の完了順による巻き戻しを防ぐ。
      if (saleLink && window.BlueskyCore && window.BlueskyCore.fillSaleLinkPlaceholder) {
        nv = window.BlueskyCore.fillSaleLinkPlaceholder(cur.value, saleLink);
      }
      cur.value = nv;
      try {
        var _sv = JSON.parse(localStorage.getItem('go5_draft_post_' + meta.id) || '{}');
        if (_sv && _sv.xText) saveDraftPost_(); // 保存済み本文があった時だけ短縮版で更新(未編集は保存しない=「空=未編集」を壊さない)
      } catch (e) {}
    };
    var filled = window.__go5FillSalePlaceholderInText(el.value, applySale_);
    if (filled && filled !== el.value) applySale_(filled);
  }

  function openPostModal_(meta) {
    _modalMeta = meta;
    _ytTitleDirty = false;
    var m = $('draftPostModal');
    if (!m) return;
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem('go5_draft_post_' + meta.id) || '{}'); } catch (e) {}
    var composedXText;
    if (saved.xText) {
      // この投稿を投稿モードで手編集した履歴があるときだけ、その編集を優先(データ喪失を防ぐ)。
      //   ★空文字('')は「未編集」とみなして再合成する。過去に空で保存されると saved.xText!==undefined が真になり、
      //     以後ずっと空欄のまま貼れなくなっていた(Chami報告2026-08-02②「X用投稿テキストは空欄」)。
      composedXText = saved.xText;
    } else {
      composedXText = composeXForModal_(meta); // 合成(短縮URL置換)→販促テンプレ解決(%:/¥:・N%/N円)
    }
    if (!composedXText) composedXText = masterBody_(meta); // 最後の砦：合成が空でも本文そのままは出す(空欄で貼れない事故の防止)
    $('draftXText').value = composedXText;
    // ①短縮URL置換：この作品のアフィリンクの短縮を発番し、本文に残る生アフィリンク/プレースホルダを短縮へ差し替える。
    //   ★短縮は draft の作品に対して非同期で発番する(live UIの作品とは別・workShortCache_は使わない)。
    //   ★保存済み(saved.xText)でも生アフィリンク完全一致/プレースホルダは短縮へ置換する(2026-08-12)。
    //     復元ドラフトは saved.xText が残るため以前はmintを丸ごとスキップし、X用アフィリンクが生のまま
    //     凍結されていた(Chami報告2026-08-11)。mintDraftWorkShort_ は生リンク/プレースホルダ以外は触らない
    //     ので手編集文は壊れない(既に短縮済みなら no-op)。置換が起きて保存済み本文があった時だけ保存も更新。
    mintDraftWorkShort_(meta);
    mintDraftSaleShort_(meta); // ①-B セール側も同様に置換(saved.xText分岐でも凍結プレースホルダを埋める・2026-08-13)
    var tags = saved.ytTags !== undefined ? saved.ytTags : null;
    if (tags === null) { try { tags = localStorage.getItem('yt_tags_shared') || ''; } catch (e) { tags = ''; } }
    if (!tags) { var te = $('ytTags'); tags = te ? te.value : '#Shorts #マンガ #漫画紹介 #anime'; }
    $('draftYtTagsInput').value = tags;
    buildModalYtTitle_();
    $('draftYtUrl').value = saved.ytUrl !== undefined ? saved.ytUrl : (meta.youtubeUrl || '');
    var ytDescVal = (saved.ytDesc !== undefined && saved.ytDesc !== '') ? saved.ytDesc : '';
    var ytDescFromTemplate = !ytDescVal; // 手編集の保存が無い＝テンプレ由来なら販促解決を通す(②)
    if (!ytDescVal && window.__go5YtDescForAccount) { ytDescVal = window.__go5YtDescForAccount(meta.account || 'acc1'); }
    if (!ytDescVal) { try { ytDescVal = localStorage.getItem('yt_desc__' + (meta.account || 'acc1')) || ''; } catch (e) {} }
    // テンプレ由来のときだけ「¥N→実価格／%表示なら¥N行を削除」を反映(手編集の保存は尊重してそのまま)。
    if (ytDescFromTemplate) ytDescVal = applyPromo_(ytDescVal, meta);
    // 1行目が短縮URLプレースホルダ/実URLなら本文から外し、スロット側で扱う(textarea内に生placeholderを残さない)。
    var slotUrl = '';
    var lines = ytDescVal.split('\n');
    var first = (lines[0] || '').trim();
    if (first === PH_URL_ || /短縮URL/.test(first)) {
      lines.shift(); if (lines.length && lines[0].trim() === '') lines.shift();
    } else if (/^https?:\/\//.test(first)) {
      slotUrl = first; lines.shift(); if (lines.length && lines[0].trim() === '') lines.shift();
    }
    $('draftYtDescText').value = lines.join('\n');
    if (saved.xShortUrl) slotUrl = saved.xShortUrl;
    setDescUrlSlot_(slotUrl);
    $('draftXPostUrl').value = saved.xPostUrl || '';
    // 修正前(x.comがALLOWED_HOSTS未登録の頃)に発行された非ワーカー短縮=da.gd等は、
    //   元のX投稿リンクが残っていれば開いた時にチャンネル別ドメイン(5mgl/yoz2)へ格上げする。
    //   自前ワーカードメインの短縮はそのまま(二重短縮しない)。判定は Go5Short.ourBase。
    try {
      var og = window.Go5Short;
      var isOurs = (og && og.ourBase) ? !!og.ourBase(slotUrl) : /\/\/(?:5mgl\.com|yoz2\.com)\//.test(slotUrl);
      if (slotUrl && !isOurs) {
        if (saved.xPostUrl) applyXPostUrl_(saved.xPostUrl, null);   // 生のX投稿URLがある＝それから自前ドメインで再短縮
        else healExternalXShort_(slotUrl);                          // 無い＝da.gd等を解決して自前ドメインへ格上げ
      }
    } catch (e) {}
    // 作品遷移リンク(Chami依頼2026-07-30④)=作品のアフィリンクをタップで開ける(遷移先の確認用)。無ければ隠す。
    var wl = $('draftWorkLink'), waff = (meta.affiliateUrl || meta.workUrl || '').trim();
    if (wl) {
      if (/^https?:\/\//.test(waff)) { wl.href = waff; wl.style.display = 'inline-block'; }
      else { wl.removeAttribute('href'); wl.style.display = 'none'; }
    }
    // 公開設定(即時/予約)＋選択済みの公開枠を復元。
    _pickedSlot = (saved.pubSlot && saved.pubSlot.date) ? saved.pubSlot : null;
    var wantSched = (saved.pubMode === 'scheduled') || !!_pickedSlot;
    var rn = $('draftPubNow'), rs = $('draftPubSched');
    if (rn) rn.checked = !wantSched;
    if (rs) rs.checked = wantSched;
    syncPubModeUI_();
    renderAffCheck_(meta);
    m.style.display = 'flex';
    rememberOpenModal_(meta.id); // 再読込を跨いで開き直せるよう、開いたドラフトidを覚える
  }

  // ⑤ アフィID入り確認(Chami依頼2026-07-30)。作品紹介・セールの短縮リンクに自分のaf_idが入っているかを表示。
  //   実体の判定は bluesky.js の __go5AffCheck(作品アフィリンク＋現在のセール設定＋af_idを見る)。未読込時は表示しない。
  function renderAffCheck_(meta) {
    var box = $('draftAffCheck'); if (!box) return;
    // ★fail-open(Chami依頼2026-08-02④「消えているので復活」)=判定不能でも黙って消さない。
    //   以前は __go5AffCheck が未定義 or 例外で box を空にしていた=「アフィチェックが消えている」の真因。
    var r = null;
    if (typeof window.__go5AffCheck === 'function') {
      try { r = window.__go5AffCheck((meta && (meta.affiliateUrl || meta.workUrl)) || ''); } catch (e) { r = null; }
    }
    if (!r) {
      box.innerHTML = '<span style="font-weight:700;color:var(--accent);margin-right:6px;">アフィチェック</span><span style="color:var(--sub);">—(判定不可)</span>';
      return;
    }
    function esc2(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    // ★2つのチェックを1行に(Chami依頼2026-08-02④「2行使わず1行で」)=inline-span＋区切り。
    function chip_(label, v) {
      if (!v) return '';
      if (v.applicable === false) return '<span style="color:var(--sub);">' + label + '：—(未使用)</span>';
      if (v.ok) return '<span style="color:var(--ink);">' + label + '：<b style="color:#2bb3c0;">✅</b></span>';
      return '<span style="color:var(--ink);">' + label + '：<b style="color:#e06">🆖</b>' + (v.reason ? '<span style="color:var(--sub);font-size:.72rem;"> ' + esc2(v.reason) + '</span>' : '') + '</span>';
    }
    var parts = [chip_('投稿作品', r.work), chip_('セールURL', r.sale)].filter(Boolean);
    box.innerHTML = '<span style="font-weight:700;color:var(--accent);margin-right:6px;">アフィチェック</span>' +
      parts.join('<span style="color:var(--sub);margin:0 8px;">/</span>');
  }

  function createModal_() {
    var m = document.createElement('div');
    m.id = 'draftPostModal';
    m.style.cssText = 'display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.82);overflow-y:auto;-webkit-overflow-scrolling:touch;align-items:flex-start;justify-content:center;padding:16px 0;box-sizing:border-box;';
    var iS = 'width:100%;box-sizing:border-box;background:var(--field-bg,rgba(0,0,0,.28));color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:9px 10px;font-size:.84rem;line-height:1.5;';
    // 貼り付けボタン=候補タブの投稿編集モーダル(refImgTwitter等)と同じ .ghost paste-btn の見た目に合わせる
    //   (Chami指示2026-07-28「候補タブの投稿編集モーダルを参考にこの形に」)。文字幅・白字太字・入力と同じ高さ。
    var cpS = 'flex:0 0 auto;width:auto;margin:0;padding:0 14px;font-size:.8rem;font-weight:700;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer;white-space:nowrap;';
    var bS  = 'display:inline-block;width:auto;margin-top:7px;padding:7px 16px;font-size:.8rem;border-radius:7px;border:1px solid var(--line);background:transparent;color:var(--sub);cursor:pointer;white-space:nowrap;';
    // 入力欄＋ボタンを同じ行に置く(Chami指示①)。本体タブの .short-row と同じ実証済みレシピ=
    //   入力に flex:1;min-width:0(=flex-basis 0で残り幅を埋める・iOS Safariで潰れない)、ボタンは
    //   flex:0 0 auto(文字幅)。flex-wrapは保険(狭い時だけ折り返す)。★flex-basisを実寸%にすると
    //   iOSで折り返してしまう(v=453の失敗)ので使わない。
    // ★入力には size="1" も付ける(v=457)。<input>は初期size=20文字ぶんの固有幅を持ち、
    //   iOS Safariは min-width:0 でもこの固有幅を残して列を割ることがある(実証済みの.short-rowは
    //   <div>なのでこの穴が無かった)。size=1で固有幅を潰し、flex:1で残り幅を埋める。
    // 入力＋ボタンを同じ行に(候補タブ pasteRow と同一)。align-items:stretch=ボタンが入力と同じ高さ。
    //   ★flex-wrap は使わない=候補タブは折り返さず崩れていない。入力は size="1"+min-width:0+flex:1 で
    //   0まで縮むのでボタンは必ず同列に残る(iOS Safari列割れの実証済み回避形)。
    var rowWrap = 'display:flex;gap:6px;align-items:stretch;margin-top:6px;';
    var rowIn = 'flex:1;min-width:0;box-sizing:border-box;background:var(--field-bg,rgba(0,0,0,.28));color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:9px 10px;font-size:.84rem;line-height:1.5;';
    // 文字幅ボタン。★width:auto;margin-top:0 が必須=このモーダル(#draftPostModal)は .fz-modal/.vedit-modal
    //   ではないので style.css:471 の打ち消しが効かず、グローバル button{width:100%}(style.css:846)が勝って
    //   横いっぱいに伸び・文字が中央寄せになっていた(Chami報告2026-07-31・v=539の margin-left:auto が死んでいた真因)。
    var btnW = 'width:auto;margin-top:0;padding:7px 12px;font-size:.78rem;border-radius:7px;border:1px solid var(--line);background:transparent;color:var(--sub);cursor:pointer;white-space:nowrap;';
    // 短縮URLの確認用リンク(タップで実際に遷移・Chami確認用)。アクセント色＋下線＋折り返し。
    var lnkS = 'display:inline-block;margin:0 0 8px;font-size:.86rem;color:var(--accent);text-decoration:underline;word-break:break-all;';
    // フレックス行の中に置くリンク(下マージン無し・折り返し許容)。説明欄行の短縮URL/作品遷移リンク用。
    var lnkR = 'font-size:.82rem;color:var(--accent);text-decoration:underline;word-break:break-all;min-width:0;';
    var sH  = 'font-size:.72rem;font-weight:600;color:var(--accent);letter-spacing:.06em;text-transform:uppercase;';
    var fL  = 'font-size:.76rem;color:var(--sub);margin-bottom:4px;margin-top:12px;';
    var ctaS = 'background:linear-gradient(180deg,var(--cta-from,var(--accent)),var(--cta-to,var(--accent)));color:var(--cta-ink,#04222a);';
    m.innerHTML =
      '<div style="background:var(--card);border:1px solid var(--line);border-radius:14px;width:calc(100% - 24px);max-width:480px;margin:auto;box-sizing:border-box;overflow:hidden;color:var(--ink);">' +
        '<div style="padding:13px 16px;border-bottom:1px solid var(--line);display:flex;align-items:center;">' +
          '<div style="flex:1;"></div>' +
          '<div style="font-size:.95rem;font-weight:800;color:var(--accent);">投稿モード</div>' +
          '<div style="flex:1;display:flex;justify-content:flex-end;">' +
            '<button type="button" id="draftModalClose" style="background:none;border:none;color:var(--sub);font-size:1.2rem;cursor:pointer;padding:2px 8px;line-height:1;">✕</button>' +
          '</div>' +
        '</div>' +
        '<div style="padding:16px 16px 20px;">' +
          // ★見出しは white-space:nowrap で必ず1行に(flex:1;min-width:0 だと iOS Safari で幅が1文字ぶんへ潰れ、
          //   日本語は文字間どこでも改行できるため「X／投／稿」と縦積みになっていた・Chami報告2026-07-31①)。
          //   コピーは margin-left:auto で右端へ寄せ、幅は文字ぶんだけ(Chami③「文字の幅に合うだけ」)。
          '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;"><div style="' + sH + 'white-space:nowrap;">X 投稿</div><button type="button" id="draftCopyX" style="' + btnW + 'margin-left:auto;">コピー</button></div>' +
          '<textarea id="draftXText" rows="9" style="' + iS + 'resize:vertical;"></textarea>' + // ①縦幅(rows6→8→9・もう1行分・Chami依頼2026-08-03)
          '<div style="' + fL + '">X投稿リンク(Xに投稿後に貼ると説明欄へ短縮URLが入る)</div>' +
          '<div style="' + rowWrap + '">' +
            '<input type="url" id="draftXPostUrl" size="1" placeholder="https://x.com/.../status/..." style="' + rowIn + '">' +
            '<button type="button" id="draftPasteXPostUrl" style="' + cpS + '">貼り付け</button>' +
          '</div>' +
          '<div style="height:1px;background:var(--line);margin:18px 0;"></div>' +
          '<div style="' + sH + 'margin-bottom:10px;">YouTube</div>' +
          '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;"><div style="font-size:.78rem;font-weight:600;color:var(--sub);white-space:nowrap;">題名(コピーして貼り付け)</div><button type="button" id="draftCopyYtTitle" style="' + btnW + 'margin-left:auto;">題名をコピー</button></div>' +
          '<textarea id="draftYtTitleText" readonly rows="2" style="' + iS + 'resize:vertical;cursor:default;"></textarea>' + // ②2行の幅に(rows3→2・Chami依頼2026-08-02)
          '<div style="display:flex;align-items:center;gap:8px;' + fL + '"><span style="white-space:nowrap;">タグ(半角スペース区切り)</span><button type="button" id="draftCopyYtTags" style="' + btnW + 'margin-left:auto;">コピー</button></div>' +
          '<input type="text" id="draftYtTagsInput" style="' + iS + '">' +
          // 見出し行に作品遷移リンク(作品↗)を右寄せで同居させる(Chami依頼2026-08-03①=作品↗が
          //   下段へ改行落ちして無駄な余白ができるのを解消。見出しと同じ行の右端に置く)。
          '<div style="' + fL + 'display:flex;align-items:center;gap:8px;">' +
            '<span style="min-width:0;"><svg viewBox="0 0 28 20" style="height:1em;width:1.4em;vertical-align:-0.18em" aria-hidden="true"><rect width="28" height="20" rx="6" fill="#FF0000"/><path d="M11 6 L11 14 L20 10 Z" fill="#fff"/></svg> YouTube説明欄(コピーして概要欄に貼り付け)</span>' +
            '<a id="draftWorkLink" target="_blank" rel="noopener" style="' + lnkR + 'margin-left:auto;white-space:nowrap;flex:0 0 auto;display:none;">作品↗</a>' +
          '</div>' +
          // 説明欄の行(Chami依頼2026-08-02③)=左から「説明欄をコピー」「動画DL」。
          //   短縮URLリンク(draftYtDescUrlLink)は説明欄コピーの直後(表示は短縮URL確定時のみ)。動画DLは説明欄コピーの右横へ移動。
          // ★1行固定(flex-wrap:nowrap)＝ボタンは固定幅、短縮URLは右端に置き、収まらなければ
          //   fitDescRow_() が文字サイズを縮めて必ず1行に収める(Chami依頼2026-08-03・iPhone16対策)。
          '<div id="draftDescRow" style="display:flex;align-items:center;gap:8px;flex-wrap:nowrap;margin-bottom:8px;">' +
            '<button type="button" id="draftCopyYtDesc" style="' + btnW + 'flex:0 0 auto;">説明欄をコピー</button>' +
            '<button type="button" id="draftDlVideo" style="' + btnW + 'flex:0 0 auto;">動画DL</button>' +
            '<a id="draftYtDescUrlLink" target="_blank" rel="noopener" style="' + lnkR + 'white-space:nowrap;flex:0 0 auto;margin-left:auto;display:none;"></a>' +
          '</div>' +
          '<textarea id="draftYtDescText" rows="11" style="' + iS + 'resize:vertical;"></textarea>' +
          // 公開設定(Chami依頼2026-08-04)=YouTube動画をいつ公開するか。即時/予約をラジオで選び、
          //   予約なら「公開枠を選ぶ」でカレンダーが上から降りてくる→枠を選ぶと投稿履歴/カレンダー/予約が結びつく。
          //   ★予約でもカレンダー登録は必須にしない(枠未選択のまま予約でも保存できる)。Xは手動運用=ここはYouTube公開の話。
          '<div style="height:1px;background:var(--line);margin:18px 0;"></div>' +
          '<div style="' + sH + 'margin-bottom:10px;">公開設定(YouTube)</div>' +
          '<div style="display:flex;gap:18px;align-items:center;margin-bottom:6px;font-size:.86rem;">' +
            '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;"><input type="radio" name="draftPubMode" id="draftPubNow" value="now" checked style="accent-color:var(--accent);width:auto;margin:0;">即時投稿</label>' +
            '<label style="display:flex;align-items:center;gap:6px;cursor:pointer;"><input type="radio" name="draftPubMode" id="draftPubSched" value="scheduled" style="accent-color:var(--accent);width:auto;margin:0;">予約投稿</label>' +
          '</div>' +
          '<div id="draftSchedRow" style="display:none;margin-bottom:2px;">' +
            '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
              '<button type="button" id="draftPickSlot" style="' + btnW + '">📅 公開枠を選ぶ</button>' +
              '<span id="draftPickedSlot" style="font-size:.82rem;color:var(--ink);min-width:0;"></span>' +
              '<button type="button" id="draftClearSlot" style="' + btnW + 'display:none;">解除</button>' +
            '</div>' +
            '<div style="font-size:.72rem;color:var(--sub);margin-top:5px;">カレンダー登録は必須ではありません(枠なしの予約でも保存できます)。</div>' +
          '</div>' +
          '<div style="' + fL + '">YouTube URL(投稿後に貼る)</div>' +
          '<div style="' + rowWrap + '">' +
            '<input type="url" id="draftYtUrl" size="1" placeholder="https://www.youtube.com/shorts/..." style="' + rowIn + '">' +
            '<button type="button" id="draftPasteYtUrl" style="' + cpS + '">貼り付け</button>' +
          '</div>' +
          // アフィID入り確認(Chami依頼2026-07-30⑤)。作品紹介・セールの短縮リンクに自分のaf_idが入っているか。
          '<div id="draftAffCheck" style="font-size:.78rem;margin-top:10px;line-height:1.65;"></div>' +
          // 🔄 データ再生成(Chami依頼2026-08-18): 一連のデータ(動画・元画像・仕上がりプレビュー)のうち、まだ
          //   Googleドライブに無いものだけを"投稿完了と同じ経路"で作って保存する(既にあれば作り直さない・gap-fill)。
          '<div style="margin-top:14px;"><button type="button" id="draftRegenData" style="' + btnW + '" title="この作品の一連のデータ(動画・元画像・仕上がりプレビュー)のうち、まだGoogleドライブに無いものだけを作って保存します(既にあれば作り直しません)">🔄 データ再生成</button></div>' +
          // 🧹 名前を正しく保存し直す(Chami依頼2026-08-22・古いフォルダのファイル名が誤名 candidate.jpg 等になっている作品の正常化)。
          //   正しい名前で一式を作り直し、古いフォルダはGoogleドライブのゴミ箱へ(30日間復元可)。この端末に動画素材が残っている時のみ完全正常化。
          '<div style="margin-top:8px;"><button type="button" id="draftNormalizeData" style="' + btnW + '" title="Googleドライブのファイル名が誤って保存された作品を、正しい名前(題名_元画像 / 題名_プレビュー)で作り直します。古いフォルダはゴミ箱へ(30日間復元可)。この端末に動画素材が残っている場合のみ完全に正常化できます">🧹 名前を正しく保存し直す</button></div>' +
          '<div style="display:flex;gap:8px;margin-top:20px;">' +
            '<button type="button" id="draftModalComplete" style="flex:1;padding:13px;font-size:.88rem;font-weight:700;border-radius:10px;border:none;' + ctaS + 'cursor:pointer;">投稿完了</button>' +
            '<button type="button" id="draftModalSave" style="flex:1;padding:13px;font-size:.88rem;font-weight:600;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer;">内容を保存</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(m);

    $('draftXText').addEventListener('input', saveDraftPost_);
    $('draftYtTagsInput').addEventListener('input', function () {
      buildModalYtTitle_();
      try { localStorage.setItem('yt_tags_shared', this.value); } catch (e) {}
      var yt = $('ytTags'); if (yt) yt.value = this.value;
      saveDraftPost_();
    });
    $('draftYtUrl').addEventListener('input', saveDraftPost_);
    // 公開設定：即時/予約ラジオ。予約のときだけ「公開枠を選ぶ」行を表示。
    function onPubModeChange_() { syncPubModeUI_(); saveDraftPost_(); }
    $('draftPubNow').addEventListener('change', onPubModeChange_);
    $('draftPubSched').addEventListener('change', onPubModeChange_);
    $('draftPickSlot').addEventListener('click', openSlotPicker_);
    $('draftClearSlot').addEventListener('click', function () { _pickedSlot = null; renderPickedSlot_(); saveDraftPost_(); });
    $('draftCopyX').addEventListener('click', function () { copyText_(($('draftXText') || {}).value || '', this); });
    $('draftCopyYtTitle').addEventListener('click', function () { copyText_(($('draftYtTitleText') || {}).value || '', this); });
    $('draftCopyYtTags').addEventListener('click', function () { copyText_(($('draftYtTagsInput') || {}).value || '', this); }); // タグ欄をコピー(Chami依頼2026-07-30③)
    $('draftDlVideo').addEventListener('click', function () { if (_modalMeta) downloadStock_(_modalMeta.id, _modalMeta.videoName, this); }); // 動画DL(Chami依頼2026-07-30④)。this=押した瞬間に「準備中…」表示
    $('draftCopyYtDesc').addEventListener('click', function () {
      // 短縮URLは概要欄テキストボックスの最上段に既に入っている(setDescUrlSlot_)ので、
      //   テキストボックスの中身をそのままコピーする(先頭URLを二重に足さない)。
      //   ★タグが¥価格のときは「¥N」を実価格へ置換してコピー(④・テキストボックスの中身は¥Nのまま保つ)。
      copyText_(resolveYtDescYen_(($('draftYtDescText') || {}).value || '', _modalMeta), this);
    });
    $('draftYtDescText').addEventListener('input', saveDraftPost_);
    $('draftPasteXPostUrl').addEventListener('click', function () {
      var btn = this;
      if (navigator.clipboard && navigator.clipboard.readText) {
        navigator.clipboard.readText().then(function (text) { applyXPostUrl_(text, btn); })
          .catch(function () { alert('クリップボードの読み取りに失敗しました。手動で貼り付けてください。'); });
      } else {
        alert('この環境ではクリップボードの自動読み取りができません。手動で貼り付けてください。');
      }
    });
    $('draftXPostUrl').addEventListener('change', function () { applyXPostUrl_(this.value, null); });
    // ★貼り付けた瞬間に生URLを保存＆全端末へ即push(短縮はchange時=blurで実行)。
    //   blur前に別端末へ移っても値が渡るようにする(Chami「サブ端末で貼って保存しても反映なし」2026-08-05)。
    $('draftXPostUrl').addEventListener('input', saveDraftPost_);
    $('draftPasteYtUrl').addEventListener('click', function () {
      var btn = this;
      if (navigator.clipboard && navigator.clipboard.readText) {
        navigator.clipboard.readText().then(function (text) {
          $('draftYtUrl').value = text.trim(); saveDraftPost_();
          var o = btn.textContent; btn.textContent = '貼り付けました'; setTimeout(function () { btn.textContent = o; }, 2000);
        }).catch(function () { alert('クリップボードの読み取りに失敗しました。手動で貼り付けてください。'); });
      } else {
        alert('この環境ではクリップボードの自動読み取りができません。手動で貼り付けてください。');
      }
    });
    $('draftModalSave').addEventListener('click', function () {
      // 保存したらモーダルを閉じる(Chami指示2026-07-29「内容を保存を押したら保存してモーダルが閉じるように」)。
      saveDraftPost_();
      closeModal_();
    });
    $('draftModalClose').addEventListener('click', function () { closeModal_(); });
    // 🔄 データ再生成=投稿完了と同じ経路(Go5Stock.regenDataset→driveSaveForCompleted_)で足りないデータだけ作る。
    var _regenBtn = $('draftRegenData');
    if (_regenBtn) _regenBtn.addEventListener('click', function () {
      var btn = this;
      if (!_modalMeta) return;
      if (!(window.Go5Stock && Go5Stock.regenDataset)) { alert('データ再生成の土台(Go5Stock)が読み込まれていません。ページを再読み込みしてもう一度お試しください。'); return; }
      if (!window.confirm('この作品のデータを再生成しますか?\n\n一連のデータ(動画・元画像・仕上がりプレビュー)のうち、まだGoogleドライブに無いものだけを作って保存します。\n(既に揃っていれば作り直しません)')) return;
      var orig = btn.textContent;
      btn.disabled = true; btn.textContent = '再生成中…';
      Go5Stock.regenDataset(_modalMeta, {
        silent: true,
        onDone: function (ok, msg) {
          btn.disabled = false; btn.textContent = orig;
          alert(ok ? ('データ再生成が完了しました。\n・' + (msg || '足りていないデータをGoogleドライブへ保存'))
                   : ('再生成できませんでした。\n' + (msg || 'もう一度お試しください。')));
        }
      });
    });
    // 🧹 名前を正しく保存し直す=正常化(normalize)。データ再生成と同じ経路(regenDataset→driveSaveForCompleted_)だが、
    //   normalize:true で「もう保存済み→追記だけ」の近道を通さず必ず正しい名前で作り直し、古いフォルダはWorkerが
    //   新規保存の"後"にゴミ箱送りする(30日復元可)。削除面に触るので明示のこのボタンだけがintentを立てる(Chami承認2026-08-22)。
    var _normBtn = $('draftNormalizeData');
    if (_normBtn) _normBtn.addEventListener('click', function () {
      var btn = this;
      if (!_modalMeta) return;
      if (!(window.Go5Stock && Go5Stock.regenDataset)) { alert('正常化の土台(Go5Stock)が読み込まれていません。ページを再読み込みしてもう一度お試しください。'); return; }
      if (!window.confirm('この作品を正しいファイル名で保存し直しますか?\n\n・正しい名前(題名_元画像 / 題名_プレビュー)で一式を作り直します\n・古いフォルダはGoogleドライブのゴミ箱へ移動します(30日間は復元できます)\n・この端末に動画素材が残っている場合のみ完全に正常化できます(残っていなければ古いフォルダはそのまま)')) return;
      var orig = btn.textContent;
      btn.disabled = true; btn.textContent = '保存し直し中…';
      Go5Stock.regenDataset(_modalMeta, {
        silent: true,
        normalize: true,
        onDone: function (ok, msg) {
          btn.disabled = false; btn.textContent = orig;
          alert(ok ? ('保存し直しを開始しました。\n・' + (msg || '正しい名前で作り直し、古いフォルダはゴミ箱へ(30日復元可)') + '\n\n数十秒後にGoogleドライブで新しいフォルダのファイル名をご確認ください。')
                   : ('保存し直せませんでした。\n' + (msg || 'この端末に動画素材が残っていない可能性があります。もう一度お試しください。')));
        }
      });
    });
    $('draftModalComplete').addEventListener('click', function () {
      if (!_modalMeta) return;
      if (!window.confirm('投稿履歴に反映します。OKを押すと正式に投稿完了になります。')) return;
      var id = _modalMeta.id;
      var ytUrl = ($('draftYtUrl') || {}).value || '';
      var slot = $('draftYtDescUrlLink');
      var shortUrl = (slot && slot.dataset && slot.dataset.url) || '';
      // ★導線2の作品計測用短縮URLがまだ発番中(link-worker往復・非同期)なら、投稿完了で履歴の計測URL欄が
      //   空に化けないよう、着地を最大2.5秒だけ待ってから記録する(REQ-65c7897f2f)。取れなければ従来どおり進む。
      var btn = this, origLabel = btn.textContent;
      btn.disabled = true; btn.textContent = '記録中…';
      waitWorkShortSettle_(id, 2500, function () {
        btn.disabled = false; btn.textContent = origLabel;
        // 履歴への保存を確認できた時だけ閉じる。失敗時はドラフトとモーダルを残して再試行可能にする。
        if (handleCompleteOk_(id, ytUrl.trim(), shortUrl)) closeModal_();
      });
    });
    document.addEventListener('go5-disc-url-changed', function () {
      if (!m || m.style.display === 'none' || !_modalMeta) return;
      if (window.__go5ComposeXTextForBskyText) {
        var xtEl = $('draftXText');
        if (xtEl) xtEl.value = composeXForModal_(_modalMeta);
      }
    });
    document.addEventListener('go5-work-short-ready', function () {
      if (!m || m.style.display === 'none' || !_modalMeta) return;
      if (window.__go5ComposeXTextForBskyText) {
        var xtEl = $('draftXText');
        if (xtEl) xtEl.value = composeXForModal_(_modalMeta);
      }
    });
    m.addEventListener('click', function (e) { if (e.target === m) { closeModal_(); } });
    return m;
  }

  // ── 初期化 ──
  function init() {
    createModal_();

    // ★永続化ストレージを要求(C-1・Fable5設計2026-08-17)。iOSはIDBの動画(数MB)を容量都合で退避しがちで、
    //   それが「DLのたびにR2まで取りに行く/自動遷移が雲待ちで遅い」の根。persist() は退役確率を下げ、
    //   結果(persisted())をDL診断へ載せて「端末実測が要る(推測で埋めない)」を満たす。コスト1行・失敗無害。
    try {
      if (navigator.storage && navigator.storage.persist && navigator.storage.persisted) {
        navigator.storage.persisted().then(function (already) {
          _persisted = already ? 'yes' : 'no';
          if (!already) {
            try { navigator.storage.persist().then(function (g) { _persisted = g ? 'granted' : 'denied'; }, function () {}); } catch (e) {}
          }
        }).catch(function () {});
      }
    } catch (e) {}

    // 軽量ドラフトページの「再作成」から来た時だけ、本体の動画作成DOMへ流し込んでから元ドラフトを外す。
    // sessionStorageなので別タブ/別端末とは混ざらず、成功前削除もしない。
    (function resumeRemakeFromSplit_() {
      if (!$('author')) return;
      var id = ''; try { id = sessionStorage.getItem(REMAKE_PENDING_KEY) || ''; } catch (e) {}
      if (!id) return;
      try { sessionStorage.removeItem(REMAKE_PENDING_KEY); } catch (e) {}
      setTimeout(function () {
        var meta = loadMeta().filter(function (m) { return m.id === id; })[0];
        if (meta) { try { remakeStock_(meta); } catch (e) {} }
      }, 350);
    }());

    // ★iOSがアプリ復帰時にこのタブを捨てて再読込しても、投稿モードを開いていたなら開き直す
    //   (Chami報告2026-08-08「戻るとリロードする」の実害=作業中の投稿モードが消えることを無効化する)。
    //   sessionStorageはタブが生きている限り残る=再読込直後だけ復元し、タブを閉じれば消える(勝手には開かない)。
    (function restoreOpenModal_() {
      var id = '';
      try { id = sessionStorage.getItem(OPEN_MODAL_KEY) || ''; } catch (e) {}
      if (!id) return;
      setTimeout(function () {
        var meta = loadMeta().filter(function (m) { return m.id === id; })[0]
                 || loadArchive().filter(function (m) { return m.id === id; })[0];
        if (meta) { try { openPostModal_(meta); } catch (e) {} }
        else forgetOpenModal_(); // ドラフトがもう無い=覚えを捨てる
      }, 600); // 他モジュール(合成/短縮/カレンダー橋渡し)の初期化を少し待ってから開く
    }());

    var draftMakeBtn = $('draftMakeBtn');
    if (draftMakeBtn) {
      draftMakeBtn.addEventListener('click', function () {
        // ★「これはドラフト作成だ」を作成イベントに載せるだけ=app.js make()が入口で一度消費し detail.draft に確定、
        //   bluesky.js handleVideoCreated は detail.draft を最上段で見て投稿/引き継ぎを断ち切る(Chami報告2026-08-11)。
        //   ★bskyEnableは触らない/_draftMode等の状態も持たない(2026-08-13)。旧実装は投機的にbskyEnableを外し
        //     _draftMode/_restoreBskyElを持たせたが、make()が入口ガード(写真未選択・狙い/コメント型未選択)で
        //     早期returnするとこの状態が復元されず、①自動投稿が黙って外れたまま ②後続の「今すぐ作成」が
        //     _draftMode残留でドラフト扱いに化ける——というドラフト/投稿の取り違えを生んでいた。権威フラグ一本に統一する。
        window.__go5DraftPending = true; // ★後方互換の保険。第一の権威は直接口の引数 {draft:true}(app.js make(opts))
        // ★make() を直接呼ぶ。従来の makeBtn.click() は、makeBtn が disabled(前回作成の固着など)だと
        //   click イベントが発火せず make() に入らない=「押しても無反応」に落ちていた(Chami報告2026-08-16)。
        //   直接口 __go5RequestMake なら disabled を跨いで make() の入口(再入判定・stale奪回)へ到達する。
        //   ★ドラフト意図は引数 {draft:true} で明示的に運ぶ=グローバルフラグ消費レースの根絶(Chami報告2026-08-16
        //     「ドラフトに遷移しない」)。古い読み込み順で直接口が未定義のときだけ従来の click()(グローバルフラグ)へ。
        if (typeof window.__go5RequestMake === 'function') {
          try { window.__go5RequestMake({ draft: true }); }
          catch (e) { var mb0 = $('makeBtn'); if (mb0) mb0.click(); }
        } else {
          var makeBtn = $('makeBtn');
          if (makeBtn) makeBtn.click();
        }
      });
    }

    document.addEventListener('video-created', function (e) {
      // detail.draft(app.jsがmake()入口で__go5DraftPendingを消費して確定した権威)だけで判定する。
      if (!(e && e.detail && e.detail.draft)) return;
      var detail = e.detail;
      var blobUsable = isUsableVideoBlob_(detail.blob);
      // ★①「自動遷移が遅い/手動タブの方が速い」の解消(B・Fable5設計2026-08-17)。
      //   生成完了で即ドラフト一覧をページ内表示=着地(navigate)を待たずに一覧が出る。新ドラフトは下の
      //   onStart で pending の「保存中…」カードとして先頭に出る。破壊遷移(location.href)は着地検証後 or
      //   保存窓外のみ=8/15の全滅の不変条件(未着地で遷移しない)は維持。standalone(Stock.html単独)では不要。
      if (!window.__go5StockStandalone) { try { showStockInline_(); } catch (_e) {} }
      // ★holdMessage は「実因が判明したら上書きできる」よう可変にする(Fable5診断2026-08-16)。
      //   従来は原因に関わらず“動画のせい”に見せる固定文で、localStorage逼迫のメタ書込み失敗も同じ文面だった。
      var holdMessageBase = blobUsable
        ? '動画をこの端末にも雲にも確認できませんでした。ページは移動せず動画を保持しています。「もう一度保存」で再確認します。'
        : '生成された動画データが空または不完全でした。壊れたドラフトは一覧へ保存していません。動画作成タブで、もう一度「ドラフトで作成」を押してください。';
      var holdMessage = holdMessageBase;
      var retryPossible = blobUsable;
      // 生成完了で動画作成タブ→ドラフトタブへ自動遷移(Chami依頼2026-08-13「前は遷移してた、戻して」)。
      //   ★ボタンの click 経由(tabStock.click)に依存せず、ドラフトページ(Stock.html)へ明示遷移する=
      //     配線変更や他ハンドラの割り込みで遷移が黙って止まらないようにする。既にドラフトページ上なら再描画のみ。
      var _navigated = false;
      var goDraft_ = function () {
        if (_navigated) return; _navigated = true; // 保険のタイマとsaveStock_完了で二重遷移しない
        window.__go5SaveInFlight = false; // 着地決着=以後の手動タブ/リロードは通常どおり Stock.html へ
        if (window.__go5StockStandalone) { render(); return; }
        // ページ内表示(B)中は既に #pageStock が前面=再描画で pending を通常カードへ置換して終わり(遷移しない)。
        var ps = $('pageStock');
        if (ps && !ps.hidden) { render(); return; }
        try { location.href = 'Stock.html'; }
        catch (e2) { var tb = $('tabStock'); if (tb) tb.click(); else render(); }
      };

      // ★単一着地権威(Go5SaveGate)。遷移は「動画が 手元(IDB) か 雲(R2) に着地した」時だけ。
      //   タイマーは"進む"既定を持たない=期限が来て未着地なら黙って遷移せず『保留(hold)』へ倒す。
      //   従来 navTimer は 25秒で無条件に goDraft_ していたため、IDB死かつR2失敗/タブ破棄の二重故障で
      //   「動画がどこにも無いのに遷移=全滅」していた(8/15朝 5031ddb の再発の芯・改善提案部門の型§1)。
      var gate = { localLanded: false, cloudLanded: false, timerFired: false };
      var draftId = null;
      var navTimer = null;
      var waitTimer = null;
      function decideNav_() {
        var act = (window.Go5SaveGate && Go5SaveGate.decide)
          ? Go5SaveGate.decide(gate)
          : (gate.localLanded || gate.cloudLanded ? 'navigate' : (gate.timerFired ? 'hold' : 'wait'));
        if (act === 'navigate') { if (navTimer) { clearTimeout(navTimer); navTimer = null; } if (waitTimer) { clearTimeout(waitTimer); waitTimer = null; } hideSaveWait_(); hideSaveHold_(); goDraft_(); }
        else if (act === 'hold') { if (navTimer) { clearTimeout(navTimer); navTimer = null; } if (waitTimer) { clearTimeout(waitTimer); waitTimer = null; } hideSaveWait_(); showSaveHold_(holdMessage, retryPossible); }
      }
      // ★飛行中のレーンは失敗ではない(Fable5診断2026-08-17・P2)。旧25秒は無条件に hold へ倒していたが、
      //   iPhoneの細い上りでは動画のR2 PUTが25秒を普通に超える=保存が成功しつつある最中に
      //   「確認できませんでした」を見せていた(①「自動遷移しない(実は保存成功中)」の芯)。
      //   25秒=進捗表示のみ(判定は変えない)。hold は onBothFailed(両レーン失敗確定)か 75秒の最終期限だけ。
      //   P1(core/sync.js api timeoutMs=60s)により雲レーンは必ず決着する=75秒は沈黙ハングの最終安全網。
      //   ★遷移は従来どおり localLanded/cloudLanded(実物の着地検証済)の時だけ=8/15の全滅回帰は構造的に不可。
      waitTimer = setTimeout(function () {
        if (gate.localLanded || gate.cloudLanded || gate.timerFired) return;
        showSaveWait_('動画を保存中です…このままお待ちください(電波が細いと1分ほどかかることがあります)');
      }, 25000);
      navTimer = setTimeout(function () { gate.timerFired = true; decideNav_(); }, 75000);

      var hooks = {
        // 作成直後の動画blobをメモリ層へ即載せる=生成→即DLがタップ即応(②即DL・Fable5設計2026-08-17)。
        onStart: function (id) { draftId = id; if (blobUsable) putVidMem_(id, detail.blob); render(); /* pending「保存中…」カードを先頭へ */ },
        onLocal: function (id) { draftId = id; gate.localLanded = true; decideNav_(); },
        onCloud: function (id) { draftId = id; gate.cloudLanded = true; decideNav_(); },
        // 両方が「着地できずに」決着=着地不能が確定。25秒を待たず今すぐ hold へ倒す。
        //   ★実因(手元/雲それぞれの失敗理由)を hold文面へ差し込む=“動画のせい”の誤誘導を止め、
        //     メタ書込み失敗(localStorage逼迫)と動画着地失敗を切り分けて見せる(Fable5診断2026-08-16)。
        onBothFailed: function (id, reasons) {
          draftId = id;
          var _pf = _pendingDraftMeta[id]; if (_pf) { _pf._failed = true; render(); } // pendingカードを「保存に失敗」表記へ
          if (reasons && (reasons.local || reasons.cloud)) {
            // ★draft-meta-readback-failed は verifyCloudVideoWrite_ 成功後にだけ出る=動画は雲(R2)へ着地済みで、
            //   失敗したのは端末localStorageの台帳書込みだけ。旧文面「雲にも確認できませんでした」は実態と逆の
            //   誤誘導だった。動画は喪失していないと明言し、原因(端末の空き容量)を言う(Fable5診断C-2・2026-08-18)。
            if (reasons.cloud === 'draft-meta-readback-failed') {
              holdMessage = '動画は雲(クラウド)へ保存済みです(消えていません)。ただしこの端末の保存領域が満杯で、ドラフト一覧の台帳に載せられませんでした。ほかのタブを閉じるなどで空き容量を作ってから「もう一度保存」を押してください。';
            } else {
              holdMessage = holdMessageBase + ' 内訳=手元:' + (reasons.local || 'ok') + ' / 雲:' + (reasons.cloud || 'ok') + '。';
            }
          }
          gate.timerFired = true; decideNav_();
        }
      };

      window.__go5HoldGoDraft = goDraft_; // 「このまま履歴へ」=ユーザーの明示選択でのみ遷移
      // 保留(hold)からのリトライ=メモリ上の動画blobをR2へ再度上げる。着地したら遷移(I4のリトライ)。
      //   遷移(location.href)でJSコンテキストを壊さない限り detail.blob は生きている=ここで救える。
      window.__go5RetrySave = function () {
        hideSaveHold_();
        gate.timerFired = false;
        if (!draftId || !isUsableVideoBlob_(detail.blob)) {
          retryPossible = false;
          gate.timerFired = true;
          decideNav_();
          return;
        }
        var _pr = _pendingDraftMeta[draftId]; if (_pr) { _pr._failed = false; render(); } // pendingカードを「保存中…」表記へ戻す
        showSaveWait_('もう一度保存しています…このままお待ちください(最大1分ほど)');
        navTimer = setTimeout(function () { gate.timerFired = true; decideNav_(); }, 75000); // 20秒は同じ早すぎhold病=75秒へ(P2)
        // リトライはR2だけでなくIDB書込み+読み戻しも再実行する。同期未設定端末でも手元保存の復帰で救える。
        try {
          firstVideoLanding_(draftId, detail.blob).then(function (kind) {
            var pending = _pendingDraftMeta[draftId];
            if (pending) { pending.videoReadyAt = Date.now(); pending.videoBytes = detail.blob.size; }
            return commitPendingDraft_(draftId).then(function () { return kind; });
          }).then(function (kind) {
            if (kind === 'local') gate.localLanded = true; else gate.cloudLanded = true;
            decideNav_();
          }).catch(function () {
            gate.timerFired = true;
            decideNav_();
          });
        } catch (e3) { gate.timerFired = true; decideNav_(); }
      };

      // ★saveStock_ が「同期例外」を投げた場合、.then/.catch のどちらにも乗らず遷移が黙って消える。
      //   try で囲い、同期例外でも黙って全滅させない=着地不能扱いで hold(リトライで救える)。
      try {
        saveStock_(detail, hooks).then(function () { decideNav_(); }).catch(function (err) {
          alert('ドラフト保存に失敗しました: ' + (err ? err.message || String(err) : '不明なエラー'));
          gate.timerFired = true; decideNav_(); // 黙って遷移せず hold へ(材料が有ればリトライで救える)
        });
      } catch (err2) {
        try { if (window.console && console.warn) console.warn('[stock] saveStock_ 同期例外・着地不能扱い:', err2 && (err2.message || err2)); } catch (_) {}
        gate.timerFired = true; decideNav_();
      }
    });

    var tabStockBtn = $('tabStock');
    if (tabStockBtn) tabStockBtn.addEventListener('click', function () { setTimeout(render, 0); });

    document.addEventListener('account-changed', function () {
      var page = $('pageStock');
      if (page && !page.hidden) render();
    });

    // 全端末同期の「何かが変わった」だけでは一覧を作り直さない。同期対象は数百キーあるため、
    // ドラフト以外の設定変更でも pulled>0 となる=60秒ごと/アプリ復帰ごとの全DOM交換がリロードに見えていた。
    // ドラフト配列の署名が変わった時、または未表示サムネがあり画像が届いた時だけ更新する。
    document.addEventListener('go5-synced', function (e) {
      var d = e && e.detail;
      if (!d || (!d.pulled && !d.pulledImg)) return;
      if (d.pulledImg) { try { backfillUsedPreview_(); } catch (_) {} }
      var page = $('pageStock');
      if (!page || page.hidden) return;
      var curAcct = (window.Go5Acct && Go5Acct.current && Go5Acct.current()) || 'acc1';
      var dataChanged = !!d.pulled && stockViewSig_(curAcct) !== _lastRenderedStockSig;
      var imageChanged = !!d.pulledImg && Object.keys(_missingThumbs).length > 0;
      if (!dataChanged && !imageChanged) return;
      if (modalIsOpen_()) { _stockBgPending = true; return; } // 入力・コピー中はDOMを触らず、閉じた後に1回だけ反映
      render();
      if (dataChanged) setTimeout(warmNewestVideos_, 0); // 新しいドラフトが同期で増えたら動画を先読み(②即DL)
    });

    // ★IDBが無言死(iOS Safariのメモリ圧・バックグラウンド化)から回復した合図で、未表示サムネが
    //   残っていれば描き直す。従来サムネは起動時の一発読みだけで、IDBが後から回復しても「閉じて開き直す」
    //   まで黒箱のままだった(Chami報告2026-08-16「更新では直らない・閉じて開くと出る」の一因)。
    document.addEventListener('go5-idb-recovered', function () {
      try {
        var page = $('pageStock');
        if (!page || page.hidden) return;
        if (modalIsOpen_()) { _stockBgPending = true; return; } // 入力・コピー中はDOMを触らない
        if (Object.keys(_missingThumbs).length > 0) render();
      } catch (e) {}
    });

    // 起動直後にも一度、過去分のプレビュー遡及補完を試す(既に同期済みミラーがあれば即補完)。
    setTimeout(function () { try { backfillUsedPreview_(); } catch (_) {} }, 1500);

    // 一度きり：既存の作成履歴を投稿履歴ミラー(D1 posted_log)へ流す(daily_pick 用・二重送信はフラグで防止)。
    setTimeout(function () { try { backfillPostedLog_(); } catch (_) {} }, 3000);

    // ドラフトタブのボタン操作(event delegation)
    var page = $('pageStock');
    if (page) {
      // 作成履歴(details)の開閉をユーザー操作から拾って保持する(toggleはbubbleしないのでcaptureで拾う)。
      //   これで再描画(削除/復元など)後もrenderが open を復元し、開いたまま維持できる。
      page.addEventListener('toggle', function (e) {
        var d = e.target;
        if (d && d.id === 'stkArchDetails') _archOpen = !!d.open;
      }, true);
      page.addEventListener('click', function (e) {
        var btn = e.target;
        if (!btn || !btn.dataset || !btn.dataset.id) return;
        var id = btn.dataset.id;
        // meta はドラフト本体・作成履歴のどちらにあるか分からない(動画DLは両方から押せる)ので両方から探す。
        var meta = loadMeta().filter(function (m) { return m.id === id; })[0]
                 || loadArchive().filter(function (m) { return m.id === id; })[0];

        if (btn.classList.contains('stk-dl')) {
          if (meta) downloadStock_(id, meta.videoName, btn); // btn=押した瞬間に「準備中…」表示(無反応を断つ)

        } else if (btn.classList.contains('stk-drive')) {
          // ☁️ Drive保存(作成履歴カード)=作成時にDriveへ上がっていない過去分を後から保存する。
          //   素材(動画)が端末にまだ残っていればフル保存、既に作成時に上がっていればプレビュー追記(冪等)。
          //   ★押した瞬間から結果までボタンで状態を見せる(作成時に保存済みだと従来は無反応で「押せない」に見えた)。
          if (meta && !btn.disabled) {
            // ★処理中UIの終端は core/operation-gate.js が唯一の正本。
            //   本番コードをコピーしたテストではなく、同じ状態機械を本番とNodeテストの双方が直接使う。
            var _op = window.Go5OperationGate && window.Go5OperationGate.armButton
              ? window.Go5OperationGate.armButton(btn, {
                  pendingLabel: '☁️ 保存中…', successLabel: '✅ 保存済み',
                  timeoutLabel: '⏱ 中断(再度お試しください)', timeoutMs: 90000, restoreDelayMs: 4000
                })
              : null;
            if (!_op) { alert('保存制御の読込に失敗しました。ページを再読込してもう一度お試しください。'); return; }
            driveSaveForCompleted_(meta, { silent: false, onDone: function (ok) { _op.finish(ok); } });
          }

        } else if (btn.classList.contains('stk-mode')) {
          if (meta) openPostModal_(meta);

        } else if (btn.classList.contains('stk-remake')) {
          if (meta) remakeStock_(meta);

        } else if (btn.classList.contains('stk-restore')) {
          restoreStock_(id);
          render();

        } else if (btn.classList.contains('stk-arch-del')) {
          if (!window.confirm('「' + (meta ? meta.label || '動画' : '動画') + '」を作成履歴から完全に削除しますか?\n(復元できなくなります・Driveの動画は残ります)')) return;
          purgeArchived_(id);
          render();

        } else if (btn.classList.contains('stk-del')) {
          if (!window.confirm('「' + (meta ? meta.label || '動画' : '動画') + '」をドラフトから削除しますか?')) return;
          deleteStock_(id);
          render();
        }
      });
    }

    // ★window.Go5Stock の露出は init() の外(モジュールスコープ・下の init 呼び出し直前)へ前出し済み。
    //   ここ(init 末尾)で公開する旧設計は、init 途中がiOSで転ぶと土台ごと未定義になる脆さがあった
    //   =「データ再生成の土台(Go5Stock)が読み込まれていません」の一因(Chami報告2026-08-18)。

    // 動画・画像ミラーは保存直後に即送信し、ここでは旧データ/一時失敗ぶんだけを静かに再試行する。
    // 最大50件を同時発火していた旧30秒sweepはiOSのメモリ圧を上げるため、逐次処理＋2分周期へ変更。
    setTimeout(sweepVideoMirror_, 1000);  // 起動直後(sync設定の読み込みを少し待つ・追いつきを速く)
    setTimeout(sweepVideoMirror_, 6000);  // 1本目でsync未設定だった時の取りこぼしを拾う二度目(重複はbusyガード)
    document.addEventListener('visibilitychange', function () { if (!document.hidden) sweepVideoMirror_(); });
    setInterval(sweepVideoMirror_, 120000);

    // ★save_job 永続pending の再送(2026-08-16)。前回投稿完了でqueueSaveが届かなかったぶんを、
    //   起動時と復帰時・定期に「Driveにもう在るか」照会して畳む/再送する(sync設定の読込を少し待つ)。
    setTimeout(sweepSaveJobs_, 3000);
    setTimeout(sweepSaveJobs_, 12000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) sweepSaveJobs_(); });
    setInterval(sweepSaveJobs_, 180000);

    // 初回アクセスでドラフトが空表示になる穴の根治(Chami 2026-07-29):
    //   affiliate.js の restoreActiveTab_ が「このモジュールより先」に走ると、ドラフトタブへ
    //   復元されても showTab の render 呼び出しが window.Go5Stock 未定義でスキップされ、
    //   タブは開いているのに中身が空のまま(再タップで直る)になっていた。読み込み順に依存せず、
    //   init 時点でドラフトタブが既に表示中なら自分で描画して穴を塞ぐ。
    if (page && !page.hidden) render();
    setTimeout(warmNewestVideos_, 1500); // ②最新ドラフト動画をR2から先読み=即DL(sync設定の読込を少し待つ)
  }

  // ★土台(Go5Stock)はモジュールスコープで即公開する=init()を待たない/init()が途中で転んでも生きる。
  //   参照する5関数は全てモジュールスコープの関数宣言(巻き上げ済み)で、依存するモジュール変数も宣言時初期化
  //   =init時セットアップに依存しない(検証済み)。投稿履歴ページ(StockLists.html)からも regenDataset を確実に呼べる。
  window.Go5Stock = { render: render, previewForVideoId: previewForVideoId_, previewFromVideoBlob: previewFromVideoBlob_, videoBlobForId: videoBlobForId_, regenDataset: regenDataset_ };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
