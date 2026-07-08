/**
 * sync-worker — 5秒動画メーカー 全端末クラウド同期の基盤。
 *
 * 役割：どの端末からでも「素材(候補)・設定・投稿履歴・(暗号化した)鍵」を常に最新で同期する。
 *   ・状態(JSON) … KV `state` に version 付きで1ドキュメント保持（楽観的並行制御）。
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
 *
 * セキュリティ：
 *   ・/api/* は X-Sync-Token（env.SYNC_TOKEN）一致必須。Origin は env.ALLOWED_ORIGINS（"*"可）。
 *   ・鍵(アプリPW等)は「クライアント側でパスフレーズ暗号化済み」の文字列として blob に含まれる前提＝
 *     このworkerは平文の鍵を一切扱わない/知らない（暗号文をそのまま保管するだけ）。
 *   ・KV日次レート制限（KV未設定でも停止しない）。
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
      if (await rateLimited(env)) return json({ ok: false, error: "rate_limited" }, 429, cors);
      return putImage(decodeURIComponent(path.slice(9)), request, env, cors);
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

    // 状態 push
    if (path === "/api/push" && request.method === "POST") {
      if (!authOk(request, env)) return json({ ok: false, error: "bad_token" }, 403, cors);
      if (await rateLimited(env)) return json({ ok: false, error: "rate_limited" }, 429, cors);
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
//   KV レイアウト：state:doc → blob文字列 / state:meta → {version, updatedAt, device}
async function statePull(env, cors) {
  if (!env.SYNC) return json({ ok: false, error: "kv_unset" }, 500, cors);
  const blob = await env.SYNC.get("state:doc");
  if (blob === null) return json({ ok: true, empty: true, version: 0 }, 200, cors);
  const meta = parseJson(await env.SYNC.get("state:meta")) || {};
  return json({ ok: true, blob, version: meta.version || 0, updatedAt: meta.updatedAt || "", device: meta.device || "" }, 200, cors);
}
async function statePush(request, env, cors) {
  if (!env.SYNC) return json({ ok: false, error: "kv_unset" }, 500, cors);
  const body = parseJson(await request.text());
  if (!body || typeof body.blob !== "string") return json({ ok: false, error: "bad_body" }, 400, cors);
  if (body.blob.length > 8 * 1024 * 1024) return json({ ok: false, error: "too_large" }, 413, cors); // KV値上限25MB。安全側で8MB
  const meta = parseJson(await env.SYNC.get("state:meta")) || { version: 0 };
  const cur = meta.version || 0;
  const base = Number(body.baseVersion || 0);
  // 楽観的並行制御：baseVersion が現行と食い違う＝他端末が先に更新した→衝突を返す（呼び出し側でマージ再送）。
  if (cur !== 0 && base !== cur) {
    const blob = await env.SYNC.get("state:doc");
    return json({ ok: false, conflict: true, version: cur, blob: blob, updatedAt: meta.updatedAt || "", device: meta.device || "" }, 200, cors);
  }
  const nextVer = cur + 1;
  const nextMeta = { version: nextVer, updatedAt: body.updatedAt || new Date().toISOString(), device: String(body.device || "") };
  await env.SYNC.put("state:doc", body.blob);
  await env.SYNC.put("state:meta", JSON.stringify(nextMeta));
  return json({ ok: true, version: nextVer, updatedAt: nextMeta.updatedAt }, 200, cors);
}

// ── 画像(R2) ───────────────────────────────────────────────
function validKey(k) { return /^[a-f0-9]{16,64}$/.test(String(k || "")); } // sha256 hex（推測困難・パス安全）
async function putImage(key, request, env, cors) {
  if (!env.SYNC_IMAGES) return json({ ok: false, error: "r2_unset" }, 500, cors);
  if (!validKey(key)) return json({ ok: false, error: "bad_key" }, 400, cors);
  const existing = await env.SYNC_IMAGES.head(key);
  if (existing) return json({ ok: true, key, deduped: true }, 200, cors); // 冪等：同一content-hashは再保存しない
  const ct = request.headers.get("Content-Type") || "application/octet-stream";
  const buf = await request.arrayBuffer();
  if (buf.byteLength > 12 * 1024 * 1024) return json({ ok: false, error: "img_too_large" }, 413, cors);
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
async function imgHas(url, env, cors) {
  if (!env.SYNC_IMAGES) return json({ ok: false, error: "r2_unset" }, 500, cors);
  const keys = String(url.searchParams.get("keys") || "").split(",").map((s) => s.trim()).filter(validKey).slice(0, 200);
  const present = [];
  for (const k of keys) { if (await env.SYNC_IMAGES.head(k)) present.push(k); }
  return json({ ok: true, present }, 200, cors);
}

// ── レート制限（KV日次カウンタ・未設定でも停止しない）─────────────
async function rateLimited(env) {
  try {
    if (!env.SYNC) return false;
    const day = new Date().toISOString().slice(0, 10);
    const key = "rl:" + day;
    const cur = parseInt((await env.SYNC.get(key)) || "0", 10) || 0;
    const cap = parseInt(String(env.DAILY_CAP || "5000"), 10) || 5000;
    if (cur >= cap) return true;
    await env.SYNC.put(key, String(cur + 1), { expirationTtl: 172800 });
    return false;
  } catch (e) { return false; }
}

// ── ユーティリティ ─────────────────────────────────────────
function parseJson(s) { try { return JSON.parse(s); } catch (e) { return null; } }
function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), { status, headers: Object.assign({ "Content-Type": "application/json" }, cors || {}) });
}
function text(s, status) { return new Response(s, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } }); }
