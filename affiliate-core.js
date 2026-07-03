/**
 * affiliate-core.js
 * FANZAアフィリエイトリンク生成 — 純粋関数（UI非依存）
 * ブラウザ（window グローバル）と Node.js（CommonJS）の両方で動く。
 */

/**
 * @param {string} rawUrl  - 作品URL（計測パラメータ付きでも可）
 * @param {string} afId    - アフィリエイトID（空の場合は【アフィID】で構造プレビュー）
 * @returns {{ ok: true, cid: string, link: string }
 *           |{ ok: false, error: 'empty'|'no_cid'|'bad_url' }}
 */
function buildAffiliateLink(rawUrl, afId) {
  const raw = (rawUrl || '').trim();
  if (!raw) return { ok: false, error: 'empty' };

  let cid = null;

  // FANZA Books: book.dmm.(com|co.jp)/product/【数字ID】/【コード】/ の2階層（実URL）。
  //  ・旧 book.dmm.co.jp は2階層目が API 照会可能な content_id(b915…形式)なので優先抽出。
  //  ・現行 book.dmm.com は2階層目がショップ/シリーズ码で API 照会不可のため、安定した
  //    数字の商品ID(1階層目)を内部cidに使う（情報はPCスクレイプ→override経由で解決）。
  //  ・「/product/【商品ID】/」1階層だけのURLでも動く。
  const booksM = raw.match(/book\.dmm\.(com|co\.jp)\/product\/([^/?&#\s]+)(?:\/([^/?&#\s]+))?/);
  if (booksM) cid = (booksM[1] === 'co.jp') ? (booksM[3] || booksM[2]) : booksM[2];

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
 * アフィリンク付きURL・計測パラメータ付きURLを「素の作品URL」に正規化する。
 * - al.fanza.co.jp/?lurl=… → lurl をデコードして取り出す
 * - ?以降・#以降の計測パラメータを除去（dmm系は cid= がパス側にあるため安全）
 * @param {string} rawUrl
 * @returns {string} 正規化済みURL（不正なら ''）
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

// ブラウザ環境向けグローバル公開
if (typeof window !== 'undefined') {
  window.buildAffiliateLink = buildAffiliateLink;
  window.normalizeWorkUrl = normalizeWorkUrl;
}

// Node.js（CommonJS）向けエクスポート
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { buildAffiliateLink, normalizeWorkUrl };
}
