/**
 * tests/test_affiliate.js
 * Node で実行できる自己完結テスト（追加パッケージ不使用）
 * 実行: node tests/test_affiliate.js
 */

'use strict';

const assert = require('assert');
const { buildAffiliateLink } = require('../affiliate-core.js');

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
// T-1 完全一致テスト
// ────────────────────────────────────────────────────────────
test('T-1: 典型的なURL + アフィID → cid・link完全一致', function () {
  const url = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/?dmmref=ListSales&i3_ref=list&i3_ord=1';
  const afId = 'test-001';
  const result = buildAffiliateLink(url, afId);

  assert.strictEqual(result.ok, true, 'ok should be true');
  assert.strictEqual(result.cid, 'd_748504', 'cid mismatch');

  const expectedLink = 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fwww.dmm.co.jp%2Fdc%2Fdoujin%2F-%2Fdetail%2F%3D%2Fcid%3Dd_748504%2F&af_id=test-001&ch=toolbar&ch_id=link';
  assert.strictEqual(result.link, expectedLink, 'link mismatch\n  got:      ' + result.link + '\n  expected: ' + expectedLink);
});

// ────────────────────────────────────────────────────────────
// T-2 末尾スラッシュあり
// ────────────────────────────────────────────────────────────
test('T-2: 末尾スラッシュあり → cid=d_768597、テンプレ通りリンク', function () {
  const url = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_768597/';
  const result = buildAffiliateLink(url, 'test-001');

  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.cid, 'd_768597');
  assert.ok(result.link.startsWith('https://al.fanza.co.jp/?lurl='), 'link should start with al.fanza');
  assert.ok(result.link.includes('&af_id=test-001'), 'link should contain af_id');
  assert.ok(result.link.includes('&ch=toolbar&ch_id=link'), 'link should contain ch params');
});

// ────────────────────────────────────────────────────────────
// T-3 末尾スラッシュなし → T-2 と同一リンク
// ────────────────────────────────────────────────────────────
test('T-3: 末尾スラッシュなし → T-2 と同一リンク', function () {
  const urlWith    = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_768597/';
  const urlWithout = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_768597';
  const r1 = buildAffiliateLink(urlWith,    'test-001');
  const r2 = buildAffiliateLink(urlWithout, 'test-001');

  assert.strictEqual(r1.ok, true);
  assert.strictEqual(r2.ok, true);
  assert.strictEqual(r1.link, r2.link, 'links should be identical with or without trailing slash');
});

// ────────────────────────────────────────────────────────────
// T-4 cid= を含まないURL → no_cid
// ────────────────────────────────────────────────────────────
test('T-4: cid= を含まないURL → {ok:false, error:no_cid}', function () {
  const result = buildAffiliateLink('https://www.dmm.co.jp/mono/pcgame/-/list/=/');
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.error, 'no_cid');
});

// ────────────────────────────────────────────────────────────
// 追加エッジケース
// ────────────────────────────────────────────────────────────
test('Edge: 空文字 → {ok:false, error:empty}', function () {
  const result = buildAffiliateLink('');
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.error, 'empty');
});

test('Edge: undefined → {ok:false, error:empty}', function () {
  const result = buildAffiliateLink(undefined);
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.error, 'empty');
});

test('Edge: ftp://...cid=x → {ok:false, error:bad_url}', function () {
  const result = buildAffiliateLink('ftp://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_123456/');
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.error, 'bad_url');
});

test('Edge: cid=d_748504&x=y → cidは d_748504 のみ（&以降除外）', function () {
  const result = buildAffiliateLink('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504&x=y');
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.cid, 'd_748504');
});

test('Edge: afId空 → af_id=【アフィID】', function () {
  const result = buildAffiliateLink('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/', '');
  assert.strictEqual(result.ok, true);
  assert.ok(result.link.includes('af_id=%E3%80%90%E3%82%A2%E3%83%95%E3%82%A3ID%E3%80%91') ||
            result.link.includes('af_id=【アフィID】'),
    'link should contain 【アフィID】, got: ' + result.link);
});

test('Edge: afId未指定（undefined）→ af_id=【アフィID】', function () {
  const result = buildAffiliateLink('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/');
  assert.strictEqual(result.ok, true);
  assert.ok(result.link.includes('af_id=【アフィID】'),
    'link should contain af_id=【アフィID】, got: ' + result.link);
});

test('Edge: 計測パラメータ付きURL → ?以降除去して処理', function () {
  const urlWithParam = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/?dmmref=ListSales&i3_ref=list';
  const urlClean     = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/';
  const r1 = buildAffiliateLink(urlWithParam, 'af001');
  const r2 = buildAffiliateLink(urlClean,     'af001');
  assert.strictEqual(r1.ok, true);
  assert.strictEqual(r1.link, r2.link, 'link with params should equal link without params');
});

// ────────────────────────────────────────────────────────────
// T-5 / T-6  FANZA Books
// ────────────────────────────────────────────────────────────
test('T-5: Books URL → 商品ID抽出・リンク生成', function () {
  const url = 'https://book.dmm.co.jp/product/4148691/';
  const result = buildAffiliateLink(url, 'test-001');

  assert.strictEqual(result.ok, true, 'ok should be true');
  assert.strictEqual(result.cid, '4148691', 'cid mismatch');

  const expectedLink = 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fbook.dmm.co.jp%2Fproduct%2F4148691%2F&af_id=test-001&ch=toolbar&ch_id=link';
  assert.strictEqual(result.link, expectedLink, 'link mismatch\n  got:      ' + result.link + '\n  expected: ' + expectedLink);
});

test('T-6: Books URL パラメータ付き → ?以降除去してリンク生成', function () {
  const url = 'https://book.dmm.co.jp/product/4148691/?dmmref=something';
  const result = buildAffiliateLink(url, 'test-001');

  assert.strictEqual(result.ok, true, 'ok should be true');
  assert.strictEqual(result.cid, '4148691', 'cid mismatch');

  const expectedLink = 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fbook.dmm.co.jp%2Fproduct%2F4148691%2F&af_id=test-001&ch=toolbar&ch_id=link';
  assert.strictEqual(result.link, expectedLink, 'link mismatch\n  got:      ' + result.link + '\n  expected: ' + expectedLink);
});

// ────────────────────────────────────────────────────────────
// 結果集計
// ────────────────────────────────────────────────────────────
console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');

if (failed > 0) {
  process.exit(1);
}
