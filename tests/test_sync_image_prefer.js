/**
 * tests/test_sync_image_prefer.js — 画像同期「実体優先マージ」回帰テスト(v=638の固定・オタコン 2026-08-05)
 *
 * 【解く問題】サブ端末で直近の画像(候補タブの動画生成用画像・投稿履歴プレビュー)が表示されない事故が
 *   3回繰り返した(v=634/635/638)。真因=R2未反映のタイミングで pull すると本体が空の「残骸レコード」で
 *   書かれ、その ts が新しいため LWW で勝ち続け、実体が永久に負ける。v=638 で「片側だけ残骸なら ts を無視して
 *   実体側を採用(自己回復)」を入れた。このルールが将来のリファクタで静かに消えると、また Chami が
 *   バグとして踏む=手数。ここで純関数 preferImgRecord_ / hasEmptyImgSlot を実物ごと固定する。
 *
 * 実行: node tests/test_sync_image_prefer.js
 */
"use strict";
var Sync = require("../core/sync.js")._test;
var preferImgRecord_ = Sync.preferImgRecord_, hasEmptyImgSlot = Sync.hasEmptyImgSlot;

var fails = 0, checks = 0;
function eq(actual, expected, label) {
  checks++;
  if (actual === expected) return;
  fails++;
  console.log("❌ " + label + " : 期待=" + JSON.stringify(expected) + " 実際=" + JSON.stringify(actual));
}

// ── hasEmptyImgSlot の判定 ──
eq(hasEmptyImgSlot({ img: "" }), true, "img空=残骸");
eq(hasEmptyImgSlot({ img: "data:x" }), false, "img実体=非残骸");
eq(hasEmptyImgSlot({ imgs: ["data:a", ""] }), true, "imgs配列に空=残骸");
eq(hasEmptyImgSlot({ imgs: ["data:a", "data:b"] }), false, "imgs全実体=非残骸");
eq(hasEmptyImgSlot({ img: "", imgs: ["data:a"] }), false, "imgsを持つ物のimg空は無視(bsky系のみ残骸扱い)");
eq(hasEmptyImgSlot({}), false, "空オブジェクト=非残骸");
eq(hasEmptyImgSlot(null), false, "null=非残骸");

// ── preferImgRecord_ の勝敗(★ここが v=638 の核心) ──
var real = { t: 100, v: { imgs: ["data:real"] } };       // 古いが実体あり
var empty = { t: 200, v: { imgs: [""] } };               // 新しいが残骸(R2未反映で書かれた)
var realB = { t: 50, v: { imgs: ["data:realB"] } };

// ローカルが残骸(新ts)・リモートが実体(古ts) → 実体(リモート)を採用=ts無視
eq(preferImgRecord_(empty, realB), realB, "ローカル残骸(新)vsリモート実体(古)→実体側");
// リモートが残骸(新ts)・ローカルが実体(古ts) → 実体(ローカル)を守る=ts無視
eq(preferImgRecord_(real, empty), real, "リモート残骸(新)vsローカル実体(古)→実体側");
// 両方実体 → null(通常のLWWへ委ねる)
eq(preferImgRecord_(real, realB), null, "両方実体→LWWに委ねる(null)");
// 両方残骸 → null
eq(preferImgRecord_(empty, { t: 300, v: { imgs: [""] } }), null, "両方残骸→null");
// 片側が墓標(d) → null(削除はLWW/tombstoneに任せる)
eq(preferImgRecord_({ t: 1, d: 1 }, real), null, "片側墓標→null");
eq(preferImgRecord_(real, { t: 1, d: 1 }), null, "片側墓標(逆)→null");
// 片側欠落 → null
eq(preferImgRecord_(real, undefined), null, "リモート欠落→null");
eq(preferImgRecord_(undefined, real), null, "ローカル欠落→null");

if (fails) { console.log("\n" + fails + " 件 失敗 / " + checks + " 検査"); process.exit(1); }
console.log("✅ 全 " + checks + " 検査PASS (画像同期の実体優先マージ=v=638 固定)");
