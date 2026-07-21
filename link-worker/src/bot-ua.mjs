/**
 * bot-ua.mjs — クリック計測から除外するUA判定（純粋関数・副作用なし）
 *
 * ★なぜ必要か★
 *   X(Twitter)・Bluesky・Discord等は投稿の「カード」生成のため、投稿のたびに自動で
 *   短縮URLを叩く(Twitterbot等)。これをクリックとして数えるとクリック数が実態より
 *   膨らむ（計測の信頼性が崩れる）。
 *   ★リダイレクト自体は必ず返す（302を返さないとカードが壊れ投稿の見栄えが死ぬ）＝
 *   ここでは「数えるか否か」だけを判定する。呼び出し側で302は常に返すこと。
 *
 * 対象：SNS/チャットのカード生成クローラ・主要検索エンジンのクローラ（要件どおり）。
 *   大文字小文字は区別しない（実装によりUAの大文字小文字はまちまちのため）。
 *
 * UAヘッダ無しの扱い：botとみなして除外する。
 *   理由＝現行の主要ブラウザ(Chrome/Safari/Firefox/Edge)はすべて User-Agent を送信し、
 *   人間がUA無しでアクセスすることは実質ありえない。一方 curl 等の簡易スクリプトや
 *   一部の自動クローラはUAを省略することがある。「計測の水増しを防ぐ」という今回の目的
 *   に照らし、迷ったら数えない側（安全側）に倒す。
 */

const BOT_UA_SUBSTRINGS = [
  "twitterbot",
  "facebookexternalhit",
  "slackbot",
  "discordbot",
  "bluesky",     // Bluesky本体のカード生成クローラ（UAに bluesky を含む）
  "cardyb",      // Bluesky公式のリンクカード生成プロキシ(cardyb.bsky.app)
  "linkedinbot",
  "telegrambot",
  "whatsapp",
  "googlebot",
  "bingbot",
];

/**
 * @param {string|null|undefined} userAgent - Request の User-Agent ヘッダの値
 * @returns {boolean} true＝botとみなしクリックを数えない／false＝人間として数える
 */
function isBotUA(userAgent) {
  const ua = String(userAgent || "").trim();
  if (!ua) return true; // UA無し＝bot扱い（理由は上部コメント参照）
  const lower = ua.toLowerCase();
  return BOT_UA_SUBSTRINGS.some((needle) => lower.includes(needle));
}

export { isBotUA, BOT_UA_SUBSTRINGS };
