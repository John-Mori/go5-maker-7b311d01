const { test, expect } = require('@playwright/test');

test.use({ timezoneId: 'Asia/Tokyo' });

const TARGET_ID = 'deepnight01';
const OTHER_ID = 'otherrow001';

async function seedHistory(page) {
  await page.addInitScript(({ targetId, otherId }) => {
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
      {
        videoId: 'hist-target',
        ytUrl: 'https://youtu.be/' + targetId,
        ts: Date.parse('2026-10-15T01:10:00+09:00'),
        title: '深夜公開の動画',
        account
      },
      {
        videoId: 'hist-other',
        ytUrl: 'https://youtu.be/' + otherId,
        ts: Date.parse('2026-10-15T10:00:00+09:00'),
        title: '比較用の動画',
        account
      }
    ]));
  }, { targetId: TARGET_ID, otherId: OTHER_ID });
}

function videoItem(id, title, publishedAt, status) {
  return {
    id,
    snippet: { title, channelId: 'UC-e2e', publishedAt },
    statistics: { viewCount: '123' },
    status: status || { privacyStatus: 'public' }
  };
}

async function historyRow(page, title) {
  const row = page.locator('.vrow').filter({ has: page.locator('.vrow-title', { hasText: title }) });
  await expect(row).toBeVisible();
  return row;
}

async function clickApiRefresh(page) {
  const tools = page.locator('.tools-fold');
  if (!(await tools.getAttribute('open'))) await tools.locator('summary').click();
  await page.locator('#ytClickRefresh').click();
}

test('videos.list の公開時刻変更で見出し・並び・日別集計の起点が更新される', async ({ page }) => {
  await seedHistory(page);
  let targetPublishedAt = '2026-10-15T01:10:00+09:00';
  await page.route('**/youtube/v3/videos?*', async (route) => {
    const ids = new URL(route.request().url()).searchParams.get('id').split(',');
    const items = ids.map((id) => id === TARGET_ID
      ? videoItem(id, '深夜公開の動画', targetPublishedAt)
      : videoItem(id, '比較用の動画', '2026-10-15T10:00:00+09:00'));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items }) });
  });

  await page.goto('StockLists.html?history-publish-time=api', { waitUntil: 'domcontentloaded' });
  const target = await historyRow(page, '深夜公開の動画');
  await expect(target.locator('.vrow-h')).toContainText('01:10');
  await expect(page.locator('.vrow-title').first()).toContainText('比較用の動画');

  targetPublishedAt = '2026-10-15T19:30:00+09:00';
  await clickApiRefresh(page);

  const refreshed = await historyRow(page, '深夜公開の動画');
  await expect(refreshed.locator('.vrow-h')).toContainText('19:30');
  await expect(page.locator('.vrow-title').first()).toContainText('深夜公開の動画');
  await expect(refreshed.locator('.vrow-delta')).toHaveAttribute(
    'data-delta-ts',
    String(Date.parse('2026-10-15T19:30:00+09:00'))
  );
});

test('日時変更ボタンは出さず、過去の手動日時が残っていてもAPI時刻を表示する', async ({ page }) => {
  // Chami 2026-10-17 msg 1560865357139542176「日時変更というの、いらない」
  await seedHistory(page);
  await page.addInitScript(({ targetId }) => {
    const rec = { manualMs: Date.parse('2026-10-16T20:15:00+09:00'), manualAt: Date.now() };
    localStorage.setItem('hist_post_time_v1', JSON.stringify({ ['yt:' + targetId]: rec }));
  }, { targetId: TARGET_ID });
  await page.route('**/youtube/v3/videos?*', async (route) => {
    const ids = new URL(route.request().url()).searchParams.get('id').split(',');
    const items = ids.map((id) => id === TARGET_ID
      ? videoItem(id, '深夜公開の動画', '2026-10-17T18:40:00+09:00')
      : videoItem(id, '比較用の動画', '2026-10-15T10:00:00+09:00'));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items }) });
  });

  await page.goto('StockLists.html?history-publish-time=no-manual', { waitUntil: 'domcontentloaded' });
  await clickApiRefresh(page);
  const target = await historyRow(page, '深夜公開の動画');
  await expect(target.locator('.vrow-h')).toContainText('10/17');
  await expect(target.locator('.vrow-h')).toContainText('18:40');
  await expect(page.locator('.vdate-edit-btn')).toHaveCount(0);
  await expect(page.locator('.vdate-editor')).toHaveCount(0);
  await expect(target.locator('.vdate-manual-tag')).toHaveCount(0);
  await expect(target.locator('.vrow-delta')).toHaveAttribute(
    'data-delta-ts',
    String(Date.parse('2026-10-17T18:40:00+09:00'))
  );
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('hist_post_time_v1') || '{}'));
  expect(stored['yt:' + 'deepnight01'].manualMs).toBe(Date.parse('2026-10-16T20:15:00+09:00'));
});

test('予約中は status.publishAt を snippet.publishedAt より優先する', async ({ page }) => {
  await seedHistory(page);
  await page.route('**/youtube/v3/videos?*', async (route) => {
    const ids = new URL(route.request().url()).searchParams.get('id').split(',');
    const items = ids.map((id) => id === TARGET_ID
      ? videoItem(id, '深夜公開の動画', '2026-10-15T01:10:00+09:00', {
          privacyStatus: 'private',
          publishAt: '2030-10-15T19:30:00+09:00'
        })
      : videoItem(id, '比較用の動画', '2026-10-15T10:00:00+09:00'));
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items }) });
  });

  await page.goto('StockLists.html?history-publish-time=scheduled', { waitUntil: 'domcontentloaded' });
  const target = await historyRow(page, '深夜公開の動画');
  await expect(target.locator('.vrow-h')).toContainText('2030');
  await expect(target.locator('.vrow-h')).toContainText('19:30');
  await expect(target.locator('.vrow-h')).toContainText('投稿予定');
  await expect(target.locator('.vrow-delta')).toHaveAttribute('data-delta-prepost', '1');
});
