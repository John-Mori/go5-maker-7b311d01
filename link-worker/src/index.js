/**
 * link-worker — 5秒動画メーカー 専用URL短縮（自前・中間ページなし）
 *
 * ★なぜ自前か★
 *   TinyURL等の無料短縮は開封時に広告的な「Preview（中間）ページ」を挟むことがあり、
 *   ユーザーを不安にさせ直帰の原因になる。自前なら 302 で即リダイレクトでき、
 *   中間ページは原理的に出ない。CORSも自分で設定するのでブラウザから必ず短縮できる。
 *
 * ルート：
 *   POST /api/shorten           {url}（form or json）→ 短縮コード発行・KV保存・短縮URL返却
 *   GET  /:code                 → 302 リダイレクト（中間ページなし）＋クリック概算カウント
 *   GET  /api/stats?code=&secret= → クリック数を返す（将来 Bitly 置換用）
 *   GET  /                      → ヘルスチェック（"go5-short ok"）
 *
 * 安全（多層防御。drive-worker と同方針）：
 *   - 宛先は ALLOWED_HOSTS に限定（既定 bsky.app / bsky.social）。万一ソフト鍵が漏れても
 *     Bluesky以外へ飛ばす踏み台（オープンリダイレクタ）にならない。"*" で全許可も可。
 *   - 作成は Origin 制限＋共有シークレット（ソフト鍵）＋KV日次レート制限。
 *   - KVの u:<code>（コード→URL）は一度書いたら不変＝既存の短縮リンクが書き換わらない。
 *   - 秘密の本体（SHARED_SECRET）は Worker Secrets。レスポンス・ログに出さない。
 *
 * KVレイアウト（単一 namespace: LINKS）：
 *   u:<code>  → 宛先URL（不変）
 *   c:<code>  → クリック数（概算・GET毎に+1）
 *   rl:<日付> → 日次の発行カウンタ（レート制限・2日で自動失効）
 */

const BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
const CODE_MIN = 7;   // 既定のコード長（62^7 ≈ 3.5兆通り。個人運用には十分）
const CODE_MAX = 12;  // 万一の衝突時はここまで伸ばして再試行

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "";

    // ---- 短縮の発行（ブラウザから呼ぶ：CORS対象）----
    if (path === "/api/shorten") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const cors = corsHeaders(origin, allowed);
      if (!cors) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, cors);
      return handleShorten(request, env, cors);
    }

    // ---- クリック数の取得（管理用・共有シークレット）----
    if (path === "/api/stats") {
      if (request.method !== "GET") return json({ ok: false, error: "method_not_allowed" }, 405, {});
      return handleStats(url, env);
    }

    // ---- ヘルスチェック ----
    if (path === "/" || path === "") {
      return text("go5-short ok", 200);
    }

    // ---- それ以外は短縮コードとして 302 リダイレクト（中間ページなし）----
    if (request.method === "GET" || request.method === "HEAD") {
      const code = path.slice(1).split("/")[0];
      if (/^[0-9A-Za-z]+$/.test(code)) return handleRedirect(code, env, ctx);
    }
    return text("Not found", 404);
  },
};

/* ====================== 発行 ====================== */
async function handleShorten(request, env, cors) {
  // 共有シークレット（ソフト鍵・多層防御の1枚）
  const secret = request.headers.get("X-Shared-Secret") || "";
  if (!env.SHARED_SECRET || secret !== env.SHARED_SECRET) {
    return json({ ok: false, error: "bad_secret" }, 401, cors);
  }
  // 日次レート制限（KV未設定でも停止させない）
  try { if (await rateLimited(env)) return json({ ok: false, error: "rate_limited" }, 429, cors); }
  catch (e) { /* 他の防御で守る */ }

  // 入力（form-encoded 優先、json も許容）
  let urlStr = "";
  try {
    const ct = request.headers.get("Content-Type") || "";
    if (ct.includes("application/json")) { const b = await request.json(); urlStr = String((b && b.url) || ""); }
    else { const f = await request.formData(); urlStr = String(f.get("url") || ""); }
  } catch (e) { return json({ ok: false, error: "bad_input" }, 400, cors); }
  urlStr = urlStr.trim();

  // 宛先ホスト制限（踏み台防止）
  if (!hostAllowed(urlStr, env)) return json({ ok: false, error: "host_not_allowed" }, 400, cors);

  if (!env.LINKS) return json({ ok: false, error: "kv_unbound" }, 500, cors);

  // 決定的コード（同じURLは常に同じコード＝重複作成なし）。衝突時のみ伸ばす。
  const full = await codeFor(urlStr);
  let code = "";
  for (let len = CODE_MIN; len <= CODE_MAX; len++) {
    const cand = full.slice(0, len);
    const existing = await env.LINKS.get("u:" + cand);
    if (existing === null) { await env.LINKS.put("u:" + cand, urlStr); code = cand; break; }
    if (existing === urlStr) { code = cand; break; } // 既存の同一URL＝そのまま使い回し（冪等）
    // それ以外（別URLが既に占有）＝衝突 → さらに1文字伸ばして再試行
  }
  if (!code) return json({ ok: false, error: "code_alloc_failed" }, 500, cors);

  const origin = new URL(request.url).origin;
  return json({ ok: true, code, short: origin + "/" + code, url: urlStr }, 200, cors);
}

/* ====================== リダイレクト ====================== */
async function handleRedirect(code, env, ctx) {
  if (!env.LINKS) return text("Not found", 404);
  const urlStr = await env.LINKS.get("u:" + code);
  if (!urlStr) return text("Not found", 404);
  // クリックを概算カウント（リダイレクトはブロックしない）
  if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(bumpClick(env, code));
  // 302（恒久キャッシュでカウントが漏れないよう一時リダイレクト）
  return new Response(null, { status: 302, headers: { Location: urlStr, "Cache-Control": "no-store" } });
}

/* ====================== クリック数取得 ====================== */
async function handleStats(url, env) {
  // 読み取り専用＋共有シークレット必須なので、検証タブ（ブラウザ）から読めるよう ACAO:* を付ける。
  // クリック数は機微情報ではなく、ソフト鍵は元々クライアントにある前提（公開可）。
  const cors = { "Access-Control-Allow-Origin": "*" };
  const secret = url.searchParams.get("secret") || "";
  if (!env.SHARED_SECRET || secret !== env.SHARED_SECRET) return json({ ok: false, error: "bad_secret" }, 401, cors);
  const code = (url.searchParams.get("code") || "").trim();
  if (!code) return json({ ok: false, error: "missing_code" }, 400, cors);
  if (!env.LINKS) return json({ ok: false, error: "kv_unbound" }, 500, cors);
  const urlStr = await env.LINKS.get("u:" + code);
  const clicks = parseInt((await env.LINKS.get("c:" + code)) || "0", 10);
  return json({ ok: true, code, exists: !!urlStr, clicks }, 200, cors);
}

/* ====================== ヘルパ ====================== */
async function codeFor(urlStr) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(urlStr));
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < CODE_MAX; i++) s += BASE62[bytes[i] % 62];
  return s;
}

function hostAllowed(urlStr, env) {
  let u;
  try { u = new URL(urlStr); } catch (e) { return false; }
  if (u.protocol !== "https:" && u.protocol !== "http:") return false;
  const list = String(env.ALLOWED_HOSTS || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (list.includes("*")) return true;
  const h = u.hostname.toLowerCase();
  return list.some((d) => h === d || h.endsWith("." + d));
}

async function bumpClick(env, code) {
  try {
    const k = "c:" + code;
    const cur = parseInt((await env.LINKS.get(k)) || "0", 10);
    await env.LINKS.put(k, String(cur + 1));
  } catch (e) { /* 計測失敗はリダイレクトに影響させない */ }
}

async function rateLimited(env) {
  if (!env.LINKS) return false;
  const limit = parseInt(env.DAILY_LIMIT || "500", 10);
  const day = new Date().toISOString().slice(0, 10); // UTC日付
  const key = "rl:" + day;
  const cur = parseInt((await env.LINKS.get(key)) || "0", 10);
  if (cur >= limit) return true;
  await env.LINKS.put(key, String(cur + 1), { expirationTtl: 172800 }); // 2日で自動失効
  return false;
}

/* ====================== CORS / レスポンス ====================== */
function corsHeaders(origin, allowed) {
  if (!allowed || origin !== allowed) return null;
  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Shared-Secret",
    "Vary": "Origin",
  };
}
function preflight(origin, allowed) {
  const h = corsHeaders(origin, allowed);
  if (!h) return new Response(null, { status: 403 });
  return new Response(null, { status: 204, headers: h });
}
function json(obj, status, cors) {
  const headers = Object.assign({ "Content-Type": "application/json; charset=utf-8" }, cors || {});
  return new Response(JSON.stringify(obj), { status, headers });
}
function text(s, status) {
  return new Response(s, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
