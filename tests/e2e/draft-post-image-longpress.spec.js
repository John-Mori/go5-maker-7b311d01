// @ts-check
// ドラフトの投稿モードの投稿画像が、黒帯つきの低い枠(max-height:220px・object-fit:contain)に押し込まれ、
//   blob:URLのためiPhoneの長押し保存も効かなかった
//   (Chami 2026-10-16 msg 1560575304139935815「ドラフトタブのここ普通の投稿画像にして長押ししたら普通にDLできるようにして」)。
//   黒帯の枠をやめて画像そのものを元の縦横比で出し(大きさは10-12の「こんなに大きくなくていい」=高さ220px上限を維持)、
//   src を data:URL にして長押しの保存メニューが出る形を本物の画面で固定する。
const { test, expect } = require('@playwright/test');

test('ドラフトの投稿画像は黒帯なし・元の縦横比・高さ220px以内・data:URL・長押し可', async ({ page }) => {
  const id = 'stk_e2e_post_img_lp';
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => !!window.Go5Idb)).toBe(true);
  await page.evaluate(async ({ id }) => {
    const c = document.createElement('canvas'); c.width = 300; c.height = 450; // 縦長(2:3)
    const g = c.getContext('2d'); g.fillStyle = '#ee44aa'; g.fillRect(0, 0, 300, 450);
    const blob = await new Promise((r) => c.toBlob(r, 'image/png'));
    await window.Go5Idb.set('stock_img_' + id, blob);
    const account = window.Go5Acct.current();
    localStorage.setItem('go5_stock_meta', JSON.stringify([{ id, ts: Date.now(), addedAt: Date.now(), account, label: '投稿画像の長押し', title: '投稿画像の長押し', author: 'test', videoName: 't.mp4', attrs: {} }]));
  }, { id });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator(`.stk-mode[data-id="${id}"]`).click();
  const img = page.locator('#draftImg');
  await expect(img).toBeVisible();
  await expect.poll(() => img.evaluate((el) => el.src.slice(0, 11))).toBe('data:image/');
  const m = await img.evaluate((el) => {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return { ratio: r.height / r.width, h: r.height, bg: cs.backgroundColor, fit: cs.objectFit, callout: cs.webkitTouchCallout || el.style.webkitTouchCallout || '' };
  });
  expect(m.ratio).toBeGreaterThan(1.45); // 元の2:3(=1.5)のまま=画像の外に黒帯の枠を作らない
  expect(m.ratio).toBeLessThan(1.55);
  expect(m.h).toBeLessThanOrEqual(222); // 10-12「こんなに大きくなくていい」の大きさは保つ(枠線2px込み)
  expect(m.bg).toBe('rgba(0, 0, 0, 0)');
  expect(m.fit).not.toBe('contain');
  expect(m.callout).not.toBe('none');
});
