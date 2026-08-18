/**
 * tests/test_promo_digit_sheet.js
 * Node で実行できる自己完結テスト（追加パッケージ不使用）
 * 実行: node tests/test_promo_digit_sheet.js
 *
 * 対象＝js/promo-label.js の layoutDigitGlyphs（純粋関数・canvas非依存）。
 *   お手本シート(0〜9)から各桁のグリフ矩形を切り出し、slot内へ中央揃えで並べる
 *   配置(drawImage引数)を計算するだけの関数。実描画(drawDigitsFromSheet)はctx依存のためここでは対象外。
 * 仕様の経緯＝2026-08-18 Chami依頼「販促ラベルの数字をシステムフォントでなくお手本シート切り出しに」。
 */

'use strict';

const assert = require('assert');
const { layoutDigitGlyphs, TEMPLATES } = require('../js/promo-label.js');

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log('PASS: ' + name);
    passed++;
  } catch (e) {
    console.log('FAIL: ' + name);
    console.log('      ' + e.message);
    failed++;
  }
}

// 宵桜シート相当のダミー定義(実アセットと同じ形。幅は桁ごとに違う=可変幅の検証に使う)。
const SHEET = {
  cellY: 0.4, cellH: 0.2,
  glyphs: [
    { x: 0.00, w: 0.10 }, // 0
    { x: 0.10, w: 0.06 }, // 1(細い)
    { x: 0.16, w: 0.10 }, // 2
    { x: 0.26, w: 0.10 }, // 3
    { x: 0.36, w: 0.10 }, // 4
    { x: 0.46, w: 0.10 }, // 5
    { x: 0.56, w: 0.10 }, // 6
    { x: 0.66, w: 0.08 }, // 7
    { x: 0.74, w: 0.10 }, // 8
    { x: 0.84, w: 0.10 }  // 9
  ]
};
const NATURAL = { w: 1000, h: 500 };

test('D-1: 1文字ぶんの配置を1件返す', function () {
  var box = { x: 100, y: 200, w: 300, h: 60 };
  var out = layoutDigitGlyphs(SHEET, NATURAL, box, '7');
  assert.strictEqual(out.length, 1);
});

test('D-2: 桁数ぶんの配置を返す(可変幅=細い"1"と太い"8"で幅が違う)', function () {
  var box = { x: 0, y: 0, w: 1000, h: 100 };
  var out = layoutDigitGlyphs(SHEET, NATURAL, box, '18');
  assert.strictEqual(out.length, 2);
  assert.ok(out[0].dw < out[1].dw, '"1"は"8"より細いので描画幅も狭い(可変幅が反映される)');
});

test('D-3: 中央揃え(box中心と配置全体の中心が一致)', function () {
  var box = { x: 50, y: 0, w: 400, h: 80 };
  var out = layoutDigitGlyphs(SHEET, NATURAL, box, '99');
  var left = out[0].dx, right = out[out.length - 1].dx + out[out.length - 1].dw;
  var groupCenter = (left + right) / 2;
  var boxCenter = box.x + box.w / 2;
  assert.ok(Math.abs(groupCenter - boxCenter) < 1e-6, 'グループ中心とbox中心がほぼ一致');
});

test('D-4: 高さいっぱいに収まる時はbox.hがそのまま描画高さになる(幅に余裕あり)', function () {
  var box = { x: 0, y: 0, w: 1000, h: 50 };
  var out = layoutDigitGlyphs(SHEET, NATURAL, box, '7');
  assert.ok(Math.abs(out[0].dh - box.h) < 1e-6);
});

test('D-5: 幅に収まらない時は縮小され、結果の全幅がbox幅(-左右余白)を超えない', function () {
  var box = { x: 0, y: 0, w: 60, h: 1000 }; // 高さ基準だと幅が全く足りないケース
  var out = layoutDigitGlyphs(SHEET, NATURAL, box, '99');
  var left = out[0].dx, right = out[out.length - 1].dx + out[out.length - 1].dw;
  assert.ok(right - left <= box.w + 1e-6, '縮小後の全幅がboxを超えない(実測=' + (right - left) + ' box.w=' + box.w + ')');
});

test('D-6: 数字以外の文字を含むと空配列(呼び出し側でフォールバックさせる契約)', function () {
  var box = { x: 0, y: 0, w: 300, h: 60 };
  assert.deepStrictEqual(layoutDigitGlyphs(SHEET, NATURAL, box, '7a'), []);
  assert.deepStrictEqual(layoutDigitGlyphs(SHEET, NATURAL, box, '¥10'), []);
});

test('D-7: 空文字は空配列', function () {
  var box = { x: 0, y: 0, w: 300, h: 60 };
  assert.deepStrictEqual(layoutDigitGlyphs(SHEET, NATURAL, box, ''), []);
});

test('D-8: source矩形(sx,sy,sw,sh)はシートの比率×natural寸法どおり(切り出し座標の正しさ)', function () {
  var box = { x: 0, y: 0, w: 1000, h: 100 };
  var out = layoutDigitGlyphs(SHEET, NATURAL, box, '3');
  var g = SHEET.glyphs[3];
  assert.strictEqual(out[0].sx, g.x * NATURAL.w);
  assert.strictEqual(out[0].sw, g.w * NATURAL.w);
  assert.strictEqual(out[0].sy, SHEET.cellY * NATURAL.h);
  assert.strictEqual(out[0].sh, SHEET.cellH * NATURAL.h);
});

test('D-9: 複数桁はdx(描画x)が左から右へ単調増加(重ならず並ぶ)', function () {
  var box = { x: 0, y: 0, w: 1000, h: 80 };
  var out = layoutDigitGlyphs(SHEET, NATURAL, box, '1099');
  assert.strictEqual(out.length, 4);
  for (var i = 1; i < out.length; i++) {
    assert.ok(out[i].dx >= out[i - 1].dx + out[i - 1].dw, '桁' + i + 'が前の桁と重ならない');
  }
});

// ── 月詠み(acc1)の実テンプレ検査 ────────────────────────────────
//   2026-08-18 AD研究室ルカ代行発注(REQ-research-room-43292a14fc「7がへにょへにょ」)で月詠みも
//   digitSheet化。ここは実際に配線した TEMPLATES.acc1.digitSheet を検査する=空PASS禁止:
//   ①未配線なら M-1 で落ちる ②座標を打ち間違え/acc2(1536x1024)の座標を流用すると
//   桁が重なる or シートからはみ出す→ M-3/M-5 で落ちる。
// 月詠みシート実画素サイズ(assets/promo/tsukuyomi-digits.png・PIL実測)。
const TSU_SHEET_NATURAL = { w: 2172, h: 724 };

test('M-1: acc1にdigitSheet(0〜9の10グリフ)が配線されている', function () {
  assert.ok(TEMPLATES && TEMPLATES.acc1, 'TEMPLATES.acc1 が公開されている');
  var ds = TEMPLATES.acc1.digitSheet;
  assert.ok(ds, 'acc1.digitSheet が存在する(未配線ならここで落ちる)');
  assert.strictEqual(ds.src, 'assets/promo/tsukuyomi-digits.png');
  assert.strictEqual(ds.glyphs.length, 10, '0〜9の10グリフ');
});

test('M-2: cellY/cellH とグリフ座標がすべて 0..1 の範囲に収まる', function () {
  var ds = TEMPLATES.acc1.digitSheet;
  assert.ok(ds.cellY >= 0 && ds.cellH > 0 && ds.cellY + ds.cellH <= 1, '帯がシート内に収まる');
  ds.glyphs.forEach(function (g, i) {
    assert.ok(g.x >= 0 && g.w > 0 && g.x + g.w <= 1, '桁' + i + ' がシート幅内に収まる');
  });
});

test('M-3: グリフは左→右へ重ならず単調に並ぶ(座標の打ち間違い/流用を検出)', function () {
  var gs = TEMPLATES.acc1.digitSheet.glyphs;
  for (var i = 1; i < gs.length; i++) {
    assert.ok(gs[i].x >= gs[i - 1].x + gs[i - 1].w,
      '桁' + i + ' の左端(' + gs[i].x + ')が前の桁の右端(' + (gs[i - 1].x + gs[i - 1].w) + ')以降にある');
  }
});

test('M-4: "1"が最も細い(月詠みシートの実測特徴=誤テンプレ検出の目印)', function () {
  var gs = TEMPLATES.acc1.digitSheet.glyphs;
  var one = gs[1].w;
  for (var i = 0; i < gs.length; i++) {
    if (i === 1) continue;
    assert.ok(gs[i].w > one, '桁' + i + '(' + gs[i].w + ') は "1"(' + one + ') より太い');
  }
});

test('M-5: 実テンプレ+実画素サイズで切り出すと source矩形がシート内に収まる("70"で検証)', function () {
  var ds = TEMPLATES.acc1.digitSheet;
  var box = { x: 100, y: 200, w: 400, h: 120 };
  var out = layoutDigitGlyphs(ds, TSU_SHEET_NATURAL, box, '70');
  assert.strictEqual(out.length, 2);
  out.forEach(function (p) {
    assert.ok(p.sx >= 0 && p.sx + p.sw <= TSU_SHEET_NATURAL.w + 1e-6, 'sx+sw がシート幅(2172)内');
    assert.ok(p.sy >= 0 && p.sy + p.sh <= TSU_SHEET_NATURAL.h + 1e-6, 'sy+sh がシート高(724)内');
  });
  assert.ok(out[1].dx >= out[0].dx + out[0].dw, '"7""0"が重ならず並ぶ');
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');

if (failed > 0) {
  process.exit(1);
}
