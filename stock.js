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

  function render() {
    var page = $('pageStock');
    if (!page || page.hidden) return;
    var curAcct = window.getCurrentAccount ? window.getCurrentAccount() : 'acc1';
    var metas = loadMeta().filter(function (m) { return (m.account || 'acc1') === curAcct; });

    if (!metas.length) {
      page.innerHTML = '<div class="card" style="color:var(--sub);text-align:center;padding:32px 16px;font-size:.9rem;">' +
        'このアカウントのドラフトはまだありません。<br>動画作成タブの「📦 ドラフトで作成」で動画をここへ貯められます。</div>';
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

  // ── 投稿モード モーダル ──
  var _modalMeta = null;

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
    var data = {
      xText:   ($('draftXText')       || {}).value || '',
      ytTitle: ($('draftYtTitleText') || {}).value || '',
      ytTags:  ($('draftYtTagsInput') || {}).value || '',
      ytUrl:   ($('draftYtUrl')       || {}).value || '',
      ytDesc:  ($('draftYtDescText')  || {}).value || '',
    };
    try { localStorage.setItem('go5_draft_post_' + _modalMeta.id, JSON.stringify(data)); } catch (e) {}
  }

  function openPostModal_(meta) {
    _modalMeta = meta;
    var m = $('draftPostModal');
    if (!m) return;
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem('go5_draft_post_' + meta.id) || '{}'); } catch (e) {}
    var composedXText;
    if (saved.xText !== undefined) {
      composedXText = saved.xText;
    } else if (window.__go5ComposeXTextForBskyText) {
      composedXText = window.__go5ComposeXTextForBskyText(meta.bskyText || '');
    } else {
      composedXText = (meta.bskyText || '');
    }
    $('draftXText').value = composedXText;
    var tags = saved.ytTags !== undefined ? saved.ytTags : null;
    if (tags === null) { try { tags = localStorage.getItem('yt_tags_shared') || ''; } catch (e) { tags = ''; } }
    if (!tags) { var te = $('ytTags'); tags = te ? te.value : '#Shorts #マンガ #漫画紹介 #anime'; }
    $('draftYtTagsInput').value = tags;
    buildModalYtTitle_();
    if (saved.ytTitle !== undefined) $('draftYtTitleText').value = saved.ytTitle;
    $('draftYtUrl').value = saved.ytUrl !== undefined ? saved.ytUrl : (meta.youtubeUrl || '');
    var ytDescKey = 'yt_desc__' + (meta.account || 'acc1');
    var ytDescVal = saved.ytDesc !== undefined ? saved.ytDesc : '';
    if (!ytDescVal) { try { ytDescVal = localStorage.getItem(ytDescKey) || ''; } catch (e) {} }
    $('draftYtDescText').value = ytDescVal;
    m.style.display = 'flex';
  }

  function createModal_() {
    var m = document.createElement('div');
    m.id = 'draftPostModal';
    m.style.cssText = 'display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.82);overflow-y:auto;-webkit-overflow-scrolling:touch;align-items:flex-start;justify-content:center;padding:16px 0;box-sizing:border-box;';
    var iS = 'width:100%;box-sizing:border-box;background:var(--field-bg,rgba(0,0,0,.28));color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:9px 10px;font-size:.84rem;line-height:1.5;';
    var cpS = 'flex:0 0 auto;padding:7px 12px;font-size:.78rem;border-radius:7px;border:1px solid var(--line);background:transparent;color:var(--sub);cursor:pointer;white-space:nowrap;';
    var sH  = 'font-size:.72rem;font-weight:600;color:var(--accent);letter-spacing:.06em;text-transform:uppercase;';
    var fL  = 'font-size:.76rem;color:var(--sub);margin-bottom:4px;margin-top:12px;';
    var ctaS = 'background:linear-gradient(180deg,var(--cta-from,var(--accent)),var(--cta-to,var(--accent)));color:var(--cta-ink,#04222a);';
    m.innerHTML =
      '<div style="background:var(--card);border:1px solid var(--line);border-radius:14px;width:calc(100% - 24px);max-width:480px;margin:auto;box-sizing:border-box;overflow:hidden;color:var(--ink);">' +
        '<div style="padding:13px 16px;border-bottom:1px solid var(--line);display:flex;align-items:center;position:relative;">' +
          '<div style="flex:1;text-align:center;font-size:.95rem;font-weight:800;color:var(--accent);">投稿モード</div>' +
          '<button type="button" id="draftModalClose" style="position:absolute;right:8px;background:none;border:none;color:var(--sub);font-size:1.2rem;cursor:pointer;padding:2px 8px;line-height:1;">✕</button>' +
        '</div>' +
        '<div style="padding:16px 16px 20px;">' +
          '<div style="' + sH + 'margin-bottom:8px;">X 投稿</div>' +
          '<textarea id="draftXText" rows="6" style="' + iS + 'resize:vertical;"></textarea>' +
          '<button type="button" id="draftCopyX" style="width:100%;margin-top:7px;padding:8px;font-size:.82rem;border-radius:8px;border:1px solid var(--line);background:transparent;color:var(--sub);cursor:pointer;">コピー</button>' +
          '<div style="height:1px;background:var(--line);margin:18px 0;"></div>' +
          '<div style="' + sH + 'margin-bottom:10px;">YouTube</div>' +
          '<div style="' + fL + 'margin-top:0;">題名</div>' +
          '<div style="display:flex;gap:7px;align-items:flex-start;">' +
            '<div style="flex:1;min-width:0;overflow:hidden;">' +
              '<textarea id="draftYtTitleText" rows="3" style="width:100%;box-sizing:border-box;background:var(--field-bg,rgba(0,0,0,.28));color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:9px 10px;font-size:.82rem;line-height:1.5;resize:vertical;"></textarea>' +
            '</div>' +
            '<button type="button" id="draftCopyYtTitle" style="' + cpS + '">コピー</button>' +
          '</div>' +
          '<div style="' + fL + '">タグ</div>' +
          '<div style="display:flex;gap:7px;align-items:center;">' +
            '<div style="flex:1;min-width:0;overflow:hidden;">' +
              '<input type="text" id="draftYtTagsInput" style="width:100%;box-sizing:border-box;background:var(--field-bg,rgba(0,0,0,.28));color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:9px 10px;font-size:.82rem;">' +
            '</div>' +
            '<button type="button" id="draftCopyYtTags" style="' + cpS + '">コピー</button>' +
          '</div>' +
          '<div style="' + fL + '">YouTube URL(投稿後に貼る)</div>' +
          '<input type="url" id="draftYtUrl" placeholder="https://www.youtube.com/shorts/..." style="' + iS + '">' +
          '<div style="' + fL + '">YouTube説明欄</div>' +
          '<div style="display:flex;gap:7px;align-items:flex-start;">' +
            '<div style="flex:1;min-width:0;overflow:hidden;">' +
              '<textarea id="draftYtDescText" rows="5" style="width:100%;box-sizing:border-box;background:var(--field-bg,rgba(0,0,0,.28));color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:9px 10px;font-size:.82rem;line-height:1.5;resize:vertical;"></textarea>' +
            '</div>' +
            '<button type="button" id="draftCopyYtDesc" style="' + cpS + '">コピー</button>' +
          '</div>' +
          '<div style="display:flex;gap:8px;margin-top:20px;">' +
            '<button type="button" id="draftModalComplete" style="flex:1;padding:13px;font-size:.88rem;font-weight:700;border-radius:10px;border:none;' + ctaS + 'cursor:pointer;">投稿完了</button>' +
            '<button type="button" id="draftModalSave" style="flex:1;padding:13px;font-size:.88rem;font-weight:600;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer;">内容を保存</button>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(m);

    $('draftXText').addEventListener('input', saveDraftPost_);
    $('draftYtTitleText').addEventListener('input', saveDraftPost_);
    $('draftYtTagsInput').addEventListener('input', function () {
      buildModalYtTitle_();
      try { localStorage.setItem('yt_tags_shared', this.value); } catch (e) {}
      var yt = $('ytTags'); if (yt) yt.value = this.value;
      saveDraftPost_();
    });
    $('draftYtUrl').addEventListener('input', saveDraftPost_);
    $('draftCopyX').addEventListener('click', function () { copyText_(($('draftXText') || {}).value || '', this); });
    $('draftCopyYtTitle').addEventListener('click', function () { copyText_(($('draftYtTitleText') || {}).value || '', this); });
    $('draftCopyYtTags').addEventListener('click', function () { copyText_(($('draftYtTagsInput') || {}).value || '', this); });
    $('draftCopyYtDesc').addEventListener('click', function () { copyText_(($('draftYtDescText') || {}).value || '', this); });
    $('draftYtDescText').addEventListener('input', saveDraftPost_);
    $('draftModalSave').addEventListener('click', function () {
      saveDraftPost_();
      var btn = this; var orig = btn.textContent; btn.textContent = '保存しました'; setTimeout(function () { btn.textContent = orig; }, 2000);
    });
    $('draftModalClose').addEventListener('click', function () { m.style.display = 'none'; _modalMeta = null; });
    $('draftModalComplete').addEventListener('click', function () {
      if (!_modalMeta) return;
      if (!window.confirm('投稿履歴に反映します。OKを押すと正式に投稿完了になります。')) return;
      var ytUrl = ($('draftYtUrl') || {}).value || '';
      handleCompleteOk_(_modalMeta.id, ytUrl.trim());
      m.style.display = 'none'; _modalMeta = null;
    });
    document.addEventListener('go5-disc-url-changed', function () {
      if (!m || m.style.display === 'none' || !_modalMeta) return;
      if (window.__go5ComposeXTextForBskyText) {
        var xtEl = $('draftXText');
        if (xtEl) xtEl.value = window.__go5ComposeXTextForBskyText(_modalMeta.bskyText || '');
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

        } else if (btn.classList.contains('stk-mode')) {
          if (meta) openPostModal_(meta);

        } else if (btn.classList.contains('stk-remake')) {
          if (meta) remakeStock_(meta);

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
