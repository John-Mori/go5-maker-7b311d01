// @ts-check
// ドラフトのままBlueskyへ投稿しただけで投稿履歴に行が出ていた
//   (Chami 2026-10-16 msg 1560466397182693502「ドラフトにしただけでとうこうりれきにのせないで。投稿完了を押したら正式に載るように」)。
//   Bluesky投稿時の自動記録行は残す(導線1の計測・後の追記用)が、投稿完了を押すまで一覧に出さないことを本物の画面で固定する。
const { test, expect } = require('@playwright/test');

test('ドラフトでBluesky投稿しただけでは投稿履歴に出ず、投稿完了で1件だけ出る', async ({ page }) => {
  const draftId = 'stk_e2e_bsky_draft_hidden';
  const title = 'ドラフト段階は投稿履歴に出さない';
  const anchor = '投稿履歴の描画確認用の通常行';
  const ytUrl = 'https://www.youtube.com/shorts/DrAfTHiDe12';
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  const identity = await page.evaluate(({ draftId, title, anchor }) => {
    const account = window.Go5Acct.current();
    const videoId = account + '-20261016-1100-dhid';
    localStorage.setItem('bsky_gas_url', '');
    localStorage.setItem('hist_maint_at', String(Date.now()));
    localStorage.setItem('hist_metrics_at', String(Date.now()));
    localStorage.setItem('verify_manual__' + account, JSON.stringify([{ manual: true, id: 'm:anchor', ts: Date.now() - 86400000, title: anchor, videoId: account + '-20261015-1100-anch' }]));
    localStorage.setItem('short_hist__' + account, '[]');
    localStorage.setItem('verify_yt__' + account, '{}');
    localStorage.setItem('go5_stock_archive', '[]');
    localStorage.setItem('go5_stock_meta', JSON.stringify([{
      id: draftId, ts: Date.now(), addedAt: Date.now(), account,
      label: title, title, author: 'test', bskyText: 'テスト本文',
      affiliateUrl: '', workUrl: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_dhid/', videoName: 'test.mp4',
      videoId, attrs: {}
    }]));
    return { account, videoId };
  }, { draftId, title, anchor });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => typeof window.Go5History?.addCompletedPost)).toBe('function');
  // Blueskyへの実投稿だけ差し替える(以降の自動記録・ドラフト保存は本物)。
  await page.evaluate(() => {
    window.Go5FreshWorkInfo = () => Promise.resolve(null);
    window.Go5DraftBskyThread = () => Promise.resolve({
      parentUrl: 'https://bsky.app/profile/e2e/post/p1', replyUrl: 'https://bsky.app/profile/e2e/post/r1',
      bskyWorkShortUrl: '', parentShortUrl: '', replyShortUrl: ''
    });
  });

  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await expect(page.locator('#draftPostModal')).toBeVisible();
  page.on('dialog', (d) => d.accept());
  await page.locator('#draftBskyPost').click();
  await expect(page.locator('#draftBskyStatus')).toContainText('投稿済み');
  // 自動記録行そのものは保存される(投稿完了での追記先)。
  await expect.poll(() => page.evaluate(({ account, videoId }) => {
    const h = JSON.parse(localStorage.getItem('verify_manual__' + account) || '[]');
    return h.filter((x) => x.videoId === videoId).map((x) => !!x.autoRecorded);
  }, identity)).toEqual([true]);

  await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.vrow-title').filter({ hasText: anchor })).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.vrow-title').filter({ hasText: title })).toHaveCount(0);

  // 投稿完了を押したら正式に載る(同じ行へ追記・1件だけ)。
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => typeof window.Go5History?.addCompletedPost)).toBe('function');
  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await expect(page.locator('#draftPostModal')).toBeVisible();
  await page.locator('#draftPubNow').check();
  await page.locator('#draftYtUrl').fill(ytUrl);
  await page.locator('#draftModalComplete').click();
  await expect.poll(() => page.evaluate(({ account, videoId }) => {
    const h = JSON.parse(localStorage.getItem('verify_manual__' + account) || '[]');
    return h.filter((x) => x.videoId === videoId).map((x) => !!x.autoRecorded);
  }, identity)).toEqual([false]);

  await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.vrow-title').filter({ hasText: anchor })).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.vrow-title').filter({ hasText: title })).toHaveCount(1);
});
