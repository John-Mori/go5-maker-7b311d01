'use strict';

var assert = require('assert');
var mod = require('../candidates.js');
var usable = mod.usableCandidatePrefetch_;

assert.strictEqual(usable(null), false);
assert.strictEqual(usable({ done: false, info: { title: 'pending' }, errored: false }), false);
assert.strictEqual(usable({ done: true, info: null, errored: true }), false);
assert.strictEqual(usable({ done: true, info: { __error: true }, errored: true }), false);
assert.strictEqual(usable({ done: true, info: { title: 'ok' }, errored: false }), true);

console.log('PASS: failed candidate prefetch is retried on add');
