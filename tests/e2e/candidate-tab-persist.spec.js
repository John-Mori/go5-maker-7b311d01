// @ts-check
// 候補ページを再読込しても、選んでいたサブタブとページ番号に留まる(Chami 2026-10-22「いちいち手動追加にページが戻る」)。
//   iOS Safariは外部リンクから戻ると再読込することがあり、以前はそのたびに手動追加の1ページ目へ戻っていた。
const { test, expect } = require('@playwright/test');

test.describe('candidate tab survives reload', () => {
  test('selected sub-tab is kept after reload', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.cand-tab.active[data-ct="main"]')).toBeVisible();

    await page.locator('.cand-tab[data-ct="auto"]').click();
    await expect(page.locator('.cand-tab.active[data-ct="auto"]')).toBeVisible();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.cand-tab.active[data-ct="auto"]')).toBeVisible();
    await expect(page.locator('.cand-tab.active')).toHaveCount(1);

    await page.locator('.cand-tab[data-ct="all"]').click();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.cand-tab.active[data-ct="all"]')).toBeVisible();
  });

  test('a remembered tab that no longer exists falls back to 手動追加', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => localStorage.setItem('cand_active_tab', 'ct_deleted_tab'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.cand-tab.active[data-ct="main"]')).toBeVisible();
    await expect(page.locator('.cand-tab.active')).toHaveCount(1);
  });

  test('page number of the list is kept after reload', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      const now = Date.now();
      const items = [];
      for (let i = 0; i < 45; i++) {
        const cid = 'd_tab_persist_' + i;
        items.push({ cid, title: 'ページ保持確認' + i, url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/', addedAt: now - i });
      }
      localStorage.setItem('cand_items', JSON.stringify(items));
      localStorage.setItem('cand_page_size', '20');
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('.cand-page-btn[data-candpage="2"]').first().click();
    await expect(page.locator('.cand-page-btn.active').first()).toHaveText('2');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.cand-tab.active[data-ct="main"]')).toBeVisible();
    await expect(page.locator('.cand-page-btn.active').first()).toHaveText('2');
  });
});
