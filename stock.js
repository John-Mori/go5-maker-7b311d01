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
  function saveMeta(arr) { try { localStorage.setItem(META_KEY, JSON.stringify(arr.slice(0, MAX))); } catch (e) {} kickSync_(); }
  function loadArchive() { try { return JSON.parse(localStorage.getItem(ARCHIVE_KEY) || '[]') || []; } catch (e) { return []; } }
  function saveArchive(arr) { try { localStorage.setItem(ARCHIVE_KEY, JSON.stringify(arr.slice(0, ARCHIVE_MAX))); } catch (e) {} }
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
      if (!blob) return; // 実体が無い端末=上げない(取り寄せる側)
      return Go5Sync.putBlobR2At(VIDNAME(id), blob).then(function (key) {
        if (key) _vidUp[id] = 1; // 成功=このセッションでは再送しない。失敗時は次のsweepでまた試す(非破壊)
      });
    }).catch(function () {});
    _vidMirrorBusy[id] = job.then(function (v) { delete _vidMirrorBusy[id]; return v; }, function () { delete _vidMirrorBusy[id]; });
    return _vidMirrorBusy[id];
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
      return toBlobSafe_(cv, 'image/jpeg', 0.85, 6000);
    } catch (e) { return Promise.resolve(null); }
  }

  // ── 過去分プレビュー復元：動画blobの先頭フレームをJPEGへ(Chami依頼2026-08-13「作られてないプレビューを
  //   自動で作成」)。仕上がりプレビュー=動画の先頭フレームなので、動画さえ手元にあれば後からでも同じ絵を
  //   復元できる。iOS Safariの沈黙ハング(loadeddata/seeked が来ない・canvas.toBlobが呼ばれない等)に備え、
  //   8秒の番犬で必ず resolve(null) に倒す(toBlobSafe_ と同じ fail-open の作法。ここでは reject しない)。
  function videoFirstFramePreview_(blob) {
    return new Promise(function (resolve) {
      if (!blob) { resolve(null); return; }
      var url = null;
      try { url = URL.createObjectURL(blob); } catch (e) { resolve(null); return; }
      var done = false;
      var timer = null;
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
      v.onloadeddata = function () {
        try { v.currentTime = 0.03; } catch (e) { capture_(); }
      };
      v.onseeked = capture_;
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

  // 動画作成タブのカテゴリ(ジャンル)チェックを読む。投稿完了時に投稿履歴へ引き継ぐ(Chami依頼2026-07-30)。
  //   これが無いと下書き→投稿完了で履歴にジャンルのチェックが渡らず、毎回手で入れ直しになる。
  // カテゴリの正本は core/categories.js(Go5Cats)。チェックボックスの要素IDは Go5Cats.elId(key)。
  function readMovieAttrs_() {
    var o = {};
    var cats = (window.Go5Cats && window.Go5Cats.visible()) || [];
    cats.forEach(function (c) { var el = $(window.Go5Cats.elId(c.key)); if (el && el.checked) o[c.key] = true; });
    return o;
  }

  function saveStock_(evDetail) {
    var ts = Date.now();
    var id = 'stk' + ts;
    var title = evDetail.title || '';
    var meta = {
      id: id, ts: ts,
      addedAt: ts, // 墓標(go5_stock_del)を越えて残すための追加時刻。復元時は now で打ち直す(全端末同期)。
      account: evDetail.account || 'acc1',
      label: title.length > 22 ? title.slice(0, 22) + '…' : (title || '(無題)'),
      title: title,
      author: ($('author') || {}).value || '',
      bskyText: ($('bskyText') || {}).value || '',
      affiliateUrl: ($('movieWorkAffi') || {}).value || '',
      workUrl: ($('movieWorkUrl') || {}).value || '',
      videoName: evDetail.name || (title.replace(/[\\/:"*?<>|]/g, '_') + '.mp4'),
      // ★動画IDを保持＝投稿完了時に投稿履歴↔使用画像(usedImgSaveはvideoIdキー)を紐付ける。(Chami依頼2026-07-30)
      videoId: evDetail.videoId || '',
      // カテゴリ(ジャンル)チェックを作成時にスナップ＝投稿完了で投稿履歴へ引き継ぐ(Chami依頼2026-07-30)。
      attrs: readMovieAttrs_(),
      // 割引%/価格も作成時にスナップ＝生キャッシュ失効・再作成の往復でも投稿モードでN%にしない(Chami依頼2026-08-06④)。
      priceInfo: livePriceInfo_(($('movieWorkUrl') || {}).value || ($('movieWorkAffi') || {}).value || ''),
      youtubeUrl: '',
    };
    // ★サムネ/プレビューは「今のCanvas」に依存するので、タブ遷移・再描画より前に取得を開始しておく。
    var capP = Promise.all([captureThumb_(), capturePreview_()]).catch(function () { return [null, null]; });
    // ★★メタ(localStorage)は最優先で即保存する=IDB blob 保存の成否に一覧の在否を依存させない
    //   (Chami報告2026-08-12「ドラフトに情報が行かない」の根治)。従来は Promise.all(ops)=IDBへの
    //   動画/サムネ書込が成功して初めて saveMeta していたため、iOS Safariが接続を無言で殺して idb-timeout
    //   (2周とも死)になると saveMeta まで到達せず、ドラフトが一覧に一切載らなかった。一覧は軽い
    //   localStorage に確実に載せ、重い blob 保存は best-effort(失敗しても握り潰す=一覧は残る)に分離する。
    var arr = loadMeta();
    arr.unshift(meta);
    saveMeta(arr); // ← ここで一覧に載る(=自動遷移で必ず見える)。以降の blob 失敗は一覧を消さない。
    return capP.then(function (caps) {
      var thumbBlob = caps[0], prevBlob = caps[1];
      // ★サムネが取れなかった時(canvas由来の取得が全滅)でも黒箱にしない=前景の元画像を代替サムネにする。
      //   sourceImageFile は toBlob を通さず直接保存する実体なので沈黙経路が無い(Chami報告2026-08-13①の保険)。
      if (!thumbBlob && evDetail.sourceImageFile) thumbBlob = evDetail.sourceImageFile;
      var store = idb();
      var ops = [];
      if (store) {
        if (evDetail.blob) ops.push(store.set('stock_v_' + id, evDetail.blob));
        if (thumbBlob)      ops.push(store.set('stock_t_' + id, thumbBlob));
        // 元画像(前景)もIDBへ保存＝投稿完了(別セッションのこともある)まで残し、Driveへ動画と一緒に上げる。
        //   これが無いと handleCompleteOk_ の時点で元画像が手元に無く、Driveに動画だけが保存される(Chami指摘2026-07-29)。
        if (evDetail.sourceImageFile) ops.push(store.set('stock_img_' + id, evDetail.sourceImageFile));
        // 仕上がりプレビューも投稿完了まで退避(使用画像1ページ目＋Drive行き)。
        if (prevBlob) ops.push(store.set('stock_prev_' + id, prevBlob));
      }
      // ★blob 保存が2周とも死んでも reject しない=メタは既に保存済みなので一覧には出る。
      //   動画DL/サムネは mirror(雲)や後続の backfill で追って効かせる(fail-open)。
      return Promise.all(ops).catch(function (e) {
        try { if (window.console && console.warn) console.warn('[stock] draft blob save failed (meta kept in list):', e && (e.message || e)); } catch (_) {}
      }).then(function () {
        ensureBlobMirror_(id); // ①-B サムネ/プレビュー/元画像を雲へ(2台目でも出す)
        ensureVideoMirror_(id, evDetail.blob); // ② 動画本体もR2へ=メモリのblobを直接渡す(ローカル保存が死んでもDL可能に)
        return id;
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
  function resolveVideoFromR2_(id) {
    if (!(window.Go5Sync && Go5Sync.fetchBlobR2At)) return Promise.resolve(null);
    var store = idb();
    var fetchP = Go5Sync.fetchBlobR2At('go5vid:' + id).then(function (b) {
      if (b && store) { try { store.set('stock_v_' + id, b); } catch (e) {} } // 取り寄せた実体は手元にも保存=次回は即使える
      return b;
    }).catch(function () { return null; });
    var toP = new Promise(function (res) { setTimeout(function () { res(null); }, 45000); });
    return Promise.race([fetchP, toP]);
  }
  function resolveVideoBlob_(id) {
    var store = idb();
    if (!store) return resolveVideoFromR2_(id);
    return store.get('stock_v_' + id).then(function (blob) {
      if (blob) return blob;
      return resolveVideoFromR2_(id); // 手元に無い=R2の控えから取り寄せ
    }, function () {
      // ★IDB get が iOS Safari で idb-timeout / idb-open-timeout 等で reject した時も R2 へ倒す(2026-08-13)。
      //   従来は reject が .then を素通りして downloadStock_ の catch(「動画データの取得に失敗しました」)へ
      //   直行し、作成直後に ensureVideoMirror_ で R2 へ上げた実体があっても一切取りに行けなかった
      //   (Chami報告2026-08-12①「動画データの取得に失敗。3回くらい出た」の根治)。拒否=手元が無応答なので
      //   雲の控えを見に行く=これが可用性を喋る側へ倒す fail-open。
      return resolveVideoFromR2_(id);
    });
  }

  // ── 動画DL ──
  function downloadStock_(id, videoName) {
    var store = idb();
    if (!store) { alert('IndexedDB未対応のため再DLできません。'); return; }
    resolveVideoBlob_(id).then(function (blob) {
      if (!blob) {
        // 手元にも雲にも無い=作った端末からまだ上がっていない(その端末でアプリを開けば数十秒で上がる)。
        alert('動画がまだ雲に届いていません。動画を作成した端末でこのアプリを開いていれば数十秒で自動的に上がります。少し待ってもう一度お試しください。');
        return;
      }
      var name = videoName || 'video.mp4';
      // ★iPhoneはカメラロール(アルバム)へ直接入れたい(Chami指示2026-07-29)。<a download>だと「ファイル」アプリ止まりで
      //   写真アルバムに入らない。Web共有シート(navigator.share)には「ビデオを保存」があり、そこからアルバムへ入る=
      //   本体タブの保存ボタン(app.js saveBtn)と同じ経路。共有が使えない/断られた時だけ従来の<a download>へ落とす。
      var file = null;
      try { file = new File([blob], name, { type: blob.type || 'video/mp4' }); } catch (e) {}
      if (file && navigator.canShare && navigator.canShare({ files: [file] })) {
        // ★共有シートを出せたらキャンセル/完了に関わらずここで完結する。<a download>へ落とすと
        //   iOSで共有シートの後に「ダウンロードしますか?」が二重に出て邪魔(Chami指摘2026-07-29・スクショ実物)。
        navigator.share({ files: [file], title: name }).catch(function () {});
        return;
      }
      anchorDownload_(blob, name);
    }).catch(function () { alert('動画データの取得に失敗しました。'); });
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
    if (!meta) return false;
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
    try {
      if (window.Go5History && typeof window.Go5History.addCompletedPost === 'function') {
        _res = window.Go5History.addCompletedPost({
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
        });
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
          var _byJa = _res.matchedBy === 'ytUrl' ? 'YouTube URL一致' : _res.matchedBy === 'shortUrl' ? '短縮URL一致' : '同じ動画ID';
          var _ex = _res.existing || {};
          alert('この作品は既に投稿履歴に載っています(' + _byJa + ')。二重登録を防ぎました。\n既存: ' + (_ex.title || '(題名なし)') + (_ex.videoId ? ' / ' + _ex.videoId : ''));
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
    // 投稿履歴へ「新規保存できた」または「既に載っている」と確認できた時だけ完了を進める。
    // API未起動/識別不能/保存失敗/例外でドラフトを作成履歴へ移すと再試行手段を失うため、ここで止める。
    if (!_res || (_res.ok === false && _res.reason !== 'dupe')) return false;
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
    return true;
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
    var folderId = window.Go5Drive.folderIdFor ? window.Go5Drive.folderIdFor(meta.videoId) : '';
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
    // ── 既にDriveへフォルダがある=動画/元画像は作成時に保存済み。プレビューだけ追記する(blob不要=blob寿命に依存しない)。
    if (folderId) {
      Promise.all([
        store.get('stock_prev_' + id).catch(function () { return null; }),
        store.get('stock:imgs:' + id).catch(function () { return null; })
      ]).then(function (r) {
        var prev = r[0], mirror = r[1] || {};
        var prevP = prev ? Promise.resolve(prev) : durlToBlob_(mirror.prev);
        prevP.then(function (prevB) {
          if (prevB && window.Go5Drive.appendImage) window.Go5Drive.appendImage(meta.account, meta.title, folderId, prevB, null);
          applyPreview(prevB);
          done(true, '作成時に保存済み(プレビュー追記)');
        });
      });
      return;
    }
    // ── フォールバック：作成時にDrive未保存。動画blobを取り直してフル保存(動画+元画像+プレビュー)。
    resolveVideoBlob_(id).then(function (blob) {
      if (!blob) { if (!opts.silent) alert('動画データが見つかりません(保存期間が過ぎたか削除されました)。投稿履歴には記録済みです。Google Driveへの動画保存だけスキップしました。'); done(false, '動画データ無し'); return; }
      Promise.all([
        store.get('stock_img_' + id).catch(function () { return null; }),
        store.get('stock_prev_' + id).catch(function () { return null; }),
        store.get('stock:imgs:' + id).catch(function () { return null; }) // 同期ミラー(別端末で作った動画の画像)
      ]).then(function (r) {
        var img = r[0], prev = r[1], mirror = r[2] || {};
        // ★サブ端末では stock_prev_/stock_img_(Blob)が無いので、同期ミラー stock:imgs: の dataURL から実体へ戻す
        //   (Chami 2026-08-04「サブ端末で投稿すると投稿履歴の画像に動画投稿プレビューが表示されない」)。
        var imgP  = img  ? Promise.resolve(img)  : durlToBlob_(mirror.src);
        var prevP = prev ? Promise.resolve(prev) : durlToBlob_(mirror.prev);
        Promise.all([imgP, prevP]).then(function (bs) {
          var imgB = bs[0], prevB = bs[1];
          window.Go5Drive.upload(blob, meta.videoName, meta.title, meta.account, meta.id, imgB ? [imgB] : [], prevB || null);
          applyPreview(prevB);
          done(true, 'Driveへ保存開始');
        });
      }).catch(function () {
        window.Go5Drive.upload(blob, meta.videoName, meta.title, meta.account, meta.id, []);
        done(true, 'Driveへ保存開始');
      });
    }).catch(function (err) {
      if (!opts.silent) alert('動画データの取得に失敗しました(投稿履歴には記録済み): ' + (err ? err.message || String(err) : '不明'));
      done(false, '取得失敗');
    });
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
    // ②再作成したらこのドラフトはドラフト一覧から外す(Chami依頼2026-08-06②)。作り直しの起点なので
    //   元の下書きは残さない=消し忘れによる二重ドラフトを防ぐ(墓標で他端末のドラフトからも消える)。
    try { deleteStock_(meta.id); render(); } catch (e) {}
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
                : '<div style="width:48px;height:85px;border-radius:5px;background:#0e1422;flex:0 0 auto;"></div>') +
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

  // 作成履歴(退避済み)の1行。復元・動画DL(blobは残してある)・完全削除。
  function renderArchItem_(meta, thumbUrl) {
    var id = meta.id;
    var acctLabel = meta.account === 'acc2' ? '宵桜艶帖' : '月詠み';
    var hasYt = !!(meta.youtubeUrl);
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
  //   先頭フレームで仕上がりプレビューを起こして dataURL を返す。呼び出し側(yt-clicks.js)が投稿履歴の
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
        return videoFirstFramePreview_(vBlob).then(function (prevBlob) {
          if (!prevBlob) return null;
          try { if (store) store.set('stock_prev_' + m.id, prevBlob).catch(function () {}); } catch (e) {} // 次回のために控える(冪等)
          return blobToDataUrlP_(prevBlob);
        });
      });
    }).catch(function () { return null; });
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
    var arch = loadArchive().filter(function (m) { return (m.account || 'acc1') === curAcct; });
    var sig = stockViewSig_(curAcct), seq = ++_renderSeq;

    var store = idb();
    var all = metas.concat(arch);

    // 一覧HTMLを thumbFor(id→サムネURL/null)から組み立てて描画する。(サムネの有無に依らず同じ骨格)
    function paint_(thumbFor) {
      if (seq !== _renderSeq || page.hidden) return;
      // ★過去分プレビューの一括復元は「投稿履歴の🔁ボタン」へ統合した(Chami依頼2026-08-13)。
      //   ドラフトタブのこのボタンは撤去(Chami「ドラフトタブにそのボタンは不要・削除で」)。
      var html = '<div class="card">';
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
    all.forEach(function (m) { var u = _thumbCache[m.id] || null; cachedFor[m.id] = u; if (!u) _missingThumbs[m.id] = 1; });
    paint_(cachedFor);

    var thumbPs = all.map(function (m) {
      if (_thumbCache[m.id]) return Promise.resolve(_thumbCache[m.id]);
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
              return null;
            }).catch(function () { return null; });
          }).catch(function () { return null; });
        }).catch(function () { return null; });
      }).catch(function () { return null; });
    });

    Promise.all(thumbPs).then(function (thumbUrls) {
      // 非同期サムネ読込中にアカウント/同期データが変わった古い描画は捨てる。古いPromiseが後勝ちしない。
      var nowAcct = (window.Go5Acct && Go5Acct.current && Go5Acct.current()) || 'acc1';
      if (seq !== _renderSeq || page.hidden || nowAcct !== curAcct || stockViewSig_(curAcct) !== sig) {
        if (!page.hidden && !modalIsOpen_()) setTimeout(render, 0);
        return;
      }
      var thumbFor = {}; _missingThumbs = {};
      all.forEach(function (m, i) { thumbFor[m.id] = thumbUrls[i]; if (!thumbUrls[i]) _missingThumbs[m.id] = 1; });
      paint_(thumbFor); // サムネが揃ったら差し替え描画(即描画の骨格を上書き)
    });
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
          var share = (r && (r.shareUrl || r.shortUrl)) || '';
          if (share) { _shortMintCache[aff] = { shortUrl: (r && r.shortUrl) || '', shareUrl: (r && r.shareUrl) || '' }; applyShare_(_shortMintCache[aff]); return; }
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
    $('draftDlVideo').addEventListener('click', function () { if (_modalMeta) downloadStock_(_modalMeta.id, _modalMeta.videoName); }); // 動画DL(Chami依頼2026-07-30④)
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
    $('draftModalComplete').addEventListener('click', function () {
      if (!_modalMeta) return;
      if (!window.confirm('投稿履歴に反映します。OKを押すと正式に投稿完了になります。')) return;
      var ytUrl = ($('draftYtUrl') || {}).value || '';
      var slot = $('draftYtDescUrlLink');
      var shortUrl = (slot && slot.dataset && slot.dataset.url) || '';
      // 履歴への保存を確認できた時だけ閉じる。失敗時はドラフトとモーダルを残して再試行可能にする。
      if (handleCompleteOk_(_modalMeta.id, ytUrl.trim(), shortUrl)) closeModal_();
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
        window.__go5DraftPending = true;
        var makeBtn = $('makeBtn');
        if (makeBtn) makeBtn.click();
      });
    }

    document.addEventListener('video-created', function (e) {
      // detail.draft(app.jsがmake()入口で__go5DraftPendingを消費して確定した権威)だけで判定する。
      if (!(e && e.detail && e.detail.draft)) return;
      var detail = e.detail;
      // 生成完了で動画作成タブ→ドラフトタブへ自動遷移(Chami依頼2026-08-13「前は遷移してた、戻して」)。
      //   ★ボタンの click 経由(tabStock.click)に依存せず、ドラフトページ(Stock.html)へ明示遷移する=
      //     配線変更や他ハンドラの割り込みで遷移が黙って止まらないようにする。既にドラフトページ上なら再描画のみ。
      var _navigated = false;
      var goDraft_ = function () {
        if (_navigated) return; _navigated = true; // 保険のタイマとsaveStock_完了で二重遷移しない
        if (window.__go5StockStandalone) { render(); return; }
        try { location.href = 'Stock.html'; }
        catch (e2) { var tb = $('tabStock'); if (tb) tb.click(); else render(); }
      };
      // ★saveStock_ が「同期例外」を投げた場合、.then/.catch のどちらにも乗らず遷移が黙って消える
      //   (=動画は録れているのにドラフトタブへ移らない・Chami報告2026-08-13 月詠み)。try で囲い、
      //   同期例外でも必ず goDraft_ へ抜ける=生成後の自動遷移をどんな失敗でも止めない(§3 沈黙が最悪)。
      // ★さらに saveStock_ 内の非同期処理(toBlob/IDB書込)が「settleしない」で固着しても遷移が消える。
      //   メタは saveStock_ 冒頭で同期保存済み(一覧には必ず出る)ので、8秒以内に完了しなければ遷移を先行する
      //   =生成後の遷移をどんな沈黙でも止めない。blob/サムネは mirror/backfill が後追いで効かせる。
      var navTimer = setTimeout(function () {
        try { if (window.console && console.warn) console.warn('[stock] saveStock_ が8秒以内に完了せず=遷移を先行(メタは保存済み)'); } catch (_) {}
        goDraft_();
      }, 8000);
      try {
        saveStock_(detail).then(function () { clearTimeout(navTimer); goDraft_(); }).catch(function (err) {
          clearTimeout(navTimer);
          alert('ドラフト保存に失敗しました: ' + (err ? err.message || String(err) : '不明なエラー'));
          goDraft_(); // メタは saveStock_ 内で先に保存済み=一覧には出るので、blob 保存が転んでも遷移はする
        });
      } catch (err2) {
        clearTimeout(navTimer);
        try { if (window.console && console.warn) console.warn('[stock] saveStock_ 同期例外・遷移は続行:', err2 && (err2.message || err2)); } catch (_) {}
        goDraft_();
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
    });

    // 起動直後にも一度、過去分のプレビュー遡及補完を試す(既に同期済みミラーがあれば即補完)。
    setTimeout(function () { try { backfillUsedPreview_(); } catch (_) {} }, 1500);

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
          if (meta) downloadStock_(id, meta.videoName);

        } else if (btn.classList.contains('stk-drive')) {
          // ☁️ Drive保存(作成履歴カード)=作成時にDriveへ上がっていない過去分を後から保存する。
          //   素材(動画)が端末にまだ残っていればフル保存、既に作成時に上がっていればプレビュー追記(冪等)。
          //   ★押した瞬間から結果までボタンで状態を見せる(作成時に保存済みだと従来は無反応で「押せない」に見えた)。
          if (meta && !btn.disabled) {
            var _orig = btn.textContent;
            btn.textContent = '☁️ 保存中…'; btn.disabled = true;
            // ★終着点で必ずボタンを戻す=二重発火(onDoneとwatchdogの両方)しても1回だけ効かせる。
            var _settled = false;
            var _finish = function (ok, errText) {
              if (_settled) return; _settled = true;
              btn.disabled = false;
              btn.textContent = ok ? '✅ 保存済み' : (errText || _orig);
              if (ok) setTimeout(function () { if (btn.textContent === '✅ 保存済み') btn.textContent = _orig; }, 4000);
            };
            // ★「保存中…」のまま返らない事故を機構で塞ぐ=90秒で必ず戻す(Chami報告2026-08-11①・押せない/固まるの根治)。
            //   driveSaveForCompleted_ 内の各分岐は done() を呼ぶが、万一どれかが無応答でも UI は自力で回復する(fail-open)。
            var _wd = setTimeout(function () { _finish(false, '⏱ 中断(再度お試しください)'); }, 90000);
            driveSaveForCompleted_(meta, { silent: false, onDone: function (ok) { clearTimeout(_wd); _finish(ok); } });
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

    window.Go5Stock = { render: render, previewForVideoId: previewForVideoId_ };

    // 動画・画像ミラーは保存直後に即送信し、ここでは旧データ/一時失敗ぶんだけを静かに再試行する。
    // 最大50件を同時発火していた旧30秒sweepはiOSのメモリ圧を上げるため、逐次処理＋2分周期へ変更。
    setTimeout(sweepVideoMirror_, 1000);  // 起動直後(sync設定の読み込みを少し待つ・追いつきを速く)
    setTimeout(sweepVideoMirror_, 6000);  // 1本目でsync未設定だった時の取りこぼしを拾う二度目(重複はbusyガード)
    document.addEventListener('visibilitychange', function () { if (!document.hidden) sweepVideoMirror_(); });
    setInterval(sweepVideoMirror_, 120000);

    // 初回アクセスでドラフトが空表示になる穴の根治(Chami 2026-07-29):
    //   affiliate.js の restoreActiveTab_ が「このモジュールより先」に走ると、ドラフトタブへ
    //   復元されても showTab の render 呼び出しが window.Go5Stock 未定義でスキップされ、
    //   タブは開いているのに中身が空のまま(再タップで直る)になっていた。読み込み順に依存せず、
    //   init 時点でドラフトタブが既に表示中なら自分で描画して穴を塞ぐ。
    if (page && !page.hidden) render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
