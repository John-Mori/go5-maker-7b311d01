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
  // 過去日(昨日)に投稿した分も、ピッカーで見返すと題名が出る。題名の後ろのタグは出さない
  //   (Chami 2026-10-18「ドラフト参照時のカレンダー、昨日など過去や未来の情報を保存したものを表示するようにして。題名の後ろのタグは非表示でいい」)。
  test('昨日の投稿もタグ抜きの題名で表示する', async ({ page }) => {
    const allowedOrigin = new URL(process.env.BASE_URL || 'https://john-mori.github.io/go5-maker-7b311d01/').origin;
    await page.route('**/*', async (route) => {
      const url = new URL(route.request().url());
      if (url.origin === allowedOrigin) await route.continue();
      else await route.abort();
    });
    const draftId = 'stk_e2e_taken_past';
    await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
    const info = await page.evaluate(({ draftId }) => {
      const jst = (ms) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ms));
      const today = jst(Date.now());
      const y = jst(Date.parse(today + 'T12:00:00+09:00') - 86400000);
      localStorage.setItem('current_account', 'acc3');
      localStorage.setItem('hist_post_time_v1', '{}');
      localStorage.setItem('verify_manual__acc3', '[]');
      localStorage.setItem('short_hist__acc3', JSON.stringify([
        { videoId: 'acc3-past-1', ts: Date.now() - 86400000, plannedAt: y + 'T13:07:00+09:00', title: '昨日の動画 #shorts #漫画 #漫画紹介', account: 'acc3' }
      ]));
      const now = Date.now();
      localStorage.setItem('go5_stock_meta', JSON.stringify([{
        id: draftId, ts: now, addedAt: now, account: 'acc3', label: '今日のドラフト', title: '今日のドラフト', author: 'test',
        bskyText: '本文', affiliateUrl: '', workUrl: '', videoName: 'p.mp4', videoId: 'acc3-20261018-0900-past', attrs: {}
      }]));
      const wd = new Date(today + 'T12:00:00+09:00').getUTCDay();
      return { md: y.slice(5).replace('-', '/'), monday: wd === 1 };
    }, { draftId });
    await page.reload({ waitUntil: 'domcontentloaded' });

    await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
    await page.locator('#draftPubSched').check();
    await page.locator('#draftPickSlot').click();
    const picker = page.frameLocator('#draftPickerFrame');
    await expect(picker.locator('.slot .cell[data-acc="acc3"]').first()).toBeVisible();
    if (info.monday) await picker.getByRole('button', { name: /前週/ }).click();
    const day = picker.locator('.day').filter({ has: picker.locator('.day-md', { hasText: info.md }) }).first();
    const note = day.locator('.taken-note');
    await expect(note).toHaveCount(1);
    await expect(note).toContainText('投稿済み：昨日の動画(13:07公開)');
    await expect(note).not.toContainText('#');
  });
});
