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
  function setDescUrlSlot_(url) {
    var lk = $('draftYtDescUrlLink');
    var ok = url && /^https?:\/\//.test(url);
    if (lk) {
      if (ok) { lk.href = url; lk.textContent = url; lk.dataset.url = url; lk.style.display = 'inline-block'; }
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
  function kickSync_() { try { if (window.Go5Sync && window.Go5Sync.requestSync) window.Go5Sync.requestSync(); } catch (e) {} }
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
  function ensureBlobMirror_(id) {
    var store = idb(); if (!store) return;
    store.get('stock:imgs:' + id).then(function (existing) {
      if (existing && existing.th) return; // 既にミラー済み=再送しない
      return Promise.all([store.get('stock_t_' + id), store.get('stock_prev_' + id), store.get('stock_img_' + id)]).then(function (bs) {
        if (!bs[0] && !bs[1] && !bs[2]) return; // 実体が無い端末=作らない(同期で降ってくる側)
        return Promise.all([blobToDataUrlP_(bs[0]), blobToDataUrlP_(bs[1]), blobToDataUrlP_(bs[2])]).then(function (du) {
          var rec = {};
          if (du[0]) rec.th = du[0];
          if (du[1]) rec.prev = du[1];
          if (du[2]) rec.src = du[2];
          if (rec.th || rec.prev || rec.src) return store.set('stock:imgs:' + id, rec).then(kickSync_);
        });
      });
    }).catch(function () {});
  }

  // ── ② 動画本体を全端末でDLできるようにする(2026-08-01・Chami依頼)──
  //   動画blob(stock_v_)は重いので周期同期レールには載せず、R2へ raw-bytes hash で直接PUT。
  //   台帳(ドラフトメタ)には vidHash だけ持たせ(=go5_stock_metaのsyncに相乗り・軽い)、
  //   実体を持たない端末(2台目)は downloadStock_ の時に vidHash で R2 からGETして落とす。
  //   実体を持つ端末だけが未アップ時に1回上げる(冪等)。既存ドラフトも開けば後追いで運ばれる。
  function ensureVideoMirror_(id) {
    var store = idb(); if (!store) return;
    if (!(window.Go5Sync && Go5Sync.configured && Go5Sync.configured() && Go5Sync.putBlobR2)) return;
    var meta = loadMeta().filter(function (m) { return m.id === id; })[0];
    if (!meta || meta.vidHash) return; // 既に雲へ上げ済み=何もしない
    store.get('stock_v_' + id).then(function (blob) {
      if (!blob) return; // 実体が無い端末=上げない(同期で hash が降ってくる側)
      return Go5Sync.putBlobR2(blob).then(function (h) {
        if (!h) return; // 失敗(未設定/上限超/通信)=次回の描画でまた試す(非破壊)
        var arr = loadMeta();
        var m2 = arr.filter(function (x) { return x.id === id; })[0];
        if (m2 && !m2.vidHash) { m2.vidHash = h; saveMeta(arr); } // saveMeta が kickSync_ する
      });
    }).catch(function () {});
  }

  function idb() { return window.Go5Idb; }

  // ── サムネ取得(canvas最終フレームを小さいJPEGに) ──
  function captureThumb_() {
    try {
      var cv = $('cv');
      if (!cv) return Promise.resolve(null);
      var c = document.createElement('canvas');
      var W = 90, H = Math.round(90 * cv.height / cv.width);
      c.width = W; c.height = H;
      c.getContext('2d').drawImage(cv, 0, 0, W, H);
      return new Promise(function (resolve) {
        c.toBlob(function (b) { resolve(b); }, 'image/jpeg', 0.5);
      });
    } catch (e) { return Promise.resolve(null); }
  }

  // ── 仕上がりプレビュー取得(canvas最終フレームを原寸JPEGで) ──
  //   これを投稿履歴の使用画像1ページ目＋Driveへ入れる(Chami依頼2026-07-30)。
  //   video-created の時点で #cv は最終フレームを保持している(captureThumb_ と同じ前提)。
  function capturePreview_() {
    try {
      var cv = $('cv');
      if (!cv || !cv.width) return Promise.resolve(null);
      return new Promise(function (resolve) {
        cv.toBlob(function (b) { resolve(b); }, 'image/jpeg', 0.85);
      });
    } catch (e) { return Promise.resolve(null); }
  }
  function blobToDataUrl_(blob, cb) {
    try {
      var r = new FileReader();
      r.onload = function () { cb(r.result || ''); };
      r.onerror = function () { cb(''); };
      r.readAsDataURL(blob);
    } catch (e) { cb(''); }
  }

  // ── 保存 ──
  var _draftMode = false;
  var _restoreBskyEl = null;
  var _thumbCache = {}; // id → ObjectURL

  // 動画作成タブのカテゴリ(ジャンル)チェックを読む。投稿完了時に投稿履歴へ引き継ぐ(Chami依頼2026-07-30)。
  //   これが無いと下書き→投稿完了で履歴にジャンルのチェックが渡らず、毎回手で入れ直しになる。
  var MOVIE_ATTR_IDS = { chara: 'movieAttrChara', jk: 'movieAttrJk', gyaru: 'movieAttrGyaru', isekai: 'movieAttrIsekai', harem: 'movieAttrHarem', ai: 'movieAttrAi', ol: 'movieAttrOl', soshu: 'movieAttrSoshu' };
  function readMovieAttrs_() {
    var o = {};
    Object.keys(MOVIE_ATTR_IDS).forEach(function (kk) { var el = $(MOVIE_ATTR_IDS[kk]); if (el && el.checked) o[kk] = true; });
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
      youtubeUrl: '',
    };
    return Promise.all([captureThumb_(), capturePreview_()]).then(function (caps) {
      var thumbBlob = caps[0], prevBlob = caps[1];
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
      return Promise.all(ops).then(function () {
        var arr = loadMeta();
        arr.unshift(meta);
        saveMeta(arr);
        ensureBlobMirror_(id); // ①-B サムネ/プレビュー/元画像を雲へ(2台目でも出す)
        ensureVideoMirror_(id); // ② 動画本体もR2へ(2台目でDLできるように)
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
    writeStockDel_(id); // 投稿完了＝ドラフト本体から外す。他端末のドラフト一覧からも消す(復活防止)
    saveMeta(metas.filter(function (m) { return m.id !== id; }));
    var arch = loadArchive().filter(function (m) { return m.id !== id; }); // 二重退避を防ぐ
    arch.unshift(meta);
    var dropped = arch.slice(ARCHIVE_MAX); // 上限超過分=保持できないので blob を掃除
    dropped.forEach(function (m) { delBlobs_(m.id); });
    saveArchive(arch);
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
  function purgeArchived_(id) {
    saveArchive(loadArchive().filter(function (m) { return m.id !== id; }));
    delBlobs_(id);
  }

  // ── 動画DL ──
  function downloadStock_(id, videoName) {
    var store = idb();
    if (!store) { alert('IndexedDB未対応のため再DLできません。'); return; }
    store.get('stock_v_' + id).then(function (blob) {
      if (blob) return blob;
      // ★実体が無い端末(2台目)=同期で来た vidHash があれば R2 から取り寄せて落とす(②・2026-08-01)。
      var meta = loadMeta().filter(function (m) { return m.id === id; })[0]
               || loadArchive().filter(function (m) { return m.id === id; })[0];
      var h = meta && meta.vidHash;
      if (h && window.Go5Sync && Go5Sync.fetchBlobR2) {
        return Go5Sync.fetchBlobR2(h).then(function (b) {
          if (b) { try { idb().set('stock_v_' + id, b); } catch (e) {} } // 取り寄せた実体は手元にも保存=次回は即DL
          return b;
        });
      }
      return null;
    }).then(function (blob) {
      if (!blob) { alert('動画データが見つかりません(保存期間が過ぎたか削除されました)。'); return; }
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
    if (!store) { alert('IndexedDB未対応のため動画データを取得できません。'); return; }
    var metas = loadMeta();
    var meta = metas.filter(function (m) { return m.id === id; })[0];
    if (!meta) return;
    // ★X短縮URLが引数で来なかった時(短縮生成前・スロット読み取り失敗)でも、保存済みドラフトデータ
    //   (saveDraftPost_ が xShortUrl として都度保存)から補って投稿履歴へ渡す。これが無いと投稿履歴の
    //   「投稿URL(計測用の短縮URL)」欄が空になり毎回手入力になる(Chami指摘2026-07-29)。
    if (!shortUrl) {
      try { var sv = JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}'); shortUrl = (sv.xShortUrl || '').trim(); } catch (e) {}
    }
    store.get('stock_v_' + id).then(function (blob) {
      if (!blob) { alert('動画データが見つかりません(保存期間が過ぎたか削除されました)。'); return; }
      if (window.Go5Drive && typeof window.Go5Drive.upload === 'function') {
        // 元画像＋仕上がりプレビュー(保存時にIDBへ退避したもの)も一緒にDriveへ。取れなくても動画だけは必ず上げる。
        Promise.all([
          store.get('stock_img_' + id).catch(function () { return null; }),
          store.get('stock_prev_' + id).catch(function () { return null; })
        ]).then(function (r) {
          var img = r[0], prev = r[1];
          window.Go5Drive.upload(blob, meta.videoName, meta.title, meta.account, meta.id, img ? [img] : [], prev || null);
          // ★投稿履歴の使用画像1ページ目に仕上がりプレビューを差し込む(videoIdで紐付く・Chami依頼2026-07-30)。
          if (prev && meta.videoId && window.Go5Cand && window.Go5Cand.usedImgSave && window.Go5Cand.usedImgs) {
            blobToDataUrl_(prev, function (durl) {
              if (!durl) return;
              var cur = window.Go5Cand.usedImgs(meta.videoId) || [];
              if (cur[0] === durl) return; // 再投稿完了で二重差し込みしない(冪等)
              // 先頭1枚=投稿プレビュー画像(拡大表示の見出しを「投稿プレビュー画像」に分ける・Chami依頼2026-07-30)
              window.Go5Cand.usedImgSave(meta.videoId, [durl].concat(cur.filter(function (u) { return u !== durl; })), 1);
            });
          }
        }).catch(function () {
          window.Go5Drive.upload(blob, meta.videoName, meta.title, meta.account, meta.id, []);
        });
      } else {
        alert('Drive連携が未設定です。動画作成タブのDriveStatus欄を確認してください。');
      }
      if (ytUrl) {
        metas.forEach(function (m) { if (m.id === id) m.youtubeUrl = ytUrl; });
        saveMeta(metas);
      }
      // ①投稿完了 → 投稿履歴へ1件記録(既存の投稿履歴機構=Go5History)。載れば予約公開の動画は
      //   既存の updateYtScheduled_ が予約タブへ拾う(②は自動達成)。ytUrl も shortUrl も無ければ載せない。
      try {
        if (window.Go5History && typeof window.Go5History.addCompletedPost === 'function') {
          window.Go5History.addCompletedPost({
            account: meta.account || 'acc1',
            ytUrl: ytUrl || '',
            shortUrl: shortUrl || '',
            title: meta.title || '',
            workUrl: meta.workUrl || meta.affiliateUrl || '',
            videoId: meta.videoId || '',
            attrs: meta.attrs || null // ジャンルのチェックを引き継ぐ(Chami依頼2026-07-30)
          });
        }
      } catch (e) {}
      // ③投稿完了=作成完了 → ドラフト本体から外し、④作成履歴へ退避(復元可)。youtubeUrl保存の後に行う。
      archiveStock_(id);
      render();
    }).catch(function (err) {
      alert('動画データの取得に失敗しました: ' + (err ? err.message || String(err) : '不明'));
    });
  }

  // ── 再作成(ドラフトデータを動画作成タブに復元) ──
  function remakeStock_(meta) {
    var a = $('author');
    if (a) { a.value = meta.author || ''; a.dispatchEvent(new Event('input')); }
    var t = $('top');
    if (t) { t.value = meta.title || ''; t.dispatchEvent(new Event('input')); }
    var b = $('bskyText');
    if (b) b.value = meta.bskyText || '';
    var w = $('movieWorkUrl');
    if (w) { w.value = meta.workUrl || ''; w.dispatchEvent(new Event('input')); }
    var tab = $('tabMovie');
    if (tab) tab.click();
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
    var btnBase = 'width:auto;margin:0;padding:5px 10px;font-size:.76rem;border-radius:6px;cursor:pointer;white-space:nowrap;';
    return '<div data-item-id="' + esc(id) + '" style="display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid #2a3346;opacity:.92;">' +
      (thumbUrl ? '<img src="' + esc(thumbUrl) + '" alt="" style="width:40px;height:71px;object-fit:cover;border-radius:5px;flex:0 0 auto;">'
                : '<div style="width:40px;height:71px;border-radius:5px;background:#0e1422;flex:0 0 auto;"></div>') +
      '<div style="flex:1 1 0;min-width:0;">' +
        '<div style="font-size:.84rem;font-weight:700;color:#cbd5e3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(meta.label) + '</div>' +
        '<div style="font-size:.72rem;color:#7a8fa3;margin-top:1px;">' + esc(acctLabel) + ' · 完了 ' + esc(fmtTs(meta.completedTs || meta.ts)) + '</div>' +
        (hasYt ? '<div style="font-size:.71rem;color:var(--accent);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">✅ <a href="' + esc(meta.youtubeUrl) + '" target="_blank" rel="noopener" style="color:var(--accent);">' + esc((meta.youtubeUrl).replace(/^https?:\/\//, '').slice(0, 44)) + '</a></div>' : '') +
        '<div style="display:flex;gap:5px;margin-top:7px;flex-wrap:wrap;">' +
          '<button type="button" class="stk-restore" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid var(--accent);background:transparent;color:var(--accent);font-weight:700;">↩ 復元</button>' +
          '<button type="button" class="stk-dl" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #3a4a5e;background:transparent;color:#ccc;">⬇ 動画DL</button>' +
          '<button type="button" class="stk-arch-del" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #5a2a2a;background:transparent;color:#c77;padding:5px 8px;">🗑 完全削除</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  function render() {
    var page = $('pageStock');
    if (!page || page.hidden) return;
    var curAcct = window.getCurrentAccount ? window.getCurrentAccount() : 'acc1';
    var metas = loadMeta().filter(function (m) { return (m.account || 'acc1') === curAcct; });
    var arch = loadArchive().filter(function (m) { return (m.account || 'acc1') === curAcct; });

    var store = idb();
    var all = metas.concat(arch);
    var thumbPs = all.map(function (m) {
      if (_thumbCache[m.id]) return Promise.resolve(_thumbCache[m.id]);
      if (!store) return Promise.resolve(null);
      return store.get('stock_t_' + m.id).then(function (blob) {
        if (blob) {
          _thumbCache[m.id] = URL.createObjectURL(blob);
          ensureBlobMirror_(m.id); // 実体を持つ端末=未送なら雲へミラー(①-B・既存ドラフトの後追い同期)
          ensureVideoMirror_(m.id); // 実体を持つ端末=未送なら動画本体もR2へ(②・既存ドラフトの後追い)
          return _thumbCache[m.id];
        }
        // 実体が無い端末(2台目)=同期で来た stock:imgs ミラーの dataURL からサムネを出す(①-B)
        return store.get('stock:imgs:' + m.id).then(function (mir) {
          var du = mir && mir.th;
          if (du) { _thumbCache[m.id] = du; return du; }
          return null;
        }).catch(function () { return null; });
      }).catch(function () { return null; });
    });

    Promise.all(thumbPs).then(function (thumbUrls) {
      var thumbFor = {};
      all.forEach(function (m, i) { thumbFor[m.id] = thumbUrls[i]; });
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
        html += '<details style="margin-top:12px;">' +
          '<summary style="cursor:pointer;font-size:.86rem;font-weight:700;color:var(--sub);padding:11px 14px;background:var(--card);border:1px solid var(--line);border-radius:12px;">🗂 作成履歴(投稿完了ぶん・' + arch.length + '件) — タップで開く/復元</summary>' +
          '<div class="card" style="margin-top:8px;">' +
          arch.map(function (m) { return renderArchItem_(m, thumbFor[m.id]); }).join('') +
          '</div></details>';
      }
      page.innerHTML = html;
    });
  }

  // ── 投稿モード モーダル ──
  var _modalMeta = null;
  var _ytTitleDirty = false; // ユーザーが題名を手編集したかどうか(trueの間はタグ変更で上書きしない)

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
    };
    try { localStorage.setItem('go5_draft_post_' + _modalMeta.id, JSON.stringify(data)); } catch (e) {}
    kickSync_(); // 投稿編集も全端末へ運ぶ
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
      if (b && cur === acc && b.value) return b.value;
    } catch (e) {}
    try {
      var k = (window.Go5Acct && Go5Acct.key) ? Go5Acct.key('bsky_text', acc) : ('bsky_text__' + acc);
      var v = localStorage.getItem(k);
      if (v != null && v !== '') return v;
    } catch (e) {}
    return (meta && meta.bskyText) || '';
  }

  function openPostModal_(meta) {
    _modalMeta = meta;
    _ytTitleDirty = false;
    var m = $('draftPostModal');
    if (!m) return;
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem('go5_draft_post_' + meta.id) || '{}'); } catch (e) {}
    var composedXText;
    if (saved.xText !== undefined) {
      // この投稿を投稿モードで手編集した履歴があるときだけ、その編集を優先(データ喪失を防ぐ)。
      composedXText = saved.xText;
    } else if (window.__go5ComposeXTextForBskyText) {
      composedXText = window.__go5ComposeXTextForBskyText(masterBody_(meta), meta.affiliateUrl || '');
    } else {
      composedXText = masterBody_(meta);
    }
    $('draftXText').value = composedXText;
    var tags = saved.ytTags !== undefined ? saved.ytTags : null;
    if (tags === null) { try { tags = localStorage.getItem('yt_tags_shared') || ''; } catch (e) { tags = ''; } }
    if (!tags) { var te = $('ytTags'); tags = te ? te.value : '#Shorts #マンガ #漫画紹介 #anime'; }
    $('draftYtTagsInput').value = tags;
    buildModalYtTitle_();
    $('draftYtUrl').value = saved.ytUrl !== undefined ? saved.ytUrl : (meta.youtubeUrl || '');
    var ytDescVal = (saved.ytDesc !== undefined && saved.ytDesc !== '') ? saved.ytDesc : '';
    if (!ytDescVal && window.__go5YtDescForAccount) { ytDescVal = window.__go5YtDescForAccount(meta.account || 'acc1'); }
    if (!ytDescVal) { try { ytDescVal = localStorage.getItem('yt_desc__' + (meta.account || 'acc1')) || ''; } catch (e) {} }
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
      if (slotUrl && !isOurs && saved.xPostUrl) { applyXPostUrl_(saved.xPostUrl, null); }
    } catch (e) {}
    // 作品遷移リンク(Chami依頼2026-07-30④)=作品のアフィリンクをタップで開ける(遷移先の確認用)。無ければ隠す。
    var wl = $('draftWorkLink'), waff = (meta.affiliateUrl || meta.workUrl || '').trim();
    if (wl) {
      if (/^https?:\/\//.test(waff)) { wl.href = waff; wl.style.display = 'inline-block'; }
      else { wl.removeAttribute('href'); wl.style.display = 'none'; }
    }
    renderAffCheck_(meta);
    m.style.display = 'flex';
  }

  // ⑤ アフィID入り確認(Chami依頼2026-07-30)。作品紹介・セールの短縮リンクに自分のaf_idが入っているかを表示。
  //   実体の判定は bluesky.js の __go5AffCheck(作品アフィリンク＋現在のセール設定＋af_idを見る)。未読込時は表示しない。
  function renderAffCheck_(meta) {
    var box = $('draftAffCheck'); if (!box) return;
    if (typeof window.__go5AffCheck !== 'function') { box.innerHTML = ''; return; }
    var r; try { r = window.__go5AffCheck((meta && (meta.affiliateUrl || meta.workUrl)) || ''); } catch (e) { box.innerHTML = ''; return; }
    if (!r) { box.innerHTML = ''; return; }
    function esc2(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
    function line_(label, v) {
      if (!v) return '';
      if (v.applicable === false) return '<div style="color:var(--sub);">' + label + '：—(未使用)</div>';
      if (v.ok) return '<div style="color:var(--ink);">' + label + '：<b style="color:#2bb3c0;">✅</b></div>';
      return '<div style="color:var(--ink);">' + label + '：<b style="color:#e06">🆖</b>' + (v.reason ? ' <span style="color:var(--sub);">' + esc2(v.reason) + '</span>' : '') + '</div>';
    }
    box.innerHTML = '<div style="font-weight:700;color:var(--accent);margin-bottom:2px;">アフィチェック</div>' +
      line_('投稿作品', r.work) + line_('セールURL', r.sale);
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
          '<textarea id="draftXText" rows="6" style="' + iS + 'resize:vertical;"></textarea>' +
          '<div style="' + fL + '">X投稿リンク(Xに投稿後に貼ると説明欄へ短縮URLが入る)</div>' +
          '<div style="' + rowWrap + '">' +
            '<input type="url" id="draftXPostUrl" size="1" placeholder="https://x.com/.../status/..." style="' + rowIn + '">' +
            '<button type="button" id="draftPasteXPostUrl" style="' + cpS + '">貼り付け</button>' +
          '</div>' +
          '<div style="height:1px;background:var(--line);margin:18px 0;"></div>' +
          '<div style="' + sH + 'margin-bottom:10px;">YouTube</div>' +
          '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;"><div style="font-size:.78rem;font-weight:600;color:var(--sub);white-space:nowrap;">題名(コピーして貼り付け)</div><button type="button" id="draftCopyYtTitle" style="' + btnW + 'margin-left:auto;">題名をコピー</button></div>' +
          '<textarea id="draftYtTitleText" readonly rows="3" style="' + iS + 'resize:vertical;cursor:default;"></textarea>' +
          '<div style="display:flex;align-items:center;gap:8px;' + fL + '"><span style="white-space:nowrap;">タグ(半角スペース区切り)</span><button type="button" id="draftCopyYtTags" style="' + btnW + 'margin-left:auto;">コピー</button></div>' +
          '<input type="text" id="draftYtTagsInput" style="' + iS + '">' +
          '<div style="' + fL + '">' +
            '<svg viewBox="0 0 28 20" style="height:1em;width:1.4em;vertical-align:-0.18em" aria-hidden="true"><rect width="28" height="20" rx="6" fill="#FF0000"/><path d="M11 6 L11 14 L20 10 Z" fill="#fff"/></svg> YouTube説明欄(コピーして概要欄に貼り付け)' +
          '</div>' +
          // 説明欄の短縮リンク行(Chami依頼2026-07-30④)=左に「説明欄をコピー」・短縮リンク／右に作品遷移リンク・動画DL
          '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;">' +
            '<button type="button" id="draftCopyYtDesc" style="' + btnW + '">説明欄をコピー</button>' +
            '<a id="draftYtDescUrlLink" target="_blank" rel="noopener" style="' + lnkR + 'display:none;"></a>' +
            '<span style="flex:1;min-width:8px;"></span>' +
            '<a id="draftWorkLink" target="_blank" rel="noopener" style="' + lnkR + 'display:none;">作品遷移↗</a>' +
            '<button type="button" id="draftDlVideo" style="' + btnW + '">動画DL</button>' +
          '</div>' +
          '<textarea id="draftYtDescText" rows="11" style="' + iS + 'resize:vertical;"></textarea>' +
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
    $('draftCopyX').addEventListener('click', function () { copyText_(($('draftXText') || {}).value || '', this); });
    $('draftCopyYtTitle').addEventListener('click', function () { copyText_(($('draftYtTitleText') || {}).value || '', this); });
    $('draftCopyYtTags').addEventListener('click', function () { copyText_(($('draftYtTagsInput') || {}).value || '', this); }); // タグ欄をコピー(Chami依頼2026-07-30③)
    $('draftDlVideo').addEventListener('click', function () { if (_modalMeta) downloadStock_(_modalMeta.id, _modalMeta.videoName); }); // 動画DL(Chami依頼2026-07-30④)
    $('draftCopyYtDesc').addEventListener('click', function () {
      // 短縮URLは概要欄テキストボックスの最上段に既に入っている(setDescUrlSlot_)ので、
      //   テキストボックスの中身をそのままコピーする(先頭URLを二重に足さない)。
      copyText_(($('draftYtDescText') || {}).value || '', this);
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
      m.style.display = 'none'; _modalMeta = null;
    });
    $('draftModalClose').addEventListener('click', function () { m.style.display = 'none'; _modalMeta = null; });
    $('draftModalComplete').addEventListener('click', function () {
      if (!_modalMeta) return;
      if (!window.confirm('投稿履歴に反映します。OKを押すと正式に投稿完了になります。')) return;
      var ytUrl = ($('draftYtUrl') || {}).value || '';
      var slot = $('draftYtDescUrlLink');
      var shortUrl = (slot && slot.dataset && slot.dataset.url) || '';
      handleCompleteOk_(_modalMeta.id, ytUrl.trim(), shortUrl);
      m.style.display = 'none'; _modalMeta = null;
    });
    document.addEventListener('go5-disc-url-changed', function () {
      if (!m || m.style.display === 'none' || !_modalMeta) return;
      if (window.__go5ComposeXTextForBskyText) {
        var xtEl = $('draftXText');
        if (xtEl) xtEl.value = window.__go5ComposeXTextForBskyText(masterBody_(_modalMeta), _modalMeta.affiliateUrl || '');
      }
    });
    document.addEventListener('go5-work-short-ready', function () {
      if (!m || m.style.display === 'none' || !_modalMeta) return;
      if (window.__go5ComposeXTextForBskyText) {
        var xtEl = $('draftXText');
        if (xtEl) xtEl.value = window.__go5ComposeXTextForBskyText(masterBody_(_modalMeta), _modalMeta.affiliateUrl || '');
      }
    });
    m.addEventListener('click', function (e) { if (e.target === m) { m.style.display = 'none'; _modalMeta = null; } });
    return m;
  }

  // ── 初期化 ──
  function init() {
    createModal_();

    var draftMakeBtn = $('draftMakeBtn');
    if (draftMakeBtn) {
      draftMakeBtn.addEventListener('click', function () {
        var bskyEnable = $('bskyEnable');
        var wasChecked = !!(bskyEnable && bskyEnable.checked);
        if (wasChecked) bskyEnable.checked = false;
        _restoreBskyEl = wasChecked ? bskyEnable : null;
        _draftMode = true;
        var makeBtn = $('makeBtn');
        if (makeBtn) makeBtn.click();
      });
    }

    document.addEventListener('video-created', function (e) {
      if (!_draftMode) return;
      _draftMode = false;
      if (_restoreBskyEl) { _restoreBskyEl.checked = true; _restoreBskyEl = null; }
      var detail = (e && e.detail) || {};
      saveStock_(detail).then(function () {
        var tabBtn = $('tabStock');
        if (tabBtn) tabBtn.click();
        else render();
      }).catch(function (err) {
        alert('ドラフト保存に失敗しました: ' + (err ? err.message || String(err) : '不明なエラー'));
      });
    });

    var tabStockBtn = $('tabStock');
    if (tabStockBtn) tabStockBtn.addEventListener('click', function () { setTimeout(render, 0); });

    document.addEventListener('account-changed', function () {
      var page = $('pageStock');
      if (page && !page.hidden) render();
    });

    // ★全端末同期で別端末のドラフトが降ってきたら、開いていれば即再描画(タブを再タップしなくても出る)。
    document.addEventListener('go5-synced', function () {
      var page = $('pageStock');
      if (page && !page.hidden) render();
    });

    // ドラフトタブのボタン操作(event delegation)
    var page = $('pageStock');
    if (page) {
      page.addEventListener('click', function (e) {
        var btn = e.target;
        if (!btn || !btn.dataset || !btn.dataset.id) return;
        var id = btn.dataset.id;
        // meta はドラフト本体・作成履歴のどちらにあるか分からない(動画DLは両方から押せる)ので両方から探す。
        var meta = loadMeta().filter(function (m) { return m.id === id; })[0]
                 || loadArchive().filter(function (m) { return m.id === id; })[0];

        if (btn.classList.contains('stk-dl')) {
          if (meta) downloadStock_(id, meta.videoName);

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

    window.Go5Stock = { render: render };
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
