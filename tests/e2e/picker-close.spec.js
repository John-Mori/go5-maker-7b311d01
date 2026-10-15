// @ts-check
// 投稿モードで公開枠カレンダーを開いたまま「内容を保存」「投稿完了」を押したら、カレンダーも一緒に閉じる。
const { test, expect } = require('@playwright/test');

async function openWithPicker(page, draftId) {
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => typeof window.Go5Acct?.current)).toBe('function');
  await page.evaluate(({ draftId }) => {
    const account = window.Go5Acct.current();
    localStorage.setItem('go5_stock_meta', JSON.stringify([{
      id: draftId, ts: Date.now(), addedAt: Date.now(), account,
      label: 'カレンダー連動で閉じる', title: 'カレンダー連動で閉じる', author: 'test',
      bskyText: 'テスト本文', affiliateUrl: '', workUrl: '', videoName: 'test.mp4',
      videoId: account + '-20261015-0900-pick', attrs: {}
    }]));
  }, { draftId });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await expect(page.locator('#draftPostModal')).toBeVisible();
  await page.locator('#draftPubSched').check();
  await page.locator('#draftPickSlot').click();
  await expect(page.locator('#draftSlotPicker')).toBeVisible();
}

test.describe('公開枠カレンダーの自動クローズ', () => {
  test.beforeEach(async ({ context }) => {
    await context.route('**/*', (route) => {
      const u = new URL(route.request().url());
      if (u.hostname === '127.0.0.1' || u.hostname === 'localhost' || u.protocol === 'data:' || u.protocol === 'blob:') return route.continue();
      return route.abort();
    });
  });

  test('内容を保存でカレンダーも閉じる', async ({ page }) => {
    await openWithPicker(page, 'stk_e2e_pick_save');
    await page.locator('#draftModalSave').click();
    await expect(page.locator('#draftPostModal')).toBeHidden();
    await expect(page.locator('#draftSlotPicker')).toBeHidden();
  });

  test('投稿完了を押すと確認ダイアログの前にカレンダーが閉じ始める', async ({ page }) => {
    await openWithPicker(page, 'stk_e2e_pick_done');
    await page.evaluate(() => {
      window.confirm = () => { window.__pickerAtConfirm = document.getElementById('draftSlotPicker').style.transform; return false; };
    });
    await page.locator('#draftModalComplete').click();
    await expect.poll(() => page.evaluate(() => window.__pickerAtConfirm)).toBe('translateY(-100%)');
    await expect(page.locator('#draftSlotPicker')).toBeHidden();
    // キャンセルなのでモーダルは残る(投稿完了は取り消せる)。
    await expect(page.locator('#draftPostModal')).toBeVisible();
  });
});
