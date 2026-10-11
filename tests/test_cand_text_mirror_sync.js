'use strict';
// LS満杯の端末でIDBミラー(meta:cand_text)にだけ載ったメモが、同期入力へ合流して雲へ上がることを固定する。
// 症状: 旧iPhoneで書いたメモが新Androidへ来ない(Chami 2026-10-11)。同期入力がLSしか見ていなかった。
// ★must-fail: 合流しない実装・IDB丸ごと採用(LSの新しい編集を巻き戻す)実装のどちらでも赤くなる。
var assert = require('assert');
var S = require('../core/sync.js')._test;
assert.strictEqual(typeof S.mergeCandTextMirrorIntoLs_, 'function', 'mergeCandTextMirrorIntoLs_ が export されていない');
var n = 0, ok = 0;
function eq(a, b, msg) { n++; if (JSON.stringify(a) === JSON.stringify(b)) ok++; else console.error('NG:', msg, '=>', JSON.stringify(a), '!==', JSON.stringify(b)); }

// 1) LSは満杯で古いまま、IDBにだけiPhoneで書いたメモがある → 同期入力にメモが載る(合流しない実装で赤)
var cur1 = { cand_text: JSON.stringify({ a: { comment: 'C', memo: '', at: 10 } }) };
S.mergeCandTextMirrorIntoLs_(cur1, { a: { comment: 'C', memo: 'iPhoneメモ', at: 20 }, b: { comment: '', memo: 'B', at: 15 } });
var m1 = JSON.parse(cur1.cand_text);
eq(m1.a.memo, 'iPhoneメモ', 'IDBだけの新しいメモが同期入力へ載る');
eq(m1.b && m1.b.memo, 'B', 'IDBだけのcidも同期入力へ載る');

// 2) LSにcand_textキー自体が無い(一度もLSへ書けなかった) → IDBから作られる
var cur2 = {};
S.mergeCandTextMirrorIntoLs_(cur2, { x: { memo: 'X', at: 5 } });
eq(cur2.cand_text && JSON.parse(cur2.cand_text).x.memo, 'X', 'LSに無くてもIDBのメモを送る');

// 3) LSの方が新しい編集 → 古いIDBで巻き戻さない(IDB丸ごと採用実装で赤)
var cur3 = { cand_text: JSON.stringify({ a: { memo: 'NEW', at: 30 } }) };
S.mergeCandTextMirrorIntoLs_(cur3, { a: { memo: 'OLD', at: 5 } });
eq(JSON.parse(cur3.cand_text).a.memo, 'NEW', 'LSの新しいメモを古いIDBで上書きしない');

// 4) IDBが空/不正 → LSに触らない
var cur4 = { cand_text: '{"a":{"memo":"M","at":1}}' };
S.mergeCandTextMirrorIntoLs_(cur4, null); S.mergeCandTextMirrorIntoLs_(cur4, []); S.mergeCandTextMirrorIntoLs_(cur4, {});
eq(cur4.cand_text, '{"a":{"memo":"M","at":1}}', '空/不正ミラーでLSを変えない');
var cur5 = {}; S.mergeCandTextMirrorIntoLs_(cur5, {});
eq('cand_text' in cur5, false, '空ミラーでキーを作らない');

// 5) 受信側: LSへ書けない時はIDBミラーへ着地する
var saved = null;
var idb = { available: function () { return true; }, set: function (k, v) { saved = [k, v]; return Promise.resolve(); } };
S.writeCandTextFallback_(idb, JSON.stringify({ a: { memo: 'R', at: 3 } })).then(function (r) {
  eq(r, true, 'fallback成功');
  eq(saved && saved[0], 'meta:cand_text', 'ミラーキーへ書く');
  eq(saved && saved[1].a.memo, 'R', '受信メモがミラーへ載る');
  return S.writeCandTextFallback_(idb, '[]');
}).then(function (r) {
  eq(r, false, '配列は拒否');
  console.log('test_cand_text_mirror_sync: ' + ok + '/' + n + (ok === n ? ' PASS' : ' FAIL'));
  if (ok !== n) process.exit(1);
});
