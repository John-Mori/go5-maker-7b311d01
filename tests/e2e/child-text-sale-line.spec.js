// 投稿本文にセールの文(「⇩オータムセール🌰最大99%OFF!」)があれば、ドラフトモードの子の文にも出す
// (Chami msg 1562266602194337793「2」=X用の子の文欄にもセール行を戻す)。
// v1066(msg 1561255009562132584「いらない」)で外していたが、Blueskyの返信からも消えて改悪になった(msg 1562117265153986710)。
// 癒やし倉庫(noPromo)でもセール案内の行は残し、作品の割引率(N%オフ)の行だけ外す。投稿本文(Bluesky)側はそのまま。
const { test, expect } = require('@playwright/test');

test('子の文: セールの文の行もセールリンクの見出し+リンクも残し、N%オフの行だけ外す', async ({ page }) => {
  await page.goto('Stock.html', { waitUntil: 'load' });
  await page.waitForTimeout(800);
  const acc = await page.evaluate(() => {
    const acc = window.Go5Acct.current(); // 癒やし倉庫は読込時にacc3へ寄せる
    localStorage.setItem(window.Go5Acct.key('bsky_text', acc),
      '⇩気になった方はコチラから💕 #PR #漫画\nしかも今なら N%オフ💕\n⇩オータムセール🌰最大99%OFF!\n\n⭐大幅割引セール中の同人はこちら 🎀\n(セール紹介短縮用URL)');
    const ts = Date.now();
    localStorage.setItem('go5_stock_meta', JSON.stringify([{ id: 'stk_sale_line', ts, addedAt: ts, account: acc,
      label: 'セール行', title: 'セール行', author: 'test', bskyText: '当時の本文', affiliateUrl: '', workUrl: '',
      videoName: 'test.mp4', videoId: 'vid_sale_line', attrs: {} }]));
    return acc;
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.stk-mode[data-id="stk_sale_line"]').click();
  const child = page.locator('#draftXText');
  await expect(child).toHaveValue(/^⇩気になった方はコチラから💕 #PR #漫画/);
  await expect(child).toHaveValue(/⇩オータムセール🌰最大99%OFF!/);
  await expect(child).not.toHaveValue(/N%オフ/);
  await expect(child).toHaveValue(/⭐大幅割引セール中の同人はこちら 🎀\n/);
  // 投稿本文は変えない
  expect(await page.evaluate((a) => localStorage.getItem(window.Go5Acct.key('bsky_text', a)), acc)).toContain('⇩オータムセール🌰最大99%OFF!');
});
