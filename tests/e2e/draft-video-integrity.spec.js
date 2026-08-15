// @ts-check
// 黒いサムネ/DL不能ドラフトの再発防止。
// 実物ページの video-created 境界へ故障Blobを投入し、二相コミットが fail-closed することを固定する。
const { test, expect } = require('@playwright/test');

async function ready(page) {
  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!(window.Go5Stock && window.Go5VideoIntegrity && window.Go5Idb));
  await page.evaluate(() => {
    localStorage.removeItem('go5_stock_meta');
    localStorage.removeItem('go5_stock_archive');
  });
}

test.describe('ドラフト動画の完全性ゲート', () => {
  test('空Blobは一覧へ確定せず、ページに留まって明示エラーにする', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: {
          draft: true, title: '空動画回帰', name: 'empty.mp4', account: 'acc1',
          blob: new Blob([], { type: 'video/mp4' })
        }
      }));
    });

    await expect(page.locator('#go5SaveHold')).toBeVisible();
    await expect(page.locator('#go5SaveHoldMsg')).toContainText('空または不完全');
    await expect(page.locator('#go5SaveRetry')).toBeHidden();
    expect(page.url()).toContain('index.html');
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]'))).toEqual([]);
  });

  test('IDBがset成功を返しても読み戻せなければ正常ドラフトにしない', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      const realSet = Go5Idb.set.bind(Go5Idb);
      const realGet = Go5Idb.get.bind(Go5Idb);
      Go5Idb.set = (key, value) => String(key).startsWith('stock_v_') ? Promise.resolve() : realSet(key, value);
      Go5Idb.get = (key) => String(key).startsWith('stock_v_') ? Promise.resolve(null) : realGet(key);
      if (window.Go5Sync) Go5Sync.configured = () => false;
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: {
          draft: true, title: '読戻し失敗回帰', name: 'readback.mp4', account: 'acc1',
          blob: new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' })
        }
      }));
    });

    await expect(page.locator('#go5SaveHold')).toBeVisible();
    await expect(page.locator('#go5SaveHoldMsg')).toContainText('この端末にも雲にも確認できません');
    expect(page.url()).toContain('index.html');
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]'))).toEqual([]);
  });

  test('書込み後に読める動画だけがメタ確定され、ドラフトページへ進む', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      if (window.Go5Sync) Go5Sync.configured = () => false;
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: {
          draft: true, title: '正常着地回帰', name: 'landed.mp4', account: 'acc1',
          blob: new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' })
        }
      }));
    });

    await page.waitForURL(/Stock\.html/, { timeout: 10000 });
    const saved = await page.evaluate(async () => {
      const list = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      const meta = list[0] || null;
      const blob = meta ? await Go5Idb.get('stock_v_' + meta.id) : null;
      return { count: list.length, ready: !!(meta && meta.videoReadyAt), bytes: meta && meta.videoBytes, blobBytes: blob && blob.size };
    });
    expect(saved).toEqual({ count: 1, ready: true, bytes: 32 * 1024, blobBytes: 32 * 1024 });
  });

  test('サイズだけ大きい破損mp4はブラウザの再生確認で拒否する', async ({ page }) => {
    await ready(page);
    const playable = await page.evaluate(() => Go5VideoIntegrity.probePlayable(
      new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' }),
      { timeoutMs: 2000 }
    ));
    expect(playable).toBe(false);
  });

});
