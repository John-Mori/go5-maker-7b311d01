/**
 * 画像復旧は裏で続けるが、画面を塞ぐ固定通知は二度と出さないための静的回帰テスト。
 * 実行: node tests/test_idb_hint_gate.js
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'js', 'candidates.js'), 'utf8');

assert.ok(!src.includes('idbRecoveryHint'), '固定通知のDOMを作らない');
assert.ok(!src.includes("retry.textContent = '今すぐ再試行'"), '固定通知の手動再試行ボタンを復活させない');
assert.ok(!src.includes('画像の読み込みを自動で再試行しています。'), '固定通知文を復活させない');
assert.ok(src.includes('scheduleCandidateHydrateRetry_();'), '候補画像の自動再試行は維持する');
assert.ok(src.includes('retryVisibleHistoryImages_();'), '投稿履歴画像の自動再試行は維持する');
assert.ok(src.includes("document.addEventListener('visibilitychange'"), 'タブ復帰時の自動再試行は維持する');

console.log('PASS: 画像復旧は通知なし・AIなしで自動継続する');
