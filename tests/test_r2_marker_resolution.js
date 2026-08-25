'use strict';
const assert = require('assert');
const C = require('../js/candidates.js');
const marker = { __r2n: 2, at: 1 };
assert.strictEqual(C.shouldResolveR2Marker_('cid1', false, marker, marker), true,
  'R2マーカー自体がメモリに先着しても実画像取得を開始する');
assert.strictEqual(C.shouldResolveR2Marker_('cid1', false, { imgs: ['data:image/png;base64,AA'] }, marker), false,
  '実画像がメモリにあれば再取得しない');
assert.strictEqual(C.shouldResolveR2Marker_('cid1', true, marker, marker), false,
  '同じR2取得が進行中なら多重発射しない');
assert.strictEqual(C.shouldResolveR2Marker_('', false, marker, marker), false, 'cid無しは発射しない');
console.log('All R2 marker resolution tests passed.');