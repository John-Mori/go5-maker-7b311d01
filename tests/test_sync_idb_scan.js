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
