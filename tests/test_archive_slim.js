/**
 * tests/test_archive_slim.js — 作成履歴サムネの恒久detox 純関数 slimStockArchive のテスト。
 * 対象: core/sync.js の _test.{slimStockArchive, unionByField}
 * 設計正本: docs/設計・調査/診断_作成履歴サムネ同期detox_2026-08-18.md(Fable5案C・C-043)。
 * 背景: go5_stock_archive の thumbDataUrl(≤160KB×最大30)+sync2_snap 複製でiOS約5MB箱に張り付く。
 *   雲は whole-blob 置換なので、全端末が「新しい keepN件だけ thumb を残す」決定的正規化を掛ければ
 *   不動点 slim(union(slim(x), x)) === slim(x) に収束し、古い thumb が雲から消える(item は失わない)。
 * 実行: node tests/test_archive_slim.js
 * ★test-must-fail: 下の各assertは実装を壊すと落ちることを追加時に実証済(末尾コメント参照)。
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

var T = "data:image/jpeg;base64,AAAA"; // ダミーサムネ(存在フラグとして使う)
function item(id, ts, extra) {
  var m = { id: id, completedTs: ts, title: "作品" + id, youtubeUrl: "https://y/" + id, account: "acc1", thumbDataUrl: T };
  if (extra) for (var k in extra) m[k] = extra[k];
  return m;
}
function thumbCount(str) { return JSON.parse(str).filter(function (m) { return m && m.thumbDataUrl; }).length; }
function idsOf(str) { return JSON.parse(str).map(function (m) { return m && m.id; }); }

// ── ① item は消さない・並びは変えない・thumb以外の全フィールドを保つ ──
var five = [item("a", 500), item("b", 100), item("c", 400), item("d", 200), item("e", 300)];
var s5 = S.slimStockArchive(JSON.stringify(five), 3);
eq("並び順は不変(a,b,c,d,e)", idsOf(s5), ["a", "b", "c", "d", "e"]);
ok("件数は不変(5件)", JSON.parse(s5).length === 5);
ok("thumbは新しい3件だけ残る", thumbCount(s5) === 3);
// completedTs 降順 top3 = a(500) c(400) e(300)。b(100) d(200) は剥がれる。
(function () {
  var m = {}; JSON.parse(s5).forEach(function (x) { m[x.id] = x; });
  ok("a(最新) thumb残る", !!m.a.thumbDataUrl);
  ok("c(2番) thumb残る", !!m.c.thumbDataUrl);
  ok("e(3番) thumb残る", !!m.e.thumbDataUrl);
  ok("b(古) thumb剥がれる", !m.b.thumbDataUrl);
  ok("d(古) thumb剥がれる", !m.d.thumbDataUrl);
  eq("剥がしても他フィールドは完全に残る(d)", m.d, { id: "d", completedTs: 200, title: "作品d", youtubeUrl: "https://y/d", account: "acc1" });
})();

// ── ② タイブレーク: completedTs 同値は id 降順で決定的に ──
var tie = [item("x1", 100), item("x2", 100), item("x3", 100)];
var st = S.slimStockArchive(JSON.stringify(tie), 2);
(function () {
  var m = {}; JSON.parse(st).forEach(function (x) { m[x.id] = x; });
  ok("同時刻は id 大きい2件(x3,x2)が残る", !!m.x3.thumbDataUrl && !!m.x2.thumbDataUrl);
  ok("同時刻の最小id(x1)は剥がれる", !m.x1.thumbDataUrl);
})();

// ── ③ completedTs 無しは ts をフォールバックに使う ──
var mixed = [
  { id: "p", ts: 900, thumbDataUrl: T },           // completedTs 無し→ts=900
  { id: "q", completedTs: 800, thumbDataUrl: T },
  { id: "r", ts: 100, thumbDataUrl: T }
];
var sm = S.slimStockArchive(JSON.stringify(mixed), 1);
(function () {
  var m = {}; JSON.parse(sm).forEach(function (x) { m[x.id] = x; });
  ok("ts=900 が最新扱いで残る", !!m.p.thumbDataUrl && !m.q.thumbDataUrl && !m.r.thumbDataUrl);
})();

// ── ④ 罠の実在(union は thumb を復活させる)と根治(不動点収束)の証明 ──
var x = JSON.stringify(five);
var slimX = S.slimStockArchive(x, 3);
// 4a: local=剥がし済み・remote=古thumb持ち を union → thumb が復活する(=罠が実在=①-2の証明)。
var reunion = S.unionByField(slimX, x, "id"); // older=slim, newer=fat
ok("罠の実在: union で thumb が復活(≒5件)", thumbCount(reunion) === 5);
// 4b: その結果に slim を掛けると古thumbが実際に消え、不動点 slim(union(slim(x),x))===slim(x)。
var converged = S.slimStockArchive(reunion, 3);
eq("不動点収束: slim(union(slim(x),x)) === slim(x)", JSON.parse(converged), JSON.parse(slimX));
ok("収束後の thumb は 3件", thumbCount(converged) === 3);
ok("収束後も id 集合は不変(5件)", JSON.parse(converged).length === 5);

// ── ⑤ fail-open: 壊れたJSON/非配列/空は入力をそのまま返す(null/例外を出さない) ──
eq("壊れたJSONは素通し", S.slimStockArchive("{not json", 3), "{not json");
eq("非配列(オブジェクト)は素通し", S.slimStockArchive('{"a":1}', 3), '{"a":1}');
eq("空文字→空配列文字列(parse '[]')", S.slimStockArchive("", 3), "[]");
ok("null/undefined入力でも例外を投げない", (function () { try { S.slimStockArchive(null, 3); S.slimStockArchive(undefined, 3); return true; } catch (e) { return false; } })());

// ── ⑥ keepN が件数以上なら 1件も剥がさない(全部残す) ──
ok("keepN>=件数なら全thumb残る", thumbCount(S.slimStockArchive(JSON.stringify(five), 10)) === 5);
ok("keepN=0 なら全thumb剥がす", thumbCount(S.slimStockArchive(JSON.stringify(five), 0)) === 0);

console.log((fail === 0 ? "✅ PASS " : "❌ FAIL ") + pass + " / " + (pass + fail));
process.exit(fail === 0 ? 0 : 1);

/* test-must-fail 実証(追加時に1回・2026-08-18):
 *   - slimStockArchive を「return arrStr(恒等)」に差し替え → ①③④の strip/収束assertが落ちる(確認済)。
 *   - keep選抜を昇順(古い順を残す)に差し替え → ①「a,c,e残る」が落ちる(確認済)。
 *   - fail-open を「catchでnull返し」に差し替え → ⑤「壊れたJSONは素通し」が落ちる(確認済)。
 */
