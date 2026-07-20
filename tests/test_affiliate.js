/**
 * tests/test_affiliate.js
 * Node で実行できる自己完結テスト（追加パッケージ不使用）
 * 実行: node tests/test_affiliate.js
 */

'use strict';

const assert = require('assert');
const { buildAffiliateLink, buildFanzaListLink, normalizeWorkUrl } = require('../affiliate-core.js');

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

test('T-7: Books 実URL(2階層: 数字ID/content_id) → cid=content_id・lurlは元URL全体', function () {
  const url = 'https://book.dmm.co.jp/product/6277990/b915awnmg04393/';
  const result = buildAffiliateLink(url, 'test-001');

  assert.strictEqual(result.ok, true, 'ok should be true');
  assert.strictEqual(result.cid, 'b915awnmg04393', 'cid should be content_id (2nd segment)');

  const expectedLink = 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fbook.dmm.co.jp%2Fproduct%2F6277990%2Fb915awnmg04393%2F&af_id=test-001&ch=toolbar&ch_id=link';
  assert.strictEqual(result.link, expectedLink, 'link mismatch\n  got:      ' + result.link + '\n  expected: ' + expectedLink);
});

test('T-8: Books 2階層+パラメータ付き → cid=content_id・?以降除去', function () {
  const r1 = buildAffiliateLink('https://book.dmm.co.jp/product/6277990/b915awnmg04393/?dmmref=x', 'af001');
  const r2 = buildAffiliateLink('https://book.dmm.co.jp/product/6277990/b915awnmg04393/', 'af001');
  assert.strictEqual(r1.ok, true);
  assert.strictEqual(r1.cid, 'b915awnmg04393');
  assert.strictEqual(r1.link, r2.link, 'link with params should equal link without params');
});

// ────────────────────────────────────────────────────────────
// N-1〜N-4  normalizeWorkUrl（アフィリンク→素の作品URL）
// ────────────────────────────────────────────────────────────
test('N-1: al.fanza アフィリンク → lurl の素URLへ正規化', function () {
  const aff = 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fwww.dmm.co.jp%2Fdc%2Fdoujin%2F-%2Fdetail%2F%3D%2Fcid%3Dd_748504%2F&af_id=test-001&ch=toolbar&ch_id=link';
  assert.strictEqual(normalizeWorkUrl(aff), 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/');
});
test('N-2: Booksアフィリンク → 素URLへ正規化', function () {
  const aff = 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fbook.dmm.co.jp%2Fproduct%2F6277990%2Fb915awnmg04393%2F&af_id=x&ch=toolbar&ch_id=link';
  assert.strictEqual(normalizeWorkUrl(aff), 'https://book.dmm.co.jp/product/6277990/b915awnmg04393/');
});
test('N-3: 計測パラメータ付き素URL → ?以降除去', function () {
  assert.strictEqual(normalizeWorkUrl('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/?dmmref=x#top'),
    'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_748504/');
});
test('N-4: 空/非URL → 空文字', function () {
  assert.strictEqual(normalizeWorkUrl(''), '');
  assert.strictEqual(normalizeWorkUrl('d_748504'), '');
});

test('T-9: Books .com 2階層URL → cid=content_id（旧仕様は数字ID＝API照会不可でタイトル未取得の原因）', function () {
  // ユーザー報告の実URL形（2026-07-06）: book.dmm.com でも2階層目に content_id が来る
  const r = buildAffiliateLink('https://book.dmm.com/product/4163193/b062aftwk01392/', 'test-001');
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.cid, 'b062aftwk01392', '.com 2階層でも content_id(2階層目) を cid にする');
  // 1階層だけの .com URL は従来どおり1階層目を cid に（後方互換）
  const r1 = buildAffiliateLink('https://book.dmm.com/product/4163193/', 'test-001');
  assert.strictEqual(r1.ok, true);
  assert.strictEqual(r1.cid, '4163193');
});

// ────────────────────────────────────────────────────────────
// L-1〜L-4  buildFanzaListLink（セール会場・一覧・キャンペーンページのアフィ化）
// ────────────────────────────────────────────────────────────
test('L-1: セール会場(キャンペーン)URL → cid不要で一覧リンク生成', function () {
  const url = 'https://www.dmm.co.jp/dc/doujin/-/list/=/article=campaign/id=317274/sort=sales/';
  // 作品リンク関数は cid が無いので弾く（＝UIが一覧経路へフォールバックする条件）
  assert.strictEqual(buildAffiliateLink(url, 'af001').error, 'no_cid');
  // 一覧リンク関数は成功する
  const r = buildFanzaListLink(url, 'af001');
  assert.strictEqual(r.ok, true, 'list link should succeed');
  const expected = 'https://al.fanza.co.jp/?lurl=' + encodeURIComponent(url) + '&af_id=af001&ch=toolbar&ch_id=link';
  assert.strictEqual(r.link, expected, 'link mismatch\n  got:      ' + r.link + '\n  expected: ' + expected);
});
test('L-2: 一覧URL + 計測パラメータ付き → utm等を除去して包む', function () {
  const withParam = 'https://www.dmm.co.jp/dc/doujin/-/list/=/article=campaign/id=317274/sort=sales/?utm_source=x&dmmref=y';
  const clean     = 'https://www.dmm.co.jp/dc/doujin/-/list/=/article=campaign/id=317274/sort=sales/';
  const r1 = buildFanzaListLink(withParam, 'af001');
  const r2 = buildFanzaListLink(clean,     'af001');
  assert.strictEqual(r1.ok, true);
  assert.strictEqual(r1.clean, clean, 'clean should strip ?以降');
  assert.strictEqual(r1.link, r2.link, 'param-stripped link should match clean link');
});
test('L-3: 他人のアフィリンク(al.fanza lurl包み) → 素URLを取り出し自分のaf_idで包み直す', function () {
  const others = 'https://al.fanza.co.jp/?lurl=' +
    encodeURIComponent('https://www.dmm.co.jp/dc/doujin/-/list/=/article=campaign/id=317274/') +
    '&af_id=SOMEONE_ELSE&ch=toolbar&ch_id=link';
  const r = buildFanzaListLink(others, 'MY_ID');
  assert.strictEqual(r.ok, true);
  assert.ok(r.link.includes('af_id=MY_ID'), 'should use my af_id, got: ' + r.link);
  assert.ok(!r.link.includes('SOMEONE_ELSE'), 'must not retain the other affiliate id');
  assert.strictEqual(r.clean, 'https://www.dmm.co.jp/dc/doujin/-/list/=/article=campaign/id=317274/');
});
test('L-4: 非URL → {ok:false, error:bad_url}', function () {
  assert.strictEqual(buildFanzaListLink('not a url', 'af001').error, 'bad_url');
  assert.strictEqual(buildFanzaListLink('', 'af001').error, 'empty');
});

// ────────────────────────────────────────────────────────────
// 結果集計
// ────────────────────────────────────────────────────────────
console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');

if (failed > 0) {
  process.exit(1);
}
