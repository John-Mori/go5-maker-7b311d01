// DLサイト便(acc3)でも、投稿本文のセール案内行(「⇩オータムセール🌰最大99%OFF!」)は子の文に入れる
// (Chami msg 1561255009562132584「オータムセールの文がドラフトモードの子の文に入らない」)。
// 作品の割引率の行(「しかも今なら N%オフ💕」)は従来どおり外す(DLサイト便は割引率を出さない)。
const { test, expect } = require('@playwright/test');

test('acc3の子の文: %OFFを含むセール行は残し、作品の割引行は外す', async ({ page }) => {
  await page.goto('Stock.html', { waitUntil: 'load' });
  await page.waitForTimeout(800);
  await page.evaluate(() => {
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem(window.Go5Acct.key('bsky_text', 'acc3'),
      '⇩気になった方はコチラから💕 #PR #漫画\nしかも今なら N%オフ💕\n⇩オータムセール🌰最大99%OFF!');
    const ts = Date.now();
    localStorage.setItem('go5_stock_meta', JSON.stringify([{ id: 'stk_sale_line', ts, addedAt: ts, account: 'acc3',
      label: 'セール行', title: 'セール行', author: 'test', bskyText: '当時の本文', affiliateUrl: '', workUrl: '',
      videoName: 'test.mp4', videoId: 'vid_sale_line', attrs: {} }]));
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.stk-mode[data-id="stk_sale_line"]').click();
  const child = page.locator('#draftXText');
  await expect(child).toHaveValue(/⇩オータムセール🌰最大99%OFF!$/);
  await expect(child).not.toHaveValue(/今なら/);
});
