// @ts-check
const { test, expect } = require('@playwright/test');

async function makeForeground(page, name, color, origin = 'manual-test') {
  return page.evaluate(async ({ name, color, origin }) => {
    const canvas = document.createElement('canvas');
    canvas.width = 48; canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = color; ctx.fillRect(0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    const file = new File([blob], name, { type: 'image/png', lastModified: Date.now() });
    return window.Go5SetForegroundFileReady(file, null, { origin });
  }, { name, color, origin });
}

test.describe('動画生成用画像の耐久保存', () => {
  test('localStorage容量超過でもIDB正本から画像・File・候補由来をreload復元する', async ({ page }) => {
    await page.addInitScript(() => {
      const realSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (this === localStorage && key === 'movie_photo_cache') {
          throw new DOMException('forced quota', 'QuotaExceededError');
        }
        return realSetItem.call(this, key, value);
      };
    });
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => { window.__go5MovieSrcMark = { cid: 'd_foreground_keep', hash: 'hash-keep' }; });

    const receipt = await makeForeground(page, 'keep-after-crash.png', '#13c66b', 'candidate');
    expect(receipt.ok).toBe(true);
    expect(receipt.primary).toBe(true);
    expect(await page.evaluate(() => localStorage.getItem('movie_photo_cache'))).toBeNull();
    const before = await page.evaluate(async () => {
      const head = await Go5Idb.getResult('movie:foreground:head:v1');
      const data = head.ok && head.value && head.value.key ? await Go5Idb.getResult(head.value.key) : null;
      return {
        headOk: !!(head.ok && head.value && !head.value.empty),
        blobOk: !!(data && data.ok && data.value && data.value.blob && data.value.blob.size),
        tokenMatch: !!(data && data.value && head.value && data.value.token === head.value.token)
      };
    });
    expect(before).toEqual({ headOk: true, blobOk: true, tokenMatch: true });

    await page.reload({ waitUntil: 'domcontentloaded' });
    const restored = await page.evaluate(async () => {
      const ready = await Go5ForegroundReady();
      const file = Go5ForegroundFile();
      return {
        ready: !!ready.ok,
        primary: !!ready.primary,
        name: file && file.name,
        size: file && file.size,
        hasRect: !!Go5PhotoRect(),
        mark: window.__go5MovieSrcMark || null
      };
    });
    expect(restored.ready).toBe(true);
    expect(restored.primary).toBe(true);
    expect(restored.name).toBe('keep-after-crash.png');
    expect(restored.size).toBeGreaterThan(0);
    expect(restored.hasRect).toBe(true);
    expect(restored.mark).toEqual({ cid: 'd_foreground_keep', hash: 'hash-keep' });
  });

  test('新しい画像だけを復元し、明示消去後は古い画像を復活させない', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    expect((await makeForeground(page, 'old-red.png', '#ff0000')).primary).toBe(true);
    expect((await makeForeground(page, 'new-blue.png', '#0055ff')).primary).toBe(true);
    await page.evaluate(() => localStorage.removeItem('movie_photo_cache'));

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(async () => {
      await Go5ForegroundReady();
      return Go5ForegroundFile() && Go5ForegroundFile().name;
    })).toBe('new-blue.png');

    const cleared = await page.evaluate(async () => {
      Go5ClearForeground();
      return Go5ForegroundReady();
    });
    expect(cleared.primary).toBe(true);
    await page.reload({ waitUntil: 'domcontentloaded' });
    const empty = await page.evaluate(async () => {
      await Go5ForegroundReady();
      return { file: !!Go5ForegroundFile(), rect: !!Go5PhotoRect(), label: document.getElementById('photoName').textContent };
    });
    expect(empty).toEqual({ file: false, rect: false, label: '未選択' });
  });

  test('旧版のlocalStorage画像を初回にIDB正本へ移し、旧キャッシュ削除後も復元する', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('movie_photo_cache', 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl3Z0QAAAAASUVORK5CYII=');
    });
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    const migrated = await page.evaluate(async () => {
      const ready = await Go5ForegroundReady();
      const head = await Go5Idb.getResult('movie:foreground:head:v1');
      return { ready: !!ready.ok, primary: !!ready.primary, head: !!(head.ok && head.value && head.value.key) };
    });
    expect(migrated).toEqual({ ready: true, primary: true, head: true });
    await page.evaluate(() => localStorage.removeItem('movie_photo_cache'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(async () => {
      await Go5ForegroundReady();
      return !!(Go5ForegroundFile() && Go5PhotoRect());
    })).toBe(true);
  });

  test('ドラフト再作成は前景IDB着地失敗時に元ドラフトを消さず、再試行成功後だけ外す', async ({ page }) => {
    const id = 'stock-remake-foreground-safe';
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(async ({ id }) => {
      const canvas = document.createElement('canvas');
      canvas.width = 32; canvas.height = 48;
      canvas.getContext('2d').fillStyle = '#ee44aa';
      canvas.getContext('2d').fillRect(0, 0, 32, 48);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
      await Go5Idb.set('stock_img_' + id, blob);
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('go5_stock_meta', JSON.stringify([{
        id, account: 'acc1', title: '再作成の元画像', label: '再作成の元画像', author: 'test',
        ts: Date.now(), attrs: {}, workUrl: '', goal: '', cmtType: ''
      }]));
      sessionStorage.setItem('go5_stock_remake_pending', id);
    }, { id });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      window.Go5SetForegroundFileReady = () => Promise.resolve({ ok: false, primary: false, reason: 'forced-test' });
    });
    await page.waitForTimeout(900);
    expect(await page.evaluate(({ id }) => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]').some((m) => m.id === id), { id })).toBe(true);
    expect(await page.evaluate(async ({ id }) => !!(await Go5Idb.get('stock_img_' + id)), { id })).toBe(true);

    await page.evaluate(({ id }) => sessionStorage.setItem('go5_stock_remake_pending', id), { id });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(({ id }) => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]').some((m) => m.id === id), { id })).toBe(false);
    await expect.poll(() => page.evaluate(() => !!(Go5ForegroundFile() && Go5PhotoRect()))).toBe(true);
  });

  test('販促ラベルの新規既定値は78%', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      localStorage.removeItem('promo_label_scale');
      localStorage.removeItem('promo_label_scale__acc1');
      localStorage.removeItem('promo_label_scale__acc2');
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#promoSizeVal')).toHaveText('78%');
  });
});
