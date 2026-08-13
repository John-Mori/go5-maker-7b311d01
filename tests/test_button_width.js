/**
 * tests/test_button_width.js
 * 「一覧に横並びする操作ボタンを、横幅いっぱいに引き伸ばさない」を固定する回帰テスト(🔥恒久対策)。
 *
 * ★背景(なぜ要るか)：Chami のボタン幅の好みは何度も言われている恒久ルール=**中身なり幅・引き伸ばし禁止**。
 *   それでも v=730 で作成履歴の4ボタンに flex:1 1 0(4等分でfull幅に引き伸ばし)を入れて 🔥(重大炎上)を貰った
 *   (msg_id=1536774712519163914「ボタンの横幅は無闇に広げるな・前のサイズで良かった」)。
 *   「気をつける」は対策にならない=次の改修でまた誰かが flex:1 を入れうる。ここで stock.js の
 *   renderArchItem_ の btnBase を機械で検査し、成長flex が入ったら CI(smoke.yml が tests/test_*.js を全push実行)で赤にする。
 *
 * 何を禁止するか= btnBase の中に **成長する flex**(`flex:1` / `flex:1 1 …` / `flex-grow:1`)。
 *   許可= `flex:0 1 auto`(中身なり幅・収まらない時だけ縮む)。
 *
 * 実行: node tests/test_button_width.js
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

let passed = 0, failed = 0;
function test(name, fn) { try { fn(); console.log('PASS: ' + name); passed++; } catch (e) { console.log('FAIL: ' + name); console.log('      ' + e.message); failed++; } }

// renderArchItem_ 内で定義される btnBase の中身(1行の文字列リテラル)を取り出す。
function extractArchBtnBase(src) {
  const fnAt = src.indexOf('function renderArchItem_');
  assert.notStrictEqual(fnAt, -1, 'stock.js に renderArchItem_ が見つからない(関数名が変わった?)');
  const region = src.slice(fnAt, fnAt + 4000); // 関数の頭付近に btnBase 定義がある
  const m = region.match(/var\s+btnBase\s*=\s*'([^']*)'/);
  assert.ok(m, 'renderArchItem_ の中に btnBase の定義が見つからない');
  return m[1];
}

// 成長flex(横幅いっぱいへ伸びる)を検知する。flex:0 1 auto は許可、flex:1 / flex:1 1 / flex-grow:1 は禁止。
function hasGrowingFlex(style) {
  if (/flex-grow\s*:\s*[1-9]/.test(style)) return true;         // flex-grow:1+
  const m = style.match(/(?:^|;)\s*flex\s*:\s*([^;]+)/);        // flex ショートハンド
  if (m) {
    const first = m[1].trim().split(/\s+/)[0];                  // grow 値(第1トークン)
    if (/^[1-9]/.test(first)) return true;                      // flex:1 / flex:1 1 0 …
  }
  return false;
}

const stockPath = path.join(__dirname, '..', 'js', 'stock.js');
const src = fs.readFileSync(stockPath, 'utf8');
const btnBase = extractArchBtnBase(src);

test('BW-1: 作成履歴ボタンの btnBase は成長flexを含まない(横幅いっぱいへ引き伸ばさない=🔥恒久対策)', function () {
  assert.strictEqual(hasGrowingFlex(btnBase), false,
    'btnBase に成長flex(flex:1 / flex:1 1 0 / flex-grow:1)が入っている=横幅が引き伸ばされる。中身なり幅 flex:0 1 auto にすること。btnBase=' + btnBase);
});

test('BW-2: btnBase は中身なり幅(flex:0 0 auto / flex:0 1 auto=grow0・basis auto)を明示している', function () {
  // grow=0・basis=auto=文字量なりの幅。shrink は 0(折り返す)でも 1(縮む)でも「引き伸ばさない」条件は満たす。
  assert.ok(/flex\s*:\s*0\s+[01]\s+auto/.test(btnBase),
    'btnBase に flex:0 0 auto / 0 1 auto が無い(中身なり幅の明示が消えた)。btnBase=' + btnBase);
});

// ★これが幅騒動の真因だった(2026-08-12 msg1536784731872698439)。グローバル button{width:100%}(style.css:846)を
//   打ち消す width:auto が無いと、flex-basis:auto が 100% を読み、ボタンが全幅→縦積みになる。flex 指定だけでは防げない。
test('BW-4: btnBase は width:auto を明示している(グローバル button{width:100%} の打ち消し・全幅化の根治)', function () {
  assert.ok(/width\s*:\s*auto/.test(btnBase),
    'btnBase に width:auto が無い=グローバル button{width:100%} が勝ってボタンが全幅・縦積みになる。btnBase=' + btnBase);
});

// 検知ロジック自身の自己テスト(将来この判定を緩めた時に気づけるように)
test('BW-3: 検知ロジックの自己テスト(flex:1 1 0 は禁止・flex:0 1 auto は許可)', function () {
  assert.strictEqual(hasGrowingFlex('padding:4px;flex:1 1 0;min-width:0;'), true);
  assert.strictEqual(hasGrowingFlex('padding:4px;flex:1;'), true);
  assert.strictEqual(hasGrowingFlex('padding:4px;flex-grow:1;'), true);
  assert.strictEqual(hasGrowingFlex('padding:4px;flex:0 1 auto;min-width:0;'), false);
  assert.strictEqual(hasGrowingFlex('padding:4px;'), false);
});

console.log('\n' + passed + ' passed, ' + failed + ' failed');
if (failed > 0) process.exit(1);
