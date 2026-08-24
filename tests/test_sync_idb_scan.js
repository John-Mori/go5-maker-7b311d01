/**
 * core/sync.js が共有IndexedDB全体(ドラフト動画Blobを含む)を展開せず、同期対象prefixだけを読む門。
 */
'use strict';

var assert = require('assert');
var Sync = require('../core/sync.js')._test;

(async function () {
  var calls = [];
  var fake = {
    available: function () { return true; },
    entries: function () { throw new Error('full IDB scan must not be used'); },
    entriesByPrefixes: function (prefixes) {
      calls.push(prefixes.slice());
      return Promise.resolve({ 'ref:a': { img: 'data:image/gif;base64,AA' } });
    }
  };
  var out = await Sync.readSyncIdbEntries_(fake);
  assert.deepStrictEqual(calls, [['ref:', 'bsky:', 'post:', 'used:', 'stock:imgs:']]);
  assert.ok(out['ref:a']);

  // One failed image namespace must not discard healthy namespaces or create tombstones.
  var settledCalls = [];
  var fakeSettled = {
    available: function () { return true; },
    entriesByPrefixesSettled: function (prefixes) {
      settledCalls.push(prefixes.slice());
      return Promise.resolve({
        entries: { 'ref:new': { img: 'data:image/gif;base64,BB' } },
        failed: [{ prefix: 'bsky:', error: new Error('forced-prefix-timeout') }]
      });
    }
  };
  var partial = await Sync.readSyncIdbEntries_(fakeSettled);
  assert.deepStrictEqual(settledCalls, [['ref:', 'bsky:', 'post:', 'used:', 'stock:imgs:']]);
  assert.deepStrictEqual(partial.__go5FailedPrefixes, ['bsky:']);
  assert.ok(partial['ref:new'], 'healthy prefix data must survive a sibling timeout');

  var protectedPartial = Sync.protectUnreadIdb_(
    partial,
    { 'ref:old': { img: 'old' }, 'bsky:keep': { img: 'keep' }, 'post:healthy': { img: 'post' } },
    partial.__go5FailedPrefixes
  );
  assert.ok(protectedPartial['bsky:keep'], 'failed prefix must retain its previous snapshot');
  assert.strictEqual(protectedPartial['post:healthy'], undefined, 'healthy prefix must not be protected as unread');

  var start = JSON.stringify([{ cid: 'd_test', url: 'https://old.example/', title: 'old' }]);
  var fromCloud = JSON.stringify([{ cid: 'd_test', url: 'https://new.example/', title: 'new' }]);
  var unchanged = Sync.mergeLiveArray_(fromCloud, start, start, 'cid');
  assert.strictEqual(JSON.parse(unchanged)[0].url, 'https://new.example/',
    '同期中にローカル未変更なら雲の新URLを古いURLへ戻してはいけない');

  var editedDuringSync = JSON.stringify([{ cid: 'd_test', url: 'https://local-edit.example/', title: 'edited' }]);
  var protectedLive = Sync.mergeLiveArray_(fromCloud, editedDuringSync, start, 'cid');
  assert.strictEqual(JSON.parse(protectedLive)[0].url, 'https://local-edit.example/',
    '同期開始後のユーザー編集は最後に保護する');

  console.log('OK: unchanged local data cannot overwrite newer cloud candidate fields');
  console.log('OK: sync reads only IDB prefixes used by cloud sync');
})().catch(function (e) {
  console.error('FAIL: ' + (e && e.stack || e));
  process.exit(1);
});
