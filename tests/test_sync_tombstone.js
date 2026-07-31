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

// ── ドラフト(go5_stock_meta)＝id 単位 union/墓標(Chami依頼2026-07-31・全端末同期) ──
ok("isStockArrayKey", S.isStockArrayKey("go5_stock_meta") && !S.isStockArrayKey("go5_stock_archive") && !S.isStockArrayKey("cand_items"));
ok("isStockDelKey", S.isStockDelKey("go5_stock_del") && !S.isStockDelKey("cand_del"));
eq("arrIdField cand=cid", S.arrIdField_("cand_items"), "cid");
eq("arrIdField stock=id", S.arrIdField_("go5_stock_meta"), "id");
ok("arrIdField 非配列=null", S.arrIdField_("go5_stock_del") === null && S.arrIdField_("bsky_text") === null);
// id union: 端末Aのドラフトと端末Bのドラフトを両立(消さない)
eq("stock union で両端末のドラフトを保持",
   JSON.parse(S.unionByField('[{"id":"stk1","title":"A"}]', '[{"id":"stk2","title":"B"}]', "id")),
   [{ id: "stk1", title: "A" }, { id: "stk2", title: "B" }]);
eq("stock union 同idは newer 優先・欠けたフィールドは older 保持",
   JSON.parse(S.unionByField('[{"id":"stk1","title":"A","workUrl":"https://x/a/"}]', '[{"id":"stk1","title":"A2"}]', "id")),
   [{ id: "stk1", title: "A2", workUrl: "https://x/a/" }]); // title は newer、workUrl は older を保持
// 墓標: 削除したドラフトが union で復活→id/addedAt で除外
var sArr = JSON.stringify([{ id: "stk1", addedAt: 100 }, { id: "stk2", addedAt: 100 }]);
eq("stock 墓標で削除idを除外",
   JSON.parse(S.applyTombstone(sArr, { stk1: 200 }, "id", "addedAt")),
   [{ id: "stk2", addedAt: 100 }]);
eq("stock 復元(addedAt=now>削除ts)は残る",
   JSON.parse(S.applyTombstone(JSON.stringify([{ id: "stk1", addedAt: 999 }]), { stk1: 200 }, "id", "addedAt")),
   [{ id: "stk1", addedAt: 999 }]);
// 統合: A が stk1 を削除(墓標) / B は stk1 を保持 → union で復活 → 墓標で再除外
var uni = S.unionByField("[]", JSON.stringify([{ id: "stk1", addedAt: 100 }, { id: "stk2", addedAt: 100 }]), "id");
ok("stock unionで一旦復活", JSON.parse(uni).length === 2);
eq("stock 墓標で stk1 だけ除外", JSON.parse(S.applyTombstone(uni, { stk1: 150 }, "id", "addedAt")), [{ id: "stk2", addedAt: 100 }]);

// ── unionCand フィールド統合: newer に欠けた作品URLは older から保持する(作品URL消失の根治) ──
eq("union newerにurl無→olderのurlを保持",
   JSON.parse(S.unionCand('[{"cid":"a","url":"https://x/works/a/","price":500}]', '[{"cid":"a","price":400}]')),
   [{ cid: "a", url: "https://x/works/a/", price: 400 }]); // price は newer(400)、url は older を保持
eq("union newerの空文字urlはolderを上書きしない",
   JSON.parse(S.unionCand('[{"cid":"a","url":"https://x/works/a/"}]', '[{"cid":"a","url":""}]')),
   [{ cid: "a", url: "https://x/works/a/" }]);
eq("union newerの実値0は尊重(空扱いしない)",
   JSON.parse(S.unionCand('[{"cid":"a","discountPct":50}]', '[{"cid":"a","discountPct":0}]')),
   [{ cid: "a", discountPct: 0 }]);
eq("union olderに欠けnewerにあるフィールドは追加",
   JSON.parse(S.unionCand('[{"cid":"a","url":"https://x/works/a/"}]', '[{"cid":"a","title":"T"}]')),
   [{ cid: "a", url: "https://x/works/a/", title: "T" }]);

// ── ①-B ドラフトの画像ミラー(stock:imgs:)＝IDB同期レールに乗る/動画blobは乗らない(2026-07-31) ──
ok("stock:imgs は同期IDBキー", S.isSyncIdbKey("stock:imgs:stk123"));
ok("既存の同期IDBキーは維持", S.isSyncIdbKey("ref:abc") && S.isSyncIdbKey("bsky:1") && S.isSyncIdbKey("post:9"));
ok("動画/サムネの生blobキーは同期しない", !S.isSyncIdbKey("stock_v_stk1") && !S.isSyncIdbKey("stock_t_stk1") && !S.isSyncIdbKey("stock_img_stk1"));

console.log((fail === 0 ? "✅ ALL PASS" : "❌ FAIL") + "  (" + pass + " passed, " + fail + " failed)");
process.exit(fail === 0 ? 0 : 1);
