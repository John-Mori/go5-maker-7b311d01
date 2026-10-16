// @ts-check
// 候補カードの動画生成用画像は、固定URL(sync-worker /img/<hash>)が読めないと黒い枠のまま黙っていた
//   (Chami 2026-10-16 msg 1560453278234583110「過去作の画像が黒くなってる」)。
//   端末内に同じ画像があればそれへ差し替え、無ければ「読めない」札を出すことを固定する。
const { test, expect } = require('@playwright/test');

const HASH = 'c'.repeat(64);
const PNG_DATA = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

async function seed(page, cid, withLocal) {
  await page.route('**/img/' + HASH, (route) => route.fulfill({ status: 404, contentType: 'text/plain', body: 'not found' }));
  await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.Go5Idb);
  await page.evaluate(async ({ cid, hash, png, withLocal }) => {
    localStorage.setItem('current_account', 'acc1');
    localStorage.setItem('sync2_url', location.origin);
    localStorage.removeItem('sync2_token');
    localStorage.setItem('cand_items', JSON.stringify([{
      cid, title: '固定URLが読めない過去作', url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/', addedAt: Date.now()
    }]));
    const now = Date.now();
    localStorage.setItem('go5_image_manifest_v1', JSON.stringify({ ['ref:' + cid]: { keys: [hash], prev: 0, at: now } }));
    if (withLocal) await window.Go5Idb.set('ref:' + cid, { imgs: [png], at: now - 60000 });
  }, { cid, hash: HASH, png: PNG_DATA, withLocal });
  await page.reload({ waitUntil: 'domcontentloaded' });
}

test.describe('候補の動画生成用画像: 固定URLが読めない時', () => {
  test('端末内の同じ画像へ差し替えて表示する', async ({ page }) => {
    const cid = 'd_ref_cdn_fallback_local';
    await seed(page, cid, true);
    const thumb = page.locator('[data-refimgview="' + cid + '"]');
    await expect(thumb).toBeVisible();
    await expect(thumb).toHaveAttribute('src', /^data:image\/png/, { timeout: 15000 });
    await expect.poll(() => thumb.evaluate((img) => img.complete && img.naturalWidth > 0)).toBe(true);
  });

  test('端末内にも無ければ黒い枠でなく「読めない」札を出す', async ({ page }) => {
    const cid = 'd_ref_cdn_fallback_none';
    await seed(page, cid, false);
    const ph = page.locator('[data-refretry="' + cid + '"]');
    await expect(ph).toContainText('画像を読めません', { timeout: 15000 });
    await expect(page.locator('img[data-refimgview="' + cid + '"]')).toHaveCount(0);
  });

  // Chamiに「出た/出ない」を聞き返さずに済むよう、読めなかった記録を同期サーバーへ送る。
  test('読めなかった記録(応答コード・差し替え先)を同期サーバーへ1回だけ送る', async ({ page }) => {
    const cid = 'd_ref_cdn_fallback_diag';
    const posts = [];
    await page.route('**/api/**', async (route) => {
      const req = route.request();
      if (req.url().endsWith('/api/diag/img')) {
        posts.push({ token: req.headers()['x-sync-token'], body: req.postDataJSON() });
        return route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
      }
      return route.fulfill({ status: 403, contentType: 'application/json', body: '{"ok":false}' });
    });
    // sync2_token を本当に入れると起動時の同期が走って一覧が別物になるため、getConfig の返す token だけ差す。
    await page.addInitScript(() => {
      let v;
      Object.defineProperty(window, 'Go5Sync', {
        configurable: true,
        get() { return v; },
        set(x) {
          if (x && x.getConfig) {
            const orig = x.getConfig;
            x.getConfig = function () { return Object.assign({}, orig.apply(this, arguments), { token: 'TEST_TOKEN' }); };
          }
          v = x;
        }
      });
    });
    await seed(page, cid, true);
    await expect(page.locator('[data-refimgview="' + cid + '"]')).toHaveAttribute('src', /^data:image\/png/, { timeout: 15000 });
    await expect.poll(() => posts.length, { timeout: 15000 }).toBeGreaterThan(0);
    await page.waitForTimeout(4000);
    expect(posts.length).toBe(1);
    expect(posts[0].token).toBe('TEST_TOKEN');
    expect(posts[0].body.events).toEqual([{ ev: 'ref_cdn_err', cid, key: HASH, status: 404, outcome: 'local' }]);
  });
});
