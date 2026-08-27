const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "..", "sync-worker", "src", "index.js"), "utf8");
const runnable = source.replace("export default {", "globalThis.__syncWorker = {");
const context = { URL, Request, Response, Headers, Blob, Uint8Array, ArrayBuffer, TextEncoder, TextDecoder, console };
context.globalThis = context;
vm.runInNewContext(runnable, context, { filename: "sync-worker/src/index.js" });
const worker = context.__syncWorker;
assert.ok(worker && typeof worker.fetch === "function");

function memoryR2() {
  const values = new Map();
  return {
    values,
    async get(key) {
      if (!values.has(key)) return null;
      const value = values.get(key);
      return { text: async () => String(value), body: value, httpEtag: "etag" };
    },
    async put(key, value) {
      values.set(key, typeof value === "string" ? value : value);
      return {};
    },
    async head(key) { return values.has(key) ? { key } : null; }
  };
}
function req(path, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set("X-Sync-Token", "test-token");
  return new Request("https://sync.example.test" + path, { ...init, headers });
}
async function bodyOf(response) { return response.json(); }

(async function run() {
const r2 = memoryR2();
let kvGets = 0, kvPuts = 0;
const unavailableKv = {
  async get() { kvGets++; throw new Error("KV daily limit exceeded"); },
  async put() { kvPuts++; throw new Error("KV daily limit exceeded"); }
};
const env = { SYNC_IMAGES: r2, SYNC: unavailableKv, SYNC_TOKEN: "test-token", ALLOWED_ORIGINS: "*" };

// R2がまだ空でKV上限中でも、pullを失敗させずローカル状態の初回pushを許可する。
let response = await worker.fetch(req("/api/pull"), env, {});
let body = await bodyOf(response);
assert.equal(response.status, 200);
assert.equal(body.ok, true);
assert.equal(body.empty, true);
assert.equal(body.degraded, "kv_unavailable");

const firstBlob = JSON.stringify({ fmt: 2, ls: { cand_items: { t: 1, v: '[{"cid":"pc-new"}]' } }, idb: {} });
response = await worker.fetch(req("/api/push", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ blob: firstBlob, baseVersion: 0, device: "PC" })
}), env, {});
body = await bodyOf(response);
assert.equal(body.ok, true);
assert.equal(body.version, 1);
assert.ok(r2.values.has("state/sync-v1.json"));
assert.equal(kvPuts, 0, "new state must never write KV");

// R2正本ができた後はpullでもKVへ触れず、即座に同じ候補状態を返す。
kvGets = 0;
response = await worker.fetch(req("/api/pull"), env, {});
body = await bodyOf(response);
assert.equal(body.blob, firstBlob);
assert.equal(body.version, 1);
assert.equal(kvGets, 0);

// 古いbaseVersionは競合として返し、R2の正本を失わない。
response = await worker.fetch(req("/api/push", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ blob: "{}", baseVersion: 0, device: "phone" })
}), env, {});
body = await bodyOf(response);
assert.equal(body.conflict, true);
assert.equal(body.blob, firstBlob);

// 画像PUTもKVレートカウンタを使わず、KV上限中にR2へ着地できる。
kvGets = 0;
const imageKey = "a".repeat(64);
response = await worker.fetch(req("/api/img/" + imageKey, {
  method: "PUT", headers: { "Content-Type": "image/png" }, body: new Uint8Array([1, 2, 3])
}), env, {});
body = await bodyOf(response);
assert.equal(body.ok, true);
assert.equal(kvGets, 0);

// content-hashは従来どおり重複PUTを省き、論理名previewだけはreplace=1で完成フレームへ更新できる。
response = await worker.fetch(req("/api/img/" + imageKey, {
  method: "PUT", headers: { "Content-Type": "image/png" }, body: new Uint8Array([9, 9, 9, 9])
}), env, {});
body = await bodyOf(response);
assert.equal(body.deduped, true);
assert.equal(new Uint8Array(r2.values.get(imageKey)).length, 3);
response = await worker.fetch(req("/api/img/" + imageKey + "?replace=1", {
  method: "PUT", headers: { "Content-Type": "image/png" }, body: new Uint8Array([7, 8])
}), env, {});
body = await bodyOf(response);
assert.equal(body.ok, true);
assert.equal(new Uint8Array(r2.values.get(imageKey)).length, 2);

// KVが読める環境では旧stateを初回pullでR2へ自動移行する。
const legacyR2 = memoryR2();
const legacyBlob = JSON.stringify({ fmt: 2, ls: { cand_items: { t: 2, v: '[{"cid":"legacy"}]' } }, idb: {} });
const legacyKv = {
  async get(key) {
    if (key === "state:doc") return legacyBlob;
    if (key === "state:meta") return JSON.stringify({ version: 7, device: "old-PC" });
    return null;
  },
  async put() { throw new Error("legacy KV must stay read-only"); }
};
response = await worker.fetch(req("/api/pull"), { ...env, SYNC_IMAGES: legacyR2, SYNC: legacyKv }, {});
body = await bodyOf(response);
assert.equal(body.blob, legacyBlob);
assert.equal(body.version, 7);
assert.ok(legacyR2.values.has("state/sync-v1.json"));

console.log("PASS: sync worker R2 state / KV-limit fallback / legacy migration");
})().catch(function (error) { console.error(error); process.exitCode = 1; });