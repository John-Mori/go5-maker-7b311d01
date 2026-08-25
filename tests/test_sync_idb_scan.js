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

  var fastRemote = {
    fmt: 2,
    ls: {
      cand_items: { t: 200, v: JSON.stringify([{ cid: 'old', title: '雲の完全な題名', addedAt: 1 }]) },
      unrelated_setting: { t: 10, v: 'keep-me' }
    },
    idb: { 'ref:keep': { t: 10, v: { img: { __img: 'abc' } } } }
  };
  var fastMerged = Sync.fastCandidateMergeState_({
    cand_items: JSON.stringify([
      { cid: 'old', title: '(タイトル未取得)', addedAt: 1 },
      { cid: 'new-before-image-scan', title: 'PC新規候補', addedAt: 2 }
    ])
  }, fastRemote, { 'ls:cand_items': 100 }, 300);
  var fastRows = JSON.parse(fastMerged.state.ls.cand_items.v);
  assert.strictEqual(fastMerged.changed, true, '雲に無いPC新規候補は画像走査前のpush対象になる');
  assert.strictEqual(fastRows.length, 2);
  assert.strictEqual(fastRows.filter(function (it) { return it.cid === 'old'; })[0].title, '雲の完全な題名',
    '雲側が新しい時はローカルの未取得題名で完全な題名を巻き戻さない');
  assert.strictEqual(fastMerged.state.ls.unrelated_setting.v, 'keep-me', '高速レールは候補以外の雲設定を保持する');
  assert.deepStrictEqual(fastMerged.state.idb, fastRemote.idb, '高速レールは雲画像参照をそのまま保持する');

  var fastReceive = Sync.fastCandidateMergeState_({ cand_items: '[]' }, {
    fmt: 2,
    ls: { cand_items: { t: 500, v: JSON.stringify([{ cid: 'phone-new', title: 'スマホへ即表示', addedAt: 5 }]) } },
    idb: {}
  }, { 'ls:cand_items': 100 }, 600);
  assert.strictEqual(JSON.parse(fastReceive.mergedLs.cand_items)[0].cid, 'phone-new',
    '受信側は画像prefix走査なしで雲の新規候補をローカル適用できる');

  var reorderedReceive = Sync.fastCandidateMergeState_({
    cand_items: JSON.stringify([{ cid: 'old', title: '既存', addedAt: 1 }])
  }, {
    fmt: 2,
    ls: { cand_items: { t: 500, v: JSON.stringify([
      { cid: 'phone-new', title: 'スマホへ即表示', addedAt: 5 },
      { cid: 'old', title: '既存', addedAt: 1 }
    ]) } }, idb: {}
  }, { 'ls:cand_items': 100 }, 600);
  assert.strictEqual(reorderedReceive.changed, false,
    '同じ候補行の並び順だけが違う場合は不要なpushを行わない');
  assert.strictEqual(JSON.parse(reorderedReceive.mergedLs.cand_items)[0].cid, 'phone-new',
    '受信時は新しい雲側の並び順を維持する');
  console.log('OK: unchanged local data cannot overwrite newer cloud candidate fields');
  console.log('OK: sync reads only IDB prefixes used by cloud sync');
})().catch(function (e) {
  console.error('FAIL: ' + (e && e.stack || e));
  process.exit(1);
});
