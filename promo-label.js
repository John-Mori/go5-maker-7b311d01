/**
 * promo-label.js — 販促ラベル自動合成(Chami依頼2026-07-13)
 * 元写真の最上段コマ右上へ「今なら◯%OFF🌙(月詠み)/今だと◯%OFF🌸(宵桜)」の小さなラベルを1つ焼き込む。
 * 位置・大きさはChami指定: 852×1280基準でラベル左上(550,300)・幅264×高さ62・文字36px太字・右端余白33px。
 * %OFFの数値は作品情報(discountPct)から自動挿入。割引が無い作品はラベル無し(焼いてあれば原本へ戻す)。
 *
 * 仕組み: #photoのFileを「原本」として保持し、割引が確定した時点で原本から合成し直して#photoへ書き戻す。
 * 動画キャンバス・プレビュー・Bluesky添付・Drive保存は全てphoto.files[0]を読むため、1箇所の焼き込みで
 * 全経路に反映される。常に原本から焼くので二重貼りは起きない。書き戻しはBluesky側のcompressFileが
 * 1MB以下へ再圧縮するためサイズ超過の心配も無い。
 */
(function () {
  'use strict';
  var BASE_W = 852, BASE_H = 1280;
  var POS = { x: 550, y: 300, w: 264, h: 62, font: 36, rightMargin: 33, radius: 14 };
  var orig = null;        // ラベル無しの原本File(常にここから焼く=二重貼り防止)
  var lastInfo = null;    // 直近で確定した作品情報 {cid, pct}
  var appliedKey = '';    // 今photoに焼いてある内容のキー('' = 原本のまま)
  var selfSet = false;    // 自分の書き戻しで発火したchangeを原本扱いしないためのフラグ
  var posOv = null;       // 手動調整の位置(852×1280基準の左上{x,y})。写真を替えたらリセット
  var scale = 1;          // ラベルの大きさ倍率(Chami依頼2026-07-15・0.6〜2.5)。localStorageで永続
  try { var _s = parseFloat(localStorage.getItem('promo_label_scale')); if (_s >= 0.6 && _s <= 2.5) scale = _s; } catch (e) {}
  function lw() { return POS.w * scale; }  // 現在の倍率でのラベル幅(852基準)
  function lh() { return POS.h * scale; }  // 現在の倍率でのラベル高(852基準)

  function photoEl() { return document.getElementById('photo'); }
  function acct() { return window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'; }
  function labelText(pct) { return acct() === 'acc2' ? ('今だと' + pct + '%OFF🌸') : ('今なら' + pct + '%OFF🌙'); }
  function keyOf() {
    if (!orig || !lastInfo || !(lastInfo.pct > 0)) return '';
    var p = posOv ? Math.round(posOv.x) + ',' + Math.round(posOv.y) : 'def';
    return [lastInfo.cid, lastInfo.pct, acct(), orig.name, orig.size, p, scale].join('|');
  }

  // 現在のラベル位置(852×1280基準の左上)。手動調整があればそれ、無ければ既定+右余白クランプ。
  // 手動時のクランプは緩め=端からはみ出す位置まで許可(「画像内でしか動かせない」の解消・Chami依頼2026-07-15)。
  // 完全に消えないよう、幅・高さの一部は画像内に残す。
  function basisPos() {
    if (posOv) {
      var w = lw(), h = lh();
      return {
        x: Math.min(Math.max(-w * 0.7, posOv.x), BASE_W - w * 0.3),
        y: Math.min(Math.max(-h * 0.7, posOv.y), BASE_H - h * 0.3)
      };
    }
    var x = Math.min(POS.x, BASE_W - POS.rightMargin - lw()); // 右端余白30〜35px(基準33px)を厳守
    return { x: Math.max(0, x), y: POS.y };
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

  function drawLabel(ctx, imgW, imgH, pct) {
    var sx = imgW / BASE_W, sy = imgH / BASE_H;
    var bp = basisPos();
    var w = POS.w * scale * sx, h = POS.h * scale * sy;
    var x = bp.x * sx, y = bp.y * sy;
    var r = POS.radius * scale * Math.min(sx, sy);
    ctx.save();
    // 帯: 赤ピンクの角丸+白フチ+薄い影。(窓背景の白でも読める濃度・メインコピーより明確に小さい)
    ctx.shadowColor = 'rgba(0,0,0,.35)'; ctx.shadowBlur = 8 * sx; ctx.shadowOffsetY = 2 * sy;
    ctx.beginPath();
    roundRectPath(ctx, x, y, w, h, r);
    ctx.fillStyle = 'rgba(224,37,78,.93)';
    ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.lineWidth = Math.max(2, 2.5 * sx); ctx.strokeStyle = 'rgba(255,255,255,.95)'; ctx.stroke();
    // 文字: 白の太字(基準36px=指定34〜38pxの中央)。はみ出す場合だけ縮小。
    var text = labelText(pct);
    var fs = POS.font * scale * sx;
    var setF = function () { ctx.font = '700 ' + fs + 'px "Noto Sans JP", sans-serif'; };
    setF();
    while (fs > 20 && ctx.measureText(text).width > w - 18 * sx) { fs -= 1; setF(); }
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#fff';
    ctx.fillText(text, x + w / 2, y + h / 2 + fs * 0.04);
    ctx.restore();
  }

  function setFile(f) {
    var p = photoEl(); if (!p) return;
    try {
      var dt = new DataTransfer(); dt.items.add(f);
      selfSet = true;
      p.files = dt.files;
      p.dispatchEvent(new Event('change', { bubbles: true })); // 通常経路でfgImg/プレビュー/投稿添付へ反映
    } catch (e) {}
    selfSet = false; // dispatchEventは同期＝リスナー消化後にここへ戻る
  }

  function apply() {
    var k = keyOf();
    if (!k) {
      // 割引なし・情報未確定・原本なし: 焼いた状態なら原本へ戻す(作品を替えたら前作のラベルを残さない)
      if (appliedKey && orig) { appliedKey = ''; setFile(orig); }
      updateRow();
      return;
    }
    if (k === appliedKey) return; // 同内容は焼き直さない(無限ループ・無駄な再描画防止)
    var url = URL.createObjectURL(orig);
    var img = new Image();
    img.onload = function () {
      try {
        var c = document.createElement('canvas');
        c.width = img.naturalWidth; c.height = img.naturalHeight;
        var ctx = c.getContext('2d');
        ctx.drawImage(img, 0, 0);
        drawLabel(ctx, c.width, c.height, lastInfo.pct);
        c.toBlob(function (b) {
          if (!b) return;
          if (k !== keyOf()) return; // 合成中に作品/割引/口座/位置が変わった＝この結果は破棄
          var f = new File([b], ((orig.name || 'photo').replace(/\.[^.]+$/, '')) + '_off.jpg', { type: 'image/jpeg' });
          appliedKey = k;
          setFile(f);
          updateRow();
        }, 'image/jpeg', 0.92);
      } finally { URL.revokeObjectURL(url); }
    };
    img.onerror = function () { URL.revokeObjectURL(url); };
    img.src = url;
  }

  // ---- 位置の手動調整: ボタン+プレビュードラッグ(Chami依頼2026-07-14・両対応) ----
  var bakeTimer = null;
  function scheduleBake() { // ボタン連打・ドラッグ確定をまとめて1回で焼き直す
    if (bakeTimer) clearTimeout(bakeTimer);
    bakeTimer = setTimeout(function () { bakeTimer = null; apply(); }, 250);
  }
  function nudge(dx, dy) {
    if (!appliedKey) return; // ラベルが出ていない時は動かすものが無い
    var bp = basisPos();
    posOv = { x: bp.x + dx, y: bp.y + dy };
    scheduleBake();
  }
  function resetPos() { if (!appliedKey) return; posOv = null; scheduleBake(); }
  function updateSizeLabel() {
    var el = document.getElementById('promoSizeVal');
    if (el) el.textContent = Math.round(scale * 100) + '%';
  }
  function setScale(mult) {
    if (!appliedKey) return; // ラベルが出ていない時は変えるものが無い
    var ns = Math.min(2.5, Math.max(0.6, Math.round((scale + mult) * 100) / 100));
    if (ns === scale) return;
    scale = ns;
    try { localStorage.setItem('promo_label_scale', String(scale)); } catch (e) {}
    updateSizeLabel();
    scheduleBake();
  }
  function updateRow() { // 調整UIはラベルが焼かれている時だけ出す。ドラッグ中のスクロール暴発も防ぐ
    var row = document.getElementById('promoPosRow');
    if (row) row.hidden = !appliedKey;
    updateSizeLabel();
    var pw = document.querySelector('.preview-wrap');
    if (pw) pw.classList.toggle('has-dpad', !!appliedKey); // D-pad分の横余白を確保(真横並べ)
    var cv = document.getElementById('cv');
    if (cv) cv.style.touchAction = appliedKey ? 'none' : '';
  }
  (function wireButtons() {
    var map = { promoPosL: [-12, 0], promoPosR: [12, 0], promoPosU: [0, -12], promoPosD: [0, 12] };
    Object.keys(map).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('click', function () { nudge(map[id][0], map[id][1]); });
    });
    var rs = document.getElementById('promoPosReset');
    if (rs) rs.addEventListener('click', resetPos);
    var sm = document.getElementById('promoSizeMinus'); if (sm) sm.addEventListener('click', function () { setScale(-0.1); });
    var sp = document.getElementById('promoSizePlus'); if (sp) sp.addEventListener('click', function () { setScale(0.1); });
    updateSizeLabel();
  })();

  // プレビュー(canvas#cv)のラベルを指/マウスで直接ドラッグ。掴めるのはラベルの上だけ。
  // ドラッグ中は破線ゴーストで移動先を表示し、離した位置で原本から焼き直す。
  (function wireDrag() {
    var cv = document.getElementById('cv');
    if (!cv || !window.PointerEvent) return;
    var drag = null;  // {gx,gy}=掴んだ点とラベル左上のずれ(基準座標)
    var ghost = null;
    function basisPoint(ev) { // ポインタ位置→852×1280基準座標。写真の外ならnull
      var R = window.Go5PhotoRect ? window.Go5PhotoRect() : null;
      if (!R) return null;
      var b = cv.getBoundingClientRect();
      if (!b.width || !b.height) return null;
      var px = (ev.clientX - b.left) * (R.cvW / b.width);
      var py = (ev.clientY - b.top) * (R.cvH / b.height);
      var ix = (px - R.x) / R.w * R.imgW, iy = (py - R.y) / R.h * R.imgH;
      if (ix < 0 || iy < 0 || ix > R.imgW || iy > R.imgH) return null;
      return { x: ix * BASE_W / R.imgW, y: iy * BASE_H / R.imgH };
    }
    function ghostShow(bp) {
      var R = window.Go5PhotoRect ? window.Go5PhotoRect() : null;
      if (!R) return;
      var b = cv.getBoundingClientRect();
      var sx = b.width / R.cvW, sy = b.height / R.cvH; // canvas内部px→画面CSSpx
      var cx = R.x + (bp.x * R.imgW / BASE_W) * R.w / R.imgW;
      var cy = R.y + (bp.y * R.imgH / BASE_H) * R.h / R.imgH;
      var cw = (POS.w * scale * R.imgW / BASE_W) * R.w / R.imgW;
      var ch = (POS.h * scale * R.imgH / BASE_H) * R.h / R.imgH;
      if (!ghost) {
        ghost = document.createElement('div');
        ghost.style.cssText = 'position:fixed;pointer-events:none;z-index:9999;border:2px dashed #fff;background:rgba(224,37,78,.55);border-radius:8px;box-shadow:0 0 0 1px rgba(0,0,0,.4);';
        document.body.appendChild(ghost);
      }
      ghost.style.left = (b.left + cx * sx) + 'px';
      ghost.style.top = (b.top + cy * sy) + 'px';
      ghost.style.width = (cw * sx) + 'px';
      ghost.style.height = (ch * sy) + 'px';
      ghost.hidden = false;
    }
    function ghostHide() { if (ghost) ghost.hidden = true; }
    // ズーム=二本指ピンチ(Chami指定2026-07-15「タップではなく二本指」)。1本指=ラベルのドラッグ。
    var pointers = {};   // 現在触れているポインタ {id:{x,y}}
    var pinchBase = 0;   // ピンチ開始時の2点間距離
    function pinchDist() {
      var ids = Object.keys(pointers);
      if (ids.length < 2) return 0;
      var a = pointers[ids[0]], b = pointers[ids[1]];
      return Math.hypot(a.x - b.x, a.y - b.y);
    }
    cv.addEventListener('pointerdown', function (ev) {
      pointers[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
      if (Object.keys(pointers).length >= 2) {          // 二本指=ピンチ開始(ラベルドラッグは中断)
        pinchBase = pinchDist();
        if (drag) { drag = null; ghostHide(); }
        return;
      }
      if (!appliedKey) return;                          // ラベル無し=掴む対象なし
      var p = basisPoint(ev);
      if (!p) return;
      var cur = basisPos();
      if (p.x < cur.x || p.x > cur.x + lw() || p.y < cur.y || p.y > cur.y + lh()) return; // ラベル上のみ掴める
      drag = { gx: p.x - cur.x, gy: p.y - cur.y };
      try { cv.setPointerCapture(ev.pointerId); } catch (e) {}
      ghostShow(cur);
      ev.preventDefault();
    });
    cv.addEventListener('pointermove', function (ev) {
      if (pointers[ev.pointerId]) { pointers[ev.pointerId].x = ev.clientX; pointers[ev.pointerId].y = ev.clientY; }
      if (Object.keys(pointers).length >= 2 && pinchBase) { // ピンチ中=距離比で拡大/縮小
        var d = pinchDist();
        if (d) {
          if (d / pinchBase > 1.2) cv.classList.add('cv-zoom');
          else if (d / pinchBase < 0.83) cv.classList.remove('cv-zoom');
        }
        ev.preventDefault();
        return;
      }
      if (!drag) return;
      var p = basisPoint(ev);
      if (!p) return;
      posOv = { x: p.x - drag.gx, y: p.y - drag.gy };
      ghostShow(basisPos()); // クランプ後の実位置を表示
      ev.preventDefault();
    });
    function endPointer(ev) {
      delete pointers[ev.pointerId];
      if (Object.keys(pointers).length < 2) pinchBase = 0;
      if (drag) { drag = null; ghostHide(); apply(); } // 離した位置で焼き直し
    }
    cv.addEventListener('pointerup', endPointer);
    cv.addEventListener('pointercancel', endPointer);
  })();

  // 写真の変更(ユーザー選択・候補流し込み・下書き復元)=新しい原本。自分の書き戻しは除外。
  document.addEventListener('change', function (e) {
    if (!e.target || e.target.id !== 'photo' || selfSet) return;
    var p = photoEl();
    var f = p && p.files && p.files[0];
    if (!f) return;
    orig = f; appliedKey = ''; posOv = null; // 新しい写真=位置調整もやり直し(画像の内容次第のため)
    updateRow();
    apply(); // 割引が既に確定していれば即焼き込み(写真が情報より後に来た場合)
  }, true);

  // アカウント切替=文言が変わる(🌙⇔🌸)ため焼き直し。
  document.addEventListener('account-changed', function () { apply(); });

  window.Go5PromoLabel = {
    // 作品情報が確定した時に呼ぶ。(bluesky.js renderMovieInfo)割引0%はラベル無し扱い。
    notify: function (info) {
      if (!info || !info.title) return;
      var onSale = info.listPrice && info.price != null && info.discountPct > 0 && info.price < info.listPrice;
      lastInfo = { cid: String(info.cid || info.title || ''), pct: onSale ? info.discountPct : 0 };
      apply();
    },
    // 別作品の取得を始める時に呼ぶ。(前作の%で焼かない・取得失敗時に前作ラベルを残さない)
    begin: function (cid) {
      if (lastInfo && lastInfo.cid !== String(cid || '')) { lastInfo = null; apply(); }
    },
    // 新規作成の起点で呼ぶ。(Go5NewMovieReset)
    clear: function () { lastInfo = null; posOv = null; apply(); },
    // 位置調整(ボタンUIと同じ動き。デバッグ・外部利用向け)
    nudge: nudge,
    resetPos: resetPos
  };
})();
