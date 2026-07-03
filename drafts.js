/**
 * drafts.js — 動画作成タブの「下書き」機能。
 * - 「📝 下書き保存」（仕上がりプレビューの見出し行）：写真・作者名・誘導文・コメント・
 *   作品URL・カテゴリ・リビルドの現在値を1件保存する（アカウント別・最大20件・古い順に押し出し）。
 * - 「下書きから呼び出し」（ウィザード起動ボタンの隣）：保存済み下書きの一覧から選んで、
 *   動画作成タブの各欄へ書き戻す（写真は #photo の実ファイルとしてセットするため、
 *   Bluesky添付/Drive保存など後続処理も通常の写真選択と同じに動く）。
 * 他スクリプトへの依存：window.Go5SetForegroundFile（app.js）／getCurrentAccount（app.js）。
 */
(function () {
  'use strict';
  function $(id) { return document.getElementById(id); }

  var ATTR_KEYS = [
    ['chara', 'movieAttrChara', 'キャラ'], ['jk', 'movieAttrJk', 'JK'], ['gyaru', 'movieAttrGyaru', 'ギャル'],
    ['isekai', 'movieAttrIsekai', '異世界'], ['ai', 'movieAttrAi', 'AI'], ['ol', 'movieAttrOl', 'OL'], ['soshu', 'movieAttrSoshu', '総集編']
  ];
  var MAX_DRAFTS = 20;

  function acctId() { try { return (typeof window.getCurrentAccount === 'function') ? window.getCurrentAccount() : 'acc1'; } catch (e) { return 'acc1'; } }
  function draftsKey() { return 'movie_drafts__' + acctId(); }
  function loadDrafts() { try { return JSON.parse(localStorage.getItem(draftsKey()) || '[]') || []; } catch (e) { return []; } }
  function saveDrafts(arr) { try { localStorage.setItem(draftsKey(), JSON.stringify(arr.slice(0, MAX_DRAFTS))); return true; } catch (e) { return false; } }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function fmtTs(ts) {
    try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); }
    catch (e) { return ''; }
  }

  // 下書き用の縮小画像（プレビュー用途・保存容量を抑えるため小さめ）。
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
    ATTR_KEYS.forEach(function (a) { var el = $(a[1]); o[a[0]] = !!(el && el.checked); });
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
    var attrs = currentAttrs_();
    var photoInput = $('photo');
    var pf = (photoInput && photoInput.files && photoInput.files[0]) ? photoInput.files[0] : null;

    function finish(photoDataUrl, photoName) {
      var draft = {
        id: 'd' + new Date().getTime(), ts: new Date().getTime(),
        photo: photoDataUrl || null, photoName: photoName || '',
        author: author, detail: detail, top: top, workUrl: workUrl,
        attrs: attrs, rebuild: rebuild,
        label: makeLabel_(top, author)
      };
      var arr = loadDrafts();
      arr.unshift(draft);
      var ok = saveDrafts(arr);
      if (btn) flashBtn_(btn, ok ? ('✅ 保存しました(' + Math.min(arr.length, MAX_DRAFTS) + '件)') : '⚠️ 保存に失敗(容量不足?)');
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
    if (author) { author.value = draft.author || ''; author.dispatchEvent(new Event('change', { bubbles: true })); }
    if (detail) { detail.value = draft.detail || ''; detail.dispatchEvent(new Event('change', { bubbles: true })); }
    if (top) { top.value = draft.top || ''; top.dispatchEvent(new Event('change', { bubbles: true })); }
    if (workUrl) { workUrl.value = draft.workUrl || ''; workUrl.dispatchEvent(new Event('input', { bubbles: true })); }
    if (rebuild) rebuild.checked = !!draft.rebuild;
    ATTR_KEYS.forEach(function (a) { var el = $(a[1]); if (el) el.checked = !!(draft.attrs && draft.attrs[a[0]]); });

    function done() { showRecallToast_('✅ 下書き「' + draft.label + '」を呼び出しました'); }
    if (draft.photo) {
      dataUrlToFile_(draft.photo, draft.photoName).then(function (file) {
        var ok = window.Go5SetForegroundFile && window.Go5SetForegroundFile(file);
        if (!ok) showRecallToast_('⚠️ 写真の復元に失敗しました（文章欄のみ反映）。写真は選び直してください。');
        else done();
      }).catch(function () { showRecallToast_('⚠️ 写真の復元に失敗しました（文章欄のみ反映）。'); });
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

  // ── 一覧モーダル（下書きから呼び出し） ──
  function buildPicker_() {
    var overlay = document.createElement('div');
    overlay.id = 'draftPicker';
    overlay.style.cssText = [
      'position:fixed', 'top:0', 'left:0', 'right:0', 'bottom:0',
      'background:rgba(0,0,0,0.75)', 'z-index:60', 'display:none',
      'align-items:center', 'justify-content:center', 'padding:16px', 'box-sizing:border-box'
    ].join(';');
    var card = document.createElement('div');
    card.style.cssText = 'background:#1a1a2e;border-radius:14px;padding:18px;width:100%;max-width:480px;max-height:85vh;overflow-y:auto;color:#eee;box-sizing:border-box;';
    var title = document.createElement('div');
    title.style.cssText = 'font-size:1.05rem;font-weight:700;margin-bottom:10px;color:#d4b3ff;';
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
    if (!arr.length) { list.innerHTML = '<p style="color:#999;font-size:.88rem;">保存済みの下書きはまだありません。「📝 下書き保存」で今の内容を保存できます。</p>'; return; }
    list.innerHTML = arr.map(function (d, i) {
      return '<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #333;">' +
        (d.photo ? '<img src="' + d.photo + '" alt="" style="width:44px;height:44px;object-fit:cover;border-radius:6px;flex:0 0 auto;">' : '<div style="width:44px;height:44px;border-radius:6px;background:#2a2a3e;flex:0 0 auto;"></div>') +
        '<div style="flex:1;min-width:0;">' +
          '<div style="font-size:.88rem;color:#eee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(d.label) + '</div>' +
          '<div style="font-size:.75rem;color:#888;">' + esc(fmtTs(d.ts)) + '</div>' +
        '</div>' +
        '<button type="button" data-recall="' + i + '" style="flex:0 0 auto;padding:7px 12px;border-radius:8px;border:none;background:#5b3f8e;color:#fff;font-size:.82rem;font-weight:700;cursor:pointer;">呼び出す</button>' +
        '<button type="button" data-del="' + i + '" style="flex:0 0 auto;padding:7px 9px;border-radius:8px;border:1px solid #555;background:transparent;color:#999;font-size:.82rem;cursor:pointer;">🗑</button>' +
      '</div>';
    }).join('');
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
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
