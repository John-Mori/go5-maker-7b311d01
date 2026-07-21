/**
 * tests/test_link_worker_bot_ua.js
 * Node で実行できる自己完結テスト（追加パッケージ不使用）
 * 実行: node tests/test_link_worker_bot_ua.js
 *
 * 対象は link-worker/src/bot-ua.mjs の純粋関数 isBotUA のみ（KV・ネットワークは検証しない）。
 * ネットワーク越しの実挙動（302を返す・KVを増減しない）は wrangler dev + curl で別途確認済み
 * （AD-GL依頼の対応報告を参照）。
 */

'use strict';

const assert = require('assert');

let passed = 0;
let failed = 0;

function test(name, fn) {
  return fn()
    .then(() => { console.log('PASS:', name); passed++; })
    .catch((e) => { console.log('FAIL:', name, '-', e.message); failed++; });
}

(async () => {
  const { isBotUA } = await import('../link-worker/src/bot-ua.mjs');

  await test('Twitterbot は bot と判定される', async () => {
    assert.strictEqual(isBotUA('Twitterbot/1.0'), true);
  });

  await test('大文字小文字を区別しない(小文字 twitterbot)', async () => {
    assert.strictEqual(isBotUA('twitterbot/1.0'), true);
  });

  await test('facebookexternalhit は bot と判定される', async () => {
    assert.strictEqual(isBotUA('facebookexternalhit/1.1'), true);
  });

  await test('Slackbot は bot と判定される', async () => {
    assert.strictEqual(isBotUA('Slackbot-LinkExpanding 1.0'), true);
  });

  await test('Discordbot は bot と判定される', async () => {
    assert.strictEqual(isBotUA('Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)'), true);
  });

  await test('Bluesky系クローラ(cardyb)は bot と判定される', async () => {
    assert.strictEqual(isBotUA('Bluesky Cardyb/1.1'), true);
  });

  await test('LinkedInBot は bot と判定される', async () => {
    assert.strictEqual(isBotUA('LinkedInBot/1.0'), true);
  });

  await test('TelegramBot は bot と判定される', async () => {
    assert.strictEqual(isBotUA('TelegramBot (like TwitterBot)'), true);
  });

  await test('WhatsApp は bot と判定される', async () => {
    assert.strictEqual(isBotUA('WhatsApp/2.23.20'), true);
  });

  await test('Googlebot は bot と判定される', async () => {
    assert.strictEqual(isBotUA('Googlebot/2.1 (+http://www.google.com/bot.html)'), true);
  });

  await test('bingbot は bot と判定される', async () => {
    assert.strictEqual(isBotUA('Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)'), true);
  });

  await test('通常のiPhoneブラウザは bot と判定されない', async () => {
    assert.strictEqual(isBotUA('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'), false);
  });

  await test('通常のデスクトップブラウザは bot と判定されない', async () => {
    assert.strictEqual(isBotUA('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'), false);
  });

  await test('UAヘッダ無し(空文字)は bot 扱い(除外側)', async () => {
    assert.strictEqual(isBotUA(''), true);
  });

  await test('UAヘッダ無し(null)は bot 扱い(除外側)', async () => {
    assert.strictEqual(isBotUA(null), true);
  });

  await test('UAヘッダ無し(undefined)は bot 扱い(除外側)', async () => {
    assert.strictEqual(isBotUA(undefined), true);
  });

  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed > 0) process.exit(1);
})();
