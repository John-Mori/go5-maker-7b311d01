// @ts-check
const { test, expect } = require('@playwright/test');

const HASH = 'a'.repeat(64);
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64'
);

async function serveImage(page) {
  await page.route('**/img/' + HASH, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'image/png',
      headers: { 'Cache-Control': 'public,max-age=31536000,immutable', 'Access-Control-Allow-Origin': '*' },
      body: PNG
    });
  });
}

test.describe('direct image CDN manifest', () => {
  test('candidate image renders from its stable URL without waiting for IndexedDB', async ({ page }) => {
    const cid = 'd_direct_manifest_candidate';
    await serveImage(page);
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ cid, hash }) => {
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('sync2_url', location.origin);
      localStorage.removeItem('sync2_token');
      localStorage.setItem('cand_items', JSON.stringify([{
        cid,
        title: '固定URLで即表示する候補画像',
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/',
        addedAt: Date.now()
      }]));
      localStorage.setItem('go5_image_manifest_v1', JSON.stringify({
        ['ref:' + cid]: { keys: [hash], prev: 0, at: Date.now() }
      }));
    }, { cid, hash: HASH });

    await page.route('**/js/candidates.js*', async (route) => {
      const response = await route.fetch();
      const body = await response.text();
      const shim = '(function () {' +
        'var original = Go5Idb.getResult.bind(Go5Idb);' +
        'Go5Idb.getResult = function (key) {' +
          'if (key === "ref:' + cid + '") {' +
            'window.__directCandidateIdbReads = (window.__directCandidateIdbReads || 0) + 1;' +
            'return new Promise(function () {});' +
          '}' +
          'return original(key);' +
        '};' +
      '})();';
      await route.fulfill({ response, body: shim + body });
    });

    await page.reload({ waitUntil: 'domcontentloaded' });
    const thumb = page.locator('[data-refimgview="' + cid + '"]');
    await expect(thumb).toBeVisible({ timeout: 1500 });
    await expect(thumb).toHaveAttribute('src', new RegExp('/img/' + HASH + '$'));
    await expect.poll(() => thumb.evaluate((img) => img.complete && img.naturalWidth > 0)).toBe(true);
    expect(await page.evaluate(() => window.__directCandidateIdbReads || 0)).toBe(0);
  });

  test('post-history used image renders from its stable URL before its IDB provider settles', async ({ page }) => {
    const videoId = 'acc1-20260826-directcdn';
    await serveImage(page);
    await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ videoId, hash }) => {
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('sync2_url', location.origin);
      localStorage.removeItem('sync2_token');
      localStorage.setItem('bsky_gas_url', '');
      localStorage.setItem('hist_maint_at', String(Date.now()));
      localStorage.setItem('hist_metrics_at', String(Date.now()));
      localStorage.setItem('verify_manual__acc1', '[]');
      localStorage.setItem('verify_yt__acc1', '{}');
      localStorage.setItem('short_hist__acc1', JSON.stringify([{
        videoId, ts: Date.now(), title: '固定URLで即表示する投稿履歴画像', account: 'acc1'
      }]));
      localStorage.setItem('go5_image_manifest_v1', JSON.stringify({
        ['used:' + videoId]: { keys: [hash], prev: 1, at: Date.now() }
      }));
    }, { videoId, hash: HASH });

    await page.route('**/js/candidates.js*', async (route) => {
      const response = await route.fetch();
      const body = await response.text();
      const shim = '(function () {' +
        'var original = Go5Idb.getResult.bind(Go5Idb);' +
        'Go5Idb.getResult = function (key) {' +
          'if (key === "used:' + videoId + '") return new Promise(function () {});' +
          'return original(key);' +
        '};' +
      '})();';
      await route.fulfill({ response, body: shim + body });
    });

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.vrow-title').filter({ hasText: '固定URLで即表示する投稿履歴画像' })).toBeVisible();
    const thumb = page.locator('.vrow-refimg[data-usedkey="' + videoId + '"]');
    await expect(thumb).toBeVisible({ timeout: 2000 });
    await expect(thumb).toHaveAttribute('src', new RegExp('/img/' + HASH + '$'));
    await expect.poll(() => thumb.evaluate((img) => img.complete && img.naturalWidth > 0)).toBe(true);
  });
});
