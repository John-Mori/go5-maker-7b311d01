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

  // 予約投稿して投稿完了を押すとドラフトは一覧から外れる。それでも枠は埋まっているので、
  //   次のドラフトのピッカーに題名つきで出す(Chami 2026-10-15「どこが？」・癒やし倉庫の実機)。
  test('投稿完了した予約投稿の枠も題名つきで表示する', async ({ page }) => {
    const allowedOrigin = new URL(process.env.BASE_URL || 'https://john-mori.github.io/go5-maker-7b311d01/').origin;
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin === allowedOrigin) await route.continue();
      else await route.abort();
    });

    const doneId = 'stk_e2e_taken_done';
    const nextId = 'stk_e2e_taken_next';
    await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ doneId, nextId }) => {
      localStorage.setItem('current_account', 'acc3');
      const now = Date.now();
      localStorage.setItem('go5_stock_meta', JSON.stringify([
        {
          id: doneId, ts: now, addedAt: now, account: 'acc3',
          label: '予約済みの動画', title: '予約済みの動画', author: 'test',
          bskyText: '本文', affiliateUrl: '', workUrl: '', videoName: 'done.mp4',
          videoId: 'acc3-20261015-1100-done1', attrs: {}
        },
        {
          id: nextId, ts: now - 1, addedAt: now - 1, account: 'acc3',
          label: '次のドラフト', title: '次のドラフト', author: 'test',
          bskyText: '本文', affiliateUrl: '', workUrl: '', videoName: 'next.mp4',
          videoId: 'acc3-20261015-1101-next1', attrs: {}
        }
      ]));
    }, { doneId, nextId });
    await page.reload({ waitUntil: 'domcontentloaded' });

    // 1本目:翌週の枠を選んで予約 → 投稿完了(本物の確認ダイアログはOK)。
    await page.locator(`.stk-mode[data-id="${doneId}"]`).click();
    await page.locator('#draftPubSched').check();
    await page.locator('#draftPickSlot').click();
    const picker = page.frameLocator('#draftPickerFrame');
    await picker.getByRole('button', { name: /翌週/ }).click();
    const slot = picker.locator('.slot .cell[data-acc="acc3"]').first();
    await expect(slot).toBeVisible();
    await slot.click();
    await picker.locator('#integ-pick').click();
    await expect(page.locator('#draftPickedSlot')).toContainText('選択中：');
    page.on('dialog', (d) => d.accept());
    await page.locator('#draftModalComplete').click();
    await expect(page.locator('#draftPostModal')).toBeHidden();
    await expect(page.locator(`.stk-mode[data-id="${doneId}"]`)).toHaveCount(0);
    await page.waitForTimeout(350);

    // 2本目:同じ週を開くと、1本目の枠に題名が出る。
    await page.locator(`.stk-mode[data-id="${nextId}"]`).click();
    await page.locator('#draftPubSched').check();
    await page.locator('#draftPickSlot').click();
    // ピッカーの iframe は使い回され、前回の「翌週」表示が残る。今週へ戻してから翌週を開き直す。
    await picker.getByRole('button', { name: /^今週$/ }).click();
    await picker.getByRole('button', { name: /翌週/ }).click();
    const takenNote = picker.locator('.taken-note');
    await expect(takenNote).toBeVisible();
    await expect(takenNote).toContainText('選択済み：予約済みの動画');
  });
});
