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

  function photoEl() { return document.getElementById('photo'); }
  function acct() { return window.getCurrentAccount ? window.getCurrentAccount() : 'acc1'; }
  function labelText(pct) { return acct() === 'acc2' ? ('今だと' + pct + '%OFF🌸') : ('今なら' + pct + '%OFF🌙'); }
  function keyOf() {
    if (!orig || !lastInfo || !(lastInfo.pct > 0)) return '';
    return [lastInfo.cid, lastInfo.pct, acct(), orig.name, orig.size].join('|');
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
    var w = POS.w * sx, h = POS.h * sy;
    var x = POS.x * sx, y = POS.y * sy;
    var xMax = imgW - POS.rightMargin * sx - w; // 右端余白30〜35px(基準33px)を厳守
    if (x > xMax) x = Math.max(0, xMax);
    var r = POS.radius * Math.min(sx, sy);
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
    var fs = POS.font * sx;
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
          if (k !== keyOf()) return; // 合成中に作品/割引/口座が変わった＝この結果は破棄
          var f = new File([b], ((orig.name || 'photo').replace(/\.[^.]+$/, '')) + '_off.jpg', { type: 'image/jpeg' });
          appliedKey = k;
          setFile(f);
        }, 'image/jpeg', 0.92);
      } finally { URL.revokeObjectURL(url); }
    };
    img.onerror = function () { URL.revokeObjectURL(url); };
    img.src = url;
  }

  // 写真の変更(ユーザー選択・候補流し込み・下書き復元)=新しい原本。自分の書き戻しは除外。
  document.addEventListener('change', function (e) {
    if (!e.target || e.target.id !== 'photo' || selfSet) return;
    var p = photoEl();
    var f = p && p.files && p.files[0];
    if (!f) return;
    orig = f; appliedKey = '';
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
    clear: function () { lastInfo = null; apply(); }
  };
})();
