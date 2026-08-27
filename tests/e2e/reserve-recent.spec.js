const { test, expect } = require('@playwright/test');
test.use({ serviceWorkers: 'block' });

test('reservation tab shows today immediately and builds yesterday only on disclosure', async ({ page }) => {
  await page.goto('?reserve-recent=1', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.Scheduler && window.Go5History);
  await page.evaluate(() => {
    const start = new Date();
    start.setHours(5, 0, 0, 0);
    if (Date.now() < start.getTime()) start.setDate(start.getDate() - 1);
    const base = start.getTime();
    window.Go5History.recentPublishedCached = () => [
      { id: 'today-high', videoId: 'todayHigh01', account: 'acc1', publishedAt: base + 10 * 60 * 1000, title: 'today high', views: 500, pinkClicks: 2, peakViews: 50 },
      { id: 'today-new', videoId: 'todayNew001', account: 'acc2', publishedAt: base + 20 * 60 * 1000, title: 'today new', views: 100, pinkClicks: 8, peakViews: 80 },
      { id: 'yesterday-one', videoId: 'yesterDay01', account: 'acc1', publishedAt: base - 60 * 60 * 1000, title: 'yesterday row', views: 900, pinkClicks: 4, peakViews: 40 }
    ];
  });

  await page.locator('#reserveBtn').click();
  const today = page.locator('[data-recent-group="today"]');
  const yesterday = page.locator('[data-recent-group="yesterday"]');
  await expect(today.locator('[data-recent-toggle]')).toHaveAttribute('aria-expanded', 'true');
  await expect(today.locator('.rsv-recent-count')).toContainText('\u6708\u8a60\u307f1\u672c');
  await expect(today.locator('.rsv-recent-count')).toContainText('\u5bb5\u685c1\u672c');
  await expect(today.locator('[data-recent-item]')).toHaveCount(2);

  await expect(yesterday.locator('[data-recent-toggle]')).toHaveAttribute('aria-expanded', 'false');
  await expect(yesterday.locator('.rsv-recent-count')).toContainText('\u5408\u8a081\u672c');
  await expect(yesterday.locator('[data-recent-item]')).toHaveCount(0);

  await yesterday.locator('[data-recent-toggle]').click();
  await expect(yesterday.locator('[data-recent-item]')).toHaveCount(1);
  await expect(yesterday.locator('.vrow-title')).toHaveText('yesterday row');

  await page.locator('#rsvRecentSort').selectOption('views');
  await expect(today.locator('[data-recent-item]').first()).toHaveAttribute('data-recent-item', 'todayHigh01');

  await today.locator('[data-recent-toggle]').click();
  await expect(today.locator('[data-recent-item]')).toHaveCount(0);
});
