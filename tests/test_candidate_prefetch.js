'use strict';

var assert = require('assert');
var mod = require('../js/candidates.js');
var usable = mod.usableCandidatePrefetch_;
var modalIsOpen = mod.modalIsOpen_;

assert.strictEqual(usable(null), false);
assert.strictEqual(usable({ done: false, info: { title: 'pending' }, errored: false }), false);
assert.strictEqual(usable({ done: true, info: null, errored: true }), false);
assert.strictEqual(usable({ done: true, info: { __error: true }, errored: true }), false);
assert.strictEqual(usable({ done: true, info: { title: 'ok' }, errored: false }), true);

// 追加モーダルは閉じてもDOMに残る。祖先overlay.hidden=trueなら入力中として扱わない。
assert.strictEqual(modalIsOpen(null), false);
assert.strictEqual(modalIsOpen({ closest: function () { return { hidden: true }; } }), false);
assert.strictEqual(modalIsOpen({ closest: function () { return { hidden: false }; } }), true);
assert.strictEqual(modalIsOpen({ parentNode: { hidden: true } }), false);

console.log('PASS: candidate prefetch retry and modal visibility guards');
