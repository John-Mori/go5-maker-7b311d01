// 投稿モードの子の文は、そのchの投稿本文(bsky_text__accN)だけを正にする
// (Chami msg 1561150497170399334「ドラフトの子の文はここの投稿本文を参照して」)。
// v1055の書き戻し(子の文の手直し→投稿本文)で、テンプレ帳を反映した投稿本文が上書きされていた。
// (acc3でも%OFF入りのセール行は残す。そちらは child-text-sale-line.spec.js で見る)
const { test, expect } = require('@playwright/test');

test('子の文は投稿本文から作られ、手直ししても投稿本文を上書きしない', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('Stock.html', { waitUntil: 'load' });
  await page.waitForTimeout(800); // 初回起動の既定値書き込みが済んでから本文を入れる(入れた本文を既定値で上書きされない)
  const account = await page.evaluate(() => {
    const account = window.Go5Acct.current();
    localStorage.setItem(window.Go5Acct.key('bsky_text', account), '⇩気になった方はコチラから💕 #PR #漫画\n⇩オータムセール🌰開催中!');
    const d = (id, ts) => ({ id, ts, addedAt: ts, account, label: id, title: id, author: 'test',
      bskyText: '当時の本文', affiliateUrl: '', workUrl: '', videoName: 'test.mp4', videoId: 'vid_' + id, attrs: {} });
    localStorage.setItem('go5_stock_meta', JSON.stringify([d('stk_wb_a', Date.now()), d('stk_wb_b', Date.now() - 1000)]));
    return account;
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  const master = () => page.evaluate((a) => localStorage.getItem(window.Go5Acct.key('bsky_text', a)), account);

  const fromMaster = /^⇩気になった方はコチラから💕 #PR #漫画\n(.+\n)?⇩オータムセール🌰開催中!$/; // 2行目(話題作等)は自動で入る
  await page.locator('.stk-mode[data-id="stk_wb_a"]').click();
  await expect(page.locator('#draftXText')).toHaveValue(fromMaster);
  await page.locator('#draftXText').fill('この投稿だけ直した');
  expect(await master()).toBe('⇩気になった方はコチラから💕 #PR #漫画\n⇩オータムセール🌰開催中!');

  // 開いたまま投稿本文が変わったら(テンプレ帳反映/同期)、手直し中でなければ子の文も追従する
  await page.keyboard.press('Escape').catch(() => {});
  await page.evaluate(() => { const m = document.getElementById('draftPostModal'); if (m) m.style.display = 'none'; });
  await page.locator('.stk-mode[data-id="stk_wb_b"]').click();
  await expect(page.locator('#draftXText')).toHaveValue(fromMaster);
  await page.evaluate((a) => {
    localStorage.setItem(window.Go5Acct.key('bsky_text', a), '新しい本文\n⇩ハロウィンセール🎃');
    document.dispatchEvent(new CustomEvent('go5-body-changed'));
  }, account);
  await expect(page.locator('#draftXText')).toHaveValue('新しい本文\n⇩ハロウィンセール🎃'); // 見出し行が無い本文は2行目を足さない
  expect(errors).toEqual([]);
});
