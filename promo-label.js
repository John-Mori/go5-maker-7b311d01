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
  // 帯フォールバック用の基本寸法(テンプレPNG未設置時のみ使用・フレーム基準)。
  var LBL = { w: 335, h: 79, font: 46, radius: 18 };

  // ── デコラティブ・テンプレート(Chami依頼2026-07-15) ──
  // 文字を焼き込んでいない透過PNGを背景に敷き、文字(今なら/割引率/%OFF/絵文字)はコードで描く。
  // PNGは assets/promo/ に置く(未設置なら従来の帯へ自動フォールバック=壊れない)。
  // baseW(フレーム基準の基本幅)/aspect(暫定・実PNG読込後は実アスペクト優先)/zone(文字の安全域=装飾に重ねない箱内比率)。
  // ★実アセット差し替え後に zone と baseW を微調整する前提の暫定値。
  var TEMPLATES = {
    acc1: { src: 'assets/promo/tsukuyomi.png', baseW: 360, aspect: 360 / 900, orient: 'vertical',
            lead: '今なら', tail: 'OFF', emoji: '🌙', ink: '#f3e6c0',
            zone: { x: 0.30, y: 0.10, w: 0.52, h: 0.76 } },
    acc2: { src: 'assets/promo/yoizakura.png', baseW: 620, aspect: 620 / 165, orient: 'horizontal',
            lead: '今だと', tail: '%OFF', emoji: '🌸', ink: '#fffdf6',
            zone: { x: 0.06, y: 0.20, w: 0.66, h: 0.60 } }
  };
  var _imgCache = {};
  function tplImg(src) {
    if (!src) return null;
    var im = _imgCache[src];
    if (!im) {
      im = new Image();
      im.onload = function () { redraw(); };  // 読み込めたら再描画(帯→テンプレへ切替)
      im.onerror = function () { im._failed = true; };
      im.src = src;
      _imgCache[src] = im;
    }
    return im._failed ? null : im;
  }

  var scale = 1;    // 大きさ倍率(0.6〜2.5)
  var fpos = null;  // 手動位置 {x,y}=ラベル左上のフレーム比(0..1)。null=既定(右上)
  var pct = 0;      // 現在の割引率(0=ラベル非表示)
  var lastCid = ''; // 直近の作品id(begin/notifyの取り違え防止)
  // 表示ON/OFF(Chami依頼2026-07-16)。既定=ON。新規作成のリセット後もONへ戻す(clear参照)。
  // ★これはあくまで「出す気があるか」のスイッチ。セール判定(onSale)とはAND=定価の作品には
  //   チェックが入っていても出さない(Chami明示)。判定は active() に集約する。
  var enabled = true;
  try { var _e = localStorage.getItem('promo_label_enabled'); if (_e === '0') enabled = false; } catch (e) {}

  try { var _s = parseFloat(localStorage.getItem('promo_label_scale')); if (_s >= 0.6 && _s <= 2.5) scale = _s; } catch (e) {}
  try { var _p = JSON.parse(localStorage.getItem('promo_label_fpos') || 'null'); if (_p && typeof _p.x === 'number' && typeof _p.y === 'number') fpos = _p; } catch (e) {}

  function acct() { return window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'; }
  function tpl() { return TEMPLATES[acct()] || null; }
  function labelText(p) { return acct() === 'acc2' ? ('今だと' + p + '%OFF🌸') : ('今なら' + p + '%OFF🌙'); }
  // 表示可否の唯一の判定点。pct>0 = セール中(notifyがonSaleの時だけ入れる=定価は0)。
  // enabled = Chamiのチェックボックス。両方満たした時だけ描く。
  function active() { return enabled && pct > 0; }  // discountRate null/0/NaN/未設定=非表示(0%OFF等を出さない)
  // ラベル箱の寸法(フレーム単位)。テンプレPNGが読めていれば実アスペクト、無ければ暫定/帯。
  function boxWH() {
    var t = tpl();
    var w = (t ? t.baseW : LBL.w) * scale;
    var img = t ? tplImg(t.src) : null;
    var asp = (img && img.naturalWidth) ? (img.naturalWidth / img.naturalHeight) : (t ? t.aspect : LBL.w / LBL.h);
    return { w: w, h: w / asp };
  }
  function lw() { return boxWH().w; }
  function lh() { return boxWH().h; }

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
  // テンプレPNGが読めていれば「装飾PNG＋コード描画の文字」、無ければ従来の帯。
  function drawOverlay(ctx, W, H) {
    if (!active()) return;
    var sx = W / FRAME_W, sy = H / FRAME_H;
    var cp = curPos();
    var bw = lw() * sx, bh = lh() * sy, x = cp.x * W, y = cp.y * H;
    var t = tpl();
    var img = t ? tplImg(t.src) : null;
    if (t && img && img.complete && img.naturalWidth) {
      ctx.drawImage(img, x, y, bw, bh);        // 装飾テンプレ(透過PNG・文字なし)
      drawTplText(ctx, t, x, y, bw, bh);        // 文字はここでコード描画
    } else {
      drawBand(ctx, x, y, bw, bh, sx, sy);      // フォールバック=従来の帯
    }
  }

  // 従来の帯(テンプレPNG未設置時のフォールバック。挙動は従来通り)。
  function drawBand(ctx, x, y, w, h, sx, sy) {
    var r = LBL.radius * scale * Math.min(sx, sy);
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,.35)'; ctx.shadowBlur = 8 * sx; ctx.shadowOffsetY = 2 * sy;
    ctx.beginPath(); roundRectPath(ctx, x, y, w, h, r);
    ctx.fillStyle = 'rgba(224,37,78,.93)'; ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.lineWidth = Math.max(2, 2.5 * sx); ctx.strokeStyle = 'rgba(255,255,255,.95)'; ctx.stroke();
    var text = labelText(pct);
    var fs = LBL.font * scale * sx;
    var setF = function () { ctx.font = '700 ' + fs + 'px "Noto Sans JP", sans-serif'; }; setF();
    while (fs > 20 && ctx.measureText(text).width > w - 18 * sx) { fs -= 1; setF(); }
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#fff';
    ctx.fillText(text, x + w / 2, y + h / 2 + fs * 0.04);
    ctx.restore();
  }

  // テンプレPNGの上に文字を描く。数字を最も大きく。1〜3桁ではみ出す時だけ全体を縮小(桁数自動調整)。
  // zone=装飾に重ねない安全域(箱内の比率)。文字はzone内に収める。
  function drawTplText(ctx, t, x, y, bw, bh) {
    var z = t.zone, num = String(pct);
    var zx = x + z.x * bw, zy = y + z.y * bh, zw = z.w * bw, zh = z.h * bh;
    ctx.save();
    ctx.fillStyle = t.ink;
    ctx.shadowColor = 'rgba(0,0,0,.4)'; ctx.shadowBlur = Math.max(2, zh * 0.03); ctx.shadowOffsetY = 1;
    if (t.orient === 'horizontal') {
      // 「今だと」＋大きい数字＋「%OFF」＋🌸 を1行。数字は1.5倍。ゾーン幅に収める(3桁は自動縮小)。
      var f = zh * 0.6;
      var meas = function (fB) {
        var fN = fB * 1.5;
        ctx.font = '700 ' + fB + 'px "Noto Sans JP", sans-serif';
        var wLead = ctx.measureText(t.lead).width, wTail = ctx.measureText(t.tail).width, wEmoji = ctx.measureText(t.emoji).width;
        ctx.font = '800 ' + fN + 'px "Noto Sans JP", sans-serif';
        var wNum = ctx.measureText(num).width;
        return { fN: fN, wLead: wLead, wNum: wNum, wTail: wTail, wEmoji: wEmoji,
                 total: wLead + fB * 0.12 + wNum + fB * 0.06 + wTail + fB * 0.18 + wEmoji };
      };
      var m = meas(f);
      if (m.total > zw) { f = f * zw / m.total; m = meas(f); }
      var cx = zx + Math.max(0, (zw - m.total) / 2), cy = zy + zh / 2;
      ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
      ctx.font = '700 ' + f + 'px "Noto Sans JP", sans-serif'; ctx.fillText(t.lead, cx, cy); cx += m.wLead + f * 0.12;
      ctx.font = '800 ' + m.fN + 'px "Noto Sans JP", sans-serif'; ctx.fillText(num, cx, cy); cx += m.wNum + f * 0.06;
      ctx.font = '700 ' + f + 'px "Noto Sans JP", sans-serif'; ctx.fillText(t.tail, cx, cy); cx += m.wTail + f * 0.18;
      ctx.fillText(t.emoji, cx, cy);
    } else {
      // 縦: 「今なら」を小さく縦積み → 大きい数字＋% → 「OFF」→ 🌙。ゾーン高に収める。
      var lead = t.lead.split(''), cxc = zx + zw / 2;
      var fLead = zh * 0.072, fNum = zh * 0.26, fTail = zh * 0.11, fEmoji = zh * 0.12;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      var yy = zy + fLead;
      ctx.font = '700 ' + fLead + 'px "Noto Sans JP", sans-serif';
      for (var i = 0; i < lead.length; i++) { ctx.fillText(lead[i], cxc, yy); yy += fLead * 1.18; }
      yy += fNum * 0.55;
      var fN = fNum;
      ctx.font = '800 ' + fN + 'px "Noto Sans JP", sans-serif';
      while (fN > fNum * 0.5 && ctx.measureText(num + '%').width > zw * 0.94) { fN -= 2; ctx.font = '800 ' + fN + 'px "Noto Sans JP", sans-serif'; }
      ctx.fillText(num + '%', cxc, yy); yy += fN * 0.6 + fTail * 0.6;
      ctx.font = '700 ' + fTail + 'px "Noto Sans JP", sans-serif'; ctx.fillText(t.tail, cxc, yy); yy += fTail * 0.7 + fEmoji * 0.6;
      ctx.font = '700 ' + fEmoji + 'px sans-serif'; ctx.fillText(t.emoji, cxc, yy);
    }
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
    var en = document.getElementById('promoEnable');
    if (en) {
      en.checked = enabled;
      en.addEventListener('change', function () {
        enabled = !!en.checked;
        try { localStorage.setItem('promo_label_enabled', enabled ? '1' : '0'); } catch (e) {}
        updateRow(); redraw();
      });
    }
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
    // ★チェックは必ずONへ戻す(Chami指定2026-07-16「前の情報がリセットされた時もチェックを入れた状態に」)。
    //   前回OFFにしていても、新しい動画では既定のONから始まる=消し忘れでラベルが出ない事故を防ぐ。
    clear: function () {
      pct = 0; fpos = null;
      enabled = true;
      try { localStorage.setItem('promo_label_enabled', '1'); } catch (e) {}
      var en = document.getElementById('promoEnable'); if (en) en.checked = true;
      persist(); updateRow(); redraw();
    },
    nudge: nudge,
    resetPos: resetPos
  };

  updateRow();
})();
