/**
 * promo-label.js — 販促ラベル(今なら◯%OFF🌙/今だと◯%OFF🌸)
 *
 * 2026-07-15 作り替え(Chami指示): 写真への「焼き込み」をやめ、動画フレーム(1080×1920)への
 * 「重ね描き(オーバーレイ)」に一本化。app.js の drawFrame() が Go5PromoLabel.drawOverlay() を呼ぶ。
 *   - フレーム基準で描くので、挿入画像の外(黒帯・余白)にも自由に配置できる。
 *   - 写真File自体は無改変 → Bluesky添付画像にはラベルが入らない(Chami指定「記載しない」)。
 *   - プレビューも書き出し(録画)も同じ drawFrame を通るので一致する。
 * 位置はフレーム比(0..1)、大きさは倍率。どちらも localStorage で永続。
 * 位置調整=プレビュー横のD-pad(promoPos*)＋プレビュー上で指ドラッグ。大きさ=promoSize±。
 */
(function () {
  'use strict';
  var FRAME_W = 1080, FRAME_H = 1920;
  // scale=1 の基本寸法(フレーム基準)。旧852基準(w264/h62/font36/r14)を1080基準へ換算(×1.268)。
  var LBL = { w: 335, h: 79, font: 46, radius: 18 };

  var scale = 1;    // 大きさ倍率(0.6〜2.5)
  var fpos = null;  // 手動位置 {x,y}=ラベル左上のフレーム比(0..1)。null=既定(右上)
  var pct = 0;      // 現在の割引率(0=ラベル非表示)
  var lastCid = ''; // 直近の作品id(begin/notifyの取り違え防止)

  try { var _s = parseFloat(localStorage.getItem('promo_label_scale')); if (_s >= 0.6 && _s <= 2.5) scale = _s; } catch (e) {}
  try { var _p = JSON.parse(localStorage.getItem('promo_label_fpos') || 'null'); if (_p && typeof _p.x === 'number' && typeof _p.y === 'number') fpos = _p; } catch (e) {}

  function acct() { return window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'; }
  function labelText(p) { return acct() === 'acc2' ? ('今だと' + p + '%OFF🌸') : ('今なら' + p + '%OFF🌙'); }
  function active() { return pct > 0; }
  function lw() { return LBL.w * scale; }
  function lh() { return LBL.h * scale; }

  // 既定位置(右上・フレーム比)。scale込みで右端に余白40px。
  function defPos() { return { x: (FRAME_W - lw() - 40) / FRAME_W, y: 300 / FRAME_H }; }
  // 現在のラベル左上(フレーム比)。手動があればそれ。画像外もOK＝端から大きくはみ出す所まで許可(一部は残す)。
  function curPos() {
    var pp = fpos || defPos();
    var minx = (-lw() * 0.7) / FRAME_W, maxx = (FRAME_W - lw() * 0.3) / FRAME_W;
    var miny = (-lh() * 0.7) / FRAME_H, maxy = (FRAME_H - lh() * 0.3) / FRAME_H;
    return { x: Math.min(Math.max(minx, pp.x), maxx), y: Math.min(Math.max(miny, pp.y), maxy) };
  }

  function roundRectPath(ctx, x, y, w, h, r) {
    if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); return; }
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  // app.js drawFrame から毎フレーム呼ばれる。フレーム(W×H)にラベルを重ね描き。
  function drawOverlay(ctx, W, H) {
    if (!active()) return;
    var sx = W / FRAME_W, sy = H / FRAME_H;
    var cp = curPos();
    var w = lw() * sx, h = lh() * sy;
    var x = cp.x * W, y = cp.y * H;
    var r = LBL.radius * scale * Math.min(sx, sy);
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,.35)'; ctx.shadowBlur = 8 * sx; ctx.shadowOffsetY = 2 * sy;
    ctx.beginPath();
    roundRectPath(ctx, x, y, w, h, r);
    ctx.fillStyle = 'rgba(224,37,78,.93)';
    ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.lineWidth = Math.max(2, 2.5 * sx); ctx.strokeStyle = 'rgba(255,255,255,.95)'; ctx.stroke();
    var text = labelText(pct);
    var fs = LBL.font * scale * sx;
    var setF = function () { ctx.font = '700 ' + fs + 'px "Noto Sans JP", sans-serif'; };
    setF();
    while (fs > 20 && ctx.measureText(text).width > w - 18 * sx) { fs -= 1; setF(); }
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#fff';
    ctx.fillText(text, x + w / 2, y + h / 2 + fs * 0.04);
    ctx.restore();
  }

  // プレビュー再描画(app.jsのpreview)。連打・ドラッグ中はrAFで間引く。
  var rafPending = false;
  function redraw() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(function () { rafPending = false; if (window.Go5Preview) window.Go5Preview(); });
  }

  function persist() {
    try { localStorage.setItem('promo_label_scale', String(scale)); } catch (e) {}
    try { localStorage.setItem('promo_label_fpos', fpos ? JSON.stringify(fpos) : ''); } catch (e) {}
  }

  // ---- 位置・大きさの手動調整 ----
  function nudge(dxFrame, dyFrame) {
    if (!active()) return;
    var cp = curPos();
    fpos = { x: cp.x + dxFrame / FRAME_W, y: cp.y + dyFrame / FRAME_H };
    persist(); redraw();
  }
  function resetPos() { if (!active()) return; fpos = null; persist(); redraw(); }
  function updateSizeLabel() {
    var el = document.getElementById('promoSizeVal');
    if (el) el.textContent = Math.round(scale * 100) + '%';
  }
  function setScale(mult) {
    if (!active()) return;
    var ns = Math.min(2.5, Math.max(0.6, Math.round((scale + mult) * 100) / 100));
    if (ns === scale) return;
    scale = ns; persist(); updateSizeLabel(); redraw();
  }
  function updateRow() {
    var row = document.getElementById('promoPosRow');
    if (row) row.hidden = !active();
    updateSizeLabel();
    var pw = document.querySelector('.preview-wrap');
    if (pw) pw.classList.toggle('has-dpad', active());
  }

  (function wireButtons() {
    var map = { promoPosL: [-20, 0], promoPosR: [20, 0], promoPosU: [0, -20], promoPosD: [0, 20] };
    Object.keys(map).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('click', function () { nudge(map[id][0], map[id][1]); });
    });
    var rs = document.getElementById('promoPosReset'); if (rs) rs.addEventListener('click', resetPos);
    var sm = document.getElementById('promoSizeMinus'); if (sm) sm.addEventListener('click', function () { setScale(-0.1); });
    var sp = document.getElementById('promoSizePlus'); if (sp) sp.addEventListener('click', function () { setScale(0.1); });
    updateSizeLabel();
  })();

  // ---- プレビュー上の操作 ----
  // 二本指ピンチ=連続ズーム(画面フィット→実寸相当までズームイン・Chami「等倍で拡大」)。
  // ズーム中は一本指=パン(移動)。ズームしていない時の一本指=ラベルのドラッグ。
  (function wirePointer() {
    var cv = document.getElementById('cv');
    if (!cv || !window.PointerEvent) return;
    var pointers = {};      // 触れているポインタ {id:{x,y}}
    var pinchBase = 0;      // ピンチ開始の2点間距離
    var zoomK = 1;          // ズーム倍率(1=フィット, 上限2.8=実寸相当)
    var zoomStartK = 1;     // ピンチ開始時のzoomK
    var panX = 0, panY = 0; // パン(表示px)
    var panPrev = null;     // 一本指パンの前回座標
    var drag = null;        // ラベルドラッグ {gx,gy}=掴んだ点とラベル左上のずれ(フレーム比)

    function framePoint(ev) { // ポインタ→フレーム比(0..1)。ズーム無しの時だけ使う(変形なし)。
      var b = cv.getBoundingClientRect();
      if (!b.width || !b.height) return null;
      return { x: (ev.clientX - b.left) / b.width, y: (ev.clientY - b.top) / b.height };
    }
    function pinchDist() {
      var ids = Object.keys(pointers);
      if (ids.length < 2) return 0;
      var a = pointers[ids[0]], b = pointers[ids[1]];
      return Math.hypot(a.x - b.x, a.y - b.y);
    }
    function zoomed() { return cv.classList.contains('cv-zoom'); }
    function applyZoom() {
      if (zoomed()) cv.style.transform = 'translate(calc(-50% + ' + panX + 'px), calc(-50% + ' + panY + 'px)) scale(' + zoomK + ')';
      else { cv.style.transform = ''; zoomK = 1; panX = 0; panY = 0; }
    }
    function exitZoom() { cv.classList.remove('cv-zoom'); applyZoom(); }

    cv.addEventListener('pointerdown', function (ev) {
      pointers[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
      if (Object.keys(pointers).length >= 2) { pinchBase = pinchDist(); zoomStartK = zoomK; drag = null; panPrev = null; return; } // 二本指=ピンチ
      if (zoomed()) { panPrev = { x: ev.clientX, y: ev.clientY }; ev.preventDefault(); return; }          // ズーム中の一本指=パン
      if (!active()) return;                                                                              // ラベル無し=何もしない
      var p = framePoint(ev); if (!p) return;
      var cp = curPos(), wr = lw() / FRAME_W, hr = lh() / FRAME_H;
      if (p.x < cp.x || p.x > cp.x + wr || p.y < cp.y || p.y > cp.y + hr) return;                          // ラベル上のみ掴める
      drag = { gx: p.x - cp.x, gy: p.y - cp.y };
      try { cv.setPointerCapture(ev.pointerId); } catch (e) {}
      ev.preventDefault();
    });
    cv.addEventListener('pointermove', function (ev) {
      if (pointers[ev.pointerId]) { pointers[ev.pointerId].x = ev.clientX; pointers[ev.pointerId].y = ev.clientY; }
      if (Object.keys(pointers).length >= 2 && pinchBase) {   // 二本指=連続ズーム
        var ratio = pinchDist() / pinchBase;
        if (!zoomed() && ratio > 1.15) { cv.classList.add('cv-zoom'); zoomStartK = 1; }
        if (zoomed()) {
          zoomK = Math.min(2.8, Math.max(1, zoomStartK * ratio));
          if (zoomK <= 1 && ratio < 0.9) exitZoom(); else applyZoom();
        }
        ev.preventDefault(); return;
      }
      if (panPrev && zoomed()) {                              // 一本指パン
        panX += ev.clientX - panPrev.x; panY += ev.clientY - panPrev.y;
        panPrev = { x: ev.clientX, y: ev.clientY };
        applyZoom(); ev.preventDefault(); return;
      }
      if (!drag) return;
      var p = framePoint(ev); if (!p) return;
      fpos = { x: p.x - drag.gx, y: p.y - drag.gy };
      redraw(); // ラベルが指に追従(rAFで間引き)
      ev.preventDefault();
    });
    function endPointer(ev) {
      delete pointers[ev.pointerId];
      if (Object.keys(pointers).length < 2) pinchBase = 0;
      if (Object.keys(pointers).length === 0) panPrev = null;
      if (drag) { drag = null; persist(); redraw(); }
    }
    cv.addEventListener('pointerup', endPointer);
    cv.addEventListener('pointercancel', endPointer);
  })();

  // アカウント切替=文言(🌙⇔🌸)が変わるため再描画。
  document.addEventListener('account-changed', function () { redraw(); });

  window.Go5PromoLabel = {
    drawOverlay: drawOverlay,     // app.js drawFrame から呼ぶ(フレームへ重ね描き)
    // 作品情報が確定した時に呼ぶ(bluesky.js renderMovieInfo)。割引0%はラベル無し。
    notify: function (info) {
      if (!info || !info.title) return;
      var onSale = info.listPrice && info.price != null && info.discountPct > 0 && info.price < info.listPrice;
      lastCid = String(info.cid || info.title || '');
      pct = onSale ? info.discountPct : 0;
      updateRow(); redraw();
    },
    // 別作品の取得開始(前作の%を残さない)。
    begin: function (cid) {
      if (String(cid || '') !== lastCid) { pct = 0; updateRow(); redraw(); }
    },
    // 新規作成の起点(Go5NewMovieReset)。位置は既定へ戻す。
    clear: function () { pct = 0; fpos = null; persist(); updateRow(); redraw(); },
    nudge: nudge,
    resetPos: resetPos
  };

  updateRow();
})();
