// 投稿モードの子の文を直すと、次のドラフトでも直した文で出る
// (Chami msg 1561144626054955010「新しくドラフトで動画作ると元に戻る。戻らないようにして」)。
const { test, expect } = require('@playwright/test');

test('子の文の手直しは投稿本文へ戻り、別のドラフトを開いても元に戻らない', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  const account = await page.evaluate(() => {
    const account = window.Go5Acct.current();
    localStorage.setItem(window.Go5Acct.key('bsky_text', account), '最初の本文\n2行目');
    const d = (id, ts) => ({ id, ts, addedAt: ts, account, label: id, title: id, author: 'test',
      bskyText: '当時の本文', affiliateUrl: '', workUrl: '', videoName: 'test.mp4', videoId: 'vid_' + id, attrs: {} });
    localStorage.setItem('go5_stock_meta', JSON.stringify([d('stk_wb_a', Date.now()), d('stk_wb_b', Date.now() - 1000)]));
    return account;
  });
  await page.reload({ waitUntil: 'domcontentloaded' });

  await page.locator('.stk-mode[data-id="stk_wb_a"]').click();
  await expect(page.locator('#draftXText')).toHaveValue('最初の本文\n2行目');
  await page.locator('#draftXText').fill('最初の本文 直した\n2行目');
  expect(await page.evaluate((a) => localStorage.getItem(window.Go5Acct.key('bsky_text', a)), account)).toBe('最初の本文 直した\n2行目');

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.stk-mode[data-id="stk_wb_b"]').click();
  await expect(page.locator('#draftXText')).toHaveValue('最初の本文 直した\n2行目');
  expect(errors).toEqual([]);
});
