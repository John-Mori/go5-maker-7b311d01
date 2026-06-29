/**
 * fanza-worker — FANZA商品情報スクレイパー（go5-maker 専用）
 *
 * フロント(GitHub Pages)から cid を受け取り、FANZA同人商品ページをスクレイピングして
 * タイトル・価格情報を返す。API キー不要（DMM公開ページの JSON-LD + HTML パース）。
 *
 * ルート:
 *   POST /api/fanza-item  { cid: "d_784440" } → { ok, item }
 *   GET  /                → ヘルスチェック
 *
 * 取得データ:
 *   - タイトル・サークル名: JSON-LD <script type="application/ld+json">
 *   - 現在価格: JSON-LD offers.price
 *   - 元値(定価): .priceList__sub--big
 *   - レビュー: JS 動的ロードのため取得不可 → null を返す
 *
 * 安全:
 *   - Origin 制限（ALLOWED_ORIGIN 単一 Origin のみ）
 *   - 共有シークレット（X-Shared-Secret ヘッダ＋SHARED_SECRET Secret）
 */

const DMM_DOUJIN_BASE = "https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=";

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

      const secret = request.headers.get("X-Shared-Secret") || "";
      if (!env.SHARED_SECRET || secret !== env.SHARED_SECRET) {
        return json({ ok: false, error: "bad_secret" }, 401, cors);
      }

      let body;
      try { body = await request.json(); }
      catch (e) { return json({ ok: false, error: "bad_json" }, 400, cors); }

      const cid = String(body.cid || "").trim();
      if (!cid) return json({ ok: false, error: "missing_cid" }, 400, cors);

      const item = await scrapeFanzaItem(cid);
      if (!item) return json({ ok: false, error: "not_found", cid }, 404, cors);

      return json({ ok: true, item }, 200, cors);
    }

    if (path === "/" || path === "") {
      return text("go5-fanza-proxy ok", 200);
    }

    return json({ ok: false, error: "not_found" }, 404, null);
  }
};

/**
 * FANZA同人商品ページをスクレイピングして item オブジェクトを返す。
 * fanza-core.js の parseFanzaItem() が期待する構造に合わせる。
 */
async function scrapeFanzaItem(cid) {
  const pageUrl = DMM_DOUJIN_BASE + encodeURIComponent(cid) + "/";
  let res;
  try {
    res = await fetch(pageUrl, {
      headers: {
        "Cookie": "age_check_done=1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
      }
    });
  } catch (e) {
    return null;
  }

  if (!res.ok) return null;
  const html = await res.text();

  // 年齢確認ページが返ってきた場合
  if (!html.includes("priceList") && html.includes("age_check")) return null;

  // JSON-LD から Product 情報を取得
  let jsonLd = null;
  const ldRe = /<script\s+type="application\/ld\+json">([\s\S]*?)<\/script>/g;
  let ldM;
  while ((ldM = ldRe.exec(html)) !== null) {
    try {
      const obj = JSON.parse(ldM[1]);
      if (obj["@type"] === "Product") { jsonLd = obj; break; }
    } catch (e) {}
  }
  if (!jsonLd) return null;

  const title = jsonLd.name || "";
  const circleName = (jsonLd.brand && jsonLd.brand.name) ? String(jsonLd.brand.name) : "";
  const currentPriceStr = (jsonLd.offers && jsonLd.offers.price != null)
    ? String(jsonLd.offers.price) : null;

  // 元値: .priceList__sub--big に「550円」形式で入っている
  let listPriceStr = null;
  const lpM = html.match(/priceList__sub--big[^>]*>[\s\S]{0,60}?([\d,]+)円/);
  if (lpM) listPriceStr = lpM[1].replace(/,/g, "");

  // parseFanzaItem() が期待する item 構造を組み立てる
  return {
    content_id: cid,
    title: title,
    iteminfo: { author: circleName ? [{ name: circleName }] : [] },
    prices: {
      list_price: listPriceStr,   // 元値（割引なし商品は null）
      price: currentPriceStr      // 現在価格
    },
    review: { count: null, average: null }  // JS動的ロードのため取得不可
  };
}

// ── CORS ヘルパ ──

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
