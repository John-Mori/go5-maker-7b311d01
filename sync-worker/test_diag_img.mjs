/**
 * test_diag_img.mjs — POST /api/diag/img(画像が読めなかった記録の受け口)を実行で通す。
 * R2 だけメモリのスタブ。認証・追記・項目の切り詰め・上限は本物のまま走らせる。
 *
 * 走らせ方: node sync-worker/test_diag_img.mjs
 */
import worker from "./src/index.js";

function makeEnv(init) {
  const r2 = new Map(init || []);
  return {
    SYNC_TOKEN: "T0KEN", ALLOWED_ORIGINS: "*", SYNC: null, _r2: r2,
    SYNC_IMAGES: {
      async head(k) { return r2.has(k) ? { key: k } : null; },
      async get(k) { return r2.has(k) ? { async text() { return r2.get(k); } } : null; },
      async put(k, v) { r2.set(k, v); return { key: k }; },
    },
  };
}
function req(body, token = "T0KEN", method = "POST") {
  return new Request("https://go5-sync.example/api/diag/img", {
    method, headers: { "X-Sync-Token": token, "Content-Type": "application/json", "User-Agent": "TestUA" },
    body: method === "POST" ? JSON.stringify(body) : undefined,
  });
}

let pass = 0, fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { pass++; console.log("  PASS " + name); }
  else { fail++; console.log("  FAIL " + name + "\n    got : " + JSON.stringify(got) + "\n    want: " + JSON.stringify(want)); }
}

const day = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
const K = "diag/img/" + day + ".jsonl";
const HASH = "c".repeat(64);

let env = makeEnv();
let r = await worker.fetch(req({ events: [{ ev: "ref_cdn_err", cid: "d_1", key: HASH, status: 404, outcome: "local" }] }, "WRONG"), env, {});
check("トークン違いは403で書かない", [r.status, env._r2.has(K)], [403, false]);

r = await worker.fetch(req({ events: [{ ev: "ref_cdn_err", cid: "d_1", key: HASH, status: 404, outcome: "local" }] }), env, {});
check("1件を当日のjsonlへ足す", [r.status, await r.json()], [200, { ok: true, added: 1 }]);
let rows = env._r2.get(K).trim().split("\n").map((s) => JSON.parse(s));
check("中身", [rows[0].ev, rows[0].cid, rows[0].key, rows[0].status, rows[0].outcome, rows[0].ua], ["ref_cdn_err", "d_1", HASH, 404, "local", "TestUA"]);

r = await worker.fetch(req({ events: [{ ev: "ref_cdn_err", cid: "d_2", key: "not-a-hash", status: 0, outcome: "none" }, { cid: "no_ev" }] }), env, {});
rows = env._r2.get(K).trim().split("\n").map((s) => JSON.parse(s));
check("追記で前の行を消さない・evの無い行は捨てる", rows.length, 2);
check("hashでないkeyは空にする", rows[1].key, "");

r = await worker.fetch(req({ events: [] }), env, {});
check("空は400", r.status, 400);

env = makeEnv([[K, "x".repeat(128 * 1024 + 1)]]);
r = await worker.fetch(req({ events: [{ ev: "ref_cdn_err", cid: "d_3" }] }), env, {});
check("上限超えは507で足さない", [r.status, env._r2.get(K).length], [507, 128 * 1024 + 1]);

r = await worker.fetch(req(null, "T0KEN", "GET"), env, {});
check("GETの読み口は無い", r.status, 404);

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
