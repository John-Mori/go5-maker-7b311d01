import assert from "node:assert/strict";
import worker from "../deadman-worker/src/index.js";

class FakeR2Object {
  constructor(body) { this.body = body; }
  async text() { return this.body; }
}
class FakeR2 {
  constructor() { this.values = new Map(); this.puts = 0; }
  async get(key) { return this.values.has(key) ? new FakeR2Object(this.values.get(key)) : null; }
  async put(key, body) { this.puts++; this.values.set(key, String(body)); }
}
class FakeKv {
  constructor(values = {}) { this.values = new Map(Object.entries(values)); this.puts = 0; this.deletes = 0; }
  async get(key) { return this.values.has(key) ? this.values.get(key) : null; }
  async put(key, value) { this.puts++; this.values.set(key, value); }
  async delete(key) { this.deletes++; this.values.delete(key); }
}

const r2 = new FakeR2();
const kv = new FakeKv();
const env = { DEADMAN_STATE: r2, DEADMAN: kv, BEAT_SECRET: "secret", STALE_MIN: "35" };
const beat = await worker.fetch(new Request("https://deadman.test/beat", {
  method: "POST", headers: { "X-Beat-Secret": "secret" },
}), env);
assert.equal(beat.status, 204);
assert.equal(r2.puts, 1, "heartbeat writes one R2 object");
assert.equal(kv.puts + kv.deletes, 0, "heartbeat performs zero KV writes");
const status = await worker.fetch(new Request("https://deadman.test/status"), env);
const body = await status.json();
assert.ok(body.last_beat > 0);
assert.equal(body.alerted, false);
assert.ok(body.age_sec >= 0);

const legacyR2 = new FakeR2();
const legacyKv = new FakeKv({ last_beat: "12345", alerted: "1" });
const legacyEnv = { DEADMAN_STATE: legacyR2, DEADMAN: legacyKv };
const legacyStatus = await worker.fetch(new Request("https://deadman.test/status"), legacyEnv);
const legacyBody = await legacyStatus.json();
assert.equal(legacyBody.last_beat, 12345);
assert.equal(legacyBody.alerted, true);
assert.equal(legacyR2.puts, 1, "legacy KV state migrates once to R2");
assert.equal(legacyKv.puts + legacyKv.deletes, 0, "migration never writes KV");
console.log("deadman-worker R2 state tests: ok");
