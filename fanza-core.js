/**
 * fanza-core.js — FANZA商品情報取得・解析（純粋関数）
 * ブラウザ（window グローバル）と Node.js（CommonJS）の両方で動く。
 */

/**
 * Worker レスポンスの items[0] を受け取り、正規化した商品情報オブジェクトを返す。
 * 欠落フィールドがあっても例外を投げない。
 *
 * @param {Object|null} item - FANZA API v3 のアイテムオブジェクト
 * @returns {{ cid, title, author, listPrice, price, discountPct, reviewCount, reviewAvg, fetchedAt }|null}
 */
function parseFanzaItem(item) {
  if (!item) return null;
  var prices = item.prices || {};
  var review = item.review || {};

  var listPriceStr = prices.list_price;
  var priceStr = prices.price;
  var listPrice = (listPriceStr != null && listPriceStr !== '') ? parseInt(listPriceStr, 10) : null;
  var price = (priceStr != null && priceStr !== '') ? parseInt(priceStr, 10) : null;

  var discountPct = 0;
  if (listPrice && price && listPrice > 0 && price < listPrice) {
    discountPct = Math.round((1 - price / listPrice) * 100);
  }

  var authorArr = (item.iteminfo && Array.isArray(item.iteminfo.author)) ? item.iteminfo.author : [];
  var author = authorArr.length > 0 ? String(authorArr[0].name || '') : '';

  return {
    cid: item.content_id || '',
    title: item.title || '',
    author: author,
    listPrice: listPrice,
    price: price,
    discountPct: discountPct,
    reviewCount: (review.count !== undefined && review.count !== null) ? review.count : null,
    reviewAvg: (review.average !== undefined && review.average !== null) ? review.average : null,
    fetchedAt: new Date().toISOString()
  };
}

/**
 * fanza-worker プロキシ経由で cid → 商品情報を取得する。
 * 取得失敗・Worker 未設定はすべて null を返す（呼び出し元で try/catch 不要）。
 *
 * @param {string} cid
 * @param {string} workerUrl  - localStorage の fanza_worker_url
 * @param {string} sharedSecret - localStorage の fanza_shared_secret
 * @returns {Promise<ReturnType<parseFanzaItem>|null>}
 */
function fetchFanzaInfo(cid, workerUrl, sharedSecret) {
  if (!cid || !workerUrl) return Promise.resolve(null);
  return fetch(workerUrl + '/api/fanza-item', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Shared-Secret': sharedSecret || ''
    },
    body: JSON.stringify({ cid: cid })
  })
  .then(function (r) {
    if (!r.ok) return null;
    return r.json();
  })
  .then(function (data) {
    if (!data || !data.ok || !data.item) return null;
    return parseFanzaItem(data.item);
  })
  .catch(function () { return null; });
}

// ブラウザ環境向けグローバル公開
if (typeof window !== 'undefined') {
  window.FanzaCore = { parseFanzaItem: parseFanzaItem, fetchFanzaInfo: fetchFanzaInfo };
}

// Node.js（CommonJS）向けエクスポート
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { parseFanzaItem: parseFanzaItem, fetchFanzaInfo: fetchFanzaInfo };
}
