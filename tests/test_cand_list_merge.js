// Storage v2 Phase2: 候補リスト配列(itemsKey/K_ITEMS)の LS↔IDB マージ(candListMergeIdb_)の正しさを検査。
// ★must-fail: 「LS常勝」「IDB常勝」のどの naive 実装でも必ず1ケース以上で赤くなる組み合わせを含む。
var assert = require('assert');
global.window = global.window || {};
var C = require('../js/candidates.js');
var merge = C.candListMergeIdb_;
assert.strictEqual(typeof merge, 'function', 'candListMergeIdb_ が export されていない');

var n = 0, ok = 0;
function eq(actual, expected, msg) { n++; if (actual === expected) { ok++; } else { console.error('NG:', msg, '=>', JSON.stringify(actual), '!==', JSON.stringify(expected)); } }

// 1) IDBにしか無いcid → 復元される(LS満杯でIDBにだけ載った候補が再読込後に見える)。「LS常勝」実装で赤。
var r1 = merge([{ cid: 'a', addedAt: 10 }], [{ cid: 'b', addedAt: 5 }]);
eq(r1.changed, true, 'IDB専有cidは変更あり');
eq(r1.arr.length, 2, 'LSのa+IDBのbで2件');
eq(r1.arr.some(function (x) { return x.cid === 'a'; }), true, 'LSのaは残る');
eq(r1.arr.some(function (x) { return x.cid === 'b'; }), true, 'IDBのbが復元される');

// 2) 同一cidで LS が新しい(addedAt大) → LSを勝たせIDBで上書きしない。「IDB常勝」実装で赤。
var r2 = merge([{ cid: 'a', title: 'NEW', addedAt: 20 }], [{ cid: 'a', title: 'OLD', addedAt: 5 }]);
eq(r2.arr[0].title, 'NEW', '新しいLSをIDB(古)で上書きしない');
eq(r2.changed, false, 'LSが勝つ時は変更なし');

// 3) 同一cidで IDB が新しい(addedAt大) → IDBを採用(LS満杯後に別経路でIDBだけ更新された等)。「LS常勝」実装で赤。
var r3 = merge([{ cid: 'a', title: 'OLD', addedAt: 5 }], [{ cid: 'a', title: 'NEWER', addedAt: 30 }]);
eq(r3.arr[0].title, 'NEWER', '新しいIDBを採用');
eq(r3.changed, true, 'IDBが勝つ時は変更あり');

// 4) 両方 addedAt 欠落の同一cid → LS側を残す(IDB常勝実装で赤=arr[0].titleがOLDのまま=変更なしが正)。
var r4 = merge([{ cid: 'a', title: 'LS_KEEP' }], [{ cid: 'a', title: 'IDB_DROP' }]);
eq(r4.arr[0].title, 'LS_KEEP', '両方addedAt欠落ならLS側を残す');
eq(r4.changed, false, '両方addedAt欠落は変更なし扱い');

// 5) 空/不正入力でも壊れない(throwしない)。
assert.doesNotThrow(function () { merge(null, null); }, 'null同士でthrowしない');
assert.doesNotThrow(function () { merge('not-an-array', { a: 1 }); }, '非配列入力でthrowしない');
assert.doesNotThrow(function () { merge([null, { cid: null }, 'x'], [undefined, 42]); }, '壊れた要素でthrowしない');
eq(merge(null, null).changed, false, 'null同士は変更なし');
eq(merge([{ cid: 'a', addedAt: 1 }], null).arr.length, 1, 'IDB nullでもLSは保持');

console.log('candListMergeIdb_: ' + ok + '/' + n + ' PASS');
if (ok !== n) { process.exit(1); }
