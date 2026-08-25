'use strict';
const assert = require('assert');
const Set = require('../core/drive-set.js');

assert.strictEqual(Set.isComplete({ saved: true, hasPreview: true, hasSrc: true }), true,
  '動画・プレビュー・元画像の3点が揃った時だけ完了');
assert.strictEqual(Set.isComplete({ saved: true, hasPreview: false, hasSrc: false }), false,
  '動画だけを完了扱いしない');
assert.strictEqual(Set.isComplete({ saved: true, hasPreview: true, hasSrc: false }), false,
  '元画像欠けを完了扱いしない');
assert.strictEqual(Set.isComplete(null), false, '状態取得失敗を完了扱いしない');
assert.deepStrictEqual(Set.missing({ saved: true, hasPreview: false, hasSrc: true }), ['preview']);
assert.deepStrictEqual(Set.missing({ saved: false, hasPreview: false, hasSrc: false }), ['video', 'preview', 'source']);
console.log('All Drive three-point set tests passed.');