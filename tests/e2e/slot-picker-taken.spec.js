// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('ドラフト公開枠の重複表示', () => {
  test('別ドラフトで選んだ公開枠を題名つきで表示する', async ({ page }) => {
    const allowedOrigin = new URL(process.env.BASE_URL || 'https://john-mori.github.io/go5-maker-7b311d01/').origin;
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin === allowedOrigin) await route.continue();
      else await route.abort();
    });

    const firstId = 'stk_e2e_taken_first';
    const secondId = 'stk_e2e_taken_second';
    await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
    const account = await page.evaluate(({ firstId, secondId }) => {
      const account = window.Go5Acct.current();
      localStorage.setItem('go5_stock_meta', JSON.stringify([
        {
          id: firstId, ts: Date.now(), addedAt: Date.now(), account,
          label: '先約ドラフト', title: '先約ドラフト', author: 'test',
          bskyText: '先約本文', affiliateUrl: '', workUrl: '', videoName: 'first.mp4',
          videoId: account + '-20261015-0800-taken1', attrs: {}
        },
        {
          id: secondId, ts: Date.now() - 1, addedAt: Date.now() - 1, account,
          label: '後発ドラフト', title: '後発ドラフト', author: 'test',
          bskyText: '後発本文', affiliateUrl: '', workUrl: '', videoName: 'second.mp4',
          videoId: account + '-20261015-0801-taken2', attrs: {}
        }
      ]));
      return account;
    }, { firstId, secondId });
    await page.reload({ waitUntil: 'domcontentloaded' });

    await page.locator(`.stk-mode[data-id="${firstId}"]`).click();
    await page.locator('#draftPubSched').check();
    await page.locator('#draftPickSlot').click();

    const picker = page.frameLocator('#draftPickerFrame');
    const firstSlot = picker.locator(`.slot .cell[data-acc="${account}"]`).first();
    await expect(firstSlot).toBeVisible();
    await firstSlot.click();
    await picker.locator('#integ-pick').click();
    await expect(page.locator('#draftPickedSlot')).toContainText('選択中：');
    await expect(page.locator('#draftSlotPicker')).toBeHidden();

    // 選択した本人のドラフトから開き直した時も、その枠が使用中だと画面上で確認できる。
    await page.locator('#draftPickSlot').click();
    const ownTakenNote = picker.locator('.taken-note');
    await expect(ownTakenNote).toBeVisible();
    await expect(ownTakenNote).toContainText('選択済み：先約ドラフト');
    await page.locator('#draftPickerClose').click();
    await expect(page.locator('#draftSlotPicker')).toBeHidden();
    await page.locator('#draftModalClose').click();
    // モーダル側もピッカーを閉じるため、既存の280ms閉じ処理が終わってから次のドラフトを開く。
    await page.waitForTimeout(350);

    await page.locator(`.stk-mode[data-id="${secondId}"]`).click();
    await page.locator('#draftPubSched').check();
    await page.locator('#draftPickSlot').click();

    const takenNote = picker.locator('.taken-note');
    await expect(takenNote).toBeVisible();
    await expect(takenNote).toContainText('選択済み：先約ドラフト');
  });
});
