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

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
  function fmtTs(ts) {
    try { var d = new Date(ts), p = function (n) { return (n < 10 ? '0' : '') + n; }; return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); }
    catch (e) { return ''; }
  }

  function loadMeta() { try { return JSON.parse(localStorage.getItem(META_KEY) || '[]') || []; } catch (e) { return []; } }
  function saveMeta(arr) { try { localStorage.setItem(META_KEY, JSON.stringify(arr.slice(0, MAX))); } catch (e) {} }

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

  // ── 保存 ──
  var _draftMode = false;
  var _restoreBskyEl = null;
  var _thumbCache = {}; // id → ObjectURL

  function saveStock_(evDetail) {
    var ts = Date.now();
    var id = 'stk' + ts;
    var title = evDetail.title || '';
    var meta = {
      id: id, ts: ts,
      account: evDetail.account || 'acc1',
      label: title.length > 22 ? title.slice(0, 22) + '…' : (title || '(無題)'),
      title: title,
      author: ($('author') || {}).value || '',
      bskyText: ($('bskyText') || {}).value || '',
      affiliateUrl: ($('movieWorkAffi') || {}).value || '',
      workUrl: ($('movieWorkUrl') || {}).value || '',
      videoName: evDetail.name || (title.replace(/[\\/:"*?<>|]/g, '_') + '.mp4'),
      youtubeUrl: '',
    };
    return captureThumb_().then(function (thumbBlob) {
      var store = idb();
      var ops = [];
      if (store) {
        if (evDetail.blob) ops.push(store.set('stock_v_' + id, evDetail.blob));
        if (thumbBlob)      ops.push(store.set('stock_t_' + id, thumbBlob));
      }
      return Promise.all(ops).then(function () {
        var arr = loadMeta();
        arr.unshift(meta);
        saveMeta(arr);
        return id;
      });
    });
  }

  // ── 削除 ──
  function deleteStock_(id) {
    saveMeta(loadMeta().filter(function (m) { return m.id !== id; }));
    var store = idb();
    if (store) { store.del('stock_v_' + id).catch(function () {}); store.del('stock_t_' + id).catch(function () {}); }
    if (_thumbCache[id]) { try { URL.revokeObjectURL(_thumbCache[id]); } catch (e) {} delete _thumbCache[id]; }
  }

  // ── 動画DL ──
  function downloadStock_(id, videoName) {
    var store = idb();
    if (!store) { alert('IndexedDB未対応のため再DLできません。'); return; }
    store.get('stock_v_' + id).then(function (blob) {
      if (!blob) { alert('動画データが見つかりません(保存期間が過ぎたか削除されました)。'); return; }
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = videoName || 'video.mp4';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 3000);
    }).catch(function () { alert('動画データの取得に失敗しました。'); });
  }

  // ── 投稿タブへ引き継ぎ ──
  function sendToPost_(meta) {
    if (meta.bskyText) {
      var el = $('bskyText');
      if (el) {
        el.value = meta.bskyText;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        try { localStorage.setItem('bsky_text', meta.bskyText); } catch (e) {}
      }
    }
    var tabBtn = $('tabPost');
    if (tabBtn) tabBtn.click();
  }

  // ── 投稿完了処理 ──
  function handleCompleteOk_(id, ytUrl) {
    var store = idb();
    if (!store) { alert('IndexedDB未対応のため動画データを取得できません。'); return; }
    var metas = loadMeta();
    var meta = metas.filter(function (m) { return m.id === id; })[0];
    if (!meta) return;
    store.get('stock_v_' + id).then(function (blob) {
      if (!blob) { alert('動画データが見つかりません(保存期間が過ぎたか削除されました)。'); return; }
      if (window.Go5Drive && typeof window.Go5Drive.upload === 'function') {
        window.Go5Drive.upload(blob, meta.videoName, meta.title, meta.account, meta.id);
      } else {
        alert('Drive連携が未設定です。動画作成タブのDriveStatus欄を確認してください。');
      }
      if (ytUrl) {
        metas.forEach(function (m) { if (m.id === id) m.youtubeUrl = ytUrl; });
        saveMeta(metas);
      }
      render();
    }).catch(function (err) {
      alert('動画データの取得に失敗しました: ' + (err ? err.message || String(err) : '不明'));
    });
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
        (hasYt ? '<div style="font-size:.71rem;color:#2bb3c0;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">✅ <a href="' + esc(meta.youtubeUrl) + '" target="_blank" rel="noopener" style="color:#2bb3c0;">' + esc((meta.youtubeUrl).replace(/^https?:\/\//, '').slice(0, 44)) + '</a></div>' : '') +
        '<div style="display:flex;gap:5px;margin-top:7px;flex-wrap:wrap;">' +
          '<button type="button" class="stk-dl" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #3a4a5e;background:transparent;color:#ccc;">⬇ 動画DL</button>' +
          '<button type="button" class="stk-post" data-id="' + esc(id) + '" style="' + btnBase + 'border:none;background:#2bb3c0;color:#04222a;font-weight:700;">🦋 投稿タブへ</button>' +
          (!hasYt ? '<button type="button" class="stk-complete" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #2bb3c0;background:transparent;color:#2bb3c0;">✅ 投稿完了</button>' : '') +
          '<button type="button" class="stk-del" data-id="' + esc(id) + '" style="' + btnBase + 'border:1px solid #3a4a5e;background:transparent;color:#666;padding:5px 8px;">🗑</button>' +
        '</div>' +
        (!hasYt ? '<div data-form-id="' + esc(id) + '" style="display:none;margin-top:8px;">' +
          '<input type="url" class="stk-yt-url" placeholder="YouTube URL(省略可・後でも入力可)" style="width:100%;box-sizing:border-box;padding:6px 8px;font-size:.8rem;border-radius:6px;border:1px solid #3a4a5e;background:#0e1422;color:#eef2f7;margin-bottom:6px;">' +
          '<div style="display:flex;gap:5px;">' +
            '<button type="button" class="stk-complete-ok" data-id="' + esc(id) + '" style="flex:1;padding:6px 0;font-size:.78rem;border-radius:6px;border:none;background:#2bb3c0;color:#04222a;font-weight:700;cursor:pointer;">☁️ DriveへUP + 完了記録</button>' +
            '<button type="button" class="stk-complete-cancel" data-id="' + esc(id) + '" style="padding:6px 10px;font-size:.78rem;border-radius:6px;border:1px solid #3a4a5e;background:transparent;color:#666;cursor:pointer;">キャンセル</button>' +
          '</div>' +
        '</div>' : '') +
      '</div>' +
    '</div>';
  }

  function render() {
    var page = $('pageStock');
    if (!page || page.hidden) return;
    var metas = loadMeta();

    if (!metas.length) {
      page.innerHTML = '<div class="card" style="color:var(--sub);text-align:center;padding:32px 16px;font-size:.9rem;">' +
        'ドラフトはまだありません。<br>動画作成タブの「📦 ドラフトで作成」で動画をここへ貯められます。</div>';
      return;
    }

    var store = idb();
    var thumbPs = metas.map(function (m) {
      if (_thumbCache[m.id]) return Promise.resolve(_thumbCache[m.id]);
      if (!store) return Promise.resolve(null);
      return store.get('stock_t_' + m.id).then(function (blob) {
        if (!blob) return null;
        _thumbCache[m.id] = URL.createObjectURL(blob);
        return _thumbCache[m.id];
      }).catch(function () { return null; });
    });

    Promise.all(thumbPs).then(function (thumbUrls) {
      page.innerHTML = '<div class="card">' +
        '<div style="font-size:.95rem;font-weight:700;color:var(--accent);margin-bottom:10px;">📦 ドラフト(' + metas.length + '件)</div>' +
        metas.map(function (m, i) { return renderItem_(m, thumbUrls[i]); }).join('') +
        '</div>';
    });
  }

  // ── 初期化 ──
  function init() {
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

    // ドラフトタブのボタン操作(event delegation)
    var page = $('pageStock');
    if (page) {
      page.addEventListener('click', function (e) {
        var btn = e.target;
        if (!btn || !btn.dataset || !btn.dataset.id) return;
        var id = btn.dataset.id;
        var metas = loadMeta();
        var meta = metas.filter(function (m) { return m.id === id; })[0];

        if (btn.classList.contains('stk-dl')) {
          if (meta) downloadStock_(id, meta.videoName);

        } else if (btn.classList.contains('stk-post')) {
          if (meta) sendToPost_(meta);

        } else if (btn.classList.contains('stk-complete')) {
          var form = page.querySelector('[data-form-id="' + id + '"]');
          if (form) { form.style.display = 'block'; btn.style.display = 'none'; }

        } else if (btn.classList.contains('stk-complete-cancel')) {
          var form = page.querySelector('[data-form-id="' + id + '"]');
          if (form) form.style.display = 'none';
          var completeBtn = page.querySelector('.stk-complete[data-id="' + id + '"]');
          if (completeBtn) completeBtn.style.display = '';

        } else if (btn.classList.contains('stk-complete-ok')) {
          var form = page.querySelector('[data-form-id="' + id + '"]');
          var ytUrl = form ? (form.querySelector('.stk-yt-url') || {}).value || '' : '';
          handleCompleteOk_(id, ytUrl.trim());

        } else if (btn.classList.contains('stk-del')) {
          if (!window.confirm('「' + (meta ? meta.label || '動画' : '動画') + '」をドラフトから削除しますか?')) return;
          deleteStock_(id);
          render();
        }
      });
    }

    window.Go5Stock = { render: render };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
