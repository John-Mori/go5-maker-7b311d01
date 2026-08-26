'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

class MemoryStorage {
  constructor() { this.map = new Map(); }
  get length() { return this.map.size; }
  key(i) { return Array.from(this.map.keys())[i] || null; }
  getItem(k) { return this.map.has(String(k)) ? this.map.get(String(k)) : null; }
  setItem(k, v) { this.map.set(String(k), String(v)); }
  removeItem(k) { this.map.delete(String(k)); }
}

global.localStorage = new MemoryStorage();
global.Go5Sync = {
  getConfig: function () { return { url: 'https://sync.example.test', token: 't', hasPass: true }; },
  syncImageManifestNow: function () { return Promise.resolve({ ok: true }); }
};

const Cdn = require('../core/image-cdn.js');
const Sync = require('../core/sync.js')._test;

const H1 = '1'.repeat(64);
const H2 = '2'.repeat(64);

assert.deepStrictEqual(Cdn._test.validRec({ keys: [H1], prev: 2, at: 10 }), { keys: [H1], prev: 2, at: 10 });
assert.strictEqual(Cdn._test.validRec({ keys: ['bad'], at: 1 }), null);
assert.strictEqual(Cdn._test.recId('ref', 'abc'), 'ref:abc');
assert.deepStrictEqual(
  Cdn._test.urlsForRec({ keys: [H1, H2], prev: 0, at: 1 }, 'https://cdn.example/'),
  ['https://cdn.example/img/' + H1, 'https://cdn.example/img/' + H2]
);
assert.strictEqual(Cdn._test.hashFromDirectUrl('https://sync.example.test/img/' + H1 + '?x=1'), H1);

const local = JSON.stringify({
  'ref:a': { keys: [H1], prev: 0, at: 100 },
  'used:x': { keys: [H1], prev: 1, at: 100 }
});
const remote = JSON.stringify({
  'ref:b': { keys: [H2], prev: 0, at: 110 },
  'used:x': { keys: [H2], prev: 2, at: 120 }
});
const merged = JSON.parse(Sync.mergeImageManifest_(local, remote));
assert.deepStrictEqual(Object.keys(merged).sort(), ['ref:a', 'ref:b', 'used:x']);
assert.deepStrictEqual(merged['used:x'], { keys: [H2], prev: 2, at: 120 });

const deletionWins = Sync.chooseImageManifestRec_(
  { keys: [H1], prev: 0, at: 200 },
  { keys: [], prev: 0, at: 200 }
);
assert.deepStrictEqual(deletionWins.keys, [], 'an equal-time deletion must not be resurrected by a stale upload');

const fast = Sync.fastCandidateMergeState_(
  { go5_image_manifest_v1: local },
  { fmt: 2, ls: { go5_image_manifest_v1: { t: 120, v: remote }, unrelated: { t: 1, v: 'keep' } }, idb: { 'ref:old': { t: 1, v: {} } } },
  { 'ls:go5_image_manifest_v1': 100 },
  300
);
const fastManifest = JSON.parse(fast.mergedLs.go5_image_manifest_v1);
assert.ok(fastManifest['ref:a'] && fastManifest['ref:b']);
assert.strictEqual(fast.state.ls.unrelated.v, 'keep');
assert.ok(fast.state.idb['ref:old']);

const root = path.resolve(__dirname, '..');
['index.html', 'KouhoLists.html', 'StockLists.html', 'Stock.html', 'analytics.html'].forEach(function (name) {
  const html = fs.readFileSync(path.join(root, name), 'utf8');
  const syncAt = html.indexOf('core/sync.js');
  const cdnAt = html.indexOf('core/image-cdn.js');
  assert.ok(syncAt >= 0 && cdnAt > syncAt, name + ' must load image-cdn after sync');
});

const candidates = fs.readFileSync(path.join(root, 'js/candidates.js'), 'utf8');
assert.ok(candidates.includes("imageCdnPick_('ref'"));
assert.ok(candidates.includes("imageCdnPick_('post'"));
assert.ok(candidates.includes("imageCdnPick_('used'"));
assert.ok(candidates.includes("imageCdnMirror_('ref'"));
assert.ok(candidates.includes("go5-image-manifest-changed"));

console.log('OK: direct image manifest/CDN path and per-record merge');
