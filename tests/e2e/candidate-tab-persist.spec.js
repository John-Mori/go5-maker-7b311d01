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

  // v1087: 実機の引き金=iPhoneのLSが満杯で新しいキー cand_active_tab が書けない→画面遷移で戻るたび手動追加(v1085はここを素通りした)
  test('LSが満杯でも、動画作成画面へ行って戻った時に選んだタブのまま', async ({ page }) => {
    await page.addInitScript(() => {
      const orig = Storage.prototype.setItem;
      Storage.prototype.setItem = function (k, v) {
        if (this === window.localStorage && k === 'cand_active_tab') { const e = new Error('quota'); e.name = 'QuotaExceededError'; throw e; }
        return orig.call(this, k, v);
      };
    });
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.locator('.cand-tab[data-ct="auto"]').click();
    await expect(page.locator('.cand-tab.active[data-ct="auto"]')).toBeVisible();
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.cand-tab.active[data-ct="auto"]')).toBeVisible();
    await expect(page.locator('.cand-tab.active')).toHaveCount(1);
  });

  test('覚えていたサークルタブが同期前で無い時は一時的に手動追加、届いたら元のタブへ戻り覚えたidも消えない', async ({ page }) => {
    // 開いたままのページの再描画が先に main を書き戻す競合を避けるため、ページのスクリプトより前に仕込む(初回だけ)
    await page.addInitScript(() => {
      if (sessionStorage.getItem('__e2e_seeded')) return;
      sessionStorage.setItem('__e2e_seeded', '1');
      localStorage.removeItem('cand_tabs');
      localStorage.setItem('cand_active_tab', 'ct_sync1');
    });
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.cand-tab.active[data-ct="main"]')).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('cand_active_tab'))).toBe('ct_sync1');
    await page.evaluate(() => {
      localStorage.setItem('cand_tabs', JSON.stringify([{ id: 'ct_sync1', name: '同期タブ' }]));
      document.dispatchEvent(new CustomEvent('go5-synced', { detail: {} }));
    });
    await expect(page.locator('.cand-tab.active[data-ct="ct_sync1"]')).toBeVisible();
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
