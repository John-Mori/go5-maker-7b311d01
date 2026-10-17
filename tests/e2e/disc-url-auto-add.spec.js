// @ts-check
// 🔥セール案内URLは、名前とURLを入れて欄を離れただけで一覧へ○付きで出ること
// (Chami msg 1561054969539465236「セールにラジオボタンつけて。出てない」=iPhoneで＋追加のタップが空振りし入力欄に残った)。
const { test, expect } = require('@playwright/test');

test('名前とURLを入れて欄を離れると、＋追加を押さなくても一覧に○付きで出る', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem('disc_urls_seeded__acc3', '1'); // 既定のセールページ無し=Chamiの癒やし倉庫と同じ空の一覧から
  });
  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.locator('#tabPost').click();
  await page.locator('#discUrlsDetails > summary').click();
  await expect(page.locator('#discUrlList')).toContainText('未登録');
  await page.locator('#discUrlName').fill('秋セール');
  await page.locator('#discUrlInput').fill('https://xdgh3.com/odXX');
  await page.locator('#discUrlInput').blur();
  const row = page.locator('#discUrlList label', { hasText: '秋セール' });
  await expect(row.locator('input[type=radio]')).toBeChecked();
  await expect(page.locator('#discUrlInput')).toHaveValue('');
  // 続けて＋追加を押しても二重に入らない
  await page.locator('#discUrlAddBtn').click();
  await expect(page.locator('#discUrlList label')).toHaveCount(1);
  // 名前だけ入れて離れた時は勝手に足さない
  await page.locator('#discUrlName').fill('冬セール');
  await page.locator('#discUrlName').blur();
  await expect(page.locator('#discUrlList label')).toHaveCount(1);
});
