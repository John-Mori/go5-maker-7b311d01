// @ts-check
// 無人ドラフト自動作成(β-5b)の境界を実物ページで固定する。
//   ①読み込んだだけで FivesecAutoDraft が版付きで居る(起動係はこの版で旧デプロイを見分ける)
//   ②同期未設定なら run() は作らずに理由を返す
//   ③video-created に載った auto/autoAlt が go5_stock_meta に残る(朝の見直しと二重生成の柵がこれを読む)
const { test, expect } = require('@playwright/test');

async function ready(page) {
  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!(window.Go5Stock && window.Go5VideoIntegrity && window.Go5Idb && window.FivesecAutoDraft));
  await page.evaluate(() => {
    localStorage.removeItem('go5_stock_meta');
    localStorage.removeItem('go5_stock_archive');
  });
}

test.describe('無人ドラフト自動作成の口', () => {
  test('版を持ち、同期未設定では作らずに理由を返す', async ({ page }) => {
    await ready(page);
    const r = await page.evaluate(async () => {
      if (window.Go5Sync) Go5Sync.configured = () => false;
      return { version: FivesecAutoDraft.version, res: await FivesecAutoDraft.run({ cid: 'd_e2e', date: '20261029', title: 'e2e', image: { b64: 'AA==' } }) };
    });
    expect(r.version).toBeGreaterThanOrEqual(1);
    expect(r.res).toEqual({ ok: false, reason: 'sync_unconfigured' });
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]'))).toEqual([]);
  });

  test('video-created の auto/autoAlt がドラフトのメタに残る', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      if (window.Go5Sync) Go5Sync.configured = () => false;
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: {
          draft: true, title: '自動作成回帰', name: 'auto.mp4', account: 'acc3',
          blob: new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' }),
          srcMark: { cid: 'd_e2e', hash: 'h1' },
          auto: { date: '20261029', rank: 2 }, autoAlt: { titles: ['別題1', '別題2'], hookNote: 'メモ' }
        }
      }));
    });
    await page.waitForFunction(() => {
      const list = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      return !!(list[0] && list[0].videoReadyAt);
    }, { timeout: 10000 });
    const meta = await page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]')[0]);
    expect(meta.auto).toEqual({ date: '20261029', rank: 2 });
    expect(meta.autoAlt).toEqual({ titles: ['別題1', '別題2'], hookNote: 'メモ' });
    expect(meta.srcMark).toEqual({ cid: 'd_e2e', hash: 'h1' });
  });

  test('手動作成のドラフトには auto を付けない', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      if (window.Go5Sync) Go5Sync.configured = () => false;
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: { draft: true, title: '手動回帰', name: 'manual.mp4', account: 'acc3', blob: new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' }) }
      }));
    });
    await page.waitForFunction(() => {
      const list = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      return !!(list[0] && list[0].videoReadyAt);
    }, { timeout: 10000 });
    const meta = await page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]')[0]);
    expect(meta.auto).toBeNull();
    expect(meta.autoAlt).toBeNull();
  });
});
