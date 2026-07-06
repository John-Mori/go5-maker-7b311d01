/**
 * tests/test_fanza.js
 * parseFanzaItem の単体テスト（追加パッケージ不使用）
 * 実行: node tests/test_fanza.js
 *
 * fetchFanzaInfo は外部 Worker を呼ぶため、ここではモックを使わず対象外とする。
 * Worker 側の動作確認は fanza-worker/src/index.js のコードレビューと実機デプロイで行う。
 */

'use strict';

const assert = require('assert');
const { parseFanzaItem } = require('../fanza-core.js');

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

// ────────────────────────────────────────────────────────────
// T-1 通常の割引あり（改修書サンプル: list 770 / price 385 → 50%）
// ────────────────────────────────────────────────────────────
test('T-1: list 770 / price 385 → discountPct=50', function () {
  var item = {
    content_id: 'd_784440',
    title: 'テスト作品',
    prices: { list_price: '770', price: '385' },
    iteminfo: { author: [{ id: '1', name: '作者名' }] },
    review: { count: 25, average: 4.5 }
  };
  var r = parseFanzaItem(item);
  assert.ok(r, 'result should not be null');
  assert.strictEqual(r.cid, 'd_784440');
  assert.strictEqual(r.title, 'テスト作品');
  assert.strictEqual(r.author, '作者名');
  assert.strictEqual(r.listPrice, 770);
  assert.strictEqual(r.price, 385);
  assert.strictEqual(r.discountPct, 50);
  assert.strictEqual(r.reviewCount, 25);
  assert.strictEqual(r.reviewAvg, 4.5);
  assert.ok(r.fetchedAt, 'fetchedAt should exist');
});

// ────────────────────────────────────────────────────────────
// T-2 list_price なし（定価なし品）→ discountPct=0、listPrice=null
// ────────────────────────────────────────────────────────────
test('T-2: list_price 欠落 → discountPct=0 / listPrice=null', function () {
  var item = {
    content_id: 'd_000001',
    title: '割引なし',
    prices: { price: '550' },
    iteminfo: {},
    review: { count: 10, average: 3.0 }
  };
  var r = parseFanzaItem(item);
  assert.ok(r);
  assert.strictEqual(r.listPrice, null);
  assert.strictEqual(r.price, 550);
  assert.strictEqual(r.discountPct, 0, 'discountPct should be 0 when list_price absent');
});

// ────────────────────────────────────────────────────────────
// T-3 review フィールドなし → reviewCount/reviewAvg=null、例外なし
// ────────────────────────────────────────────────────────────
test('T-3: review なし → null 安全・例外なし', function () {
  var item = {
    content_id: 'd_000002',
    title: 'レビューなし',
    prices: { list_price: '770', price: '385' },
    iteminfo: { author: [] }
  };
  var r = parseFanzaItem(item);
  assert.ok(r);
  assert.strictEqual(r.reviewCount, null);
  assert.strictEqual(r.reviewAvg, null);
  assert.strictEqual(r.discountPct, 50);
});

// ────────────────────────────────────────────────────────────
// T-4 item = null → null を返す（パニックしない）
// ────────────────────────────────────────────────────────────
test('T-4: item=null → null', function () {
  assert.strictEqual(parseFanzaItem(null), null);
  assert.strictEqual(parseFanzaItem(undefined), null);
});

// ────────────────────────────────────────────────────────────
// T-5 iteminfo.author 空配列 → author = ''
// ────────────────────────────────────────────────────────────
test('T-5: author 空 → author=""', function () {
  var item = {
    content_id: 'd_000003',
    title: '作者不明',
    prices: {},
    iteminfo: { author: [] },
    review: {}
  };
  var r = parseFanzaItem(item);
  assert.strictEqual(r.author, '');
});

// ────────────────────────────────────────────────────────────
// T-6 prices / iteminfo / review が全部 undefined → 落ちない
// ────────────────────────────────────────────────────────────
test('T-6: prices/iteminfo/review 全欠落 → 落ちない', function () {
  var item = { content_id: 'd_000004', title: '最小' };
  var r = parseFanzaItem(item);
  assert.ok(r, 'should return non-null');
  assert.strictEqual(r.listPrice, null);
  assert.strictEqual(r.price, null);
  assert.strictEqual(r.discountPct, 0);
  assert.strictEqual(r.author, '');
  assert.strictEqual(r.reviewCount, null);
  assert.strictEqual(r.reviewAvg, null);
});

// ────────────────────────────────────────────────────────────
// T-7 price > list_price（データ異常）→ discountPct=0（マイナス不可）
// ────────────────────────────────────────────────────────────
test('T-7: price > list_price → discountPct=0', function () {
  var item = {
    content_id: 'd_000005',
    title: '異常データ',
    prices: { list_price: '300', price: '500' },
    iteminfo: {},
    review: {}
  };
  var r = parseFanzaItem(item);
  assert.strictEqual(r.discountPct, 0);
});

test('F-8: 100%OFF（price=0）でも割引計算される（0円はfalsyだがセール扱い・実バグ2026-07-06）', function () {
  var item = {
    content_id: 'b062aftwk01392',
    title: '100%OFFテスト',
    prices: { list_price: '935', price: '0' },
    iteminfo: {},
    review: {}
  };
  var r = parseFanzaItem(item);
  assert.strictEqual(r.listPrice, 935);
  assert.strictEqual(r.price, 0);
  assert.strictEqual(r.discountPct, 100);
});

// ────────────────────────────────────────────────────────────
// 結果集計
// ────────────────────────────────────────────────────────────
console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
