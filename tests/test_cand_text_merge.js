// Storage v2 Phase1: cand_text の LS↔IDB マージ(candTextMergeIdb_)の正しさを検査(設計 01_STORAGE_V2_DESIGN §8)。
// ★must-fail: 「LS常勝」「IDB常勝」「丸ごと上書き」のどの naive 実装でも必ず1ケース以上で赤くなる組み合わせを含む。
var assert = require('assert');
global.window = global.window || {};
var C = require('../js/candidates.js');
var merge = C.candTextMergeIdb_;
assert.strictEqual(typeof merge, 'function', 'candTextMergeIdb_ が export されていない');

var n = 0, ok = 0;
function eq(actual, expected, msg) { n++; if (actual === expected) { ok++; } else { console.error('NG:', msg, '=>', JSON.stringify(actual), '!==', JSON.stringify(expected)); } }

// 1) IDBにしか無いcid → 復元される(LS満杯でIDBにだけ載った編集が再読込後に見える)。「LS常勝」実装で赤。
var r1 = merge({ a: { comment: 'A', at: 10 } }, { b: { comment: 'B', at: 5 } });
eq(r1.changed, true, 'IDB専有cidは変更あり');
eq(r1.map.a && r1.map.a.comment, 'A', 'LSのaは残る');
eq(r1.map.b && r1.map.b.comment, 'B', 'IDBのbが復元される');

// 2) 同一cidで LS が新しい(at大) → LSを勝たせIDBで上書きしない。「IDB常勝」「丸ごと上書き」実装で赤。
var r2 = merge({ a: { comment: 'NEW', at: 20 } }, { a: { comment: 'OLD', at: 5 } });
eq(r2.map.a.comment, 'NEW', '新しいLSをIDB(古)で上書きしない');
eq(r2.changed, false, 'LSが勝つ時は変更なし');

// 3) 同一cidで IDB が新しい(at大) → IDBを採用(LS満杯後に別経路でIDBだけ更新された等)。「LS常勝」実装で赤。
var r3 = merge({ a: { comment: 'OLD', at: 5 } }, { a: { comment: 'NEWER', at: 30 } });
eq(r3.map.a.comment, 'NEWER', '新しいIDBを採用');
eq(r3.changed, true, 'IDBが勝つ時は変更あり');

// 4) 空/不正入力でも壊れない。
eq(merge(null, null).changed, false, 'null同士は変更なし');
eq(Object.keys(merge({ a: { at: 1 } }, null).map).length, 1, 'IDB nullでもLSは保持');

console.log('candTextMergeIdb_: ' + ok + '/' + n + ' PASS');
if (ok !== n) { process.exit(1); }
