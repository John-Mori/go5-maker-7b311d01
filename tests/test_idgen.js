/**
 * tests/test_idgen.js
 * 安定動画ID発番・YouTube videoId抽出（idgen.js）の純粋関数を Node で検証
 * 実行: node tests/test_idgen.js
 */
'use strict';
const assert = require('assert');
const { makeVideoId, youtubeId, youtubeWatchUrl, rand4, accOfId, isTestId } = require('../idgen.js');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

// 決定的な rng（0,1/36,2/36... を順に返す）→ rand4 = '0123'
function seqRng() { let i = 0; return function () { return (i++ % 36) / 36; }; }
const D = new Date(2026, 5, 25, 14, 32); // 2026-06-25 14:32（月は0始まり）

test('ID-1: 形式 {acc}-{YYYYMMDD}-{HHMM}-{rand4}', function () {
  const id = makeVideoId('acc1', D, { rng: seqRng() });
  assert.strictEqual(id, 'acc1-20260625-1432-0123');
});

test('ID-2: テストは test- 接頭辞', function () {
  const id = makeVideoId('acc2', D, { rng: seqRng(), test: true });
  assert.strictEqual(id, 'test-acc2-20260625-1432-0123');
});

test('ID-3: 不正accは acc1 へ正規化', function () {
  assert.strictEqual(makeVideoId('xxx', D, { rng: seqRng() }), 'acc1-20260625-1432-0123');
});

test('ID-4: rand4 は base36 4桁', function () {
  for (let i = 0; i < 200; i++) assert.ok(/^[0-9a-z]{4}$/.test(rand4()));
});

test('ID-5: accOfId / isTestId 補助', function () {
  assert.strictEqual(accOfId('acc2-20260625-1432-abcd'), 'acc2');
  assert.strictEqual(accOfId('test-acc1-20260625-1432-abcd'), 'acc1');
  assert.strictEqual(isTestId('test-acc1-...'), true);
  assert.strictEqual(isTestId('acc1-...'), false);
});

test('YT-1: watch?v= から11文字ID抽出', function () {
  assert.strictEqual(youtubeId('https://www.youtube.com/watch?v=dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.strictEqual(youtubeId('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s'), 'dQw4w9WgXcQ');
});

test('YT-2: youtu.be / shorts / embed / live', function () {
  assert.strictEqual(youtubeId('https://youtu.be/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.strictEqual(youtubeId('https://www.youtube.com/shorts/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.strictEqual(youtubeId('https://www.youtube.com/embed/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
  assert.strictEqual(youtubeId('https://www.youtube.com/live/dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
});

test('YT-3: 既に11文字IDならそのまま', function () {
  assert.strictEqual(youtubeId('dQw4w9WgXcQ'), 'dQw4w9WgXcQ');
});

test('YT-4: 非YouTube/短縮URLは空（後で生URLから抽出する運用）', function () {
  assert.strictEqual(youtubeId('https://da.gd/cBcV7'), '');
  assert.strictEqual(youtubeId('https://example.com/watch?v=tooShort'), '');
  assert.strictEqual(youtubeId(''), '');
});

test('YT-5: youtubeWatchUrl は11文字IDのみ受理', function () {
  assert.strictEqual(youtubeWatchUrl('dQw4w9WgXcQ'), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
  assert.strictEqual(youtubeWatchUrl('bad'), '');
});

console.log('');
console.log('結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed > 0) process.exit(1);
