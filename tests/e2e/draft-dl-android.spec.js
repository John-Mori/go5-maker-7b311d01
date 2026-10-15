// @ts-check
// Androidのドラフト「動画DL」は1回のタップで保存まで行く(Chami 2026-10-15 msg 1560117573687840769
//   「もう一度タップさせないでダウンロードさせてよ」)。取得に3秒を超えると共有シート経路が
//   「もう一度タップで保存」へ倒れていたので、その遅い取得を再現して1タップでダウンロードが起きることを固定する。
const { test, expect } = require('@playwright/test');

test.use({
  userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36'
});

test('Androidはドラフトの動画DLを1タップでダウンロードする', async ({ page }) => {
  const allowedOrigin = new URL(process.env.BASE_URL || 'https://john-mori.github.io/go5-maker-7b311d01/').origin;
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === allowedOrigin) await route.continue();
    else await route.abort();
  });

  const id = 'stk_e2e_android_dl';
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!(window.Go5Acct && window.Go5Idb));
  await page.evaluate(async ({ id }) => {
    const account = window.Go5Acct.current();
    localStorage.setItem('go5_stock_meta', JSON.stringify([{
      id, ts: Date.now(), addedAt: Date.now(), account,
      label: 'DL確認', title: 'DL確認', author: 'test', bskyText: '本文',
      affiliateUrl: '', workUrl: '', videoName: 'android.mp4', videoId: account + '-20261015-1200-dl1', attrs: {}
    }]));
    await window.Go5Idb.set('stock_v_' + id, new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' }));
  }, { id });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.Go5Idb);

  // Android Chrome と同じく共有シートAPIは「有る」。取得はタップから3秒超かかった扱いにする(Date.nowを進める)。
  await page.evaluate(({ id }) => {
    navigator.canShare = () => true;
    navigator.share = () => { window.__shared = (window.__shared || 0) + 1; return Promise.reject(Object.assign(new Error('x'), { name: 'NotAllowedError' })); };
    const realNow = Date.now.bind(Date);
    let skew = 0;
    Date.now = () => realNow() + skew;
    const realGet = window.Go5Idb.get.bind(window.Go5Idb);
    window.Go5Idb.get = (key) => realGet(key).then((v) => { if (String(key) === 'stock_v_' + id) skew += 5000; return v; });
  }, { id });

  await page.locator(`.stk-mode[data-id="${id}"]`).click();
  const dl = page.locator('#draftDlVideo');
  await expect(dl).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    dl.click()
  ]);
  expect(download.suggestedFilename()).toBe('android.mp4');
  await expect(dl).not.toContainText('もう一度タップ');
  expect(await page.evaluate(() => window.__shared || 0)).toBe(0);
});
