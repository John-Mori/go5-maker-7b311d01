'use strict';
const assert = require('assert');
const Sync = require('../core/sync.js')._test;

const key = 'yt:deepnight01';
const oldApi = JSON.stringify({
  [key]: { autoMs: 1000, autoAt: 10, autoSource: 'publishedAt', privacy: 'public' }
});
const newApi = JSON.stringify({
  [key]: { autoMs: 2000, autoAt: 20, autoSource: 'publishedAt', privacy: 'public' }
});
let merged = JSON.parse(Sync.mergeHistoryPostTimes_(oldApi, newApi));
assert.strictEqual(merged[key].autoMs, 2000, '新しいAPI観測時刻を採る');

const manualOnOtherDevice = JSON.stringify({
  [key]: { autoMs: 1000, autoAt: 10, autoSource: 'publishedAt', privacy: 'public', manualMs: 3000, manualAt: 30 }
});
merged = JSON.parse(Sync.mergeHistoryPostTimes_(newApi, manualOnOtherDevice));
assert.strictEqual(merged[key].autoMs, 2000, 'APIの新しい観測を保持する');
assert.strictEqual(merged[key].manualMs, 3000, '別端末の手動時刻も保持する');

const reset = JSON.stringify({
  [key]: { autoMs: 2000, autoAt: 20, autoSource: 'publishedAt', privacy: 'public', manualMs: 3000, manualAt: 30, resetAt: 40 }
});
const staleManual = JSON.stringify({
  [key]: { autoMs: 1000, autoAt: 10, autoSource: 'publishedAt', privacy: 'public', manualMs: 3500, manualAt: 35 }
});
merged = JSON.parse(Sync.mergeHistoryPostTimes_(reset, staleManual));
assert.strictEqual(merged[key].resetAt, 40, '新しい解除時計を保持する');
assert.strictEqual(merged[key].manualAt, 35, '履歴は保持して比較できる');
assert.ok(merged[key].resetAt > merged[key].manualAt, '古い手動指定を復活させない');

const other = JSON.stringify({
  'yt:otherrow001': { autoMs: 4000, autoAt: 50, autoSource: 'publishAt', privacy: 'private' }
});
merged = JSON.parse(Sync.mergeHistoryPostTimes_(reset, other));
assert.deepStrictEqual(Object.keys(merged).sort(), [key, 'yt:otherrow001'].sort(), '別動画の日時をwhole-key上書きで落とさない');
assert.strictEqual(merged['yt:otherrow001'].autoSource, 'publishAt');

console.log('PASS: history post time per-video clocks merge');
