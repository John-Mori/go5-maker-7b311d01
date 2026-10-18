const { test, expect } = require('@playwright/test');

// 即アフィの投稿文にも、投稿モード(composePostText)と同じセール行を入れる
// (Chami 2026-10-18 5Sec軍議 msg 1561277829524492381)。セール一覧はDMM行きなので短縮せずal.fanzaのまま。
test.describe('即アフィのセール行', () => {
  for (const acc of ['acc1', 'acc2', 'acc3']) {
    test('投稿モードの本文末尾のセール行と一致する(' + acc + ')', async ({ page }) => {
      const saleUrl = 'https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=mens/';
      let shortenCalls = 0;
      await page.route('**/api/shorten', async (route) => { shortenCalls++; await route.abort(); });
      await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
      await page.evaluate(({ acc, saleUrl }) => {
        localStorage.setItem('current_account', acc);
        localStorage.setItem('fanza_af_id', 'e2e-affiliate-001');
        localStorage.setItem('disc_urls_seeded__' + acc, '1');
        localStorage.setItem('bsky_discount_urls__' + acc, JSON.stringify([{ id: 'sale-' + acc, name: 'E2Eセール', url: saleUrl, at: Date.now() }]));
        localStorage.setItem('bsky_discount_selected__' + acc, 'sale-' + acc);
        localStorage.removeItem('bsky_discount_link_cache');
      }, { acc, saleUrl });
      // StockLists は読込時に acc3 へ固定するため、再読込せず(acctId() は都度読み)選んだアカウントで検証する
      const line = await page.evaluate(() => window.Go5SaleLineText());
      expect(line).toMatch(/^.+\nhttps:\/\/al\.fanza\.co\.jp\//);
      expect(new URL(line.split('\n')[1]).searchParams.get('lurl')).toBe(saleUrl);
      // 投稿モード側と同じ行が本文末尾に付く
      const composed = await page.evaluate(() => {
        const t = document.getElementById('bskyText'); if (t) t.value = 'テスト本文';
        return window.__go5ComposePostText();
      });
      expect(composed.endsWith(line), composed).toBe(true);
      // 即アフィの画面
      await page.locator('#quickAffiBtn').click();
      await page.locator('#qaUrl').fill('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_qa/');
      await page.locator('.qa-go').click();
      await expect.poll(() => page.locator('#qaPost').inputValue()).toContain(line);
      const post = await page.locator('#qaPost').inputValue();
      expect(post.endsWith(line)).toBe(true);
      expect((post.match(/https:\/\/al\.fanza\.co\.jp\/\S+/g) || []).length).toBe(2);
      expect(shortenCalls).toBe(0);
    });
  }
});
