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

// ── 作成履歴(go5_stock_archive)＝id union・墓標なし(Chami依頼2026-08-03・完了作品が2台目で消える件) ──
ok("isStockArchiveKey", S.isStockArchiveKey("go5_stock_archive") && !S.isStockArchiveKey("go5_stock_meta") && !S.isStockArrayKey("go5_stock_archive"));
eq("arrIdField archive=id", S.arrIdField_("go5_stock_archive"), "id"); // union対象=完了作品を端末間で失わない
eq("archive union で両端末の完了作品を保持",
   JSON.parse(S.unionByField('[{"id":"a1","title":"完了A"}]', '[{"id":"a2","title":"完了B"}]', "id")),
   [{ id: "a1", title: "完了A" }, { id: "a2", title: "完了B" }]);
// ★墓標(go5_stock_del)は archive には適用しない=完了作品は del墓標を持つが archive では残す。
//   (sync本体の墓標適用は isStockArrayKey/isCandArrayKey に限定=archiveは対象外なので、ここでは分類のみ検証)
ok("archiveは墓標適用の分類に含めない", !S.isStockArrayKey("go5_stock_archive") && !S.isCandArrayKey("go5_stock_archive"));

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

// ── 📝テンプレ帳(bsky_tpl_book__)＝name 単位 union(Chami依頼2026-08-02「保存が消える・全端末で共有」) ──
ok("isTplBookKey", S.isTplBookKey("bsky_tpl_book__acc1") && S.isTplBookKey("bsky_tpl_book") && !S.isTplBookKey("bsky_text__acc1"));
eq("arrIdField tpl=name", S.arrIdField_("bsky_tpl_book__acc2"), "name");
// ★核心: 空の端末が保存済みテンプレを丸ごと消さない(旧・whole-key LWWの事故を根治)
eq("空×populated → 消えない(空が先)",
   JSON.parse(S.unionByField("[]", '[{"name":"テンプレ1","text":"本文A","at":100}]', "name")),
   [{ name: "テンプレ1", text: "本文A", at: 100 }]);
eq("populated×空 → 消えない(空が後)",
   JSON.parse(S.unionByField('[{"name":"テンプレ1","text":"本文A","at":100}]', "[]", "name")),
   [{ name: "テンプレ1", text: "本文A", at: 100 }]);
eq("別nameは両端末で両立(集めたテンプレを失わない)",
   JSON.parse(S.unionByField('[{"name":"A","text":"a"}]', '[{"name":"B","text":"b"}]', "name")),
   [{ name: "A", text: "a" }, { name: "B", text: "b" }]);
eq("同nameは newer(後入れ)の本文を採用",
   JSON.parse(S.unionByField('[{"name":"A","text":"旧","at":1}]', '[{"name":"A","text":"新","at":2}]', "name")),
   [{ name: "A", text: "新", at: 2 }]);

// ── 📝テンプレ帳の削除墓標(bsky_tpl_del__)＝削除を全端末へ伝播(Chami依頼2026-08-03「前のやつ消して」) ──
ok("isTplDelKey", S.isTplDelKey("bsky_tpl_del__acc1") && S.isTplDelKey("bsky_tpl_del") && !S.isTplDelKey("bsky_tpl_book__acc1"));
eq("tplDelKeyOf: book→del(acct保持)", S.tplDelKeyOf("bsky_tpl_book__acc2"), "bsky_tpl_del__acc2");
// ★核心1: 削除ts が保存時刻(at)以降のテンプレは union 後に除外＝他端末から復活しない
eq("墓標で同名テンプレを除外(削除ts≧at)",
   JSON.parse(S.applyTombstone('[{"name":"旧","text":"x","at":100},{"name":"残","text":"y","at":100}]', { "旧": 200 }, "name", "at")),
   [{ name: "残", text: "y", at: 100 }]);
// ★核心2: 削除より後に再保存(at>削除ts)したものは墓標を越えて残る＝「保存は消さない」と両立
eq("削除後に再保存(at>削除ts)は残す",
   JSON.parse(S.applyTombstone('[{"name":"復活","text":"z","at":300}]', { "復活": 200 }, "name", "at")),
   [{ name: "復活", text: "z", at: 300 }]);
// ★核心3: at 欠けの古いテンプレは削除ts があれば除外(0<削除ts)
eq("at欠けの古テンプレは墓標で除外",
   JSON.parse(S.applyTombstone('[{"name":"古","text":"w"}]', { "古": 1 }, "name", "at")),
   []);
// ★墓標マップは name 単位で新しい削除tsを採用(片端末の削除を失わない)
eq("tpl墓標マージ=name単位で新ts採用",
   JSON.parse(S.mergeDelMap('{"A":100,"B":50}', '{"A":200,"C":30}')),
   { A: 200, B: 50, C: 30 });

// ── ①-B ドラフトの画像ミラー(stock:imgs:)＝IDB同期レールに乗る/動画blobは乗らない(2026-07-31) ──
ok("stock:imgs は同期IDBキー", S.isSyncIdbKey("stock:imgs:stk123"));
ok("既存の同期IDBキーは維持", S.isSyncIdbKey("ref:abc") && S.isSyncIdbKey("bsky:1") && S.isSyncIdbKey("post:9"));
ok("動画/サムネの生blobキーは同期しない", !S.isSyncIdbKey("stock_v_stk1") && !S.isSyncIdbKey("stock_t_stk1") && !S.isSyncIdbKey("stock_img_stk1"));


// ── カレンダー予定(sch_state_v1)＝日付/枠/アカウント単位の安全な同期 ──
ok("schedule key 判定", S.isScheduleStateKey("sch_state_v1") && !S.isScheduleStateKey("yt_scheduled__acc1"));
var schA = {
  overrides: { "2026-08-03": { date: "2026-08-03", note: "A", updated_at: "2026-08-03T01:00:00Z" } },
  slotData: {
    a: { id: "a", title: "作品A", updated_at: "2026-08-03T01:00:00Z", exec: { acc1: { status: "予約登録済" }, acc2: { status: "未着手" } } },
    same: { id: "same", title: "旧題", updated_at: "2026-08-03T01:00:00Z", exec: { acc1: { status: "公開済", post_url: "https://example.com/post", posted_at: "2026-08-03T01:00:00Z" }, acc2: { status: "未着手" } } }
  }
};
var schB = {
  overrides: { "2026-08-04": { date: "2026-08-04", note: "B", updated_at: "2026-08-04T01:00:00Z" } },
  slotData: {
    b: { id: "b", title: "作品B", updated_at: "2026-08-04T01:00:00Z", exec: { acc1: { status: "未着手" }, acc2: { status: "予約登録済" } } },
    same: { id: "same", title: "新題", updated_at: "2026-08-04T01:00:00Z", exec: { acc1: { status: "予約登録済" }, acc2: { status: "公開済", post_url: "https://example.com/post2" } } }
  }
};
var schMerged = JSON.parse(S.mergeScheduleState(JSON.stringify(schA), JSON.stringify(schB)));
ok("schedule 別端末の枠を両方保持", schMerged.slotData.a && schMerged.slotData.b);
ok("schedule 同じ枠の新しいプランを採用", schMerged.slotData.same.title === "新題");
ok("schedule 公開済を古い予約へ戻さない", schMerged.slotData.same.exec.acc1.status === "公開済");
ok("schedule 公開URL/投稿日時を保持", schMerged.slotData.same.exec.acc1.post_url === "https://example.com/post" && schMerged.slotData.same.exec.acc1.posted_at === "2026-08-03T01:00:00Z");
ok("schedule 2アカウントの公開状態を独立保持", schMerged.slotData.same.exec.acc2.status === "公開済" && schMerged.slotData.same.exec.acc2.post_url === "https://example.com/post2");
ok("schedule 日付overrideをunion", schMerged.overrides["2026-08-03"] && schMerged.overrides["2026-08-04"]);

var ovOld = { overrides: { "2026-08-05": { date: "2026-08-05", note: "old", force_day_off: true, updated_at: "2026-08-05T01:00:00Z" } }, slotData: {} };
var ovNew = { overrides: { "2026-08-05": { date: "2026-08-05", note: "new", updated_at: "2026-08-05T02:00:00Z" } }, slotData: {} };
var ovMerged = JSON.parse(S.mergeScheduleState(JSON.stringify(ovOld), JSON.stringify(ovNew)));
ok("schedule override はupdated_atが新しい側＋欠落補完", ovMerged.overrides["2026-08-05"].note === "new" && ovMerged.overrides["2026-08-05"].force_day_off === true);

var legacy = { overrides: {}, slotData: { legacy: { id: "legacy", status: "公開済", post_url: "https://example.com/legacy", updated_at: "2026-08-05T01:00:00Z" } } };
var modern = { overrides: {}, slotData: { legacy: { id: "legacy", updated_at: "2026-08-05T02:00:00Z", exec: { acc1: { status: "予約登録済" }, acc2: { status: "未着手" } } } } };
var legacyMerged = JSON.parse(S.mergeScheduleState(JSON.stringify(legacy), JSON.stringify(modern)));
ok("schedule 旧フラット形式もacc1へ移行して保持", legacyMerged.slotData.legacy.exec.acc1.status === "公開済" && legacyMerged.slotData.legacy.exec.acc1.post_url === "https://example.com/legacy");
ok("schedule 旧フラット実行フィールドはbodyに残さない", !Object.prototype.hasOwnProperty.call(legacyMerged.slotData.legacy, "status") && !Object.prototype.hasOwnProperty.call(legacyMerged.slotData.legacy, "post_url"));
var reservedState = { overrides: {}, slotData: { c: { id: "c", exec: { acc1: { status: "予約登録済", exec_updated_at: "2026-08-05T01:00:00Z" }, acc2: { status: "未着手" } } } } };
var cancelledState = { overrides: {}, slotData: { c: { id: "c", exec: { acc1: { status: "制作済・未予約", exec_updated_at: "2026-08-05T02:00:00Z" }, acc2: { status: "未着手" } } } } };
var cancelledMerged = JSON.parse(S.mergeScheduleState(JSON.stringify(reservedState), JSON.stringify(cancelledState)));
ok("schedule 新しい明示取消は古い予約状態より優先", cancelledMerged.slotData.c.exec.acc1.status === "制作済・未予約");
ok("schedule 実行状態の更新時刻を保持", cancelledMerged.slotData.c.exec.acc1.exec_updated_at === "2026-08-05T02:00:00Z");

var clearOld = {
  overrides: { "2026-08-06": { date: "2026-08-06", force_day_off: true, note: "旧メモ", updated_at: "2026-08-06T01:00:00Z" } },
  slotData: {
    clear: { id: "clear", title: "旧題", notes: "旧メモ", updated_at: "2026-08-06T01:00:00Z",
      exec: { acc1: { status: "公開済", post_url: "https://example.com/old", exec_updated_at: "2026-08-06T01:00:00Z" }, acc2: { status: "未着手" } } }
  }
};
var clearNew = {
  overrides: { "2026-08-06": { date: "2026-08-06", force_day_off: null, note: "", updated_at: "2026-08-06T02:00:00Z" } },
  slotData: {
    clear: { id: "clear", title: "", notes: "", updated_at: "2026-08-06T02:00:00Z",
      exec: { acc1: { status: "公開済", post_url: "", exec_updated_at: "2026-08-06T02:00:00Z" }, acc2: { status: "未着手" } } }
  }
};
var clearMerged = JSON.parse(S.mergeScheduleState(JSON.stringify(clearOld), JSON.stringify(clearNew)));
ok("schedule override の明示null/空文字を旧値で復活させない",
   clearMerged.overrides["2026-08-06"].force_day_off === null && clearMerged.overrides["2026-08-06"].note === "");
ok("schedule 題名/メモの明示クリアを旧値で復活させない",
   clearMerged.slotData.clear.title === "" && clearMerged.slotData.clear.notes === "");
ok("schedule 実行URLの明示クリアを旧値で復活させない",
   clearMerged.slotData.clear.exec.acc1.post_url === "");

var validRemote = JSON.stringify(schB);
eq("schedule 破損local＋正常remoteは正常remoteを採用",
   JSON.parse(S.mergeScheduleState("garbage", validRemote)), schB);
eq("schedule 正常local＋破損remoteは正常localを採用",
   JSON.parse(S.mergeScheduleState(JSON.stringify(schA), "garbage")), schA);
ok("schedule 両側破損だけは拒否", S.mergeScheduleState("garbage", "[1,2,3]") === null);

console.log((fail === 0 ? "✅ ALL PASS" : "❌ FAIL") + "  (" + pass + " passed, " + fail + " failed)");
process.exit(fail === 0 ? 0 : 1);
