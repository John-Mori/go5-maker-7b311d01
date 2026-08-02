/**
 * categories-ui.js — 動画作成タブのカテゴリ・チェックボックス欄の描画と「カテゴリ編集」モーダル。
 *   正本データは core/categories.js(Go5Cats)。ここは見た目と編集操作だけを担う。
 *   - #movieAttrRow へ Go5Cats.visible() のチェックボックスを描画(色はカテゴリの color をインライン適用)。
 *   - 「カテゴリ編集」ボタン→モーダルで 追加・名前・色・キーワード・並べ替え・削除/表示切替。
 *   Go5Cats.onChange で候補・履歴側も含め即再描画される。
 */
(function () {
  'use strict';
  if (typeof window === 'undefined' || !window.Go5Cats) return;
  var Cats = window.Go5Cats;
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  // ── チェックボックス欄の描画(checked 状態はキー単位で保つ) ──
  function renderRow() {
    var row = $('movieAttrRow'); if (!row) return;
    var wasChecked = {};
    var inputs = row.querySelectorAll('input[type="checkbox"]');
    for (var i = 0; i < inputs.length; i++) { if (inputs[i].dataset && inputs[i].dataset.catKey) wasChecked[inputs[i].dataset.catKey] = inputs[i].checked; }

    var html = Cats.visible().map(function (c) {
      var id = Cats.elId(c.key);
      return '<label class="movie-attr"><input id="' + id + '" type="checkbox" data-cat-key="' + esc(c.key) + '">' +
        '<span class="vatt" style="color:' + esc(c.color) + ';border-color:' + esc(c.color) + ';">' + esc(c.label) + '</span></label>';
    }).join('');
    row.innerHTML = html;
    // checked 復元(自動チェック/手動の状態を並べ替え・色替えで失わない)。
    Cats.visible().forEach(function (c) {
      var el = $(Cats.elId(c.key));
      if (el && wasChecked[c.key]) el.checked = true;
    });
  }

  // ── 編集モーダル ──
  var overlay = null;
  var draft = null; // 編集中スナップ(適用まで本体に書かない)

  function closeModal() { if (overlay) { overlay.remove(); overlay = null; draft = null; } }

  function openModal() {
    // 現在の全カテゴリ(hidden含む)を編集用にコピー。
    draft = Cats.list().map(function (c) { return { key: c.key, label: c.label, color: c.color, keywords: c.keywords.slice(), builtin: c.builtin, hidden: c.hidden }; });
    overlay = document.createElement('div');
    overlay.className = 'cat-modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.82);overflow-y:auto;display:flex;align-items:flex-start;justify-content:center;padding:16px;';
    overlay.addEventListener('click', function (e) { if (e.target === overlay) closeModal(); });
    document.body.appendChild(overlay);
    drawModal();
  }

  function drawModal() {
    if (!overlay) return;
    var rows = draft.map(function (c, idx) {
      var canDelete = !c.builtin;
      return '<div class="cat-edit-row" data-idx="' + idx + '" style="display:flex;align-items:center;gap:7px;padding:8px 0;border-bottom:1px solid #1e2d42;">' +
        '<div style="display:flex;flex-direction:column;gap:1px;">' +
          '<button type="button" class="cat-mv" data-dir="-1" data-idx="' + idx + '" style="background:none;border:none;color:#7a8fa3;cursor:pointer;font-size:.7rem;line-height:1;padding:1px 4px;">▲</button>' +
          '<button type="button" class="cat-mv" data-dir="1" data-idx="' + idx + '" style="background:none;border:none;color:#7a8fa3;cursor:pointer;font-size:.7rem;line-height:1;padding:1px 4px;">▼</button>' +
        '</div>' +
        '<input type="color" class="cat-color" data-idx="' + idx + '" value="' + esc(/^#[0-9a-fA-F]{6}$/.test(c.color) ? c.color : '#3fb6a8') + '" style="width:30px;height:30px;padding:0;border:none;background:none;cursor:pointer;flex:0 0 auto;">' +
        '<input type="text" class="cat-label" data-idx="' + idx + '" value="' + esc(c.label) + '" placeholder="名前" style="flex:0 0 92px;min-width:0;border-radius:8px;border:1px solid #3a4a5e;background:#0e1a2b;color:#e6eef5;padding:6px 8px;font-size:.82rem;">' +
        '<input type="text" class="cat-kw" data-idx="' + idx + '" value="' + esc(c.keywords.join('、')) + '" placeholder="一致キーワード(、区切り・部分一致)" style="flex:1 1 0;min-width:0;border-radius:8px;border:1px solid #3a4a5e;background:#0e1a2b;color:#aabbc8;padding:6px 8px;font-size:.78rem;">' +
        (canDelete
          ? '<button type="button" class="cat-del" data-idx="' + idx + '" title="削除" style="background:none;border:none;color:#c05a5a;cursor:pointer;font-size:1rem;padding:2px 6px;flex:0 0 auto;">✕</button>'
          : '<button type="button" class="cat-hide" data-idx="' + idx + '" title="' + (c.hidden ? '表示に戻す' : '欄から隠す') + '" style="background:none;border:none;color:' + (c.hidden ? '#5a9ec0' : '#7a8fa3') + ';cursor:pointer;font-size:.95rem;padding:2px 6px;flex:0 0 auto;">' + (c.hidden ? '◻︎' : '👁') + '</button>') +
        '</div>';
    }).join('');

    overlay.innerHTML =
      '<div class="cat-modal-card" style="background:#0e1422;border:1px solid #2a3346;border-radius:14px;overflow:hidden;box-sizing:border-box;width:100%;max-width:560px;">' +
        '<div style="padding:13px 16px;border-bottom:1px solid #1e2d42;display:flex;justify-content:space-between;align-items:center;">' +
          '<div style="color:#2bb3c0;font-size:.95rem;font-weight:700;">カテゴリ編集</div>' +
          '<button type="button" id="catModalClose" style="background:none;border:none;color:#7a8fa3;font-size:1.2rem;padding:2px 8px;cursor:pointer;">✕</button>' +
        '</div>' +
        '<div style="padding:14px 16px 20px;box-sizing:border-box;">' +
          '<div style="font-size:.72rem;font-weight:700;color:#9fb0c3;letter-spacing:.06em;margin-bottom:6px;">▲▼で並べ替え・色は左のマスをタップ・キーワードは作品ジャンル/フロア名との部分一致</div>' +
          '<div id="catEditList">' + rows + '</div>' +
          '<button type="button" id="catAddBtn" style="margin-top:12px;padding:9px 14px;border-radius:8px;border:1px dashed #3a4a5e;background:#0e1a2b;color:#aabbc8;font-size:.82rem;cursor:pointer;">＋ カテゴリを追加</button>' +
          '<button type="button" id="catApplyBtn" style="width:100%;margin-top:18px;padding:13px;border-radius:10px;border:none;background:#2bb3c0;color:#04222a;font-size:.95rem;font-weight:700;cursor:pointer;">保存する</button>' +
        '</div>' +
      '</div>';

    // 入力の即時反映(draftへ)。
    function syncInputs() {
      overlay.querySelectorAll('.cat-label').forEach(function (el) { draft[+el.dataset.idx].label = el.value; });
      overlay.querySelectorAll('.cat-color').forEach(function (el) { draft[+el.dataset.idx].color = el.value; });
      overlay.querySelectorAll('.cat-kw').forEach(function (el) {
        draft[+el.dataset.idx].keywords = el.value.split(/[、,]/).map(function (s) { return s.trim(); }).filter(Boolean);
      });
    }

    $('catModalClose').onclick = closeModal;
    $('catAddBtn').onclick = function () { syncInputs(); draft.push({ key: null, label: '新カテゴリ', color: Cats.PALETTE[draft.length % Cats.PALETTE.length], keywords: [], builtin: false, hidden: false }); drawModal(); };
    overlay.querySelectorAll('.cat-mv').forEach(function (btn) {
      btn.onclick = function () {
        syncInputs();
        var i = +btn.dataset.idx, dir = +btn.dataset.dir, j = i + dir;
        if (j < 0 || j >= draft.length) return;
        var t = draft[i]; draft[i] = draft[j]; draft[j] = t; drawModal();
      };
    });
    overlay.querySelectorAll('.cat-del').forEach(function (btn) {
      btn.onclick = function () { syncInputs(); draft.splice(+btn.dataset.idx, 1); drawModal(); };
    });
    overlay.querySelectorAll('.cat-hide').forEach(function (btn) {
      btn.onclick = function () { syncInputs(); var c = draft[+btn.dataset.idx]; c.hidden = !c.hidden; drawModal(); };
    });
    $('catApplyBtn').onclick = function () { syncInputs(); applyDraft(); closeModal(); };
  }

  // draft を Go5Cats へ反映。既存キーは update、新規(key=null)は add、消えた組み込みは削除できないので温存。
  function applyDraft() {
    var keptKeys = {};
    // 1) 新規に key を割り当てつつ、順序どおりに反映用の配列を作る。
    var finalOrder = [];
    draft.forEach(function (c) {
      var label = (c.label || '').trim() || '(無名)';
      if (!c.key) {
        var nk = Cats.add(label, c.color, c.keywords);
        finalOrder.push(nk); keptKeys[nk] = 1;
      } else {
        Cats.update(c.key, { label: label, color: c.color, keywords: c.keywords, hidden: c.hidden });
        finalOrder.push(c.key); keptKeys[c.key] = 1;
      }
    });
    // 2) draft から消された追加カテゴリ(組み込みでない)は本体からも削除。
    Cats.list().forEach(function (c) { if (!keptKeys[c.key] && !c.builtin) Cats.remove(c.key); });
    // 3) 並び順を反映。
    Cats.reorder(finalOrder);
  }

  // 「カテゴリ編集」ボタンを欄の下に用意する。
  function ensureEditBtn() {
    if ($('catEditBtn')) return;
    var row = $('movieAttrRow'); if (!row || !row.parentNode) return;
    var btn = document.createElement('button');
    btn.id = 'catEditBtn'; btn.type = 'button';
    btn.textContent = '＋ カテゴリ編集';
    btn.style.cssText = 'margin-top:6px;padding:5px 12px;border-radius:7px;border:1px solid #3a4a5e;background:#0e1a2b;color:#aabbc8;font-size:.76rem;cursor:pointer;';
    btn.onclick = openModal;
    row.parentNode.insertBefore(btn, row.nextSibling);
  }

  function init() { renderRow(); ensureEditBtn(); }
  Cats.onChange(function () { renderRow(); });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
