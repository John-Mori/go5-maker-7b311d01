/**
 * tests/test_image_role.js — 画像の役割判定 core/image-role.js(Go5ImageRole)の純粋関数テスト(Node)
 * 実行: node tests/test_image_role.js
 *
 * 何を縛るか(2026-08-23・C-038 画像取り違えの恒久ガード):
 *   Chami報告「生成に使った画像がプレビュー扱いされる」の再発を止める。判定が画面ごとに散っていたのを
 *   このファイルへ1本化したので、位置ベース/明示タグ/ファイル名ベースの各契約を実行で通し、
 *   ★とりわけ「index>=prevCount の元画像を preview と呼ばない」「prevCount=0 なら preview は0枚」を固定する。
 *   ここが壊れる(元画像をpreviewへ倒す)実装に戻したらテストがFAILする=must-fail。
 */
'use strict';
const assert = require('assert');
const R = require('../core/image-role.js');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

// --- a) 位置ベース(used レコード = {imgs, prev}) ---
test('I-1: index<prevCount は preview / index>=prevCount は source(取り違えの核心)', function () {
  assert.strictEqual(R.imageRole({ index: 0, prevCount: 1 }), 'preview');
  assert.strictEqual(R.imageRole({ index: 1, prevCount: 1 }), 'source', 'prev枚を超えた最初の1枚は元画像');
  assert.strictEqual(R.imageRole({ index: 2, prevCount: 1 }), 'source');
  assert.strictEqual(R.imageRole({ index: 1, prevCount: 2 }), 'preview', '境界の内側はpreview');
});

test('I-2: prevCount=0(プレビュー未取得)は 全部 source=previewは1枚も出ない(Chami報告の場面)', function () {
  assert.strictEqual(R.imageRole({ index: 0, prevCount: 0 }), 'source');
  assert.deepStrictEqual(R.previewImages(['a', 'b', 'c'], 0), [], 'prev=0でpreviewは空');
  assert.deepStrictEqual(R.sourceImages(['a', 'b', 'c'], 0), ['a', 'b', 'c'], 'prev=0で全部が元画像');
});

test('I-3: inUsed:false は位置に関係なく attachment', function () {
  assert.strictEqual(R.imageRole({ index: 0, prevCount: 3, inUsed: false }), 'attachment');
});

test('I-4: index<0 は attachment', function () {
  assert.strictEqual(R.imageRole({ index: -1, prevCount: 2 }), 'attachment');
});

// --- b) 明示タグ ---
test('I-5: role タグ preview/source/attachment はそのまま', function () {
  assert.strictEqual(R.imageRole({ role: 'preview' }), 'preview');
  assert.strictEqual(R.imageRole({ role: 'source' }), 'source');
  assert.strictEqual(R.imageRole({ role: 'attachment' }), 'attachment');
});

test('I-6: role:"src" は source の別名(stock.js salvageWithoutVideo_ の imgs=[{role:"src"}] 互換)', function () {
  assert.strictEqual(R.imageRole({ role: 'src' }), 'source');
});

// --- c) ファイル名ベース(Drive/File実体の命名) ---
test('I-7: 名前 "..._プレビュー.jpg"→preview / "..._元画像.jpg"→source', function () {
  assert.strictEqual(R.imageRole({ name: '作品A_プレビュー.jpg' }), 'preview');
  assert.strictEqual(R.imageRole({ name: '作品A_元画像.png' }), 'source');
  assert.strictEqual(R.imageRole({ name: '作品A_元画像.png', index: 0, prevCount: 1 }),
    'source', '名前判定は位置判定より先に効く');
});

// --- 反復ヘルパ ---
test('I-8: rolesForUsed は used配列を位置ベースで一括判定', function () {
  assert.deepStrictEqual(R.rolesForUsed(['p', 'a', 'b'], 1), ['preview', 'source', 'source']);
});

test('I-9: previewImages / sourceImages は順番通りに振り分ける', function () {
  var used = ['P0', 'P1', 'S0', 'S1'];
  assert.deepStrictEqual(R.previewImages(used, 2), ['P0', 'P1']);
  assert.deepStrictEqual(R.sourceImages(used, 2), ['S0', 'S1']);
});

test('I-10: previewImages は falsy を落としてから位置で切る(空スロット混入対策)', function () {
  assert.deepStrictEqual(R.previewImages(['P0', '', 'S0'], 1), ['P0']);
});

// --- 既定・異常 ---
test('I-11: 何も当たらない/空 rec は attachment(安全側)', function () {
  assert.strictEqual(R.imageRole({}), 'attachment');
  assert.strictEqual(R.imageRole(null), 'attachment');
  assert.strictEqual(R.imageRole(undefined), 'attachment');
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
