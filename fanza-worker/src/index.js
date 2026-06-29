/**
 * fanza-worker — FANZA商品情報API プロキシ（go5-maker 専用）
 *
 * フロント(GitHub Pages)から cid を受け取り、FANZA Affiliate API v3 を叩いて
 * 商品情報（タイトル・価格・レビュー等）を返す。
 * API ID / affiliate ID は Worker Secret にのみ保持し、レスポンス・ログに出さない。
 *
 * ルート:
 *   POST /api/fanza-item  { cid: "d_784440" } → { ok, item }
 *   GET  /                → ヘルスチェック
 *
 * 安全（drive-worker / link-worker と同方針）:
 *   - Origin 制限（env.ALLOWED_ORIGIN 単一 Origin のみ）
 *   - 共有シークレット（X-Shared-Secret ヘッダ＋env.SHARED_SECRET）
 *   - 秘密の本体（FANZA_API_ID / FANZA_AF_ID / SHARED_SECRET）は Worker Secrets のみ
 *   - レスポンス・console にキーを出さない
 */

const FANZA_API = "https://api.dmm.com/affiliate/v3/ItemList";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "";

    if (path === "/api/fanza-item") {
      if (request.method === "OPTIONS") return preflight(origin, allowed);
      const cors = corsHeaders(origin, allowed);
      if (!cors) return json({ ok: false, error: "origin_not_allowed" }, 403, null);
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, cors);

      // 共有シークレット
      const secret = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || secret !== env.SHARED_SECRET) {
        return json({ ok: false, error: "bad_secret" }, 401, cors);
      }

      // リクエストボディ解析
      let body;
      try { body = await request.json(); }
      catch (e) { return json({ ok: false, error: "bad_json" }, 400, cors); }

      const cid = String(body.cid || "").trim();
      if (!cid) return json({ ok: false, error: "missing_cid" }, 400, cors);

      // API ID / affiliate ID の存在確認（ログに値は出さない）
      if (!env.FANZA_API_ID || !env.FANZA_AF_ID) {
        return json({ ok: false, error: "worker_not_configured" }, 503, cors);
      }

      // FANZA Affiliate API v3 呼び出し
      const params = new URLSearchParams({
        api_id: env.FANZA_API_ID,
        affiliate_id: env.FANZA_AF_ID,
        site: "FANZA",
        hits: "1",
        cid: cid,
        output: "json"
      });
      let apiRes;
      try {
        apiRes = await fetch(FANZA_API + "?" + params.toString());
      } catch (e) {
        return json({ ok: false, error: "upstream_fetch_failed" }, 502, cors);
      }

      if (!apiRes.ok) {
        return json({ ok: false, error: "upstream_error", status: apiRes.status }, 502, cors);
      }

      let data;
      try { data = await apiRes.json(); }
      catch (e) { return json({ ok: false, error: "upstream_parse_failed" }, 502, cors); }

      const result = data && data.result;
      const items = result && result.items;
      if (!items || !items.length) {
        return json({ ok: false, error: "not_found", cid }, 404, cors);
      }

      // 安全のため、レスポンスには items[0] のみ返す（API ID 等は result に含まれない）
      return json({ ok: true, item: items[0] }, 200, cors);
    }

    // ヘルスチェック
    if (path === "/" || path === "") {
      return text("go5-fanza-proxy ok", 200);
    }

    return json({ ok: false, error: "not_found" }, 404, null);
  }
};

// ── CORS ヘルパ（drive-worker / link-worker と同パターン）──

function corsHeaders(origin, allowed) {
  if (!allowed) return null;
  if (allowed !== "*" && origin !== allowed) return null;
  return {
    "Access-Control-Allow-Origin": allowed === "*" ? "*" : origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Shared-Secret",
    "Access-Control-Max-Age": "86400"
  };
}

function preflight(origin, allowed) {
  const h = corsHeaders(origin, allowed);
  if (!h) return new Response(null, { status: 403 });
  return new Response(null, { status: 204, headers: h });
}

function json(obj, status, cors) {
  const headers = { "Content-Type": "application/json" };
  if (cors) Object.assign(headers, cors);
  return new Response(JSON.stringify(obj), { status, headers });
}

function text(str, status) {
  return new Response(str, { status, headers: { "Content-Type": "text/plain" } });
}
