/**
 * tests/test_hist_merge.js — 投稿履歴「シート由来・表示専用マージ」の純粋関数テスト(Node)
 * 実行: node tests/test_hist_merge.js
 */
'use strict';
const assert = require('assert');
const HM = require('../hist-merge-core.js');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

test('H-1: ローカル空 → シート由来の行がすべて表示専用アイテムとして出る', function () {
  var sheet = [
    { postUri: 'at://a/1', title: '作品A', postedAt: '2026-07-20T10:00:00.000Z', shortUrl: 'https://5mgl.com/x1', youtubeUrl: 'https://youtu.be/AAA' },
    { videoId: 'acc1-20260719-0100-abcd', title: '作品B', postedAt: '2026-07-19T01:00:00.000Z', youtubeUrl: 'https://youtu.be/BBB' }
  ];
  var extra = HM.mergeSheetExtras([], sheet);
  assert.strictEqual(extra.length, 2);
  assert.ok(extra.every(function (x) { return x._fromSheet === true; }), '全件に_fromSheetバッジが付く');
  assert.strictEqual(extra[0].ytUrl, 'https://youtu.be/AAA', 'youtubeUrl→ytUrlへ変換');
  assert.strictEqual(extra[1].videoId, 'acc1-20260719-0100-abcd');
});

test('H-2: postUri一致のローカル行があれば重複させない(ローカル優先)', function () {
  var local = [{ postUri: 'at://a/1', title: 'ローカル版' }];
  var sheet = [{ postUri: 'at://a/1', title: 'シート版', postedAt: '2026-07-20T10:00:00.000Z' }];
  var extra = HM.mergeSheetExtras(local, sheet);
  assert.strictEqual(extra.length, 0, 'postUriが一致するので追加しない');
});

test('H-3: postUriが無い行はvideoId一致で重複排除', function () {
  var local = [{ videoId: 'acc2-20260718-0900-zzzz' }];
  var sheet = [{ videoId: 'acc2-20260718-0900-zzzz', title: '重複するはず' }, { videoId: 'acc2-new-0001', title: '新規' }];
  var extra = HM.mergeSheetExtras(local, sheet);
  assert.strictEqual(extra.length, 1);
  assert.strictEqual(extra[0].videoId, 'acc2-new-0001');
});

test('H-4: postUriもvideoIdも無いシート行は安全側でスキップ(重複判定不能)', function () {
  var extra = HM.mergeSheetExtras([], [{ title: '識別子なし', shortUrl: 'https://5mgl.com/x' }]);
  assert.strictEqual(extra.length, 0);
});

test('H-5: シート内自己重複(同一postUriが2行)も1件に畳む', function () {
  var sheet = [
    { postUri: 'at://a/1', title: '1回目' },
    { postUri: 'at://a/1', title: '2回目(重複)' }
  ];
  var extra = HM.mergeSheetExtras([], sheet);
  assert.strictEqual(extra.length, 1);
});

test('H-6: null/undefined/不正入力でも例外を投げず空配列', function () {
  assert.deepStrictEqual(HM.mergeSheetExtras(null, null), []);
  assert.deepStrictEqual(HM.mergeSheetExtras(undefined, undefined), []);
  assert.deepStrictEqual(HM.mergeSheetExtras([], [null, undefined, {}]), []);
});

test('H-7: シートの作品cidを表示用の作品URLへ復元する', function () {
  var item = HM._toDisplayItem({ cid: 'd_test001' });
  assert.strictEqual(item.cid, 'd_test001');
  assert.strictEqual(item.workUrl, 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_test001/');
  assert.strictEqual(HM._toDisplayItem({ cid: '12345' }).workUrl, 'https://book.dmm.com/product/12345/');
});

test('H-8: 商品URLとアフィリエイトURLから作品cidを抽出する', function () {
  assert.strictEqual(HM.workCidFromUrl('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_test001/'), 'd_test001');
  assert.strictEqual(HM.workCidFromUrl('https://book.dmm.com/product/12345/'), '12345');
  var inner = encodeURIComponent('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_test002/');
  assert.strictEqual(HM.workCidFromUrl('https://al.fanza.co.jp/?lurl=' + inner), 'd_test002');
});

test('H-9: history再読込は同一videoIdかつ編集値の反映後だけ成功と判定する', function () {
  var rows = [{ videoId: 'acc1-1', cid: 'd_old', youtubeUrl: '', workState: '旧作' }];
  var expected = { videoId: 'acc1-1', workUrl: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_new/', workState: '旧作' };
  assert.strictEqual(HM.historyHasEdit(rows, expected), false, '反映前のcidは失敗');
  rows[0].cid = 'd_new';
  assert.strictEqual(HM.historyHasEdit(rows, expected), true, '反映後のcidは成功');
  assert.strictEqual(HM.historyHasEdit([{ videoId: 'acc2-1', cid: 'd_new', workState: '旧作' }], expected), false, '別行は成功扱いしない');
});

test('H-10: 履歴単位の使用画像があれば候補画像を混ぜない', function () {
  var got = HM.historyUsedImages(['used-1'], ['candidate-1', 'candidate-2']);
  assert.deepStrictEqual(got, ['used-1']);
});

test('H-11: 旧履歴の互換表示でも候補画像は先頭1枚だけに限定する', function () {
  var got = HM.historyUsedImages([], ['legacy-used', 'unused-candidate']);
  assert.deepStrictEqual(got, ['legacy-used']);
});

test('H-12: 使用画像を明示的に空にした履歴では旧候補画像を復活させない', function () {
  assert.deepStrictEqual(HM.historyUsedImages([], ['legacy-candidate'], true), []);
});

test('H-13: 投稿URI・短縮URLが無いシート行も動画IDで一意に識別する', function () {
  assert.strictEqual(HM.historyItemKey({ videoId: 'acc1-20260723-1200-abcd' }), 'v:acc1-20260723-1200-abcd');
});

test('H-14: 履歴キーは投稿URI→短縮URL→動画IDの優先順を守る', function () {
  assert.strictEqual(HM.historyItemKey({ postUri: 'at://post/1', shortUrl: 'https://s/1', videoId: 'vid-1' }), 'u:at://post/1');
  assert.strictEqual(HM.historyItemKey({ shortUrl: 'https://s/1', videoId: 'vid-1' }), 's:https://s/1');
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
