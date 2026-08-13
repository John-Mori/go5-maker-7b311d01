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
    overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(24,22,19,0.58);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px);overflow-y:auto;display:flex;align-items:flex-start;justify-content:center;padding:20px 16px;';
    overlay.addEventListener('click', function (e) { if (e.target === overlay) closeModal(); });
    document.body.appendChild(overlay);
    drawModal();
  }

  function drawModal() {
    if (!overlay) return;
    // ★UIごと刷新(Chami 2026-08-02「Claude Design / Anthropic公式みたいにオシャレに」)。
    //   Anthropic公式ブランド(web調査 2026-08-02)= 紙色 #faf9f5 / 墨 #141413 / クレイ橙 #d97757 を基調に、
    //   余白を広く・操作は丸い当たり判定のアイコンボタン(裸のグリフを画面端に浮かせない)・focus/hoverを付ける。
    //   スタイルは毎回このscoped <style> を先頭に差し込む(innerHTML置換で重複しない)。
    var rows = draft.map(function (c, idx) {
      var canDelete = !c.builtin;
      var atTop = (idx === 0), atBottom = (idx === draft.length - 1);
      var actBtn = canDelete
        ? '<button type="button" class="cat-del catm-ib" data-idx="' + idx + '" title="削除" aria-label="削除">✕</button>'
        : '<button type="button" class="cat-hide catm-ib" data-idx="' + idx + '" title="' + (c.hidden ? '表示に戻す' : '欄から隠す') + '" aria-label="' + (c.hidden ? '表示に戻す' : '欄から隠す') + '">' + (c.hidden ? '◻︎' : '👁') + '</button>';
      return '<div class="cat-edit-row' + (c.hidden ? ' is-hidden' : '') + '" data-idx="' + idx + '">' +
        '<div class="catm-r1">' +
          '<input type="color" class="cat-color" data-idx="' + idx + '" value="' + esc(/^#[0-9a-fA-F]{6}$/.test(c.color) ? c.color : '#d97757') + '" title="色" aria-label="色">' +
          '<input type="text" class="cat-label" data-idx="' + idx + '" value="' + esc(c.label) + '" placeholder="名前">' +
          '<div class="catm-ctl">' +
            '<button type="button" class="cat-mv catm-ib" data-dir="-1" data-idx="' + idx + '" title="上へ" aria-label="上へ"' + (atTop ? ' disabled' : '') + '>▲</button>' +
            '<button type="button" class="cat-mv catm-ib" data-dir="1" data-idx="' + idx + '" title="下へ" aria-label="下へ"' + (atBottom ? ' disabled' : '') + '>▼</button>' +
            actBtn +
          '</div>' +
        '</div>' +
        '<div class="catm-r2">' +
          '<span>一致語</span>' +
          '<input type="text" class="cat-kw" data-idx="' + idx + '" value="' + esc(c.keywords.join('、')) + '" placeholder="作品ジャンル/フロア名に含む語(、で区切る)">' +
        '</div>' +
      '</div>';
    }).join('');

    var CSS =
      '.catm{background:#faf9f5;border:1px solid #e8e4d9;border-radius:18px;overflow:hidden;box-sizing:border-box;width:100%;max-width:560px;box-shadow:0 24px 60px rgba(20,20,19,.42);}' +
      '.catm-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:17px 20px;border-bottom:1px solid #ece8dd;}' +
      '.catm-title{display:flex;align-items:center;gap:9px;}' +
      '.catm-title b{color:#141413;font-size:1.12rem;font-weight:700;white-space:nowrap;letter-spacing:.01em;}' +
      '.catm-dot{width:9px;height:9px;border-radius:3px;background:#d97757;flex:0 0 auto;}' +
      '.catm-x{width:32px;height:32px;border-radius:50%;border:none;background:transparent;color:#6b6559;font-size:1.05rem;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;}' +
      '.catm-x:hover{background:#efece2;color:#141413;}' +
      '.catm-body{padding:18px 20px 22px;box-sizing:border-box;}' +
      '.catm-help{color:#8a8271;font-size:.74rem;line-height:1.6;margin-bottom:16px;}' +
      '.cat-edit-row{background:#fff;border:1px solid #ece8dd;border-radius:14px;padding:12px 14px;margin-bottom:12px;box-sizing:border-box;box-shadow:0 1px 2px rgba(20,20,19,.05);}' +
      '.cat-edit-row.is-hidden{opacity:.55;background:#f4f2ec;}' +
      '.catm-r1{display:flex;align-items:center;gap:11px;}' +
      '.cat-color{width:26px;height:26px;padding:0;border:1px solid #e2ddd0;border-radius:50%;background:none;cursor:pointer;flex:0 0 auto;overflow:hidden;}' +
      '.cat-color::-webkit-color-swatch-wrapper{padding:0;}.cat-color::-webkit-color-swatch{border:none;border-radius:50%;}' +
      '.cat-label{flex:1 1 auto;min-width:0;border:1px solid #e0dccf;border-radius:9px;background:#fbfaf6;color:#141413;padding:8px 11px;font-size:.9rem;font-weight:600;box-sizing:border-box;}' +
      '.cat-label:focus,.cat-kw:focus{outline:none;border-color:#d97757;box-shadow:0 0 0 3px rgba(217,119,87,.16);}' +
      '.catm-ctl{display:flex;align-items:center;gap:3px;flex:0 0 auto;}' +
      '.catm-ib{width:30px;height:30px;border-radius:50%;border:none;background:transparent;color:#6b6559;font-size:.9rem;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s;flex:0 0 auto;}' +
      '.catm-ib:hover{background:#f0ede3;color:#141413;}.catm-ib:disabled{opacity:.25;cursor:default;}' +
      '.cat-del{color:#bf4d43;}.cat-del:hover{background:#f7e7e4;color:#a13a31;}' +
      '.catm-r2{display:flex;align-items:center;gap:10px;margin-top:10px;}' +
      '.catm-r2 span{font-size:.68rem;font-weight:700;color:#a39a89;letter-spacing:.04em;flex:0 0 auto;}' +
      '.cat-kw{flex:1 1 auto;min-width:0;border:1px solid #e6e2d6;border-radius:9px;background:#fbfaf6;color:#5b554a;padding:7px 11px;font-size:.8rem;box-sizing:border-box;}' +
      '#catAddBtn{width:100%;margin-top:2px;padding:11px;border-radius:11px;border:1px dashed #d3ccbb;background:transparent;color:#8a8271;font-size:.85rem;font-weight:600;cursor:pointer;transition:background .15s;}' +
      '#catAddBtn:hover{background:#f2efe7;color:#6b6559;}' +
      '#catApplyBtn{width:100%;margin-top:18px;padding:14px;border-radius:12px;border:none;background:#d97757;color:#fff;font-size:.95rem;font-weight:700;cursor:pointer;box-shadow:0 3px 10px rgba(217,119,87,.32);transition:background .15s,transform .05s;}' +
      '#catApplyBtn:hover{background:#c8663f;}#catApplyBtn:active{transform:translateY(1px);}';

    overlay.innerHTML =
      '<style>' + CSS + '</style>' +
      '<div class="cat-modal-card catm">' +
        '<div class="catm-head">' +
          '<div class="catm-title"><span class="catm-dot"></span><b>カテゴリ編集</b></div>' +
          '<button type="button" id="catModalClose" class="catm-x" aria-label="閉じる">✕</button>' +
        '</div>' +
        '<div class="catm-body">' +
          '<div class="catm-help">▲▼で並べ替え／左の丸をタップで色／「一致語」は作品ジャンル・フロア名との部分一致</div>' +
          '<div id="catEditList">' + rows + '</div>' +
          '<button type="button" id="catAddBtn">＋ カテゴリを追加</button>' +
          '<button type="button" id="catApplyBtn">保存する</button>' +
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
