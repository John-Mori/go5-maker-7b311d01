// @ts-check
// iPhoneの端末保存(LS)が満杯で go5_draft_post_ が書けない時も、Blueskyへ投稿したドラフトの
//   「✅ 投稿済み 親:開く／返信:開く」を消さない(Chami 2026-10-22 msg 1562790223455461446「Blueskyの投稿したやつが見れんくなってる」)。
//   旧版は setItem の失敗を空catchで握りつぶし、表示をLSの読み直しで描いていたため行が空になった。
const { test, expect } = require('@playwright/test');

test('LSが満杯でもBluesky投稿済みの行が出て、開き直しても履歴の行から戻る', async ({ page }) => {
  const draftId = 'stk_e2e_bsky_quota';
  const title = 'LS満杯でも投稿済みを出す';
  await page.addInitScript(() => {
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = function (k, v) {
      if (this === window.localStorage && String(k).indexOf('go5_draft_post_') === 0 && sessionStorage.getItem('__e2e_quota') === '1') {
        const e = new Error('quota'); e.name = 'QuotaExceededError'; throw e;
      }
      return orig.call(this, k, v);
    };
  });
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  const identity = await page.evaluate(({ draftId, title }) => {
    const account = window.Go5Acct.current();
    const videoId = account + '-20261022-2200-qfull';
    localStorage.setItem('bsky_gas_url', '');
    localStorage.setItem('hist_maint_at', String(Date.now()));
    localStorage.setItem('hist_metrics_at', String(Date.now()));
    localStorage.setItem('verify_manual__' + account, '[]');
    localStorage.setItem('short_hist__' + account, '[]');
    localStorage.setItem('verify_yt__' + account, '{}');
    localStorage.setItem('go5_stock_archive', '[]');
    localStorage.removeItem('go5_draft_post_' + draftId);
    localStorage.setItem('go5_stock_meta', JSON.stringify([{
      id: draftId, ts: Date.now(), addedAt: Date.now(), account,
      label: title, title, author: 'test', bskyText: 'テスト本文',
      affiliateUrl: '', workUrl: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_qfull/', videoName: 'test.mp4',
      videoId, attrs: {}
    }]));
    sessionStorage.setItem('__e2e_quota', '1');
    return { account, videoId };
  }, { draftId, title });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => typeof window.Go5History?.addCompletedPost)).toBe('function');
  await page.evaluate(() => {
    window.Go5FreshWorkInfo = () => Promise.resolve(null);
    window.Go5DraftBskyThread = () => Promise.resolve({
      parentUrl: 'https://bsky.app/profile/e2e/post/qp1', replyUrl: 'https://bsky.app/profile/e2e/post/qr1',
      bskyWorkShortUrl: '', parentShortUrl: '', replyShortUrl: ''
    });
  });
  page.on('dialog', (d) => d.accept());
  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await expect(page.locator('#draftPostModal')).toBeVisible();
  await page.locator('#draftBskyPost').click();
  await expect(page.locator('#draftBskyStatus')).toContainText('投稿済み');
  await expect(page.locator('#draftBskyStatus a').first()).toHaveAttribute('href', 'https://bsky.app/profile/e2e/post/qp1');
  // ドラフトの保存は落ちている(=iPhoneの再現になっている)ことを確かめる。
  expect(await page.evaluate((id) => localStorage.getItem('go5_draft_post_' + id), draftId)).toBeNull();
  // 履歴の自動記録行には親/返信URLが載る。
  await expect.poll(() => page.evaluate(({ account, videoId }) => {
    const h = JSON.parse(localStorage.getItem('verify_manual__' + account) || '[]');
    const r = h.filter((x) => x.videoId === videoId)[0];
    return r ? [r.bskyParentUrl || '', r.bskyReplyUrl || ''] : null;
  }, identity)).toEqual(['https://bsky.app/profile/e2e/post/qp1', 'https://bsky.app/profile/e2e/post/qr1']);

  // 再読込してモーダルを開き直しても(ドラフトにURLが無くても)履歴の行から戻して出す。
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await expect(page.locator('#draftPostModal')).toBeVisible();
  await expect(page.locator('#draftBskyStatus')).toContainText('投稿済み');
  await expect(page.locator('#draftBskyStatus')).toContainText('返信');
});
