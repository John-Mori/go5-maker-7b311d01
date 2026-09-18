/**
 * test_persona_queue.mjs — POST /api/persona/enqueue を**実行で**通す(§3)。
 *
 * 偽物にするのは外へ出る手だけ= R2(SYNC_IMAGES)/KV(SYNC) をメモリのスタブに差し替える。
 * 判定・分岐(認証・バリデーション・重複判定・容量上限・実体存在チェック)は本物のまま走らせる。
 *
 * 走らせ方: node sync-worker/test_persona_queue.mjs
 */
import worker from "./src/index.js";

const KEY_A = "a".repeat(64);
const KEY_B = "b".repeat(64);

function makeEnv(opts = {}) {
  const r2 = new Map(opts.r2 || []);
  return {
    SYNC_TOKEN: "T0KEN",
    ALLOWED_ORIGINS: "*",
    SYNC: null, // KV未設定= rateLimited は通す(fail-open)。本物の分岐をそのまま踏ませる。
    _r2: r2,
    SYNC_IMAGES: {
      async head(k) { return r2.has(k) ? { key: k } : null; },
      async get(k) {
        if (!r2.has(k)) return null;
        const v = r2.get(k);
        return { async text() { return typeof v === "string" ? v : new TextDecoder().decode(v); } };
      },
      async put(k, v) { r2.set(k, v); return { key: k }; },
    },
  };
}

function post(body, token = "T0KEN") {
  return new Request("https://go5-sync.example/api/persona/enqueue", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Sync-Token": token },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function getEdit(key, token = "T0KEN") {
  return new Request("https://go5-sync.example/api/persona/edit/" + key, {
    headers: { "X-Sync-Token": token },
  });
}

let pass = 0, fail = 0;
async function check(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) { pass++; console.log("  PASS " + name); }
  else { fail++; console.log("  FAIL " + name + "\n    got : " + JSON.stringify(got) + "\n    want: " + JSON.stringify(want)); }
}

async function run() {
  // 1) トークン不一致= 403(R2は空でも認証が先に効く)
  {
    const env = makeEnv();
    const res = await worker.fetch(post({ persona: "アメス", key: KEY_A }, "WRONG"), env, {});
    await check("トークン不一致→403", [res.status, (await res.json()).error], [403, "bad_token"]);
  }
  // 2) persona が空= 400
  {
    const env = makeEnv({ r2: [[KEY_A, new Uint8Array([1])]] });
    const res = await worker.fetch(post({ persona: "   ", key: KEY_A }), env, {});
    await check("persona空→400", [res.status, (await res.json()).error], [400, "bad_body"]);
  }
  // 3) key が sha256 hex でない= 400
  {
    const env = makeEnv();
    const res = await worker.fetch(post({ persona: "アメス", key: "../etc/passwd" }), env, {});
    await check("不正key→400", [res.status, (await res.json()).error], [400, "bad_body"]);
  }
  // 4) 実体が R2 に無い= 409(先に PUT /api/img/:key を通す約束の強制)
  {
    const env = makeEnv();
    const res = await worker.fetch(post({ persona: "アメス", key: KEY_A }), env, {});
    await check("実体なし→409", [res.status, (await res.json()).error], [409, "key_not_uploaded"]);
  }
  // 5) 正常= 200・queue.jsonl が1行になる
  {
    const env = makeEnv({ r2: [[KEY_A, new Uint8Array([1])]] });
    const res = await worker.fetch(post({ persona: "アメス", key: KEY_A, ct: "image/png" }), env, {});
    const body = await res.json();
    const q = env._r2.get("persona/queue.jsonl") || "";
    const rec = JSON.parse(q.trim());
    await check("正常→200/1行", [res.status, body.ok, body.line, q.split("\n").filter(Boolean).length], [200, true, 1, 1]);
    await check("行の中身", [rec.persona, rec.key, rec.ct], ["アメス", KEY_A, "image/png"]);
  }
  // 6) 同じ (persona,key) の二度押し= 冪等・行が増えない
  {
    const env = makeEnv({ r2: [[KEY_A, new Uint8Array([1])]] });
    await worker.fetch(post({ persona: "アメス", key: KEY_A }), env, {});
    const res = await worker.fetch(post({ persona: "アメス", key: KEY_A }), env, {});
    const body = await res.json();
    const q = env._r2.get("persona/queue.jsonl") || "";
    await check("二度押し→冪等", [body.ok, body.deduped, q.split("\n").filter(Boolean).length], [true, true, 1]);
  }
  // 7) 同じ key を**別の人格**へ= 別行として積む(同じ絵を2人に使う場合)
  {
    const env = makeEnv({ r2: [[KEY_A, new Uint8Array([1])]] });
    await worker.fetch(post({ persona: "アメス", key: KEY_A }), env, {});
    await worker.fetch(post({ persona: "トトリ", key: KEY_A }), env, {});
    const q = env._r2.get("persona/queue.jsonl") || "";
    await check("別人格・同key→2行", q.split("\n").filter(Boolean).length, 2);
  }
  // 8) 2件積むと行番号が進む
  {
    const env = makeEnv({ r2: [[KEY_A, new Uint8Array([1])], [KEY_B, new Uint8Array([2])]] });
    await worker.fetch(post({ persona: "アメス", key: KEY_A }), env, {});
    const res = await worker.fetch(post({ persona: "アメス", key: KEY_B }), env, {});
    await check("2件目→line=2", (await res.json()).line, 2);
  }
  // 9) 容量上限超え= **黙って捨てず** 507(静かな喪失を作らない)
  {
    const env = makeEnv({ r2: [[KEY_A, new Uint8Array([1])], ["persona/queue.jsonl", "x".repeat(256 * 1024 + 1)]] });
    const res = await worker.fetch(post({ persona: "アメス", key: KEY_A }), env, {});
    await check("上限超え→507", [res.status, (await res.json()).error], [507, "queue_full"]);
  }
  // 10) 壊れたJSON body= 400(500で落ちない)
  {
    const env = makeEnv();
    const res = await worker.fetch(post("{壊れて", "T0KEN"), env, {});
    await check("壊れたbody→400", [res.status, (await res.json()).error], [400, "bad_body"]);
  }
  // 11) 元画像と正方形編集レシピを保存し、完成画像keyから再取得できる
  {
    const edit = { version: 1, rot: 90, crop: { x: 12.5, y: 20, size: 300 }, source: { width: 900, height: 1200 }, outputSize: 512 };
    const env = makeEnv({ r2: [[KEY_A, new Uint8Array([1])], [KEY_B, new Uint8Array([2])]] });
    const res = await worker.fetch(post({ persona: "アメス", key: KEY_A, ct: "image/png", sourceKey: KEY_B, sourceCt: "image/jpeg", edit }), env, {});
    const body = await res.json();
    const queueRec = JSON.parse(env._r2.get("persona/queue.jsonl").trim());
    const metaKey = "persona/edit/" + KEY_A + ".json";
    await check("元画像・編集情報をキューと固定メタへ保存", [res.status, body.ok, queueRec.sourceKey, env._r2.has(metaKey)], [200, true, KEY_B, true]);
    const got = await worker.fetch(getEdit(KEY_A), env, {});
    const meta = await got.json();
    await check("編集情報を再取得", [got.status, meta.ok, meta.sourceKey, meta.edit.rot, meta.edit.crop.size], [200, true, KEY_B, 90, 300]);
  }
  // 12) 元画像の実体が無ければ受け付けない
  {
    const env = makeEnv({ r2: [[KEY_A, new Uint8Array([1])]] });
    const edit = { rot: 0, crop: { x: 0, y: 0, size: 100 }, source: { width: 100, height: 100 } };
    const res = await worker.fetch(post({ persona: "アメス", key: KEY_A, sourceKey: KEY_B, edit }), env, {});
    await check("元画像なし→409", [res.status, (await res.json()).error], [409, "source_not_uploaded"]);
  }
  // 13) 編集情報はトークン必須・未知keyは404
  {
    const env = makeEnv();
    const denied = await worker.fetch(getEdit(KEY_A, "WRONG"), env, {});
    const missing = await worker.fetch(getEdit(KEY_A), env, {});
    await check("編集情報の認証と404", [denied.status, missing.status], [403, 404]);
  }
  // 14) 既存の口を壊していないこと= GET / と 未知パスの 404
  {
    const env = makeEnv();
    const ok = await worker.fetch(new Request("https://go5-sync.example/"), env, {});
    const nf = await worker.fetch(new Request("https://go5-sync.example/api/nope"), env, {});
    await check("既存: GET / とパス外", [ok.status, await ok.text(), nf.status], [200, "go5-sync ok", 404]);
  }
  // 15) 既存の口を壊していないこと= PUT /api/img/:key が今までどおり動く
  {
    const env = makeEnv();
    const res = await worker.fetch(new Request("https://go5-sync.example/api/img/" + KEY_A, {
      method: "PUT", headers: { "X-Sync-Token": "T0KEN", "Content-Type": "image/png" }, body: new Uint8Array([1, 2, 3]),
    }), env, {});
    const body = await res.json();
    await check("既存: PUT /api/img/:key", [res.status, body.ok, body.key, env._r2.has(KEY_A)], [200, true, KEY_A, true]);
  }

  console.log("\n" + pass + " PASS / " + fail + " FAIL");
  process.exit(fail ? 1 : 0);
}
run();
