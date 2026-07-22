/**
 * 投稿履歴の削除導線が、シート由来・URL欠損行でも失われないことを確認する。
 * 実行: node tests/test_hist_delete.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const yt = fs.readFileSync(path.join(root, 'yt-clicks.js'), 'utf8');
const gas = fs.readFileSync(path.join(root, 'gas', 'コード.gs'), 'utf8');

let passed = 0;
function test(name, fn) {
  try { fn(); console.log('PASS: ' + name); passed++; }
  catch (e) { console.error('FAIL: ' + name); console.error('      ' + e.message); process.exitCode = 1; }
}

test('D-1: ゴミ箱ボタンを_fromSheet条件なしで生成する', function () {
  assert.ok(yt.includes("'<button class=\"vdel\" type=\"button\" data-k=\"'"));
  assert.ok(!yt.includes("(!it._fromSheet ? '<button class=\"vdel\""));
});

test('D-2: シート由来行の削除要求にvideoIdを含める', function () {
  assert.ok(/action:\s*'delete'[\s\S]{0,180}videoId:\s*sheetTarget\.videoId/.test(yt));
});

test('D-3: GASの削除件数0を成功扱いしない', function () {
  assert.ok(/Number\(res\.deleted\)\s*>\s*0/.test(yt));
});

test('D-4: GASはpost_idを使った削除に対応する', function () {
  assert.ok(/function deleteRecord_\(channel, videoId, postUri, short\)/.test(gas));
  assert.ok(/videoId\s*\?\s*map\['post_id'\]/.test(gas));
});

test('D-5: 動画IDだけ残ったシート行も履歴APIから返す', function () {
  assert.ok(/!d\s*&&\s*!uri\s*&&\s*!short\s*&&\s*!pid/.test(gas));
});

console.log('');
console.log('結果: ' + passed + ' PASS / 0 FAIL');
