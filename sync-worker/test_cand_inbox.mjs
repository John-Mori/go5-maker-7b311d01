/**
 * test_cand_inbox.mjs — GET /api/cand-inbox(Grok候補の受け箱)を実行で通す。
 * R2 だけメモリのスタブ。認証・未配信時の空応答・中身の素通しは本物のまま走らせる。
 *
 * 走らせ方: node sync-worker/test_cand_inbox.mjs
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
function req(method, token = "T0KEN") {
  return new Request("https://go5-sync.example/api/cand-inbox", {
    method, headers: { "X-Sync-Token": token },
  });
}

let pass = 0, fail = 0;
function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { pass++; console.log("  PASS " + name); }
  else { fail++; console.log("  FAIL " + name + "\n    got : " + JSON.stringify(got) + "\n    want: " + JSON.stringify(want)); }
}

// 未配信=空
let env = makeEnv();
let r = await worker.fetch(req("GET"), env, {});
check("未配信は200で empty", [r.status, await r.json()], [200, { ok: true, empty: true, items: [] }]);

// トークン違い=403(中身を出さない)
const doc = { ok: true, generatedAt: "2026-10-15T12:00:00+09:00", items: [{ cid: "d_1", postVerified: false }] };
env = makeEnv([["cand_inbox/latest.json", JSON.stringify(doc)]]);
r = await worker.fetch(req("GET", "WRONG"), env, {});
check("トークン違いは403", r.status, 403);

// 正しいトークン=中身をそのまま返す
r = await worker.fetch(req("GET"), env, {});
check("配信済みは中身を返す", [r.status, await r.json()], [200, doc]);
check("no-store", r.headers.get("Cache-Control"), "no-store");

// 書き込みは受けない(書くのはPCのwranglerだけ)
r = await worker.fetch(req("POST"), env, {});
check("POSTは405", r.status, 405);

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
