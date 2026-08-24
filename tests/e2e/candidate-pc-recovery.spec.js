// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('PC candidate recovery invariants', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
  });

  test('search remains available and can recover a hidden candidate', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    const search = page.locator('#candWorkSearch');
    await expect(search).toBeVisible();
    await expect(search).toHaveAttribute('aria-label', '作品検索(全候補・部分一致)');

    const hiddenCid = 'd_pc_search_hidden_recovery';
    const hiddenTitle = 'PC検索救出専用作品';
    await page.evaluate(({ hiddenCid, hiddenTitle }) => {
      localStorage.setItem('cand_items', JSON.stringify([
        {
          cid: hiddenCid,
          title: hiddenTitle,
          url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + hiddenCid + '/',
          addedAt: Date.now()
        },
        {
          cid: 'd_pc_search_other',
          title: '検索対象外の作品',
          url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_pc_search_other/',
          addedAt: Date.now() - 1
        }
      ]));
      localStorage.setItem('cand_hidden__main', JSON.stringify([hiddenCid]));
    }, { hiddenCid, hiddenTitle });
    await page.reload({ waitUntil: 'domcontentloaded' });

    await expect(page.locator('.cand-card', { hasText: hiddenTitle })).toHaveCount(0);
    await page.locator('#candWorkSearch').fill('検索救出専用');
    const recovered = page.locator('.cand-card', { hasText: hiddenTitle });
    await expect(recovered).toBeVisible();
    await expect(recovered.getByRole('button', { name: '👁 再表示' })).toBeVisible();
    await expect(page.locator('.cand-card', { hasText: '検索対象外の作品' })).toHaveCount(0);
  });

  test('a synced candidate image appears without navigating away or reloading', async ({ page }) => {
    const cid = 'd_pc_synced_image_exact_key';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ cid }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid,
        title: 'PC同期画像即時反映作品',
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/',
        addedAt: Date.now()
      }]));
    }, { cid });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-refimg="' + cid + '"]')).toBeVisible();
    await expect(page.locator('[data-refimgview="' + cid + '"]')).toHaveCount(0);

    await page.evaluate(async ({ cid }) => {
      const canvas = document.createElement('canvas');
      canvas.width = 8;
      canvas.height = 8;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#00cc66';
      ctx.fillRect(0, 0, 8, 8);
      const image = canvas.toDataURL('image/png');
      await Go5Idb.set('ref:' + cid, {
        imgs: [image],
        img: image,
        comment: 'PC sync',
        memo: '',
        at: Date.now()
      });
      document.dispatchEvent(new CustomEvent('go5-synced', {
        detail: { pulled: 0, pulledCand: 0, pulledImg: 1, pulledImgKeys: ['ref:' + cid] }
      }));
    }, { cid });

    await expect(page.locator('[data-refimgview="' + cid + '"]')).toBeVisible();
  });
});
