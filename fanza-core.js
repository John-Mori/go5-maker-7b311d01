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
  var authorId = authorArr.length > 0 && authorArr[0].id != null ? String(authorArr[0].id) : ''; // サークル/作者ID（候補タブのサークル一覧取得に使用）

  // サムネ・サンプル画像・ジャンル（詳細モーダル用）。
  var img = item.imageURL || {};
  var thumb = String(img.large || img.list || '');
  var thumbSmall = String(img.list || img.large || '');
  var sImg = item.sampleImageURL || {};
  var samples = [];
  if (sImg.sample_l && Array.isArray(sImg.sample_l.image)) samples = sImg.sample_l.image.slice();
  else if (sImg.sample_s && Array.isArray(sImg.sample_s.image)) samples = sImg.sample_s.image.slice();
  var genreArr = (item.iteminfo && Array.isArray(item.iteminfo.genre)) ? item.iteminfo.genre : [];
  var genres = genreArr.map(function (g) { return String((g && g.name) || ''); }).filter(Boolean);

  return {
    cid: item.content_id || '',
    title: item.title || '',
    partial: !!item.partial,   // 画像のみの部分情報（API未収録＋ページ取得不能の作品）
    author: author,
    authorId: authorId,
    listPrice: listPrice,
    price: price,
    discountPct: discountPct,
    releaseDate: item.date || '',   // 発売日（作品状態=新作/準新作/旧作 の判定に使用）
    service: String(item.service_name || ''),
    floor: String(item.floor_name || ''),
    thumb: thumb,
    thumbSmall: thumbSmall,
    samples: samples,
    genres: genres,
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
// 失敗時のエラーコード/HTTPから、人が読める失敗理由を作る。
function fanzaReason_(status, data) {
  var code = (data && data.error) ? String(data.error) : '';
  if (code === 'not_found') return '作品が見つかりません（cid違い・配信終了・対象フロア外の可能性）';
  if (code === 'bad_secret') return '認証エラー（共有シークレット不一致。⚙️詳細設定を確認）';
  if (code === 'origin_not_allowed') return 'Origin不許可（ワーカー設定）';
  if (code === 'missing_cid' || code === 'bad_json') return 'リクエスト不正（' + code + '）';
  if (status && status >= 500) return 'サーバーエラー（HTTP ' + status + '）';
  if (status && status >= 400) return 'リクエストエラー（HTTP ' + status + '）';
  return code ? ('エラー: ' + code) : '不明なエラー';
}
// リトライして意味があるか（一時的失敗=true / 恒久的失敗=false）。
// 「見つからない」「認証」「リクエスト不正」は何度やっても同じ＝リトライしない（無駄な待ち時間を作らない）。
function fanzaRetryable_(status, data) {
  var code = (data && data.error) ? String(data.error) : '';
  if (code === 'not_found' || code === 'bad_secret' || code === 'origin_not_allowed' || code === 'missing_cid' || code === 'bad_json') return false;
  if (status && status >= 500) return true;   // サーバー一時エラーは再試行の価値あり
  if (status && status >= 400) return false;  // その他4xxは恒久的
  return !!code === false;                    // コード不明（想定外）＝一応リトライ
}

// 成功時は parseFanzaItem の結果（title を持つ）を返す。失敗時は { __error:true, reason } を返す。
// ※呼び出し側は「info && info.title」で成功判定できる（従来どおり）。reason で失敗内容が分かる。
// srcUrl（任意・第4引数）: 作品ページの元URL。FANZA Books等、同人以外のスクレイプフォールバック先として worker が使う。
function fetchFanzaInfo(cid, workerUrl, sharedSecret, srcUrl) {
  if (!cid || !workerUrl) return Promise.resolve({ __error: true, reason: '作品URL/ワーカーURLが未設定' });
  // タイムアウト（スマホ回線での無限待ちを防ぎ、呼び出し側のリトライを効かせる）。
  var ctrl = null, timer = null, timedOut = false;
  try { ctrl = new AbortController(); timer = setTimeout(function () { timedOut = true; try { ctrl.abort(); } catch (e) {} }, 9000); } catch (e) { ctrl = null; }
  var opts = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Shared-Secret': sharedSecret || '' },
    body: JSON.stringify(srcUrl ? { cid: cid, url: srcUrl } : { cid: cid })
  };
  if (ctrl) opts.signal = ctrl.signal;
  return fetch(workerUrl + '/api/fanza-item', opts)
  .then(function (r) {
    return r.json().catch(function () { return null; }).then(function (data) {
      if (timer) clearTimeout(timer);
      if (r.ok && data && data.ok && data.item) return parseFanzaItem(data.item);
      return { __error: true, reason: fanzaReason_(r.status, data), retryable: fanzaRetryable_(r.status, data) };
    });
  })
  .catch(function () {
    if (timer) clearTimeout(timer);
    return { __error: true, reason: timedOut ? '通信タイムアウト（9秒）' : '通信エラー（オフライン/接続失敗）', retryable: true };
  });
}

// ブラウザ環境向けグローバル公開
if (typeof window !== 'undefined') {
  window.FanzaCore = { parseFanzaItem: parseFanzaItem, fetchFanzaInfo: fetchFanzaInfo };
}

// Node.js（CommonJS）向けエクスポート
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { parseFanzaItem: parseFanzaItem, fetchFanzaInfo: fetchFanzaInfo };
}
