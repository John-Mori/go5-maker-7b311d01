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

  // FANZA Books: book.dmm.co.jp/product/【数字ID】/【content_id】/ の2階層（実URL）。
  // content_id(2階層目・b915…形式)を優先して抽出（DMM APIのcid照会・作品情報取得のキー）。
  // アフィ短縮テンプレの「/product/【商品ID】/」1階層だけのURLでも動く（数字IDでもAPI照会可・実測済み）。
  const booksM = raw.match(/book\.dmm\.co\.jp\/product\/([^/?&#\s]+)(?:\/([^/?&#\s]+))?/);
  if (booksM) cid = booksM[2] || booksM[1];

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

// ブラウザ環境向けグローバル公開
if (typeof window !== 'undefined') {
  window.buildAffiliateLink = buildAffiliateLink;
}

// Node.js（CommonJS）向けエクスポート
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { buildAffiliateLink };
}
