// ドラフトで予約投稿の公開枠を選んで投稿完了したら、投稿履歴と予約タブには投稿完了の時刻ではなく
//   公開枠の予定時刻を出す(Chami msg 1561261867203039282「ドラフトタブで投稿予約時間と紐付けても
//   投稿完了した時刻が表示される。投稿予定時間を表示して欲しい」)。
const { test, expect } = require('@playwright/test');

test.use({ timezoneId: 'Asia/Tokyo' });

test('予約投稿で投稿完了 → 投稿履歴と予約タブに予定時刻', async ({ page, baseURL }) => {
  const self = new URL(baseURL || 'https://john-mori.github.io/go5-maker-7b311d01/').origin;
  await page.route('**/*', async (route) => {
    const u = new URL(route.request().url());
    if (u.hostname === 'www.googleapis.com') {
      // 予約公開中の動画はAPIキーの videos.list に返らない(=空応答)。
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [] }) });
    }
    if (u.origin === self || u.hostname === 'localhost' || u.hostname === '127.0.0.1') return route.continue();
    // 計測(クリック数)のWorkerも空で返す(拒否すると取得全体が中断し、予約タブの抽出まで進まない)。
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  const draftId = 'stk_e2e_planned';
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate(({ draftId }) => {
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem('yt_api_key', 'e2e-dummy-key');
    localStorage.setItem('bsky_gas_url', '');
    const now = Date.now();
    localStorage.setItem('go5_stock_meta', JSON.stringify([{
      id: draftId, ts: now, addedAt: now, account: 'acc3', label: '予定時刻の動画', title: '予定時刻の動画', author: 'test',
      bskyText: '本文', affiliateUrl: '', workUrl: '', videoName: 'p.mp4', videoId: 'acc3-20261018-1505-plan1', attrs: {}
    }]));
  }, { draftId });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => typeof window.Go5History?.addCompletedPost)).toBe('function');

  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await page.locator('#draftPubSched').check();
  await page.locator('#draftPickSlot').click();
  const picker = page.frameLocator('#draftPickerFrame');
  await picker.getByRole('button', { name: /翌週/ }).click();
  await picker.locator('.slot .cell[data-acc="acc3"]').first().click();
  await picker.locator('#integ-pick').click();
  await expect(page.locator('#draftPickedSlot')).toContainText('選択中：');
  const slotAt = await page.evaluate((id) => JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}').pubSlot.scheduled_at, draftId);
  // 時刻の解釈はページ側(Asia/Tokyo)で行う=CIランナーのTZ(UTC)に引きずられない。
  const { slotMs, hm } = await page.evaluate((at) => {
    const d = new Date(String(at).replace(' ', 'T'));
    return { slotMs: d.getTime(), hm: String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') };
  }, slotAt);
  await page.locator('#draftYtUrl').fill('https://youtu.be/planvid0001');
  page.on('dialog', (dl) => dl.accept());
  await page.locator('#draftModalComplete').click();
  await expect(page.locator('#draftPostModal')).toBeHidden();

  await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
  const row = page.locator('.vrow').filter({ has: page.locator('.vrow-title', { hasText: '予定時刻の動画' }) });
  await expect(row.locator('.vtag-scheduled')).toBeVisible({ timeout: 15000 });
  await expect(row).toContainText(hm);

  // 再生数の付いていない公開前の動画にYouTubeがアップロード時刻(=予定より前)を返しても、予定時刻を出す。
  const vid = 'planvid0001';
  await page.evaluate(({ vid }) => {
    const m = JSON.parse(localStorage.getItem('hist_post_time_v1') || '{}');
    m['yt:' + vid] = Object.assign({}, m['yt:' + vid] || {}, { autoMs: Date.now() - 60000, autoAt: Date.now(), autoSource: 'publishedAt', privacy: '' });
    localStorage.setItem('hist_post_time_v1', JSON.stringify(m));
  }, { vid });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(row.locator('.vtag-scheduled')).toBeVisible({ timeout: 15000 });
  await expect(row).toContainText(hm);
  await expect(row.locator('.vviews-sched')).toHaveText('予');

  // 予定時刻は同期キー(hist_post_time_v1)にも載る=別端末・シート由来の行でも同じ時刻になる。
  const plannedMs = await page.evaluate((vid) => (JSON.parse(localStorage.getItem('hist_post_time_v1') || '{}')['yt:' + vid] || {}).plannedMs, vid);
  expect(plannedMs).toBe(slotMs);

  // 予約タブ(⏰予約)の「YouTube公開待ち」も「公開待ち」だけでなく予定時刻を出す。
  //   投稿履歴ページで抽出した分が acc1(月詠み)の箱へ入らず、癒やし倉庫(acc3)として載ること。
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('yt_scheduled__acc3') || '[]').length), { timeout: 15000 }).toBeGreaterThan(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('yt_scheduled__acc1') || '[]').length)).toBe(0);
  await page.locator('#reserveBtn').click();
  const rsvRow = page.locator('.rsv-tab-row').filter({ hasText: '予定時刻の動画' });
  await expect(rsvRow.locator('.rsv-tab-when')).toContainText(hm, { timeout: 15000 });
  await expect(rsvRow.locator('.rsv-badge')).toHaveText('癒やし倉庫');
});
