/**
 * tests/test_record_upsert.js
 * 記録コントラクトの upsert 行選択ロジックを Node で検証。
 * ※ gas/コード.gs の upsertRowOf_ と「同一仕様」（GASはNode require不可のためミラーを定義）。
 *    どちらかを変えたら両方を揃えること。
 * 実行: node tests/test_record_upsert.js
 */
'use strict';
const assert = require('assert');

// --- gas/コード.gs:upsertRowOf_ のミラー（仕様を固定する） ---
// post_id 列の値配列(2行目以降の1次元配列)と videoId から、upsert 先の行番号(2始まり)を返す。
// 一致が無ければ 0。videoId 空なら 0（=従来の空行再利用/追記へフォールバック）。
function upsertRowOf_(postIdCol, videoId) {
  if (!videoId) return 0;
  for (let j = 0; j < postIdCol.length; j++) { if (String(postIdCol[j]) === String(videoId)) return j + 2; }
  return 0;
}

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

const VID = 'acc1-20260625-1432-0123';

test('U-1: 同一videoIdがあればその行(2始まり)を返す', function () {
  // 2行目='other', 3行目=VID → 行番号3
  assert.strictEqual(upsertRowOf_(['other', VID, 'x'], VID), 3);
});

test('U-2: 先頭(2行目)一致は 2', function () {
  assert.strictEqual(upsertRowOf_([VID, 'a', 'b'], VID), 2);
});

test('U-3: 一致が無ければ 0（=新規/空行へ）', function () {
  assert.strictEqual(upsertRowOf_(['a', 'b', 'c'], VID), 0);
});

test('U-4: videoId 空は常に 0（後方互換＝従来動作）', function () {
  assert.strictEqual(upsertRowOf_([VID, 'a'], ''), 0);
  assert.strictEqual(upsertRowOf_([VID, 'a'], null), 0);
  assert.strictEqual(upsertRowOf_([VID, 'a'], undefined), 0);
});

test('U-5: 空シート(列なし)でも落ちず 0', function () {
  assert.strictEqual(upsertRowOf_([], VID), 0);
});

test('U-6: 数値混入でも文字列比較で一致', function () {
  assert.strictEqual(upsertRowOf_([123, VID], VID), 3);
  assert.strictEqual(upsertRowOf_([123], '123'), 2);
});

console.log('\n結果: ' + passed + ' PASS / ' + failed + ' FAIL');
if (failed) process.exit(1);
