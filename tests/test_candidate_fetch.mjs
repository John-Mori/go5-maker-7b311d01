import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import worker from "../fanza-worker/src/index.js";
import { productJsonLdFromHtml } from "../scripts/fanza_jsonld.mjs";

class MemoryKv {
  constructor() { this.map = new Map(); }
  async get(key, type) {
    if (!this.map.has(key)) return null;
    const value = this.map.get(key);
    return type === "json" ? JSON.parse(value) : value;
  }
  async put(key, value) { this.map.set(key, String(value)); }
  async delete(key) { this.map.delete(key); }
  async list({ prefix = "" } = {}) {
    return { keys: [...this.map.keys()].filter((key) => key.startsWith(prefix)).map((name) => ({ name })), list_complete: true };
  }
}

const origin = "https://john-mori.github.io";
const kv = new MemoryKv();
const env = { FANZA_KV: kv, USE_D1: "off", SHARED_SECRET: "public-test", ADMIN_SECRET: "admin-test", ALLOWED_ORIGIN: origin };

// candidates.js内の実関数を直接評価し、FANZA作品へSNS URLを併記した通常候補を対象外にしないことを固定する。
const candidateSource = fs.readFileSync(new URL("../candidates.js", import.meta.url), "utf8");
const helperStart = candidateSource.indexOf("  function isInfoTarget_");
const helperEnd = candidateSource.indexOf("  function salesTargetCids_", helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart, "candidate target helpers should exist");
const helperContext = {};
vm.runInNewContext(candidateSource.slice(helperStart, helperEnd), helperContext);
assert.equal(helperContext.isInfoTarget_({ cid: "d_123", twitterUrl: "https://x.com/a/status/1" }), true, "作品URL＋SNS紐付けもFANZA情報更新の対象");
assert.equal(helperContext.isSalesTarget_({ cid: "d_123", twitterUrl: "https://x.com/a/status/1" }), true, "作品URL＋SNS紐付けも販売数取得の対象");
assert.equal(helperContext.isInfoTarget_({ cid: "tw_1", isTwitter: true }), false);
assert.equal(helperContext.isSalesTarget_({ cid: "b915book" }), false);
async function call(path, { body, admin = false } = {}) {
  const headers = admin
    ? { "Content-Type": "application/json", "X-Admin-Secret": env.ADMIN_SECRET }
    : { "Content-Type": "application/json", "X-Shared-Secret": env.SHARED_SECRET, Origin: origin };
  const res = await worker.fetch(new Request(origin + path, { method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body) }), env);
  return { status: res.status, json: await res.json() };
}

let r = await call("/api/fanza-sales", { body: { cids: ["b915awnmg03652", "tw_123", "d_615931"] } });
assert.deepEqual(r.json.unsupported, ["b915awnmg03652", "tw_123"], "Books/SNSを販売数取得列へ入れない");
assert.deepEqual(r.json.missing, ["d_615931"]);
assert.equal(kv.map.has("salesreq:d_615931"), true);
assert.equal(kv.map.has("salesreq:b915awnmg03652"), false);

r = await call("/api/fanza-sales-save", { admin: true, body: { items: [{ cid: "d_615931", status: "unavailable" }] } });
assert.equal(r.json.ok, true);
assert.equal(kv.map.has("salesreq:d_615931"), false, "取得不可を終端状態としてキューから消す");
r = await call("/api/fanza-sales", { body: { cid: "d_615931" } });
assert.deepEqual(r.json.unavailable, ["d_615931"]);
assert.deepEqual(r.json.missing, []);

await kv.put("salesreq:d_615931", JSON.stringify({ at: new Date().toISOString() }));
r = await call("/api/fanza-sales-save", { admin: true, body: { items: [{ cid: "d_615931", status: "unavailable" }] } });
assert.equal(r.json.skipped, 1, "同一データは再保存しない");
assert.equal(kv.map.has("salesreq:d_615931"), false, "同一データでも取得依頼は完了させる");

r = await call("/api/fanza-sales-save", { admin: true, body: { items: [{ cid: "d_615931", n: 12 }] } });
assert.equal(r.json.saved, 1, "後日販売数が出たら取得不可から数値へ回復できる");
r = await call("/api/fanza-sales", { body: { cid: "d_615931" } });
assert.equal(r.json.sales.d_615931, 12);

const override = {
  content_id: "d_615931", title: "レビュー作品", date: "2026-07-01 00:00:00",
  service_name: "同人", floor_name: "同人", imageURL: null, sampleImageURL: null,
  iteminfo: { author: [{ name: "サークル" }], genre: [] }, prices: { list_price: "770", price: "550" },
  review: { count: "6", average: "4.83" }, scrapedAt: "2026-07-24T00:00:00.000Z",
};
await kv.put("req:d_615931", JSON.stringify({ at: new Date().toISOString() }));
r = await call("/api/fanza-override", { admin: true, body: { items: [override] } });
assert.equal(r.json.saved, 1);
assert.deepEqual((await kv.get("ov:d_615931", "json")).review, { count: 6, average: 4.83 }, "PCで取れたレビューを捨てずに保存する");
await kv.put("req:d_615931", JSON.stringify({ at: new Date().toISOString() }));
r = await call("/api/fanza-override", { admin: true, body: { items: [override] } });
assert.equal(r.json.skipped, 1);
assert.equal(kv.map.has("req:d_615931"), false, "同一の作品情報でも取得依頼は完了させる");

const noRating = productJsonLdFromHtml('<script type="application/ld+json">{"@type":"Product","offers":{}}</script>');
assert.equal(noRating.price, null, "欠損価格を0円と誤認しない");
assert.equal(noRating.reviewCount, null, "欠損レビューを0件と誤認しない");
const graph = productJsonLdFromHtml('<script type="application/ld+json">{"@graph":[{"@type":"https://schema.org/Product","offers":{"price":"1,100"},"brand":{"name":"作者"},"aggregateRating":{"ratingCount":"6","ratingValue":"4.83"}}]}</script>');
assert.deepEqual(graph, { price: 1100, brand: "作者", image: "", releaseDate: "", reviewCount: 6, reviewAvg: 4.83 });

await kv.put("salesreq:b915bad", JSON.stringify({ at: new Date().toISOString() }));
await kv.put("salesreq:d_keep", JSON.stringify({ at: new Date().toISOString() }));
r = await call("/api/fanza-sales-queue", { admin: true });
assert.deepEqual(r.json.queued, ["d_keep"]);
assert.equal(kv.map.has("salesreq:b915bad"), false, "旧版が残した対象外販売数キューも清掃する");
await kv.put("req:tw_999", JSON.stringify({ at: new Date().toISOString() }));
r = await call("/api/fanza-queue", { admin: true });
assert.equal(r.json.queued.includes("tw_999"), false);
assert.equal(kv.map.has("req:tw_999"), false, "旧版が残したSNS作品情報キューも清掃する");

console.log("PASS: candidate fetch queue / unavailable state / review preservation");