/**
 * tests/test_verify.js — Phase4 検証コアの純粋関数テスト（Node・追加パッケージ不使用）
 * 実行: node tests/test_verify.js
 */
'use strict';
const assert = require('assert');
const VC = require('../verify-core.js');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

test('V-1: buildGetPostsUrl は uris をエンコードして連結（最大25件）', function () {
  var url = VC.buildGetPostsUrl(['at://did:plc:a/app.bsky.feed.post/1', 'at://did:plc:b/app.bsky.feed.post/2']);
  assert.ok(url.indexOf('public.api.bsky.app/xrpc/app.bsky.feed.getPosts?') > -1);
  assert.ok(url.indexOf('uris=at%3A%2F%2Fdid%3Aplc%3Aa%2Fapp.bsky.feed.post%2F1') > -1, 'encoded uri1');
  assert.strictEqual((url.match(/uris=/g) || []).length, 2);
  var many = VC.buildGetPostsUrl(Array.from({ length: 40 }, function (_, i) { return 'at://x/' + i; }));
  assert.strictEqual((many.match(/uris=/g) || []).length, 25, '25件で打ち切り');
});

test('V-2: parseEngagement は uri→カウントへ', function () {
  var m = VC.parseEngagement({ posts: [
    { uri: 'at://a', likeCount: 5, repostCount: 2, replyCount: 1, quoteCount: 3 },
    { uri: 'at://b', likeCount: 0 }
  ] });
  assert.deepStrictEqual(m['at://a'], { like: 5, repost: 2, reply: 1, quote: 3 });
  assert.deepStrictEqual(m['at://b'], { like: 0, repost: 0, reply: 0, quote: 0 });
});

test('V-3: parseEngagement は空/不正でも落ちない', function () {
  assert.deepStrictEqual(VC.parseEngagement(null), {});
  assert.deepStrictEqual(VC.parseEngagement({}), {});
  assert.deepStrictEqual(VC.parseEngagement({ posts: [{}] }), {}); // uri無しは無視
});

test('V-4: postedSlotsFromState は 公開済＋post付き のみ・新しい順', function () {
  var state = { slotData: {
    'a#0': { id: 'a#0', date: '2026-06-10', slot_index: 0, status: '公開済', post_uri: 'at://1' },
    'b#1': { id: 'b#1', date: '2026-06-12', slot_index: 1, status: '公開済', post_url: 'https://x' },
    'c#0': { id: 'c#0', date: '2026-06-13', slot_index: 0, status: '未着手' },                 // 未公開→除外
    'd#0': { id: 'd#0', date: '2026-06-14', slot_index: 0, status: '公開済' }                  // post無し→除外
  } };
  var r = VC.postedSlotsFromState(state).map(function (s) { return s.id; });
  assert.deepStrictEqual(r, ['b#1', 'a#0']); // 日付の新しい順
});

test('V-5: 空stateでも空配列', function () {
  assert.deepStrictEqual(VC.postedSlotsFromState(null), []);
  assert.deepStrictEqual(VC.postedSlotsFromState({}), []);
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
