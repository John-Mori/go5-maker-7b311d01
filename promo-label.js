/**
 * promo-label.js — 販促ラベル(セールラベル)
 *
 * 2026-07-16 作り替え(Chami指示・指示書「セールラベル数値可変化」):
 *   Chami提供の完成デザインPNG(数字なしテンプレ)を敷き、数字だけをコードで描く。
 *   - テンプレは4種: 月詠み(acc1)×[割引率/価格] / 宵桜(acc2)×[割引率/価格]。
 *   - 固定文言(今なら/%OFF/月影に綴る/¥/作品案内…)は全てPNG側に焼き込み済み=コードでは触らない。
 *   - 数字は指示書の通り「数字領域(slot)の中央」へ。1〜3桁は幅に合わせ自動縮小。
 *   - 不正値(0/負/NaN/未設定)はラベルごと非表示。定価(セールでない)も非表示。
 *   - 数字の質感はCanvas描画で原画に合わせる(提供された数字シートは背景が焼き込みで
 *     切り出すと継ぎ目が出るため不採用。シートは local/promo-ref/ に保管=将来の精密化用)。
 *
 * 2026-07-15の設計を継承: 写真への焼き込みはせず、動画フレーム(1080×1920)への重ね描き。
 *   app.js の drawFrame() が Go5PromoLabel.drawOverlay() を呼ぶ。プレビュー=書き出し一致。
 *   位置はフレーム比(0..1)、大きさは倍率。D-pad+指ドラッグで調整、localStorageで永続。
 */
(function () {
  'use strict';
  var FRAME_W = 1080, FRAME_H = 1920;
  // 帯フォールバック用の基本寸法(テンプレPNGが読めない間のみ使用・フレーム基準)。
  var LBL = { w: 335, h: 79, font: 46, radius: 18 };

  // ── テンプレート定義 ──
  // slot = 数字を置く領域(画像内の比率)。基材PNGの画素解析で確定した値(2026-07-16):
  //   ・月詠み割引: 「今なら」(行331-436)と「%OFF」(行781-)の間の空き
  //   ・月詠み価格: 仕切り(〜754)と「作品」(995-)の間・¥の右側
  //   ・宵桜割引: 「今だと」(列〜753)と「%OFF」(列1292-)の間
  //   ・宵桜価格: 「今宵の¥」(列〜848)と「作品案内」(列1297-)の間
  // ink = 数字の色(グラデ上/下・縁・光彩)。原画の数字(クリーム金/白桜)に合わせる。
  var TEMPLATES = {
    acc1: {
      baseW: 360, aspect: 1024 / 1536,
      ink: { top: '#fff6d8', bottom: '#f0cf8a', edge: 'rgba(210,168,90,.85)', glow: 'rgba(255,224,150,.9)' },
      discount: { src: 'assets/promo/tsukuyomi-discount-base.png',
                  slot: { x: 0.332, y: 0.306, w: 0.342, h: 0.189 } },
      price:    { src: 'assets/promo/tsukuyomi-price-base.png',
                  slot: { x: 0.440, y: 0.505, w: 0.233, h: 0.140 } }
    },
    acc2: {
      baseW: 620, aspect: 2172 / 724,
      ink: { top: '#ffffff', bottom: '#f8c9d6', edge: 'rgba(214,130,150,.9)', glow: 'rgba(255,160,185,.95)' },
      discount: { src: 'assets/promo/yoizakura-discount-base.png',
                  slot: { x: 0.364, y: 0.260, w: 0.211, h: 0.490 } },
      price:    { src: 'assets/promo/yoizakura-price-base.png',
                  slot: { x: 0.405, y: 0.260, w: 0.175, h: 0.490 } }
    }
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

  var scale = 1;      // 大きさ倍率(0.6〜2.5)
  var fpos = null;    // 手動位置 {x,y}=ラベル左上のフレーム比(0..1)。null=既定(右上)
  var pct = 0;        // 割引率(セール中のみ>0)
  var priceVal = 0;   // 割引後価格(セール中のみ>0)。価格ラベルの数字
  var ltype = 'discount'; // ラベル種類 'discount'(◯%OFF) | 'price'(¥◯)
  var lastCid = '';   // 直近の作品id(begin/notifyの取り違え防止)
  // 表示ON/OFF(Chami依頼2026-07-16)。既定=ON。新規作成のリセット後もONへ戻す(clear参照)。
  // ★これはあくまで「出す気があるか」のスイッチ。セール判定(onSale)とはAND=定価の作品には
  //   チェックが入っていても出さない(Chami明示)。判定は active() に集約する。
  var enabled = true;
  try { var _e = localStorage.getItem('promo_label_enabled'); if (_e === '0') enabled = false; } catch (e) {}
  try { var _t = localStorage.getItem('promo_label_type'); if (_t === 'price') ltype = 'price'; } catch (e) {}
  try { var _s = parseFloat(localStorage.getItem('promo_label_scale')); if (_s >= 0.6 && _s <= 2.5) scale = _s; } catch (e) {}
  try { var _p = JSON.parse(localStorage.getItem('promo_label_fpos') || 'null'); if (_p && typeof _p.x === 'number' && typeof _p.y === 'number') fpos = _p; } catch (e) {}

  function acct() { return window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'; }
  function tplAcct() { return TEMPLATES[acct()] || TEMPLATES.acc1; }
  function tplVariant() { return tplAcct()[ltype] || tplAcct().discount; }
  // 表示する数字。指示書§7: 正の整数のみ(0/負/NaN/undefinedは不正=非表示)。
  function val() {
    var v = ltype === 'price' ? priceVal : pct;
    return (typeof v === 'number' && isFinite(v) && Math.floor(v) === v && v > 0) ? v : 0;
  }
  // 表示可否の唯一の判定点。val()>0 = セール中かつ値が正当(notifyがonSaleの時だけ値を入れる=定価は0)。
  // enabled = Chamiのチェックボックス。両方満たした時だけ描く。
  function active() { return enabled && val() > 0; }
  // フォールバック帯の文言(テンプレ未読込時のみ)。
  function labelText(v) {
    if (ltype === 'price') return (acct() === 'acc2' ? '今宵の¥' + v + '作品案内🌸' : '月影に綴る¥' + v + '作品🌙');
    return acct() === 'acc2' ? ('今だと' + v + '%OFF🌸') : ('今なら' + v + '%OFF🌙');
  }
  // ラベル箱の寸法(フレーム単位)。テンプレPNGが読めていれば実アスペクト、無ければ定義値/帯。
  function boxWH() {
    var t = tplAcct(), v = tplVariant();
    var w = t.baseW * scale;
    var img = tplImg(v.src);
    var asp = (img && img.naturalWidth) ? (img.naturalWidth / img.naturalHeight) : t.aspect;
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
  function drawOverlay(ctx, W, H) {
    if (!active()) return;
    var sx = W / FRAME_W;
    var cp = curPos();
    var bw = lw() * sx, bh = lh() * (H / FRAME_H), x = cp.x * W, y = cp.y * H;
    var v = tplVariant();
    var img = tplImg(v.src);
    if (img && img.complete && img.naturalWidth) {
      ctx.drawImage(img, x, y, bw, bh);              // 完成デザイン(数字なし透過PNG)
      drawDigits(ctx, tplAcct().ink, v.slot, x, y, bw, bh, String(val()));
    } else {
      drawBand(ctx, x, y, bw, bh, sx, H / FRAME_H);  // フォールバック=従来の帯
    }
  }

  // 数字だけを slot(数字領域)の中央へ描く。指示書§3.2/§6:
  //   ・slotの中心位置は固定。桁数が変わっても中央揃え(幅に収まるよう縮小のみ)。
  //   ・質感=原画の数字に合わせたグラデ+縁+光彩。フォントは近似セリフ(指示書§12の許容)。
  // ★書体(Chami指摘2026-07-17「数字がクールじゃない」): 原画の数字は Didot/Bodoni 系の
  //   ディドネ体=縦が太く横が極細のハイコントラスト。旧実装は Georgia の bold(700) で、
  //   Georgia は画面可読性重視の低コントラスト書体+太字化で細い横線が潰れる=真逆の性格。
  //   同じ札の「%OFF」(基材に焼き込み済み)が上品なセリフ体のため、数字だけ浮いていた。
  //   → ディドネ体を優先し、太字化をやめる(400)。iOS/macOSは Didot / Bodoni 72 を標準搭載
  //   =主戦場のiPhoneで原画とほぼ一致する。非搭載環境は Georgia の regular へ落ちる。
  var DIGIT_FONT = 'Didot, "Bodoni 72", "Bodoni MT", "Playfair Display", Georgia, "Times New Roman", serif';
  function drawDigits(ctx, ink, slot, x, y, bw, bh, text) {
    var zx = x + slot.x * bw, zy = y + slot.y * bh, zw = slot.w * bw, zh = slot.h * bh;
    var fs = zh;                                   // 高さ基準で開始し、幅に収める
    ctx.save();
    var setF = function () { ctx.font = '400 ' + fs + 'px ' + DIGIT_FONT; };
    setF();
    var pad = zw * 0.04;
    while (fs > zh * 0.4 && ctx.measureText(text).width > zw - pad * 2) { fs -= Math.max(1, fs * 0.04); setF(); }
    var cx = zx + zw / 2, cy = zy + zh / 2;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    var grad = ctx.createLinearGradient(0, cy - fs / 2, 0, cy + fs / 2);
    grad.addColorStop(0, ink.top); grad.addColorStop(1, ink.bottom);
    // 1) 光彩(2度描きで原画のふわっとした光に寄せる。広げすぎると枠線を跨ぐので0.18に抑える)
    ctx.shadowColor = ink.glow; ctx.shadowBlur = fs * 0.18; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 0;
    ctx.fillStyle = grad; ctx.fillText(text, cx, cy);
    ctx.shadowBlur = fs * 0.07; ctx.fillText(text, cx, cy);
    // 2) 縁(光彩なしで輪郭を締める)
    ctx.shadowColor = 'transparent';
    ctx.lineWidth = Math.max(1, fs * 0.028); ctx.strokeStyle = ink.edge; ctx.strokeText(text, cx, cy);
    ctx.restore();
  }

  // 従来の帯(テンプレPNGが読めない間のフォールバック)。
  function drawBand(ctx, x, y, w, h, sx, sy) {
    var r = LBL.radius * scale * Math.min(sx, sy);
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,.35)'; ctx.shadowBlur = 8 * sx; ctx.shadowOffsetY = 2 * sy;
    ctx.beginPath(); roundRectPath(ctx, x, y, w, h, r);
    ctx.fillStyle = 'rgba(224,37,78,.93)'; ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.lineWidth = Math.max(2, 2.5 * sx); ctx.strokeStyle = 'rgba(255,255,255,.95)'; ctx.stroke();
    var text = labelText(val());
    var fs = LBL.font * scale * sx;
    var setF = function () { ctx.font = '700 ' + fs + 'px "Noto Sans JP", sans-serif'; }; setF();
    while (fs > 20 && ctx.measureText(text).width > w - 18 * sx) { fs -= 1; setF(); }
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#fff';
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
    try { localStorage.setItem('promo_label_type', ltype); } catch (e) {}
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
    var sel = document.getElementById('promoType');
    if (sel && sel.value !== ltype) sel.value = ltype;
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
    var sel = document.getElementById('promoType');
    if (sel) {
      sel.value = ltype;
      sel.addEventListener('change', function () {
        ltype = (sel.value === 'price') ? 'price' : 'discount';
        persist(); updateRow(); redraw();
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

  // アカウント切替=テンプレ(月詠み⇔宵桜)が変わるため再描画。
  document.addEventListener('account-changed', function () { redraw(); });

  window.Go5PromoLabel = {
    drawOverlay: drawOverlay,     // app.js drawFrame から呼ぶ(フレームへ重ね描き)
    // 作品情報が確定した時に呼ぶ(bluesky.js renderMovieInfo)。セール中のみ値を保持(定価=0=非表示)。
    notify: function (info) {
      if (!info || !info.title) return;
      var onSale = info.listPrice && info.price != null && info.discountPct > 0 && info.price < info.listPrice;
      lastCid = String(info.cid || info.title || '');
      pct = onSale ? Math.round(info.discountPct) : 0;
      priceVal = onSale ? Math.round(info.price) : 0;
      updateRow(); redraw();
    },
    // 別作品の取得開始(前作の値を残さない)。
    begin: function (cid) {
      if (String(cid || '') !== lastCid) { pct = 0; priceVal = 0; updateRow(); redraw(); }
    },
    // 新規作成の起点(Go5NewMovieReset)。位置は既定へ戻す。
    // ★チェックは必ずONへ戻す(Chami指定2026-07-16「前の情報がリセットされた時もチェックを入れた状態に」)。
    //   前回OFFにしていても、新しい動画では既定のONから始まる=消し忘れでラベルが出ない事故を防ぐ。
    clear: function () {
      pct = 0; priceVal = 0; fpos = null;
      enabled = true;
      try { localStorage.setItem('promo_label_enabled', '1'); } catch (e) {}
      var en = document.getElementById('promoEnable'); if (en) en.checked = true;
      persist(); updateRow(); redraw();
    },
    nudge: nudge,
    resetPos: resetPos,
    // 検証用(テストからテンプレ+数字を素のサイズで描かせる。実機能はdrawOverlay経由)。
    _test: {
      slots: TEMPLATES,
      renderTo: function (canvas, acctId, type, value) {
        var t = TEMPLATES[acctId], v = t[type];
        var img = tplImg(v.src);
        if (!img || !img.complete || !img.naturalWidth) return false;
        canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
        var c = canvas.getContext('2d');
        c.clearRect(0, 0, canvas.width, canvas.height);
        c.drawImage(img, 0, 0);
        drawDigits(c, t.ink, v.slot, 0, 0, canvas.width, canvas.height, String(value));
        return true;
      }
    }
  };

  updateRow();
})();
