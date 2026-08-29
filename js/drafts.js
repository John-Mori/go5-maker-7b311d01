/**
 * drafts.js — 動画作成タブの「下書き」機能。
 * - 「📝 下書き保存」(仕上がりプレビューの見出し行)：写真・作者名・誘導文・コメント・
 *   作品URL・カテゴリ・リビルドの現在値を1件保存する。(アカウント別・最大20件・古い順に押し出し)
 * - 「下書きから呼び出し」(ウィザード起動ボタンの隣)：保存済み下書きの一覧から選んで、
 *   動画作成タブの各欄へ書き戻す(写真は #photo の実ファイルとしてセットするため、
 *   Bluesky添付/Drive保存など後続処理も通常の写真選択と同じに動く)。
 * 他スクリプトへの依存：window.Go5SetForegroundFile(app.js)／getCurrentAccount。(app.js)
 */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }

  // カテゴリの正本は core/categories.js(Go5Cats)。ここは [key, elId] を list()/elId() から派生させる(ハードコードしない)。
  function attrKeys_() {
    var cats = (window.Go5Cats && window.Go5Cats.visible()) || [];
    return cats.map(function (c) { return [c.key, window.Go5Cats.elId(c.key)]; });
  }
  var MAX_DRAFTS = 20;

  function acctId() { try { return (typeof window.getCurrentAccount === 'function') ? window.getCurrentAccount() : 'acc1'; } catch (e) { return 'acc1'; } }
  function draftsKey() { return 'movie_drafts__' + acctId(); }
  function loadDrafts() { try { return JSON.parse(localStorage.getItem(draftsKey()) || '[]') || []; } catch (e) { return []; } }

  // 素の書き込み(容量オーバーで throw→false)。
  function tryWrite_(arr) {
    try { localStorage.setItem(draftsKey(), JSON.stringify(arr.slice(0, MAX_DRAFTS))); return true; }
    catch (e) { return false; }
  }
  // 再取得できるキャッシュだけを退避して空きを作る(Go5Keys.isPurgeable=正本/唯一コピーには触れない)。
  //   ★下書きの写真・作成履歴・候補の退避画像などは決して消さない(C-041)。
  function purgeableSweep_() {
    var n = 0;
    try {
      if (!(window.Go5Keys && window.Go5Keys.isPurgeable)) return 0;
      for (var i = localStorage.length - 1; i >= 0; i--) {
        var k = localStorage.key(i);
        if (k && window.Go5Keys.isPurgeable(k)) { localStorage.removeItem(k); n++; }
      }
    } catch (e) {}
    return n;
  }
  // ★localStorage逼迫でも「下書きの本文は必ず残す」ための段階縮退つき保存。
  //   Chami依頼2026-08-17「下書きも以前はできてたのに失敗になる。どうにかして」=保存が全か無かで
  //   容量不足だと丸ごと失敗していた。以前できていたのは store がまだ空いていたから(archiveのサムネ・
  //   候補base64・写真キャッシュが月日で積もり iOS の約5MB壁に達した)。
  //   ①素で書く → ②再取得可能キャッシュを退避して再試行 → ③古い下書きを削って再試行(新しい方を守る)
  //   → ④最新も含め写真を落として本文だけでも残す。返り値で縮退の度合いを伝える。
  //   返り値: '' 失敗 / 'ok' 素で成功 / 'purged'|'trimmed'|'nophoto' 縮退して成功(本文は保存済み)。
  function saveDrafts(arr) {
    if (tryWrite_(arr)) return 'ok';
    if (purgeableSweep_() > 0 && tryWrite_(arr)) return 'purged';
    // 古い下書きを新しい順に守りつつ末尾(古い)から削る(最低3件までは写真つきで残そうと試みる)。
    for (var keep = arr.length - 1; keep >= 3; keep--) {
      if (tryWrite_(arr.slice(0, keep))) { arr.splice(keep); return 'trimmed'; }
    }
    // 最終手段: 写真を全部落として本文だけでも残す(写真は下書き呼び出し時に選び直せる)。
    var lean = arr.map(function (d) { var c = {}; for (var kk in d) { if (Object.prototype.hasOwnProperty.call(d, kk)) c[kk] = d[kk]; } c.photo = null; c.photoName = ''; return c; });
    if (tryWrite_(lean)) {
      for (var m = 0; m < arr.length; m++) { arr[m].photo = null; arr[m].photoName = ''; }
      return 'nophoto';
    }
    return '';
  }

  // ── 下書きの写真は IndexedDB へ逃がす(恒久対策・Fable5設計案3 2026-08-18)。
  //   movie_drafts__ は同期対象外(core/storage-keys.js の許可リストに無い)なので、写真を localStorage から
  //   IDBへ移しても別端末から復活しない=iOSの約5MB壁に張り付く最大の要因(写真dataURL×最大20件×2ch)を根絶できる。
  //   ★verify-then-strip(C-041): IDBへ書いて読み戻せた時だけ localStorage の photo を外す。読み戻せなければ
  //   dataURLをそのまま localStorage に据え置く=唯一のコピーを先に消さない。IDB未対応/不健康なら触らない。
  var IDB_PREFIX = 'draftimg:';
  function idbUsable_() { try { return !!(window.Go5Idb && window.Go5Idb.available()); } catch (e) { return false; } }
  // dataURLをIDBへ退避し、読み戻せたら true(=LSから外してよい)。失敗/未対応は false(=LSに据え置き)。
  function stashPhotoIdb_(id, dataUrl) {
    if (!dataUrl || !id || !idbUsable_()) return Promise.resolve(false);
    return window.Go5Idb.set(IDB_PREFIX + id, dataUrl)
      .then(function () { return window.Go5Idb.get(IDB_PREFIX + id); }) // 読み戻し検証(get はfail-openでnull)
      .then(function (v) { return typeof v === 'string' && v.length > 0; })
      .catch(function () { return false; });
  }
  function loadPhotoIdb_(id) {
    if (!id || !idbUsable_()) return Promise.resolve(null);
    try { return window.Go5Idb.get(IDB_PREFIX + id).catch(function () { return null; }); }
    catch (e) { return Promise.resolve(null); }
  }
  function delPhotoIdb_(id) {
    try { if (id && idbUsable_()) window.Go5Idb.del(IDB_PREFIX + id).catch(function () {}); } catch (e) {}
  }
  // 起動時ワンタイム移行: 既存下書きのインライン写真をIDBへ寄せる(両アカウント)。読み戻せた分だけLSから外す。
  //   IDBが不健康な起動では一切触らない(一度のget失敗を不在と断定しない・C-041。次回起動でやり直す=冪等)。
  function migrateDraftPhotosToIdb_() {
    try {
      if (!idbUsable_() || (window.Go5Idb.isHealthy && !window.Go5Idb.isHealthy())) return;
      ['acc1', 'acc2'].forEach(function (acc) {
        var key = 'movie_drafts__' + acc, arr;
        try { arr = JSON.parse(localStorage.getItem(key) || '[]') || []; } catch (e) { return; }
        var pending = arr.filter(function (d) { return d && d.photo && !d.photoIdb && d.id; });
        if (!pending.length) return;
        var chain = Promise.resolve(), moved = false;
        pending.forEach(function (d) {
          chain = chain.then(function () {
            return stashPhotoIdb_(d.id, d.photo).then(function (ok) {
              if (ok) { d.photo = null; d.photoIdb = true; moved = true; }
            });
          });
        });
        chain.then(function () {
          if (!moved) return;                          // 1件も外せなければ書き戻さない(無変更)
          try { localStorage.setItem(key, JSON.stringify(arr.slice(0, MAX_DRAFTS))); } catch (e) {}
        });
      });
    } catch (e) {}
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // サークルを表すアイコン。(旧「🏷」の置き換え＝グレー人物シルエットのSVG・白背景は透過・文字サイズに追従)
  var CIRCLE_ICON = '<svg viewBox="0 0 100 100" width="1em" height="1em" aria-hidden="true" focusable="false" style="display:inline-block;vertical-align:-0.15em;">' +
    '<ellipse cx="50" cy="33" rx="25" ry="30" fill="#c2c4c7"/>' +
    '<path fill="#c2c4c7" d="M50 57C33 57 21 64 15 74 10 82 8 91 8 100L92 100C92 91 90 82 85 74 79 64 67 57 50 57Z"/>' +
    '</svg>';
  function fmtTs(ts) {
    try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); }
    catch (e) { return ''; }
  }

  // 下書き用の縮小画像。(プレビュー用途・保存容量を抑えるため小さめ)
  function compressForDraft_(file) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        try {
          var maxSide = 480, scale = Math.min(1, maxSide / Math.max(img.width, img.height));
          var c = document.createElement('canvas');
          c.width = Math.max(1, Math.round(img.width * scale));
          c.height = Math.max(1, Math.round(img.height * scale));
          c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
          resolve(c.toDataURL('image/jpeg', 0.55));
        } catch (e) { resolve(null); }
        URL.revokeObjectURL(url);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(null); };
      img.src = url;
    });
  }

  function dataUrlToFile_(dataUrl, name) {
    return fetch(dataUrl).then(function (r) { return r.blob(); }).then(function (blob) {
      return new File([blob], name || 'draft.jpg', { type: blob.type || 'image/jpeg' });
    });
  }

  // ── 下書き保存 ──
  function currentAttrs_() {
    var o = {};
    attrKeys_().forEach(function (a) { var el = $(a[1]); o[a[0]] = !!(el && el.checked); });
    return o;
  }
  function makeLabel_(top, author) {
    var t = (top || '').trim(), a = (author || '').trim();
    if (t) return t.length > 22 ? t.slice(0, 22) + '…' : t;
    if (a) return a.length > 22 ? a.slice(0, 22) + '…' : a;
    return '(無題の下書き)';
  }
  function flashBtn_(btn, msg) {
    if (!btn) return;
    var orig = btn.getAttribute('data-orig') || btn.textContent;
    btn.setAttribute('data-orig', orig);
    btn.textContent = msg;
    setTimeout(function () { btn.textContent = btn.getAttribute('data-orig') || orig; }, 1600);
  }
  function saveCurrentAsDraft(btn) {
    var author = ($('author') || {}).value || '';
    var detail = ($('detail') || {}).value || '';
    var top = ($('top') || {}).value || '';
    var workUrl = ($('movieWorkUrl') || {}).value || '';
    var rebuild = !!($('movieRebuild') || {}).checked;
    // ★2行モードのON/OFFも保存する(Chami指定2026-07-19「更新前に下書き保存した作品でも、
    //   更新後に下書きから引っ張る作品は更新後の影響を反映して表示すること」)。
    //   これが無いと: top/author の値には改行が入っているのに、呼び出し先のチェックがOFFだと
    //   fitOneLine で1行に潰れ、**保存した時と見た目が変わる**。下書きは見た目の再現が仕事なので
    //   表示を決めるフラグを本文と一緒に持たせる。
    var topTwo = !!($('topTwoLine') || {}).checked;
    var authorTwo = !!($('authorTwoLine') || {}).checked;
    var attrs = currentAttrs_();
    var photoInput = $('photo');
    var pf = (photoInput && photoInput.files && photoInput.files[0]) ? photoInput.files[0] : ((window.Go5ForegroundFile && window.Go5ForegroundFile()) || null);

    function finish(photoDataUrl, photoName) {
      // 作品URLからDMM作品情報(作品名/作者)をスナップショット。(取得済みキャッシュのみ・通信しない)
      var wTitle = '', wAuthor = '';
      try {
        var wi = (workUrl && window.Go5WorkInfo) ? window.Go5WorkInfo(workUrl) : null;
        if (wi) { wTitle = wi.title || ''; wAuthor = wi.author || ''; }
      } catch (e) {}
      var draft = {
        id: 'd' + new Date().getTime(), ts: new Date().getTime(),
        photo: photoDataUrl || null, photoName: photoName || '',
        author: author, detail: detail, top: top, workUrl: workUrl,
        workTitle: wTitle, workAuthor: wAuthor,
        attrs: attrs, rebuild: rebuild,
        topTwoLine: topTwo, authorTwoLine: authorTwo,
        label: makeLabel_(top, author)
      };
      // ★写真は先にIDBへ逃がす(読み戻せたらdataURLをLSから外す=容量を食わない)。IDB不可/失敗ならdataURL同梱のまま。
      stashPhotoIdb_(draft.id, photoDataUrl).then(function (stashed) {
        if (stashed) { draft.photo = null; draft.photoIdb = true; }
        var arr = loadDrafts();
        arr.unshift(draft);
        var st = saveDrafts(arr);
        var msg = {
          'ok': '✅ 保存しました(' + Math.min(arr.length, MAX_DRAFTS) + '件)',
          'purged': '✅ 保存(空き容量を整理しました)',
          'trimmed': '✅ 保存(古い下書きを一部整理して容量を確保)',
          'nophoto': '✅ 本文を保存(容量不足のため写真は付けられません)'
        }[st] || '⚠️ 保存に失敗(容量不足)。他タブを閉じるなど空きを作って再試行';
        if (btn) flashBtn_(btn, msg);
      });
    }
    if (pf) {
      compressForDraft_(pf).then(function (dataUrl) { finish(dataUrl, pf.name); });
    } else {
      finish(null, '');
    }
  }

  // ── 下書きの呼び出し ──
  function applyDraft_(draft) {
    var author = $('author'), detail = $('detail'), top = $('top'), workUrl = $('movieWorkUrl'), rebuild = $('movieRebuild');
    // ★2行モードは**本文より先に**復元する(Chami指定2026-07-19)。
    //   textareaへ値を入れると change が飛んでプレビューが再描画されるため、
    //   後からチェックを変えると一瞬1行で描かれてから2行になる(ちらつき)。
    //   ★旧い下書き(このフラグを持たない時期に保存したもの)への後方互換:
    //     フラグが無ければ**本文に改行が入っているかどうか**から推定する。
    //     保存時に2行だったからこそ改行が入っているので、これで当時の見た目を復元できる。
    //     undefined と false を区別するため hasOwnProperty で判定する(=== undefined だと
    //     「意図してOFFで保存した下書き」まで推定に流れてしまう)。
    function twoLineOf_(key, text) {
      if (draft && Object.prototype.hasOwnProperty.call(draft, key)) return !!draft[key];
      return String(text || '').indexOf('\n') >= 0;
    }
    var topTwoEl = $('topTwoLine'), authorTwoEl = $('authorTwoLine');
    if (topTwoEl) {
      topTwoEl.checked = twoLineOf_('topTwoLine', draft.top);
      topTwoEl.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (authorTwoEl) {
      authorTwoEl.checked = twoLineOf_('authorTwoLine', draft.author);
      authorTwoEl.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (author) { author.value = draft.author || ''; author.dispatchEvent(new Event('change', { bubbles: true })); }
    if (detail) { detail.value = draft.detail || ''; detail.dispatchEvent(new Event('change', { bubbles: true })); }
    if (top) { top.value = draft.top || ''; top.dispatchEvent(new Event('change', { bubbles: true })); }
    if (workUrl) { workUrl.value = draft.workUrl || ''; workUrl.dispatchEvent(new Event('input', { bubbles: true })); }
    if (rebuild) rebuild.checked = !!draft.rebuild;
    attrKeys_().forEach(function (a) { var el = $(a[1]); if (el) el.checked = !!(draft.attrs && draft.attrs[a[0]]); });

    function done() { showRecallToast_('✅ 下書き「' + draft.label + '」を呼び出しました'); }
    function restorePhoto_(dataUrl) {
      if (!dataUrl) { showRecallToast_('⚠️ 写真の復元に失敗しました。(文章欄のみ反映)写真は選び直してください。'); return; }
      dataUrlToFile_(dataUrl, draft.photoName).then(function (file) {
        var ok = window.Go5SetForegroundFile && window.Go5SetForegroundFile(file);
        if (!ok) showRecallToast_('⚠️ 写真の復元に失敗しました。(文章欄のみ反映)写真は選び直してください。');
        else done();
      }).catch(function () { showRecallToast_('⚠️ 写真の復元に失敗しました。(文章欄のみ反映)'); });
    }
    if (draft.photoIdb) {
      loadPhotoIdb_(draft.id).then(restorePhoto_);   // IDBへ逃がした写真
    } else if (draft.photo) {
      restorePhoto_(draft.photo);                     // 旧い下書き(インラインdataURL)= 後方互換
    } else {
      done();
    }
    try { window.scrollTo(0, 0); } catch (e) {}
  }
  function showRecallToast_(msg) {
    var el = $('draftRecallToast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'draftRecallToast';
      el.style.cssText = 'margin:8px 14px 0;font-size:.82rem;color:var(--sub);';
      var slotCtx = $('slotCtxMovie');
      if (slotCtx && slotCtx.parentNode) slotCtx.parentNode.insertBefore(el, slotCtx.nextSibling);
      else document.body.appendChild(el);
    }
    el.textContent = msg;
    setTimeout(function () { if (el.textContent === msg) el.textContent = ''; }, 5000);
  }

  // ── 一覧モーダル(下書きから呼び出し) ──
  function buildPicker_() {
    var overlay = document.createElement('div');
    overlay.id = 'draftPicker';
    overlay.style.cssText = [
      'position:fixed', 'top:0', 'left:0', 'right:0', 'bottom:0',
      'background:rgba(0,0,0,0.75)', 'z-index:60', 'display:none',
      'align-items:center', 'justify-content:center', 'padding:16px', 'box-sizing:border-box'
    ].join(';');
    var card = document.createElement('div');
    card.style.cssText = 'background:#141a26;border-radius:14px;padding:18px;width:100%;max-width:480px;max-height:85vh;overflow-y:auto;color:#eee;box-sizing:border-box;';
    var title = document.createElement('div');
    title.style.cssText = 'font-size:1.05rem;font-weight:700;margin-bottom:10px;color:#2bb3c0;';
    title.textContent = '📝 下書きから呼び出し';
    var list = document.createElement('div');
    list.id = 'draftPickerList';
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.textContent = '✕ 閉じる';
    closeBtn.style.cssText = 'display:block;width:100%;margin-top:12px;padding:10px;border-radius:8px;border:1px solid #555;background:transparent;color:#aaa;cursor:pointer;font-size:.9rem;';
    closeBtn.addEventListener('click', closePicker);
    card.appendChild(title); card.appendChild(list); card.appendChild(closeBtn);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    return overlay;
  }
  var _pickerEl = null;
  function renderPickerList_() {
    var list = $('draftPickerList');
    if (!list) return;
    var arr = loadDrafts();
    if (!arr.length) {
      // 別アカウントに下書きがある場合はそれも案内。(アカウント別保存のため「消えた?」を防ぐ)
      var other = (acctId() === 'acc2') ? 'acc1' : 'acc2';
      var otherName = (other === 'acc2') ? '宵桜艶帖' : '月詠み';
      var otherN = 0;
      try { otherN = (JSON.parse(localStorage.getItem('movie_drafts__' + other) || '[]') || []).length; } catch (e) {}
      list.innerHTML = '<p style="color:var(--sub);font-size:.88rem;line-height:1.7;">' +
        'このアカウントの下書きはまだありません。<br>プレビュー欄の「📝 下書き保存」で今の内容を保存できます。' +
        (otherN ? '<br><b style="color:var(--accent);">' + otherName + '</b>アカウントに ' + otherN + '件 あります。(上部でアカウントを切り替えてください)' : '') +
        '</p>';
      return;
    }
    list.innerHTML = arr.map(function (d, i) {
      // 題名部分：作品URLのDMM作品名＋作者(保存時スナップ)＋保存日時。無ければ従来のコメントラベル。
      var line1 = d.workTitle || d.label;
      // line2html は既に安全なHTML。(アイコンSVG＋escした著者名)作者が無ければescしたラベル。
      var line2html = d.workAuthor ? (CIRCLE_ICON + ' ' + esc(d.workAuthor)) : (d.workTitle ? esc(d.label) : '');
      // 幅が足りない時は flex-wrap でボタン行が下段へ落ちる。(スマホはみ出し対策)
      // ※ボタンは width:auto 明示＝グローバル button{width:100%} の波及ではみ出す事故(INC-47系)の再発防止。
      // サムネ: 旧い下書きはインラインdataURL / IDBへ逃がした写真は空箱を出してから非同期で背景に差し込む(壊れ画像アイコンを避ける)。
      var thumbHtml = d.photo
        ? '<img src="' + d.photo + '" alt="" style="width:44px;height:44px;object-fit:cover;border-radius:6px;flex:0 0 auto;">'
        : (d.photoIdb
          ? '<div data-thumbidb="' + esc(d.id) + '" style="width:44px;height:44px;border-radius:6px;background:#0e1422 center/cover no-repeat;flex:0 0 auto;"></div>'
          : '<div style="width:44px;height:44px;border-radius:6px;background:#0e1422;flex:0 0 auto;"></div>');
      return '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #2a3346;">' +
        thumbHtml +
        '<div style="flex:1 1 160px;min-width:0;">' +
          '<div style="font-size:.88rem;color:#eef2f7;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">' + esc(line1) + '</div>' +
          (line2html ? '<div style="font-size:.76rem;color:#9fb0c3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + line2html + '</div>' : '') +
          '<div style="font-size:.72rem;color:#8a93a3;">保存: ' + esc(fmtTs(d.ts)) + '</div>' +
        '</div>' +
        '<div style="display:flex;gap:6px;flex:0 0 auto;margin-left:auto;">' +
          '<button type="button" data-recall="' + i + '" style="width:auto;margin:0;flex:0 0 auto;padding:7px 12px;border-radius:8px;border:none;background:#2bb3c0;color:#04222a;font-size:.82rem;font-weight:700;cursor:pointer;white-space:nowrap;">呼び出す</button>' +
          '<button type="button" data-del="' + i + '" style="width:auto;margin:0;flex:0 0 auto;padding:7px 10px;border-radius:8px;border:1px solid #555;background:transparent;color:#999;font-size:.82rem;cursor:pointer;">🗑</button>' +
        '</div>' +
      '</div>';
    }).join('');
    // IDBへ逃がした写真のサムネを非同期で差し込む(空箱→背景画像)。読めなければ空箱のまま(fail-open)。
    list.querySelectorAll('[data-thumbidb]').forEach(function (el) {
      loadPhotoIdb_(el.getAttribute('data-thumbidb')).then(function (dataUrl) {
        if (dataUrl && el) el.style.backgroundImage = 'url("' + dataUrl + '")';
      });
    });
    list.querySelectorAll('[data-recall]').forEach(function (b) {
      b.addEventListener('click', function () {
        var idx = parseInt(b.getAttribute('data-recall'), 10);
        var d = arr[idx]; if (!d) return;
        closePicker();
        applyDraft_(d);
      });
    });
    list.querySelectorAll('[data-del]').forEach(function (b) {
      b.addEventListener('click', function () {
        var idx = parseInt(b.getAttribute('data-del'), 10);
        var d = arr[idx]; if (!d) return;
        if (!window.confirm('下書き「' + d.label + '」を削除しますか？')) return;
        delPhotoIdb_(d.id);   // IDBへ逃がした写真も一緒に消す(孤児を残さない)
        arr.splice(idx, 1); saveDrafts(arr); renderPickerList_();
      });
    });
  }
  function openPicker() {
    if (!_pickerEl) _pickerEl = buildPicker_();
    renderPickerList_();
    _pickerEl.style.display = 'flex';
  }
  function closePicker() { if (_pickerEl) _pickerEl.style.display = 'none'; }

  function init() {
    var saveBtn = $('draftSaveBtn');
    if (saveBtn) saveBtn.addEventListener('click', function () { saveCurrentAsDraft(saveBtn); });
    window.Go5Drafts = { openPicker: openPicker, closePicker: closePicker };
    try { migrateDraftPhotosToIdb_(); } catch (e) {}   // 起動時ワンタイム: 既存下書きの写真をLS→IDBへ(空きを作る)
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
