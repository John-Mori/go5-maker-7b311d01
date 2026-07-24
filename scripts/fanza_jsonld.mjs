/** FANZA/DMM商品ページのProduct JSON-LDから候補表示用の共通情報を読む純粋関数。 */
export function productJsonLdFromHtml(html) {
  const out = { price: null, brand: "", image: "", releaseDate: "", reviewCount: null, reviewAvg: null };
  const numberOf = (v) => {
    if (v == null || String(v).trim() === "") return null;
    const n = Number(String(v).replace(/,/g, "").trim());
    return Number.isFinite(n) ? n : null;
  };
  const isProduct = (t) => (Array.isArray(t) ? t : [t]).some((x) => /product$/i.test(String(x || "")));
  const readProduct = (o) => {
    const offers = Array.isArray(o.offers) ? o.offers[0] : (o.offers || {});
    const p = numberOf(offers && offers.price);
    if (p != null) out.price = Math.trunc(p);
    if (o.brand) out.brand = String(typeof o.brand === "string" ? o.brand : (o.brand.name || out.brand));
    const image = Array.isArray(o.image) ? o.image[0] : o.image;
    if (typeof image === "string") out.image = image;
    if (o.releaseDate) out.releaseDate = String(o.releaseDate).slice(0, 10);
    const rating = Array.isArray(o.aggregateRating) ? o.aggregateRating[0] : o.aggregateRating;
    if (rating && typeof rating === "object") {
      const count = numberOf(rating.reviewCount != null ? rating.reviewCount : rating.ratingCount);
      const avg = numberOf(rating.ratingValue);
      if (count != null && count >= 0) out.reviewCount = Math.trunc(count);
      if (avg != null && avg >= 0 && avg <= 5) out.reviewAvg = avg;
    }
  };
  const visit = (o) => {
    if (Array.isArray(o)) { o.forEach(visit); return; }
    if (!o || typeof o !== "object") return;
    if (isProduct(o["@type"])) readProduct(o);
    if (o["@graph"]) visit(o["@graph"]);
  };
  const re = /<script[^>]*application\/ld\+json[^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(String(html || ""))) !== null) { try { visit(JSON.parse(m[1])); } catch (e) {} }
  return out;
}