/**
 * tests/test_promo_preflight.js
 * Node で実行できる自己完結テスト（追加パッケージ不使用）
 * 実行: node tests/test_promo_preflight.js
 *
 * 対象＝js/promo-label.js から抽出した純粋関数(canvas非依存・数値だけで動く):
 *   inkBoxOf / relLuminance / contrastRatio / localBgLuminance
 * 仕様の正本＝docs/departments/kaizen-analyst/preflight_digit-on-badge.md
 */

'use strict';

const assert = require('assert');
const { inkBoxOf, relLuminance, contrastRatio, localBgLuminance } = require('../js/promo-label.js');

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

// 幅w×高さhのRGBA(Uint8ClampedArray)グリッドを作る。fillFn(x,y) は [r,g,b,a] を返す。
function makeGrid(w, h, fillFn) {
  var data = new Uint8ClampedArray(w * h * 4);
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      var px = fillFn(x, y);
      var i = (y * w + x) * 4;
      data[i] = px[0]; data[i + 1] = px[1]; data[i + 2] = px[2]; data[i + 3] = px[3];
    }
  }
  return { data: data, width: w, height: h };
}

// ────────────────────────────────────────────────────────────
// relLuminance
// ────────────────────────────────────────────────────────────
test('L-1: 白(255,255,255)の相対輝度は1', function () {
  assert.strictEqual(relLuminance(255, 255, 255), 1);
});
test('L-2: 黒(0,0,0)の相対輝度は0', function () {
  assert.strictEqual(relLuminance(0, 0, 0), 0);
});
test('L-3: 中間色は0と1の間で単調(明るいほど大きい)', function () {
  var dark = relLuminance(50, 50, 50);
  var mid = relLuminance(128, 128, 128);
  var light = relLuminance(200, 200, 200);
  assert.ok(dark < mid && mid < light, '暗→中→明の順で輝度が増える');
  assert.ok(dark > 0 && light < 1);
});

// ────────────────────────────────────────────────────────────
// contrastRatio
// ────────────────────────────────────────────────────────────
test('C-1: 白vs黒はWCAGの最大値21:1', function () {
  assert.strictEqual(contrastRatio(1, 0), 21);
});
test('C-2: 引数の順序を入れ替えても同じ結果(順不同)', function () {
  assert.strictEqual(contrastRatio(0, 1), contrastRatio(1, 0));
});
test('C-3: 同じ輝度どうしは比1:1', function () {
  assert.strictEqual(contrastRatio(0.5, 0.5), 1);
});

// ────────────────────────────────────────────────────────────
// inkBoxOf
// ────────────────────────────────────────────────────────────
test('I-1: 明るい背景に暗いインク矩形→ink-boxを比率で正しく検出', function () {
  // 6x6グリッド。背景=明るいグレー(200,200,200)、インク=x:2-3,y:2-3の暗色(10,10,10)。
  var g = makeGrid(6, 6, function (x, y) {
    var isInk = (x >= 2 && x <= 3 && y >= 2 && y <= 3);
    return isInk ? [10, 10, 10, 255] : [200, 200, 200, 255];
  });
  var box = inkBoxOf(g, 6, 6, { x: 0, y: 0, w: 1, h: 1 });
  assert.ok(box, 'ink-boxが検出される');
  assert.strictEqual(box.x, 2 / 6);
  assert.strictEqual(box.y, 2 / 6);
  assert.strictEqual(box.w, 2 / 6);
  assert.strictEqual(box.h, 2 / 6);
});
test('I-2: regionでクロップした範囲外のインクは無視される', function () {
  // 8x8グリッド。左半分(x0-3)は背景のみ、右半分(x4-7)にインクを置く。regionは左半分のみ指定。
  var g = makeGrid(8, 8, function (x, y) {
    var isInk = (x >= 5 && x <= 6 && y >= 3 && y <= 4);
    return isInk ? [0, 0, 0, 255] : [220, 220, 220, 255];
  });
  var box = inkBoxOf(g, 8, 8, { x: 0, y: 0, w: 0.5, h: 1 }); // x:0..4 のみ探索
  assert.strictEqual(box, null, 'region外のインクは拾わない=nullになる');
});
test('I-3: alpha閾値未満(透明に近い)画素はインクとして数えない', function () {
  var g = makeGrid(6, 6, function (x, y) {
    var isFaint = (x >= 2 && x <= 3 && y >= 2 && y <= 3);
    return isFaint ? [10, 10, 10, 10] : [200, 200, 200, 255]; // alpha=10 < 既定alphaMin=24
  });
  var box = inkBoxOf(g, 6, 6, { x: 0, y: 0, w: 1, h: 1 });
  assert.strictEqual(box, null, '既定alphaMin(24)未満は無視されnullになる');
});
test('I-4: opts.alphaMinを下げれば薄い画素も拾える', function () {
  var g = makeGrid(6, 6, function (x, y) {
    var isFaint = (x >= 2 && x <= 3 && y >= 2 && y <= 3);
    return isFaint ? [10, 10, 10, 10] : [200, 200, 200, 255];
  });
  var box = inkBoxOf(g, 6, 6, { x: 0, y: 0, w: 1, h: 1 }, { alphaMin: 5 });
  assert.ok(box, 'alphaMinを下げれば検出される');
  assert.strictEqual(box.x, 2 / 6);
  assert.strictEqual(box.w, 2 / 6);
});
test('I-5: opts.bgLumaを明示すれば自動平均を使わずその値で判定する', function () {
  // 背景/インクがほぼ半々(12px/25px)のregionでは、自動平均(=領域内の平均輝度)がインク側にも
  //   背景側にも寄りすぎて両方とも閾値未満になり検出できない(下のautoBoxがその再現)。だが
  //   「本当の背景輝度」を既知の値としてopts.bgLumaに渡せば、平均に頼らず正しく検出できる。
  var W = 5, H = 5; // 25px、うち12pxがインク(48%)
  var bgRGB = [237, 237, 237], inkRGB = [214, 214, 214];
  var g = makeGrid(W, H, function (x, y) {
    var idx = y * W + x;
    return idx < 12 ? inkRGB.concat(255) : bgRGB.concat(255);
  });
  var region = { x: 0, y: 0, w: 1, h: 1 };
  var autoBox = inkBoxOf(g, W, H, region);
  assert.strictEqual(autoBox, null, '背景/インクがほぼ半々だと自動平均は差を検出できずnullになる');
  var trueBgLuma = relLuminance(bgRGB[0], bgRGB[1], bgRGB[2]);
  var explicitBox = inkBoxOf(g, W, H, region, { bgLuma: trueBgLuma });
  assert.ok(explicitBox, '既知の背景輝度を明示すれば正しく検出できる');
});
test('I-6: 輝度差がlumaDiffMin未満の画素はインクとみなさない(背景ノイズ扱い)', function () {
  var g = makeGrid(6, 6, function (x, y) {
    var isNoise = (x === 3 && y === 3);
    return isNoise ? [190, 190, 190, 255] : [200, 200, 200, 255]; // 背景とほぼ同色
  });
  var box = inkBoxOf(g, 6, 6, { x: 0, y: 0, w: 1, h: 1 });
  assert.strictEqual(box, null, 'ノイズレベルの輝度差はインク扱いしない');
});
test('I-7: 全画素が透明ならnull', function () {
  var g = makeGrid(4, 4, function () { return [0, 0, 0, 0]; });
  assert.strictEqual(inkBoxOf(g, 4, 4, { x: 0, y: 0, w: 1, h: 1 }), null);
});

// ────────────────────────────────────────────────────────────
// localBgLuminance
// ────────────────────────────────────────────────────────────
test('B-1: インク矩形の外周リングの平均輝度を返す(インク内部は除外)', function () {
  // 10x10。中央(x:4-5,y:4-5)がインク(黒)、その外側リングは一様な明るい色(220)。
  var g = makeGrid(10, 10, function (x, y) {
    var isInk = (x >= 4 && x <= 5 && y >= 4 && y <= 5);
    return isInk ? [0, 0, 0, 255] : [220, 220, 220, 255];
  });
  var ink = { x: 4 / 10, y: 4 / 10, w: 2 / 10, h: 2 / 10 };
  var bg = localBgLuminance(g, 10, 10, ink, 3);
  assert.ok(bg !== null);
  // リング部分は全て(220,220,220)なので背景輝度はrelLuminance(220,220,220)に一致するはず。
  assert.ok(Math.abs(bg - relLuminance(220, 220, 220)) < 1e-9, 'リングは一様色なので誤差なく一致');
});
test('B-2: 透明画素(下地なし)はリング平均から除外される', function () {
  // リングの半分を透明、半分を(200,200,200)にする。透明を除いた実測平均になるはず。
  var g = makeGrid(8, 8, function (x, y) {
    var isInk = (x === 3 || x === 4) && (y === 3 || y === 4);
    if (isInk) return [0, 0, 0, 255];
    var inRing = x >= 2 && x <= 5 && y >= 2 && y <= 5;
    if (inRing && x < 4) return [0, 0, 0, 0]; // リング左半分は透明
    if (inRing) return [200, 200, 200, 255];  // リング右半分は不透明
    return [0, 0, 0, 0]; // リング外も透明(範囲外)
  });
  var ink = { x: 3 / 8, y: 3 / 8, w: 2 / 8, h: 2 / 8 };
  var bg = localBgLuminance(g, 8, 8, ink, 1);
  assert.ok(bg !== null);
  assert.ok(Math.abs(bg - relLuminance(200, 200, 200)) < 1e-9, '透明画素を除いた平均になる');
});
test('B-3: inkBoxRelがnull/undefinedならnull', function () {
  var g = makeGrid(2, 2, function () { return [0, 0, 0, 255]; });
  assert.strictEqual(localBgLuminance(g, 2, 2, null), null);
});

// ────────────────────────────────────────────────────────────
// 結合: inkBoxOf + localBgLuminance + contrastRatio で「slot内に収まり・コントラスト十分」の
//   典型ケースを一気通貫で確認(P1/P3相当の判定ロジックの回帰防止)。
// ────────────────────────────────────────────────────────────
test('E-1: slot内に収まる高コントラストな数字→はみ出しなし・コントラスト比が閾値(4.5)を超える', function () {
  var w = 20, h = 20;
  var slot = { x: 0.3, y: 0.3, w: 0.4, h: 0.4 }; // x:6-13, y:6-13
  var g = makeGrid(w, h, function (x, y) {
    var isInk = (x >= 8 && x <= 10 && y >= 8 && y <= 10); // slot内に収まる暗い「インク」
    return isInk ? [20, 20, 20, 255] : [235, 235, 235, 255]; // 明るい背景
  });
  var region = { x: 0.15, y: 0.15, w: 0.7, h: 0.7 }; // slotを一回り広げた探索域
  var ink = inkBoxOf(g, w, h, region);
  assert.ok(ink, 'ink-boxが検出される');
  var fits = ink.x >= slot.x && ink.y >= slot.y &&
    (ink.x + ink.w) <= (slot.x + slot.w) && (ink.y + ink.h) <= (slot.y + slot.h);
  assert.strictEqual(fits, true, 'ink-boxはslot内に収まる');
  var bgLuma = localBgLuminance(g, w, h, ink);
  var inkLuma = relLuminance(20, 20, 20);
  var ratio = contrastRatio(inkLuma, bgLuma);
  assert.ok(ratio >= 4.5, 'コントラスト比は閾値4.5以上(実測=' + ratio + ')');
});
test('E-2: slotをはみ出す配置は fits=false になる(P1相当の検出)', function () {
  var w = 20, h = 20;
  var slot = { x: 0.3, y: 0.3, w: 0.2, h: 0.2 }; // x:6-9.9, y:6-9.9(小さいslot)
  var g = makeGrid(w, h, function (x, y) {
    var isInk = (x >= 5 && x <= 12 && y >= 5 && y <= 12); // slotよりずっと大きいインク=はみ出す
    return isInk ? [20, 20, 20, 255] : [235, 235, 235, 255];
  });
  var region = { x: 0.1, y: 0.1, w: 0.8, h: 0.8 };
  var ink = inkBoxOf(g, w, h, region);
  assert.ok(ink);
  var fits = ink.x >= slot.x && ink.y >= slot.y &&
    (ink.x + ink.w) <= (slot.x + slot.w) && (ink.y + ink.h) <= (slot.y + slot.h);
  assert.strictEqual(fits, false, 'slotより大きいインクははみ出し判定になる');
});

// ────────────────────────────────────────────────────────────
// 結果集計
// ────────────────────────────────────────────────────────────
console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');

if (failed > 0) {
  process.exit(1);
}
