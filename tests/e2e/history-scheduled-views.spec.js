// 投稿予定の動画の再生数は「…」(取得中)ではなく「予」と出す(Chami msg 1561152543743021070)。
// 投稿済みの動画の再生数はそのまま数字で出す。
const { test, expect } = require('@playwright/test');

test.use({ timezoneId: 'Asia/Tokyo' });

test('投稿予定の再生数は「予」、投稿済みは数字', async ({ page }) => {
  const planned = new Date(Date.now() + 26 * 3600 * 1000).toISOString();
  await page.addInitScript(({ planned }) => {
    const account = 'acc3';
    localStorage.setItem('current_account', account);
    localStorage.setItem('yt_api_key', 'e2e-dummy-key');
    localStorage.setItem('bsky_gas_url', '');
    localStorage.setItem('sync2_url', '');
    localStorage.setItem('sync2_token', '');
    localStorage.setItem('hist_maint_at', String(Date.now()));
    localStorage.setItem('hist_metrics_at', '0');
    localStorage.setItem('yt_meta_cache', '{}');
    localStorage.setItem('hist_post_time_v1', '{}');
    localStorage.setItem('verify_manual__' + account, '[]');
    localStorage.setItem('verify_yt__' + account, '{}');
    localStorage.setItem('short_hist__' + account, JSON.stringify([
      { videoId: 'hist-sched', ytUrl: 'https://youtu.be/schedvid001', ts: Date.now() - 600000, plannedAt: planned, title: '予定の動画', account },
      { videoId: 'hist-done', ytUrl: 'https://youtu.be/donevid0001', ts: Date.now() - 2 * 86400000, title: '投稿済みの動画', account }
    ]));
  }, { planned });
  await page.route('**/youtube/v3/videos?*', async (route) => {
    const items = [{ id: 'donevid0001', snippet: { title: '投稿済みの動画', channelId: 'UC-e2e', publishedAt: new Date(Date.now() - 2 * 86400000).toISOString() },
      statistics: { viewCount: '123' }, status: { privacyStatus: 'public' } }];
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items }) });
  });
  await page.goto('StockLists.html?history-scheduled-views', { waitUntil: 'domcontentloaded' });
  const row = (t) => page.locator('.vrow').filter({ has: page.locator('.vrow-title', { hasText: t }) });
  await expect(row('予定の動画').locator('.vtag-scheduled')).toBeVisible();
  await expect(row('予定の動画').locator('.vmetrics > span').first()).toHaveText('▶ 予');
  await expect(row('投稿済みの動画').locator('.vmetrics > span').first()).not.toContainText('予');
});
