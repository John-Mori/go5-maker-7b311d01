// tests/test_disc_line.js — core/disc-line-core.js(Go5DiscLine)の純粋関数テスト。
//   割引文サフィックスの生成(排他=新作>準新作・総集編両立)と、既存行への差し替え(剥がし+再挿入)を検証。
//   ★準新作を割引文へ出す改修(Chami依頼2026-08-16③)の恒久ガード=Nodeで本物を叩く(window フックではなく)。
const assert = require('assert');
const { discSuffix, respliceDiscLine } = require('../core/disc-line-core.js');

let pass = 0;
function eq(actual, expected, name) { assert.strictEqual(actual, expected, name + ' => ' + JSON.stringify(actual)); pass++; }

// ---- discSuffix：排他(新作>準新作)・総集編両立 ----
eq(discSuffix(false, false, false), '', 'なし');
eq(discSuffix(true, false, false), 'の新作', '新作のみ');
eq(discSuffix(false, true, false), 'の準新作', '準新作のみ');
eq(discSuffix(false, false, true), 'の総集編', '総集編のみ');
eq(discSuffix(true, false, true), 'の新作&総集編', '新作&総集編');
eq(discSuffix(false, true, true), 'の準新作&総集編', '準新作&総集編');
eq(discSuffix(true, true, false), 'の新作', '新作+準新作=新作優先');
eq(discSuffix(true, true, true), 'の新作&総集編', '新作+準新作+総集編=新作優先');

// ---- respliceDiscLine：head保持・既存サフィックス剥がし・絵文字トレイル保持(acc2文面) ----
eq(respliceDiscLine('しかも今なら50%オフ💕', false, true, false), 'しかも今なら50%オフの準新作💕', '素の行へ準新作を挿入');
eq(respliceDiscLine('しかも今なら50%オフの新作💕', false, true, false), 'しかも今なら50%オフの準新作💕', '新作→準新作へ差し替え(二重化しない)');
eq(respliceDiscLine('しかも今なら50%オフの準新作💕', false, false, false), 'しかも今なら50%オフ💕', '準新作を外す=サフィックスだけ消え数字と絵文字は残る');
eq(respliceDiscLine('しかも今なら50%オフの準新作💕', false, false, true), 'しかも今なら50%オフの総集編💕', '準新作→総集編へ差し替え');
eq(respliceDiscLine('しかも今なら880円の準新作💕', false, true, true), 'しかも今なら880円の準新作&総集編💕', '円表記＋準新作&総集編');
eq(respliceDiscLine('割引行が無い普通の文', false, true, false), '割引行が無い普通の文', 'オフ/円が無い行は素通し');

console.log('test_disc_line: 全' + pass + '件 PASS');
