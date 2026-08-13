/**
 * affiliate-core.js
 * FANZAアフィリエイトリンク生成 — 純粋関数(UI非依存)
 * ブラウザ(window グローバル)と Node.js(CommonJS)の両方で動く。
 */

/**
 * @param {string} rawUrl  - 作品URL(計測パラメータ付きでも可)
 * @param {string} afId    - アフィリエイトID(空の場合は【アフィID】で構造プレビュー)
 * @returns {{ ok: true, cid: string, link: string }
 *           |{ ok: false, error: 'empty'|'no_cid'|'bad_url' }}
 */
function buildAffiliateLink(rawUrl, afId) {
  const raw = (rawUrl || '').trim();
  if (!raw) return { ok: false, error: 'empty' };

  let cid = null;

  // FANZA Books: book.dmm.(com|co.jp)/product/【数字ID】/【content_id】/ の2階層。(実URL)
  //  ・2階層目(b062…/b915…形式の content_id)があれば .com/.co.jp を問わずそれを優先。
  //    ※旧実装は「.com は1階層目の数字ID」を cid にしていたが、数字IDは DMM API の content_id
  //      照会に使えず『タイトル未取得』の原因になっていた。(例: /product/4163193/b062aftwk01392/)
  //  ・「/product/【商品ID】/」1階層だけのURLでは商品IDを内部cidに使う。(PCスクレイプ→override経由で解決)
  const booksM = raw.match(/book\.dmm\.(com|co\.jp)\/product\/([^/?&#\s]+)(?:\/([^/?&#\s]+))?/);
  if (booksM) cid = booksM[3] || booksM[2];

  // FANZA 同人・動画: cid= パラメータ
  if (!cid) {
    const m = raw.match(/cid=([^/?&\s]+)/);
    if (m) cid = m[1];
  }

  if (!cid) return { ok: false, error: 'no_cid' };

  let clean = raw.split('?')[0].trim();
  if (!/^https?:\/\//i.test(clean)) return { ok: false, error: 'bad_url' };
  if (!clean.endsWith('/')) clean += '/';
  const lurl = encodeURIComponent(clean);
  const af = (afId && afId.trim()) ? afId.trim() : '【アフィID】';
  const link = `https://al.fanza.co.jp/?lurl=${lurl}&af_id=${af}&ch=toolbar&ch_id=link`;
  return { ok: true, cid, link };
}

/**
 * 一覧・キャンペーンページ用アフィリンク。(cid不要＝作品ページ以外を包む)
 * 作品リンク(buildAffiliateLink)は cid 必須で一覧URLを弾くため、こちらで al.fanza の
 * lurl ラッパだけを作る。計測パラメータ(utm等)は normalizeWorkUrl で除去。
 * @param {string} rawUrl - 一覧/キャンペーンページのURL(utm付きでも可)
 * @param {string} afId   - アフィID(空なら【アフィID】で構造プレビュー)
 * @returns {{ok:true, link:string, clean:string}|{ok:false, error:'empty'|'bad_url'}}
 */
function buildFanzaListLink(rawUrl, afId) {
  const raw = (rawUrl || '').trim();
  if (!raw) return { ok: false, error: 'empty' };
  let clean = normalizeWorkUrl(raw); // utm等を除去(?/#以降を落とす)
  if (!clean) return { ok: false, error: 'bad_url' };
  if (!clean.endsWith('/')) clean += '/';
  const lurl = encodeURIComponent(clean);
  const af = (afId && afId.trim()) ? afId.trim() : '【アフィID】';
  const link = `https://al.fanza.co.jp/?lurl=${lurl}&af_id=${af}&ch=toolbar&ch_id=link`;
  return { ok: true, link, clean };
}

/**
 * アフィリンク付きURL・計測パラメータ付きURLを「素の作品URL」に正規化する。
 * - al.fanza.co.jp/?lurl=… → lurl をデコードして取り出す
 * - ?以降・#以降の計測パラメータを除去(dmm系は cid= がパス側にあるため安全)
 * @param {string} rawUrl
 * @returns {string} 正規化済みURL(不正なら '')
 */
function normalizeWorkUrl(rawUrl) {
  let u = (rawUrl || '').trim();
  if (!u) return '';
  const m = u.match(/[?&]lurl=([^&]+)/i);
  if (m) { try { u = decodeURIComponent(m[1]); } catch (e) { /* デコード不能なら原文のまま */ } }
  u = u.split('#')[0].split('?')[0].trim();
  if (!/^https?:\/\//i.test(u)) return '';
  return u;
}

/**
 * 短縮URLとして扱う既知ホスト。(自前r2ドメイン＋外部フォールバック。bluesky.js の
 * SHORT.WORKER_HOSTS / SHARE_SHORTENERS が実際に使う宛先と同じ＝二重処理防止の判定に使う)
 * サブドメイン(例: www.tinyurl.com)も許容。
 */
const SHORT_URL_HOSTS = ['5mgl.com', 'yoz2.com', 'r2.trustsignalbot.workers.dev', 'da.gd', 'tinyurl.com'];

/**
 * URLのホスト名が「既に短縮済み」とみなせるホストか。
 * @param {string} rawUrl
 * @param {string[]} [extraHosts] - 端末上書き等、追加で信頼するホスト
 * @returns {boolean}
 */
function isShortenedUrl(rawUrl, extraHosts) {
  const u = (rawUrl || '').trim();
  if (!u) return false;
  let host;
  try { host = new URL(u).hostname.toLowerCase(); } catch (e) { return false; }
  const hosts = SHORT_URL_HOSTS.concat(extraHosts || []);
  return hosts.some((h) => { h = String(h || '').toLowerCase(); return !!h && (host === h || host.endsWith('.' + h)); });
}

/**
 * URLに「実在のaf_id」(プレースホルダ【アフィID】でない)が入っているか。
 * @param {string} rawUrl
 * @returns {boolean}
 */
function hasRealAffiliateId(rawUrl) {
  const u = (rawUrl || '').trim();
  const m = u.match(/[?&]af_id=([^&]*)/);
  if (!m) return false;
  let v = m[1] || '';
  try { v = decodeURIComponent(v); } catch (e) { /* デコード不能ならそのまま比較 */ }
  return !!v && v !== '【アフィID】';
}

/**
 * 入力URLの状態を判定する。(セール案内URL自動解決の判断材料・純粋関数・ネットワーク不使用)
 * @param {string} rawUrl
 * @param {string[]} [extraShortHosts] - 追加で「短縮済み」とみなすホスト(端末上書き分)
 * @returns {{isShortened:boolean, hasAffiliate:boolean, needsAffiliate:boolean, needsShorten:boolean}}
 */
function classifyPromoUrl(rawUrl, extraShortHosts) {
  const isShortened = isShortenedUrl(rawUrl, extraShortHosts);
  // 短縮済みなら中身は見ない＝「もう手を加えなくてよいか」の判定にaf_idの有無は無関係。
  const hasAffiliate = isShortened ? true : hasRealAffiliateId(rawUrl);
  return {
    isShortened,
    hasAffiliate,
    needsAffiliate: !isShortened && !hasAffiliate,
    needsShorten: !isShortened
  };
}

/**
 * URLにaf_idが無ければ付与してアフィリンク化する。(cidが取れれば作品リンク、
 * 取れなければ一覧/キャンペーンページとして buildFanzaListLink で包む＝セール会場対応)
 * 既にaf_idが入っている場合は二重ラップせずそのまま返す。(冪等)
 * @param {string} rawUrl
 * @param {string} afId
 * @returns {{ok:true, link:string, wasAlready:boolean}|{ok:false, error:string}}
 */
function ensureAffiliateLink(rawUrl, afId) {
  const url = (rawUrl || '').trim();
  if (!url) return { ok: false, error: 'empty' };
  if (hasRealAffiliateId(url)) return { ok: true, link: url, wasAlready: true };
  const r1 = buildAffiliateLink(url, afId);
  if (r1.ok) return { ok: true, link: r1.link, wasAlready: false };
  const r2 = buildFanzaListLink(url, afId);
  if (r2.ok) return { ok: true, link: r2.link, wasAlready: false };
  return { ok: false, error: r2.error || r1.error };
}

// ブラウザ環境向けグローバル公開
if (typeof window !== 'undefined') {
  window.buildAffiliateLink = buildAffiliateLink;
  window.buildFanzaListLink = buildFanzaListLink;
  window.normalizeWorkUrl = normalizeWorkUrl;
  window.isShortenedUrl = isShortenedUrl;
  window.hasRealAffiliateId = hasRealAffiliateId;
  window.classifyPromoUrl = classifyPromoUrl;
  window.ensureAffiliateLink = ensureAffiliateLink;
}

// Node.js(CommonJS)向けエクスポート
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    buildAffiliateLink, buildFanzaListLink, normalizeWorkUrl,
    isShortenedUrl, hasRealAffiliateId, classifyPromoUrl, ensureAffiliateLink
  };
}
