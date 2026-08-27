/**
 * tests/test_scheduler.js
 * 予約スケジューラの純粋関数 dueItems を Node で検証（追加パッケージ不使用）
 * 実行: node tests/test_scheduler.js
 */
'use strict';
const assert = require('assert');
const { dueItems, postingDayStart, splitRecentPosts, sortRecentPosts, recentCounts } = require('../js/scheduler.js');

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

test('S-4: posting day changes at local 05:00', function () {
  const before = new Date(2026, 7, 28, 4, 59, 59).getTime();
  const after = new Date(2026, 7, 28, 5, 0, 0).getTime();
  assert.strictEqual(postingDayStart(before), new Date(2026, 7, 27, 5, 0, 0).getTime());
  assert.strictEqual(postingDayStart(after), new Date(2026, 7, 28, 5, 0, 0).getTime());
});

test('S-5: recent posts split into today and yesterday at 05:00', function () {
  const now = new Date(2026, 7, 28, 12, 0, 0).getTime();
  const rows = [
    { id: 'old', publishedAt: new Date(2026, 7, 27, 4, 59, 59).getTime() },
    { id: 'y1', publishedAt: new Date(2026, 7, 27, 5, 0, 0).getTime() },
    { id: 'y2', publishedAt: new Date(2026, 7, 28, 4, 59, 59).getTime() },
    { id: 't1', publishedAt: new Date(2026, 7, 28, 5, 0, 0).getTime() }
  ];
  const result = splitRecentPosts(rows, now);
  assert.deepStrictEqual(result.today.map(x => x.id), ['t1']);
  assert.deepStrictEqual(result.yesterday.map(x => x.id), ['y1', 'y2']);
});

test('S-6: recent-post sort modes use descending metrics and keep unknown last', function () {
  const rows = [
    { id: 'a', publishedAt: 100, views: 10, pinkClicks: null, peakViews: 30 },
    { id: 'b', publishedAt: 300, views: 30, pinkClicks: 2, peakViews: null },
    { id: 'c', publishedAt: 200, views: null, pinkClicks: 9, peakViews: 50 }
  ];
  assert.deepStrictEqual(sortRecentPosts(rows, 'latest').map(x => x.id), ['b', 'c', 'a']);
  assert.deepStrictEqual(sortRecentPosts(rows, 'views').map(x => x.id), ['b', 'a', 'c']);
  assert.deepStrictEqual(sortRecentPosts(rows, 'pink').map(x => x.id), ['c', 'b', 'a']);
  assert.deepStrictEqual(sortRecentPosts(rows, 'peak').map(x => x.id), ['c', 'a', 'b']);
});

test('S-7: account counts stay mixed and totalled', function () {
  assert.deepStrictEqual(recentCounts([{ account: 'acc1' }, { account: 'acc2' }, { account: 'acc2' }]), { acc1: 1, acc2: 2, total: 3 });
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
