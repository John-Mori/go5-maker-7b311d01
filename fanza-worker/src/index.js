/**
 * fanza-worker — FANZA商品情報取得（go5-maker 専用）
 *
 * 優先順位:
 *   1. DMM公式API（FANZA_API_ID + FANZA_AFFILIATE_ID が設定されている場合）← 確実
 *   2. HTML スクレイピング（og:title → JSON-LD → <title> の順）← APIキー不要だが不安定
 *
 * ルート:
 *   POST /api/fanza-item  { cid: "d_784440" } → { ok, item }
 *   GET  /                → ヘルスチェック（デプロイ確認用）
 *
 * Secrets（wrangler secret put で登録）:
 *   SHARED_SECRET         ← フロント認証キー（必須）
 *   FANZA_API_ID          ← DMM API ID（任意・設定すると API 優先）
 *   FANZA_AFFILIATE_ID    ← FANZA アフィリエイトID（任意・FANZA_API_ID と対で設定）
 *
 * 安全:
 *   - Origin 制限（ALLOWED_ORIGIN 単一 Origin のみ）
 *   - 共有シークレット（X-Shared-Secret ヘッダ）
 */

const DMM_API_BASE    = "https://api.dmm.com/affiliate/v3/ItemList";
const DMM_DOUJIN_BASE = "https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=";

export default {
  async fetch(request, env) {
    const url    = new URL(request.url);
    const path   = url.pathname;
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

      // ① DMM 公式 API（APIキーが設定されていれば優先）
      let item = null;
      if (env.FANZA_API_ID && env.FANZA_AFFILIATE_ID) {
        item = await fetchViaApi(cid, env.FANZA_API_ID, env.FANZA_AFFILIATE_ID);
      }

      // ② スクレイピング（API なし or API で見つからなかった場合）
      if (!item) item = await scrapeFanzaItem(cid);

      // ③ 画像CDNフォールバック：アフィリエイトAPI未収録（サークル設定等）かつ商品ページが
      //    ログイン壁（Cloudflare=海外/DC IP扱い）の作品でも、画像CDN(doujin-assets)は認証・
      //    地域制限なしで取れる。サムネ＋サンプル画像だけの「部分情報」(partial)を返す。
      if (!item) item = await cdnFallbackItem(cid);

      if (!item) return json({ ok: false, error: "not_found", cid }, 404, cors);
      return json({ ok: true, item }, 200, cors);
    }

    if (path === "/" || path === "") {
      const mode = (env.FANZA_API_ID) ? "api+scrape" : "scrape-only";
      return text("go5-fanza-proxy ok (mode=" + mode + ")", 200);
    }

    return json({ ok: false, error: "not_found" }, 404, null);
  }
};

// DMM APIのGET（一時的な失敗はshort backoffでリトライ）。成功時のみJSONを返す。
async function fetchDmmJson(url, tries) {
  for (let t = 0; t < tries; t++) {
    try {
      const res = await fetch(url, { headers: { "Accept": "application/json" } });
      if (res.ok) return await res.json();
    } catch (e) { /* リトライ */ }
    if (t < tries - 1) await new Promise((r) => setTimeout(r, 250));
  }
  return null;
}

// ── DMM 公式 API ─────────────────────────────────────────────────────────────
// https://affiliate.dmm.com/api/  で API ID を取得後に有効になる。
// doujin フロアで見つからない場合は複数フロアを試みる（CID プレフィックスで判定）。
async function fetchViaApi(cid, apiId, affiliateId) {
  // CID プレフィックスからフロアを推定。※FANZAの正しい service/floor コード（FloorList APIで確認済み）。
  //   同人＝service:doujin / floor:digital_doujin（旧コード service:digital,floor:doujin は無効）。
  const floors = cid.startsWith("d_")
    ? [
        { service: "doujin", floor: "digital_doujin"    }, // 同人（通常）
        { service: "doujin", floor: "digital_doujin_bl" }, // 同人BL
        { service: "doujin", floor: "digital_doujin_tl" }, // 同人TL
      ]
    : [
        { service: "digital", floor: "videoc" }, // 素人・アダルト動画
        { service: "digital", floor: "anime"  }, // アニメ動画
        { service: "ebook",   floor: "comic"  }, // 電子コミック
        { service: "ebook",   floor: "novel"  }, // 電子小説
      ];

  for (const { service, floor } of floors) {
    try {
      const params = new URLSearchParams({
        api_id:       apiId,
        affiliate_id: affiliateId,
        site:         "FANZA",
        service:      service,
        floor:        floor,
        cid:          cid,
        output:       "json",
      });
      // 一時的な失敗（ネットワーク/レート）を吸収するため最大2回リトライしてからJSONを得る。
      const data = await fetchDmmJson(DMM_API_BASE + "?" + params.toString(), 2);
      if (!data) continue;
      const items = (data.result && Array.isArray(data.result.items)) ? data.result.items : [];
      if (!items.length) continue;
      const it = items[0];
      const prices = it.prices || {};
      const authorArr = (it.iteminfo && Array.isArray(it.iteminfo.author)) ? it.iteminfo.author : [];
      var genreArr = (it.iteminfo && Array.isArray(it.iteminfo.genre)) ? it.iteminfo.genre : [];
      return {
        content_id:   cid,
        title:        it.title || "",
        date:         it.date  || "",   // 発売日（作品状態=新作/準新作/旧作 の判定に使用）
        service_name: it.service_name || "",
        floor_name:   it.floor_name   || "",
        imageURL:       it.imageURL       || null,   // {list, large}
        sampleImageURL: it.sampleImageURL || null,   // {sample_s:{image:[]}, sample_l:{image:[]}}
        iteminfo:   { author: authorArr, genre: genreArr },
        prices: {
          list_price: prices.list_price  || null,
          price:      prices.price       || null,
        },
        review: it.review || { count: null, average: null },
      };
    } catch (e) { /* フロアごとに失敗しても続ける */ }
  }
  return null;
}

// ── HTML スクレイピング ───────────────────────────────────────────────────────
// og:title → JSON-LD Product → <title> の順でタイトルを取得する。
// ★CloudflareのIPは海外扱いされ、DMMが /en/age_check/?rurl=… へ302で飛ばす（API未収録作品が
//   スクレイプでも取れなかった根本原因）。redirect:manual で追い、age_check へ飛ばされたら
//   rurl を取り出して年齢クッキー付きで直接再訪問して突破する。
const SCRAPE_HEADERS = {
  "Cookie":          "age_check_done=1; ckcy=1; cklg=ja",
  "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
  "Referer":         "https://www.dmm.co.jp/",
};
async function fetchDmmPage(url, trace) {
  let cur = url;
  for (let hop = 0; hop < 6; hop++) {
    const res = await fetch(cur, { headers: SCRAPE_HEADERS, redirect: "manual" });
    if (trace) trace.push({ hop, url: cur, status: res.status, loc: res.headers.get("location") || "" });
    if (res.status >= 300 && res.status < 400) {
      let loc = res.headers.get("location") || "";
      if (!loc) return res;
      try { loc = new URL(loc, cur).href; } catch (e) { return res; }
      // 年齢確認ページへ飛ばされた → rurl（本来の行き先）を取り出して直接再訪問。
      const m = loc.match(/[?&]rurl=([^&]+)/);
      if (/age_check/.test(loc) && m) {
        try { loc = decodeURIComponent(m[1]); } catch (e) {}
        // /en/ 版へ差し替えられている場合は日本版URLへ戻す
        loc = loc.replace("://www.dmm.co.jp/en/", "://www.dmm.co.jp/");
      }
      if (loc === cur) return res; // 同一URLへのループ＝突破不能
      cur = loc;
      continue;
    }
    return res;
  }
  return null;
}
async function scrapeFanzaItem(cid) {
  const pageUrl = DMM_DOUJIN_BASE + encodeURIComponent(cid) + "/";
  let res;
  try { res = await fetchDmmPage(pageUrl); } catch (e) { return null; }
  if (!res || !res.ok) return null;
  const html = await res.text();

  // ブロック・年齢確認ページ検出
  if (html.includes("age_check") && !html.includes("og:title")) return null;

  let title = "";
  let circleName = "";

  // ① og:title（最も安定）
  const ogTitleM = html.match(/<meta\s+[^>]*property=["']og:title["']\s+content=["']([^"']+)["']/i)
    || html.match(/<meta\s+[^>]*content=["']([^"']+)["']\s+property=["']og:title["']/i);
  if (ogTitleM && ogTitleM[1]) title = ogTitleM[1].trim();

  // ② JSON-LD Product
  if (!title) {
    const ldRe = /<script\s+type=["']application\/ld\+json["']>([\s\S]*?)<\/script>/g;
    let ldM;
    while ((ldM = ldRe.exec(html)) !== null) {
      try {
        const obj = JSON.parse(ldM[1]);
        if (obj["@type"] === "Product" && obj.name) {
          title = obj.name;
          if (obj.brand && obj.brand.name) circleName = String(obj.brand.name);
          break;
        }
      } catch (e) {}
    }
  }

  // ③ <title> タグ（サイト名を除去）
  if (!title) {
    const tM = html.match(/<title>([^<]+)<\/title>/);
    if (tM) title = tM[1].replace(/\s*[|｜【].*$/, "").trim();
  }

  if (!title) return null;

  // ログイン・年齢確認・ブロックページは商品タイトルでない → null 扱い
  if (
    title.includes('ログイン') ||
    title.toLowerCase().includes('login') ||
    title.includes('年齢確認') ||
    title.includes('エラー') ||
    title === 'FANZA' ||
    title === 'DMM'
  ) return null;

  // 価格情報（取れれば付ける）
  const currentPriceM = html.match(/["']offers["']\s*:\s*\{[^}]*["']price["']\s*:\s*["']?(\d+)/);
  const currentPriceStr = currentPriceM ? currentPriceM[1] : null;

  const lpM = html.match(/priceList__sub--big[^>]*>[\s\S]{0,80}?([\d,]+)円/);
  const listPriceStr = lpM ? lpM[1].replace(/,/g, "") : null;

  // 発売日（JSON-LD releaseDate / 商品情報の「YYYY-MM-DD」表記から拾えれば）。取れなければ空。
  var dateStr = "";
  var rdM = html.match(/["']releaseDate["']\s*:\s*["'](\d{4}-\d{2}-\d{2})/)
    || html.match(/(?:発売日|配信開始日)[^0-9]{0,12}(\d{4})[\/\-年](\d{1,2})[\/\-月](\d{1,2})/);
  if (rdM) {
    dateStr = rdM.length >= 4 && rdM[2] ? (rdM[1] + "-" + ("0" + rdM[2]).slice(-2) + "-" + ("0" + rdM[3]).slice(-2)) : rdM[1];
  }

  // サムネ（og:image）。サンプル画像はスクレイプでは安定取得できないため空。
  var ogImgM = html.match(/<meta\s+[^>]*property=["']og:image["']\s+content=["']([^"']+)["']/i)
    || html.match(/<meta\s+[^>]*content=["']([^"']+)["']\s+property=["']og:image["']/i);
  var ogImg = ogImgM && ogImgM[1] ? ogImgM[1].trim() : "";

  return {
    content_id: cid,
    title:      title,
    date:       dateStr,
    service_name: "同人",
    floor_name:   "同人",
    imageURL:       ogImg ? { list: ogImg, large: ogImg } : null,
    sampleImageURL: null,
    iteminfo:   { author: circleName ? [{ name: circleName }] : [], genre: [] },
    prices: {
      list_price: listPriceStr,
      price:      currentPriceStr,
    },
    review: { count: null, average: null },
  };
}

// ── 画像CDNフォールバック ─────────────────────────────────────────────────────
// doujin-assets.dmm.co.jp は認証・地域制限なし。URLは決定的パターン：
//   digital/{type}/{cid}/{cid}pl.jpg（大）/ pt.jpg（小）/ jp-001.jpg…（サンプル）
const DOUJIN_ASSET_TYPES = ["comic", "game", "voice", "cg"];
async function headInfo_(u) {
  try {
    const r = await fetch(u, { method: "HEAD" });
    return r.ok ? { ok: true, len: r.headers.get("content-length") || "", etag: r.headers.get("etag") || "" } : { ok: false };
  } catch (e) { return { ok: false }; }
}
async function cdnFallbackItem(cid) {
  for (const t of DOUJIN_ASSET_TYPES) {
    const base = "https://doujin-assets.dmm.co.jp/digital/" + t + "/" + cid + "/" + cid;
    const pl = await headInfo_(base + "pl.jpg");
    if (!pl.ok) continue;
    // ★CDNは存在しない画像でも404ではなく「200＋NOW PRINTINGプレースホルダ」を返す。
    //   確実に存在しない番号(jp-999)の指紋(ETag/サイズ)を基準に、一致する画像を除外する。
    const ref = await headInfo_(base + "jp-999.jpg");
    const isPh = (h) => ref.ok && h.ok && ((ref.etag && h.etag) ? ref.etag === h.etag : (ref.len !== "" && h.len === ref.len));
    if (isPh(pl)) continue; // 表紙自体がプレースホルダ＝このtypeに画像なし
    const pt = await headInfo_(base + "pt.jpg");
    const listUrl = (pt.ok && !isPh(pt)) ? base + "pt.jpg" : base + "pl.jpg";
    const samples = [];
    for (let n = 1; n <= 8; n++) {
      const u = base + "jp-" + String(n).padStart(3, "0") + ".jpg";
      const h = await headInfo_(u);
      if (!h.ok || isPh(h)) break; // 実在しない番号＝プレースホルダを検知したら打ち切り
      samples.push(u);
    }
    return {
      content_id: cid,
      title:   "",          // タイトルは取得不可（API未収録＋ページはログイン壁）
      partial: true,        // 画像のみの部分情報
      date: "",
      service_name: "同人",
      floor_name:   "同人",
      imageURL: { list: listUrl, large: base + "pl.jpg" },
      sampleImageURL: samples.length ? { sample_l: { image: samples } } : null,
      iteminfo: { author: [], genre: [] },
      prices: { list_price: null, price: null },
      review: { count: null, average: null },
    };
  }
  return null;
}

// ── CORS ヘルパ ──────────────────────────────────────────────────────────────

function corsHeaders(origin, allowed) {
  if (!allowed) return null;
  if (allowed !== "*" && origin !== allowed) return null;
  return {
    "Access-Control-Allow-Origin":  allowed === "*" ? "*" : origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Shared-Secret",
    "Access-Control-Max-Age":       "86400",
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
