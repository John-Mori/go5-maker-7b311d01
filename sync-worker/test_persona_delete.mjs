/**
 * test_persona_delete.mjs — POST /api/persona/delete と、削除後の上げ直し(enqueue)を実行で通す。
 * R2 だけメモリのスタブ。認証・重複判定・削除→再登録の順序判定は本物のまま走らせる。
 *
 * 走らせ方: node sync-worker/test_persona_delete.mjs
 */
import worker from "./src/index.js";

const KEY_A = "a".repeat(64);
const SRC = "c".repeat(64);

function makeEnv() {
  const r2 = new Map([[KEY_A, "x"], [SRC, "y"]]);
  return {
    SYNC_TOKEN: "T0KEN", ALLOWED_ORIGINS: "*", SYNC: null, _r2: r2,
    SYNC_IMAGES: {
      async head(k) { return r2.has(k) ? { key: k } : null; },
      async get(k) { return r2.has(k) ? { async text() { return r2.get(k); } } : null; },
      async put(k, v) { r2.set(k, v); return { key: k }; },
    },
  };
}
function req(path, body, token = "T0KEN") {
  return new Request("https://go5-sync.example" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Sync-Token": token },
    body: JSON.stringify(body),
  });
}
const lines = (env) => (env._r2.get("persona/queue.jsonl") || "").split("\n").filter(Boolean).map((l) => JSON.parse(l));

let pass = 0, fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { pass++; console.log("  PASS " + name); }
  else { fail++; console.log("  FAIL " + name + "\n    got : " + JSON.stringify(got) + "\n    want: " + JSON.stringify(want)); }
}

const env = makeEnv();
let r = await worker.fetch(req("/api/persona/delete", { persona: "アメス", key: KEY_A }, "WRONG"), env, {});
check("トークン不一致→403", r.status, 403);
r = await worker.fetch(req("/api/persona/delete", { persona: "アメス", key: "zz" }), env, {});
check("key不正→400", r.status, 400);

const add = { persona: "アメス", key: KEY_A, ct: "image/png", sourceKey: SRC, sourceCt: "image/png", edit: null };
await worker.fetch(req("/api/persona/enqueue", add), env, {});
r = await worker.fetch(req("/api/persona/delete", { persona: "アメス", key: KEY_A }), env, {});
check("削除→200", [r.status, (await r.json()).ok], [200, true]);
check("削除行が op:delete で積まれる", lines(env).map((l) => l.op || "add"), ["add", "delete"]);
r = await worker.fetch(req("/api/persona/delete", { persona: "アメス", key: KEY_A }), env, {});
check("二度押しは積まない", [(await r.json()).deduped, lines(env).length], [true, 2]);
r = await worker.fetch(req("/api/persona/enqueue", add), env, {});
check("削除後の上げ直しは積む", [(await r.json()).deduped || false, lines(env).map((l) => l.op || "add")], [false, ["add", "delete", "add"]]);
r = await worker.fetch(req("/api/persona/enqueue", add), env, {});
check("上げ直しの二度押しは積まない", [(await r.json()).deduped, lines(env).length], [true, 3]);
check("R2の画像実体は消さない", env._r2.has(KEY_A), true);

console.log(`\n${pass} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
