/**
 * tests/test_scheduler.js
 * 予約スケジューラの純粋関数 dueItems を Node で検証（追加パッケージ不使用）
 * 実行: node tests/test_scheduler.js
 */
'use strict';
const assert = require('assert');
const { dueItems } = require('../scheduler.js');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

const NOW = 1000000;

test('S-1: 期限到来(pending・scheduledAtMs<=now)のみ返す', function () {
  const q = [
    { id: 1, status: 'pending', scheduledAtMs: NOW - 10 },  // 期限切れ→対象
    { id: 2, status: 'pending', scheduledAtMs: NOW },       // ちょうど→対象
    { id: 3, status: 'pending', scheduledAtMs: NOW + 10 },  // 未来→対象外
  ];
  const due = dueItems(q, NOW).map(x => x.id);
  assert.deepStrictEqual(due, [1, 2]);
});

test('S-2: pending 以外は対象外（posting/posted/error/取消）', function () {
  const q = [
    { id: 1, status: 'posting', scheduledAtMs: NOW - 10 },
    { id: 2, status: 'posted', scheduledAtMs: NOW - 10 },
    { id: 3, status: 'error', scheduledAtMs: NOW - 10 },
    { id: 4, status: 'pending', scheduledAtMs: NOW - 10 },
  ];
  assert.deepStrictEqual(dueItems(q, NOW).map(x => x.id), [4]);
});

test('S-3: 空・不正入力でも落ちない', function () {
  assert.deepStrictEqual(dueItems([], NOW), []);
  assert.deepStrictEqual(dueItems(null, NOW), []);
  assert.deepStrictEqual(dueItems([{ status: 'pending' }], NOW), []); // scheduledAtMs欠落は除外
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
