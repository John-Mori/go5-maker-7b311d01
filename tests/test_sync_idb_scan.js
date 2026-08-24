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

  var lsWithOldCandidate = { cand_items: JSON.stringify([{ cid: 'old', title: 'LS正本' }]) };
  Sync.mergeCandListMirrorsIntoLs_(lsWithOldCandidate, {
    'meta:candlist:cand_items': [{ cid: 'new', title: 'IDBだけの新規候補' }, { cid: 'old', title: '(タイトル未取得)' }]
  });
  var mergedCandidates = JSON.parse(lsWithOldCandidate.cand_items);
  assert.strictEqual(mergedCandidates.length, 2, 'LS満杯時にIDBだけへ保存された候補も同期対象へ合流する');
  assert.strictEqual(mergedCandidates.filter(function (it) { return it.cid === 'old'; })[0].title, 'LS正本',
    '古いIDBミラーでLS側の既存候補を巻き戻さない');

  var directReads = [];
  var directMirror = {
    available: function () { return true; },
    entriesByPrefixes: function () { throw new Error('candidate mirrors must not depend on an image prefix scan'); },
    getResult: function (key) {
      directReads.push(key);
      var rows = key === 'meta:candlist:cand_items'
        ? [{ cid: 'main-new', title: 'メイン候補' }]
        : [{ cid: 'books-new', title: '独立タブ候補' }];
      return Promise.resolve({ ok: true, value: rows });
    }
  };
  var directOut = await Sync.readKnownCandListMirrors_(directMirror, {
    cand_items: '[]',
    cand_tabs: JSON.stringify([{ id: 'books', name: 'ブックス' }])
  });
  assert.deepStrictEqual(directReads, ['meta:candlist:cand_items', 'meta:candlist:cand_items__books']);
  assert.strictEqual(directOut['meta:candlist:cand_items'][0].cid, 'main-new',
    '候補リストは大量画像cursorと独立して直接取得する');

  var fallbackWrite = null;
  var fallbackOk = await Sync.writeCandListFallback_({
    available: function () { return true; },
    set: function (key, value) { fallbackWrite = { key: key, value: value }; return Promise.resolve(); }
  }, 'cand_items', JSON.stringify([{ cid: 'received-new' }]));
  assert.strictEqual(fallbackOk, true);
  assert.strictEqual(fallbackWrite.key, 'meta:candlist:cand_items');
  assert.strictEqual(fallbackWrite.value[0].cid, 'received-new',
    'LS満杯の受信端末は候補配列をIDBミラーへ着地できる');
  assert.strictEqual(await Sync.writeCandListFallback_({ available: function () { return true; }, set: function () {} }, 'cand_items', '{bad'), false);

  console.log('OK: unchanged local data cannot overwrite newer cloud candidate fields');
  console.log('OK: sync reads only IDB prefixes used by cloud sync');
})().catch(function (e) {
  console.error('FAIL: ' + (e && e.stack || e));
  process.exit(1);
});
