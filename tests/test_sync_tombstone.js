/**
 * tests/test_sync_tombstone.js — 候補削除の墓標(トゥームストーン)まわりの純関数テスト。
 * 対象: core/sync.js の _test.{mergeDelMap, applyTombstone, candDelKeyOf, unionCand}
 * 背景: INC 2026-07-15「消した候補が他端末から必ず復活する」の恒久対策。
 *   union で候補を失わないまま、削除は墓標(cid+削除ts)で伝播し、union後に除外する。
 * 実行: node tests/test_sync_tombstone.js
 */
"use strict";
var S = require("../core/sync.js")._test;
var pass = 0, fail = 0;
function eq(name, got, want) {
  var g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; }
  else { fail++; console.error("✗ " + name + "\n    got : " + g + "\n    want: " + w); }
}
function ok(name, cond) { if (cond) pass++; else { fail++; console.error("✗ " + name); } }

// ── candDelKeyOf: items キー → 墓標キー ──
eq("delKey main", S.candDelKeyOf("cand_items"), "cand_del");
eq("delKey tab", S.candDelKeyOf("cand_items__T9"), "cand_del__T9");

// ── mergeDelMap: cid 単位で union し ts の大きい方を採る ──
eq("merge 空×空", JSON.parse(S.mergeDelMap("{}", "{}")), {});
eq("merge 片側のみ", JSON.parse(S.mergeDelMap('{"a":100}', "{}")), { a: 100 });
eq("merge 別cidを両立(片側の削除を失わない)", JSON.parse(S.mergeDelMap('{"a":100}', '{"b":200}')), { a: 100, b: 200 });
eq("merge 同cidは新しいtsを採用", JSON.parse(S.mergeDelMap('{"a":100}', '{"a":300}')), { a: 300 });
eq("merge 同cidは古い側で上書きしない", JSON.parse(S.mergeDelMap('{"a":300}', '{"a":100}')), { a: 300 });
eq("merge 不正入力は空扱い", JSON.parse(S.mergeDelMap("garbage", '{"a":5}')), { a: 5 });

// ── applyTombstone: 削除ts>=addedAt を除外・addedAt新しい(再収集)は残す ──
var arr = [
  { cid: "keep", addedAt: 50 },   // 墓標なし → 残る
  { cid: "del", addedAt: 40 },    // 墓標 100 >= 40 → 除外
  { cid: "readd", addedAt: 500 }, // 墓標 100 < 500(再収集) → 残る
  { cid: "noadded" }              // addedAt なし & 墓標あり → 除外(0扱い)
];
var dm = { del: 100, readd: 100, noadded: 100 };
eq("tombstone適用", JSON.parse(S.applyTombstone(JSON.stringify(arr), dm)),
   [{ cid: "keep", addedAt: 50 }, { cid: "readd", addedAt: 500 }]);
eq("空墓標は素通し", JSON.parse(S.applyTombstone(JSON.stringify(arr), {})), arr);
ok("null墓標は素通し(文字列そのまま)", S.applyTombstone(JSON.stringify(arr), null) === JSON.stringify(arr));

// ── 統合: 端末Aが del を削除→墓標。端末Bは del を live 保持。union で復活→墓標で再除外 ──
var aArr = JSON.stringify([{ cid: "x", addedAt: 10 }]);                    // Aは x を削除済み(配列から消えている)…の前の状態としてBのみ持つ
var bArr = JSON.stringify([{ cid: "x", addedAt: 10 }, { cid: "y", addedAt: 20 }]);
var unioned = S.unionCand("[]", bArr); // Aの空配列 と Bの配列を union → x,y が復活
ok("unionで一旦復活する", JSON.parse(unioned).length === 2);
var tomb = { x: 15 }; // Aが x を addedAt(10) より後(15)に削除
var cleaned = JSON.parse(S.applyTombstone(unioned, tomb));
eq("墓標で x だけ除外・y は残る", cleaned, [{ cid: "y", addedAt: 20 }]);

// ── 再収集シナリオ: 削除後に同cidを新しく追加すると復活できる ──
var reAdd = JSON.stringify([{ cid: "x", addedAt: 999 }]); // 墓標(15)より新しい
eq("削除後の再収集は残る", JSON.parse(S.applyTombstone(reAdd, tomb)), [{ cid: "x", addedAt: 999 }]);

// ── unionCand 回帰: 既存挙動(newer優先・cid重複統合)を壊していない ──
eq("unionCand newer優先", JSON.parse(S.unionCand('[{"cid":"a","v":1}]', '[{"cid":"a","v":2}]')), [{ cid: "a", v: 2 }]);

console.log((fail === 0 ? "✅ ALL PASS" : "❌ FAIL") + "  (" + pass + " passed, " + fail + " failed)");
process.exit(fail === 0 ? 0 : 1);
