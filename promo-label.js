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
      // ★onloadだけでなくdecode()完了まで待つ(仕様§4)。complete=trueでも未デコードだと
      //   drawImageが空描画になり、Canvasの数字だけが先に出る不具合の原因になる。
      im.onload = function () {
        var done = function () { im._ready = true; _composite = null; redraw(); }; // 準備完了→合成を作り直して再描画
        if (typeof im.decode === 'function') { im.decode().then(done).catch(done); }
        else { done(); }
      };
      im.onerror = function () { im._failed = true; };
      im.src = src;
      _imgCache[src] = im;
    }
    return im._failed ? null : im;
  }

  // ChatGPT分析(Chami依頼2026-07-18「セールラベル既定配置・表示設定」)に沿う既定値。
  //   スクショの現配置を参考に、漫画・メインコピー・顔を邪魔せず自然に馴染む初期値。
  // 既定サイズ: 仕様§3「ラベル幅≈13.5%」を"視認幅"で満たす scale0.72 を、実機確認を踏まえ更に-5%(仕様§8)。
  //   0.72×0.95=0.684。視認幅≈12.6%。左の集中線・「里香さん!?」への重なりを軽減。box基準13.5%(scale0.4)は
  //   縦長PNGの透明余白で視認7%=不可読のため視認基準で管理。
  var DEFAULT_SCALE = 0.684;
  var SCALE_MIN = 0.35, SCALE_MAX = 2.5;
  var LABEL_OPACITY = 0.89;   // 既定不透明度(仕様§4・89%。文字が読めるよう下げすぎない)
  // 色の馴染ませ(仕様§6-8): 金光彩/光沢/彩度を弱め、ラベルだけ浮きすぎるのを抑える近似。
  var LABEL_FILTER = 'saturate(0.92) contrast(0.96) brightness(0.98)';
  var scale = DEFAULT_SCALE;  // 大きさ倍率(SCALE_MIN〜SCALE_MAX)
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
  try { var _s = parseFloat(localStorage.getItem('promo_label_scale')); if (_s >= SCALE_MIN && _s <= SCALE_MAX) scale = _s; } catch (e) {}
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
  // 既定位置=漫画左上へ軽く重ねる(仕様§2)。左端に密着させず少し内側・メインコピーの下・顔や右のShorts UIを避ける。
  //   852×1280基準の X48/Y300 から、一体感を高めるため 右+10px・下+8px(Chami最終微調整2026-07-18)= X58/Y308。
  function defPos() { return { x: 58 / 852, y: 308 / 1280 }; }
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

  // ── ラベル合成(方式A・仕様§2/§3): テンプレPNG+数字を1枚のオフスクリーンCanvasへ焼く。
  //   これに"だけ"フェードを掛ける=数字が本体と別タイミング/別透明度で出る不具合を根絶(仕様§1/§10)。
  //   キャッシュキー=acct|type|value|src。値/アカウント/種別が変わったら作り直す(_composite=null)。
  var _composite = null, _compKey = '';
  function compositeReady_() {
    var v = tplVariant(), img = tplImg(v.src);
    if (!img || img._failed) return null;                  // PNG恒久失敗=帯フォールバックへ
    if (!(img.complete && img.naturalWidth)) return null;  // 読込前=まだ描かない(仕様§4「読込中は全体非表示」)。
    //   ※decode完了(_ready)時にonloadが_composite=nullで作り直す=万一complete先行で空焼きしても是正される。
    var key = acct() + '|' + ltype + '|' + val() + '|' + v.src;
    if (_composite && _compKey === key) return _composite;
    var off = document.createElement('canvas');
    off.width = img.naturalWidth; off.height = img.naturalHeight;
    var octx = off.getContext('2d');
    octx.clearRect(0, 0, off.width, off.height);
    octx.drawImage(img, 0, 0);                             // 本体+装飾+三日月+固定文言(PNGに焼込済)
    drawDigits(octx, tplAcct().ink, v.slot, 0, 0, off.width, off.height, String(val())); // 数字も同じ1枚へ
    _composite = off; _compKey = key;
    return off;
  }
  function invalidateComposite_() { _composite = null; _compKey = ''; }

  // app.js drawFrame から毎フレーム呼ばれる。フレーム(W×H)にラベルを重ね描き。
  //   reveal(0..1)=前景画像と同じ登場進捗(Chami依頼2026-07-18)。ラベルは"1枚の合成画像"として
  //   前景画像と同じ透明度進行でフェードイン(仕様§5)。子要素の個別アニメ・個別透明度は一切無し。
  function drawOverlay(ctx, W, H, reveal) {
    if (!active()) return;
    var rv = (typeof reveal === 'number') ? Math.max(0, Math.min(1, reveal)) : 1;
    if (rv <= 0) return; // まだ出ていない(前景画像と同じタイミングで登場)
    var sx = W / FRAME_W, sy = H / FRAME_H;
    var cp = curPos();
    var bw = lw() * sx, bh = lh() * sy, x = cp.x * W, y = cp.y * H;
    var v = tplVariant(), img = tplImg(v.src);
    var comp = compositeReady_();
    ctx.save();
    ctx.globalAlpha = rv * LABEL_OPACITY;                  // 合成1枚にだけフェード(前景画像と同一進行)×既定89%
    // ドロップシャドウ=フレームから軽く持ち上がる(仕様§5: 黒0.16・y+3・blur7・濃くしない)。合成のalpha形状に落ちる。
    ctx.shadowColor = 'rgba(0,0,0,0.16)'; ctx.shadowBlur = 7 * sx; ctx.shadowOffsetX = 0; ctx.shadowOffsetY = 3 * sy;
    if (comp) {
      // 色の馴染ませ(仕様§6-8): 彩度/コントラスト/明度を少し下げ、金光彩・光沢の浮きを抑える近似(合成全体へ均一)。
      var prevFilter = ctx.filter;
      try { ctx.filter = LABEL_FILTER; } catch (e) {}
      ctx.drawImage(comp, x, y, bw, bh);                   // 本体+数字を1単位で描画=数字だけ先行しない
      try { ctx.filter = prevFilter || 'none'; } catch (e) {}
    } else if (img && img._failed) {
      drawBand(ctx, x, y, bw, bh, sx, sy);                 // PNG恒久失敗時のみ従来の帯(帯も本体+文言が一体)
    }
    // decode未完了(comp==null かつ失敗でもない)は何も描かない=数字だけの先行表示を防ぐ(仕様§4)。
    ctx.restore();
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
  // リセット(仕様§12): 位置=既定(漫画左上の推奨)・サイズ=既定へ戻す。
  function resetPos() { if (!active()) return; fpos = null; scale = DEFAULT_SCALE; persist(); updateSizeLabel(); redraw(); }
  function updateSizeLabel() {
    var el = document.getElementById('promoSizeVal');
    if (el) el.textContent = Math.round(scale * 100) + '%';
  }
  function setScale(mult) {
    if (!active()) return;
    var ns = Math.min(SCALE_MAX, Math.max(SCALE_MIN, Math.round((scale + mult) * 100) / 100));
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
  // 二本指ピンチ = 動画に使う前景画像そのものの拡大縮小(Chami依頼2026-07-17)。
  //   ★旧実装はピンチで canvas に CSS transform を掛け、全画面オーバーレイ(cv-zoom)へ拡大していた。
  //     それは「プレビューの見た目が拡大するだけ」で書き出す動画は一切変わらない=Chamiの意図と違った。
  //     (本人談「ズームのプレビューの概念が伝え間違えてた。動画生成に用いる画像を拡大縮小させたい」)
  //     → ピンチを app.js の OFF.imgScale(描画式に入る値)へ繋ぎ替え、モーダル/パンは廃止した。
  // 一本指 = ラベルのドラッグ(従来どおり)。
  (function wirePointer() {
    var cv = document.getElementById('cv');
    if (!cv || !window.PointerEvent) return;
    var pointers = {};      // 触れているポインタ {id:{x,y}}
    var pinchBase = 0;      // ピンチ開始の2点間距離
    var scaleStart = 1;     // ピンチ開始時の画像拡大率
    var drag = null;        // ラベルドラッグ {gx,gy}=掴んだ点とラベル左上のずれ(フレーム比)

    function framePoint(ev) { // ポインタ→フレーム比(0..1)
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
    function imgScaleApi() { return window.Go5ImgScale || null; }

    cv.addEventListener('pointerdown', function (ev) {
      pointers[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
      if (Object.keys(pointers).length >= 2) {                                                             // 二本指=画像の拡大縮小
        var api = imgScaleApi();
        pinchBase = pinchDist(); scaleStart = api ? api.get() : 1; drag = null;
        return;
      }
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
      if (Object.keys(pointers).length >= 2 && pinchBase) {   // 二本指=画像の拡大縮小(動画に反映される)
        var api = imgScaleApi();
        if (api) {
          var k = scaleStart * (pinchDist() / pinchBase);
          api.set(Math.min(api.max, Math.max(api.min, k)));   // clamp+保存+再描画はapp.js側(±ボタンと同経路)
        }
        ev.preventDefault(); return;
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
      pct = 0; priceVal = 0; fpos = null; scale = DEFAULT_SCALE; // 新規動画は既定の位置・サイズから
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
