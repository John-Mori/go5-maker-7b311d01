'use strict';
const assert = require('assert');
const Sync = require('../core/sync.js')._test;

const left = JSON.stringify({
  'acc1|v:a': { trees: [{ id: 't1', name: 'ツリー1', postUrl: 'https://x.com/a/status/1', shortUrl: 'https://5mgl.com/a1' }], at: 10 }
});
const right = JSON.stringify({
  'acc1|v:b': { trees: [{ id: 't2', name: '続編', postUrl: 'https://bsky.app/profile/a/post/b', shortUrl: 'https://5mgl.com/b1' }], at: 20 }
});
const union = JSON.parse(Sync.mergeTreeLinks_(left, right));
assert.strictEqual(Object.keys(union).length, 2, '別履歴のツリー設定をwhole-key LWWで落とさない');

const deleted = JSON.stringify({ 'acc1|v:a': { trees: [], at: 30 } });
const afterDelete = JSON.parse(Sync.mergeTreeLinks_(left, deleted));
assert.deepStrictEqual(afterDelete['acc1|v:a'].trees, [], '新しい空配列は明示削除として残る');
assert.strictEqual(afterDelete['acc1|v:a'].at, 30);

const stale = JSON.stringify({ 'acc1|v:a': { trees: [{ id: 'old', name: '古い', postUrl: 'https://x.com/a/status/2', shortUrl: 'https://5mgl.com/old1' }], at: 5 } });
const keepNewer = JSON.parse(Sync.mergeTreeLinks_(left, stale));
assert.strictEqual(keepNewer['acc1|v:a'].trees[0].id, 't1', '古い別端末値で巻き戻さない');
console.log('PASS: tree links per-history LWW merge');
