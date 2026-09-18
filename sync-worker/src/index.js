/**
 * sync-worker — 5秒動画メーカー 全端末クラウド同期の基盤。
 *
 * 役割：どの端末からでも「素材(候補)・設定・投稿履歴・(暗号化した)鍵」を常に最新で同期する。
 *   ・状態(JSON) … R2 に version 付きで1ドキュメント保持（楽観的並行制御）。旧KVは初回移行元として読む。
 *   ・画像(漫画ページ等) … R2 に content-hash(sha256) キーで保存＝重複排除・不変。
 *
 * エンドポイント（/api/* は X-Sync-Token 必須・Origin許可＋CORS）：
 *   GET  /                      → ヘルスチェック（"go5-sync ok"）
 *   GET  /api/pull              → { ok, empty?|blob, version, updatedAt, device }
 *   POST /api/push              → body {blob, updatedAt, device, baseVersion}
 *                                  baseVersion が現行と一致→保存し version+1。
 *                                  不一致→{ ok:false, conflict:true, version, blob }（呼び出し側でマージ再送）。
 *   GET  /api/img/has?keys=a,b  → { ok, present:[...存在するkey] }（アップロード要否の判定）
 *   PUT  /api/img/:key          → 本文=画像バイト。R2 に保存（既存なら何もしない＝冪等）。{ ok, key }
 *   GET  /img/:key              → R2 から配信（トークン不要＝<img src>用・key は sha256 で推測困難・長期キャッシュ）
 *   POST /api/persona/enqueue   → body {persona, key, sourceKey, edit}。完成画像と元画像を結ぶ「申告」を
 *                                  R2 persona/queue.jsonl へ**追記だけ**する。{ ok, line }
 *   GET  /api/persona/edit/:key → 登録後の再編集用に、元画像keyと正方形切り抜き情報を返す。
 *   GET  /api/teian/latest       → 提案候補の当日JSONを配信（トークン必須）。R2 teian/latest.json。
 *   GET  /api/teian/:date        → 指定日(YYYY-MM-DD)の提案候補JSON。R2 teian/<date>.json。未配信は {empty:true}。
 *                                  ※書き込みは wrangler r2 object put（PC側=scripts/teian/publish_candidates.py）。
 *
 * セキュリティ：
 *   ・/api/* は X-Sync-Token（env.SYNC_TOKEN）一致必須。Origin は env.ALLOWED_ORIGINS（"*"可）。
 *   ・鍵(アプリPW等)は「クライアント側でパスフレーズ暗号化済み」の文字列として blob に含まれる前提＝
 *     このworkerは平文の鍵を一切扱わない/知らない（暗号文をそのまま保管するだけ）。
 *   ・同期状態と画像はR2へ保存。KV上限に達しても端末同期を止めない。
 *
 * バインディング（wrangler.toml 参照）：KV=SYNC / R2=SYNC_IMAGES / Secret=SYNC_TOKEN / Var=ALLOWED_ORIGINS
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const origin = request.headers.get("Origin") || "";
    const cors = corsHeaders(origin, env);

    if (request.method === "OPTIONS") return preflight(origin, env);

    // 画像配信（トークン不要・GET/HEAD）。key は sha256 hex 前提。
    if (path.startsWith("/img/")) {
      if (request.method !== "GET" && request.method !== "HEAD") return json({ ok: false, error: "method_not_allowed" }, 405, {});
      return serveImage(decodeURIComponent(path.slice(5)), env, request.method === "HEAD");
    }

    // 画像アップロード（PUT /api/img/:key）
    if (path.startsWith("/api/img/") && request.method === "PUT") {
      if (!authOk(request, env)) return json({ ok: false, error: "bad_token" }, 403, cors);

      return putImage(decodeURIComponent(path.slice(9)), request, env, cors, url.searchParams.get("replace") === "1");
    }

    // 画像存在確認（GET /api/img/has?keys=a,b,c）
    if (path === "/api/img/has") {
      if (!authOk(request, env)) return json({ ok: false, error: "bad_token" }, 403, cors);
      return imgHas(url, env, cors);
    }

    // 状態 pull
    if (path === "/api/pull") {
      if (!authOk(request, env)) return json({ ok: false, error: "bad_token" }, 403, cors);
      return statePull(env, cors);
    }

    // 提案候補(日次JSON)配信 — PCの軍議が R2 の teian/<date>.json / teian/latest.json へ置いた
    //   当日分を、スマホの提案決定ページ(KouhoTeian.html)が取り込むための読み取り口。
    //   PC側の書き込みは wrangler r2 object put(=アカウント資格)で行う=SYNC_TOKENをPCへ置かない。
    //   読み取りは /api/pull と同じくトークン必須(候補リストは内部データ)。フロントは sync2_token を送る。
    if (path === "/api/teian/latest" || path.startsWith("/api/teian/")) {
      if (request.method !== "GET" && request.method !== "HEAD") return json({ ok: false, error: "method_not_allowed" }, 405, cors);
      if (!authOk(request, env)) return json({ ok: false, error: "bad_token" }, 403, cors);
      return serveTeian(decodeURIComponent(path.slice("/api/teian/".length)), env, cors);
    }

    // 人格ハブ アイコン追加の申告（POST /api/persona/enqueue）
    if (path === "/api/persona/enqueue" && request.method === "POST") {
      if (!authOk(request, env)) return json({ ok: false, error: "bad_token" }, 403, cors);
      return personaEnqueue(request, env, cors);
    }

    // 登録後の再編集。完成画像keyから元画像と編集レシピを引く(トークン必須)。
    if (path.startsWith("/api/persona/edit/") && request.method === "GET") {
      if (!authOk(request, env)) return json({ ok: false, error: "bad_token" }, 403, cors);
      return personaEdit(decodeURIComponent(path.slice("/api/persona/edit/".length)), env, cors);
    }
    // 状態 push
    if (path === "/api/push" && request.method === "POST") {
      if (!authOk(request, env)) return json({ ok: false, error: "bad_token" }, 403, cors);

      return statePush(request, env, cors);
    }

    if (path === "/" ) return text("go5-sync ok", 200);
    return json({ ok: false, error: "not_found" }, 404, cors);
  },
};

// ── 認証・CORS ─────────────────────────────────────────────
function authOk(request, env) {
  const tok = request.headers.get("X-Sync-Token") || "";
  const want = String(env.SYNC_TOKEN || "");
  return !!want && tok === want;
}
function allowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
}
function corsHeaders(origin, env) {
  const list = allowedOrigins(env);
  const allow = list.includes("*") ? (origin || "*") : (list.includes(origin) ? origin : (list[0] || ""));
  return {
    "Access-Control-Allow-Origin": allow || "*",
    "Access-Control-Allow-Headers": "Content-Type, X-Sync-Token",
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Vary": "Origin",
  };
}
function preflight(origin, env) {
  return new Response(null, { status: 204, headers: corsHeaders(origin, env) });
}

// ── 状態(JSON) ─────────────────────────────────────────────
// R2を正本にする。旧KV(state:doc/state:meta)はR2が空の時だけ移行元として読む。
// KVの日次上限に達して読み出せなくても empty として開始し、次のpushでR2へ着地させる。
const STATE_R2_KEY = "state/sync-v1.json";
async function readStateBundle(env) {
  if (env.SYNC_IMAGES) {
    try {
      const obj = await env.SYNC_IMAGES.get(STATE_R2_KEY);
      if (obj) {
        const saved = parseJson(await obj.text());
        if (saved && typeof saved.blob === "string") return {
          empty: false, blob: saved.blob, version: Number(saved.version || 0),
          updatedAt: String(saved.updatedAt || ""), device: String(saved.device || ""), source: "r2"
        };
      }
    } catch (e) {}
  }
  if (env.SYNC) {
    try {
      const blob = await env.SYNC.get("state:doc");
      if (blob !== null) {
        const meta = parseJson(await env.SYNC.get("state:meta")) || {};
        return { empty: false, blob, version: Number(meta.version || 0), updatedAt: String(meta.updatedAt || ""), device: String(meta.device || ""), source: "kv" };
      }
    } catch (e) {
      return { empty: true, version: 0, degraded: "kv_unavailable" };
    }
  }
  return { empty: true, version: 0 };
}
async function statePull(env, cors) {
  if (!env.SYNC_IMAGES && !env.SYNC) return json({ ok: false, error: "storage_unset" }, 500, cors);
  const state = await readStateBundle(env);
  if (state.empty) return json({ ok: true, empty: true, version: 0, degraded: state.degraded || "" }, 200, cors);
  // 旧KVから読めた時点でR2へ一度だけ移行。以後のpull/pushはKVを消費しない。
  if (state.source === "kv" && env.SYNC_IMAGES) {
    try {
      await env.SYNC_IMAGES.put(STATE_R2_KEY, JSON.stringify({ blob: state.blob, version: state.version, updatedAt: state.updatedAt, device: state.device }), {
        httpMetadata: { contentType: "application/json", cacheControl: "no-store" }
      });
    } catch (e) {}
  }
  return json({ ok: true, blob: state.blob, version: state.version, updatedAt: state.updatedAt, device: state.device }, 200, cors);
}
async function statePush(request, env, cors) {
  if (!env.SYNC_IMAGES && !env.SYNC) return json({ ok: false, error: "storage_unset" }, 500, cors);
  const body = parseJson(await request.text());
  if (!body || typeof body.blob !== "string") return json({ ok: false, error: "bad_body" }, 400, cors);
  if (body.blob.length > 8 * 1024 * 1024) return json({ ok: false, error: "too_large" }, 413, cors);
  const current = await readStateBundle(env);
  const cur = Number(current.version || 0), base = Number(body.baseVersion || 0);
  if (!current.empty && cur !== 0 && base !== cur) {
    return json({ ok: false, conflict: true, version: cur, blob: current.blob, updatedAt: current.updatedAt || "", device: current.device || "" }, 200, cors);
  }
  const nextMeta = { blob: body.blob, version: cur + 1, updatedAt: body.updatedAt || new Date().toISOString(), device: String(body.device || "") };
  if (env.SYNC_IMAGES) {
    await env.SYNC_IMAGES.put(STATE_R2_KEY, JSON.stringify(nextMeta), {
      httpMetadata: { contentType: "application/json", cacheControl: "no-store" }
    });
  } else {
    // R2未設定環境だけの後方互換。通常運用では通らない。
    await env.SYNC.put("state:doc", body.blob);
    await env.SYNC.put("state:meta", JSON.stringify({ version: nextMeta.version, updatedAt: nextMeta.updatedAt, device: nextMeta.device }));
  }
  return json({ ok: true, version: nextMeta.version, updatedAt: nextMeta.updatedAt }, 200, cors);
}
// ── 画像(R2) ───────────────────────────────────────────────
function validKey(k) { return /^[a-f0-9]{16,64}$/.test(String(k || "")); } // sha256 hex（推測困難・パス安全）
async function putImage(key, request, env, cors, replace) {
  if (!env.SYNC_IMAGES) return json({ ok: false, error: "r2_unset" }, 500, cors);
  if (!validKey(key)) return json({ ok: false, error: "bad_key" }, 400, cors);
  const existing = replace ? null : await env.SYNC_IMAGES.head(key);
  if (existing) return json({ ok: true, key, deduped: true }, 200, cors); // content-hashは冪等。論理名previewはreplace=1で完成動画に合わせて更新
  const ct = request.headers.get("Content-Type") || "application/octet-stream";
  const buf = await request.arrayBuffer();
  if (buf.byteLength > 30 * 1024 * 1024) return json({ ok: false, error: "img_too_large" }, 413, cors); // 画像+5秒動画本体(②)を許容=30MB
  await env.SYNC_IMAGES.put(key, buf, { httpMetadata: { contentType: ct, cacheControl: "public, max-age=31536000, immutable" } });
  return json({ ok: true, key }, 200, cors);
}
async function serveImage(key, env, headOnly) {
  if (!env.SYNC_IMAGES) return text("r2 unset", 500);
  if (!validKey(key)) return text("bad key", 400);
  const obj = await env.SYNC_IMAGES.get(key);
  if (!obj) return text("not found", 404);
  const headers = new Headers();
  obj.writeHttpMetadata(headers);
  headers.set("Cache-Control", "public, max-age=31536000, immutable");
  headers.set("Access-Control-Allow-Origin", "*");
  headers.set("etag", obj.httpEtag);
  return new Response(headOnly ? null : obj.body, { status: 200, headers });
}
// ── 提案候補(日次JSON) ───────────────────────────────────────
//   キー = teian/latest.json（当日の指す先）/ teian/<YYYY-MM-DD>.json（日付固定）。
//   未配信/無効日付は空(fail-open)= ページは「候補を読み込んでください」を出すだけで壊れない。
async function serveTeian(name, env, cors) {
  if (!env.SYNC_IMAGES) return json({ ok: false, error: "r2_unset" }, 500, cors);
  var key;
  if (name === "latest" || name === "") key = "teian/latest.json";
  else if (/^\d{4}-\d{2}-\d{2}$/.test(name)) key = "teian/" + name + ".json"; // 日付以外は弾く=パス横断防止
  else return json({ ok: true, empty: true, candidates: [] }, 200, cors);
  const obj = await env.SYNC_IMAGES.get(key);
  if (!obj) return json({ ok: true, empty: true, candidates: [] }, 200, cors);
  const body = await obj.text();
  return new Response(body, { status: 200, headers: Object.assign({ "Content-Type": "application/json", "Cache-Control": "no-store" }, cors || {}) });
}
async function imgHas(url, env, cors) {
  if (!env.SYNC_IMAGES) return json({ ok: false, error: "r2_unset" }, 500, cors);
  const keys = String(url.searchParams.get("keys") || "").split(",").map((s) => s.trim()).filter(validKey).slice(0, 200);
  const present = [];
  for (const k of keys) { if (await env.SYNC_IMAGES.head(k)) present.push(k); }
  return json({ ok: true, present }, 200, cors);
}

// ── 人格ハブ アイコン追加の申告キュー ───────────────────────────
//   なぜ要るか(2026-09-01 イージス研究室):
//     画像バイトの口は既に在る(PUT /api/img/:key)。足りないのは「そのkeyが誰のアイコンか」を
//     PC側へ伝える道だけだった。R2のオブジェクト一覧は wrangler に無い(get/put/delete のみ)ため、
//     PC のポーラーは新着を発見できない。→ **固定キー1本の追記ログ**にして、
//     PC は `wrangler r2 object get go5-sync-images/persona/queue.jsonl`(=アカウント資格)で読む。
//   ★SYNC_TOKEN を PC へ置かない設計を崩さない(teian と同じ向き)= 書きは Worker・読みは wrangler。
//   ★消さない= 1行ずつ追記するだけ。PC側が自分のカーソル(行数)を持つ。
//     箱を空にしてから処理する形にすると、その隙に落ちた分が無言で消える(実害の記録あり)。
const PQ_KEY = "persona/queue.jsonl";
const PQ_MAX = 256 * 1024; // これを超えたら**黙って捨てず**エラーで返す(静かな喪失を作らない)
const PE_PREFIX = "persona/edit/";
function safeName(s) {
  const t = String(s || "").replace(/[\x00-\x1f\x7f]/g, "").trim();
  return t.length >= 1 && t.length <= 40 ? t : "";
}
async function personaEnqueue(request, env, cors) {
  if (!env.SYNC_IMAGES) return json({ ok: false, error: "r2_unset" }, 500, cors);
  const body = parseJson(await request.text());
  const persona = safeName(body && body.persona);
  const key = String((body && body.key) || "");
  const sourceKey = String((body && body.sourceKey) || key);
  const sourceCt = String((body && body.sourceCt) || "").slice(0, 80);
  const edit = safeAvatarEdit(body && body.edit);
  if (!persona || !validKey(key)) return json({ ok: false, error: "bad_body" }, 400, cors);
  if (!validKey(sourceKey) || ((body && body.edit) && !edit)) return json({ ok: false, error: "bad_edit" }, 400, cors);
  // 申告された key の実体が R2 に在ることを先に確かめる(先に PUT /api/img/:key を通す約束)。
  if (!(await env.SYNC_IMAGES.head(key))) return json({ ok: false, error: "key_not_uploaded" }, 409, cors);
  if (!(await env.SYNC_IMAGES.head(sourceKey))) return json({ ok: false, error: "source_not_uploaded" }, 409, cors);
  const cur = await env.SYNC_IMAGES.get(PQ_KEY);
  const prev = cur ? await cur.text() : "";
  if (prev.length > PQ_MAX) return json({ ok: false, error: "queue_full" }, 507, cors);
  const editRec = { persona, key, ct: String((body && body.ct) || "").slice(0, 80), sourceKey, sourceCt, edit, at: new Date().toISOString() };
  // 完成画像keyごとの固定メタ。キューが台帳へ着地した後も再編集に使うため消さない。
  await env.SYNC_IMAGES.put(PE_PREFIX + key + ".json", JSON.stringify(editRec), {
    httpMetadata: { contentType: "application/json", cacheControl: "no-store" }
  });
  // 同じ (persona,key) が既に申告済みなら足さない(冪等)。ページの二度押しで行が増えない。
  const dup = '"persona":' + JSON.stringify(persona) + ',"key":"' + key + '"';
  if (prev.indexOf(dup) >= 0) return json({ ok: true, deduped: true, line: prev.split("\n").filter(Boolean).length }, 200, cors);
  const rec = JSON.stringify(editRec);
  const next = prev + (prev.endsWith("\n") || prev === "" ? "" : "\n") + rec + "\n";
  // ★read-modify-write= 同時申告が重なると片方が消えうる。手作業でアイコンを足す用途では
  //   同時実行が起きない前提。起きたらページ側が再申告すれば冪等に戻る(消えた行は残らない)。
  await env.SYNC_IMAGES.put(PQ_KEY, next, { httpMetadata: { contentType: "application/x-ndjson", cacheControl: "no-store" } });
  return json({ ok: true, line: next.split("\n").filter(Boolean).length }, 200, cors);
}

function safeAvatarEdit(value) {
  if (value == null) return null;
  if (typeof value !== "object" || Array.isArray(value)) return null;
  const rot = Number(value.rot);
  const c = value.crop || {};
  const source = value.source || {};
  const nums = [Number(c.x), Number(c.y), Number(c.size), Number(source.width), Number(source.height)];
  if (![0, 90, 180, 270].includes(rot) || nums.some((n) => !Number.isFinite(n)) || Number(c.size) <= 0) return null;
  const clean = {
    version: 1,
    rot,
    crop: { x: nums[0], y: nums[1], size: nums[2] },
    source: { width: nums[3], height: nums[4] },
    outputSize: 512,
  };
  return JSON.stringify(clean).length <= 1024 ? clean : null;
}

async function personaEdit(key, env, cors) {
  if (!env.SYNC_IMAGES) return json({ ok: false, error: "r2_unset" }, 500, cors);
  if (!validKey(key)) return json({ ok: false, error: "bad_key" }, 400, cors);
  const obj = await env.SYNC_IMAGES.get(PE_PREFIX + key + ".json");
  if (!obj) return json({ ok: false, error: "edit_not_found" }, 404, cors);
  const rec = parseJson(await obj.text());
  return rec ? json(Object.assign({ ok: true }, rec), 200, cors) : json({ ok: false, error: "edit_corrupt" }, 500, cors);
}

// ── ユーティリティ ─────────────────────────────────────────
function parseJson(s) { try { return JSON.parse(s); } catch (e) { return null; } }
function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), { status, headers: Object.assign({ "Content-Type": "application/json" }, cors || {}) });
}
function text(s, status) { return new Response(s, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } }); }
