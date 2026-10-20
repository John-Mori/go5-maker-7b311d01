// @ts-check
// 候補一覧で画像が⏳のまま残る症状(REQ-research-room-f67a6c602b・Chami 2026-08-24 msg 1541140745279512697)の段1。
//   カードが画面の手前に入った時にも per-cid 取得を起こす(IntersectionObserver)。
//   T-1 候補カードがobserverに登録される  T-2 端末内に画像がある多数カードで、末尾までスクロールすると全部に画像が出る
const { test, expect } = require('@playwright/test');

const PNG_DATA = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
const N = 40;

test('候補カードは画面に近づくと画像取得が起き、末尾まで画像が出る', async ({ page }) => {
  await page.addInitScript(() => {
    window.__ioObserved = 0;
    const Orig = window.IntersectionObserver;
    window.IntersectionObserver = function (cb, opt) {
      const io = new Orig(cb, opt);
      const ob = io.observe.bind(io);
      io.observe = function (el) { if (el && el.getAttribute && el.getAttribute('data-cid') && el.classList.contains('cand-card')) window.__ioObserved++; return ob(el); };
      return io;
    };
  });
  await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!window.Go5Idb);
  await page.evaluate(async ({ n, png }) => {
    localStorage.setItem('current_account', 'acc1');
    localStorage.setItem('sync2_url', location.origin);
    localStorage.removeItem('sync2_token');
    const items = [], now = Date.now();
    for (let i = 0; i < n; i++) {
      const cid = 'd_io_near_' + i;
      items.push({ cid, title: '近接取得' + i, url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/', addedAt: now - i });
      await window.Go5Idb.set('ref:' + cid, { imgs: [png], at: now - 60000 });
    }
    localStorage.setItem('cand_items', JSON.stringify(items));
  }, { n: N, png: PNG_DATA });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => window.__ioObserved), { timeout: 15000 }).toBeGreaterThan(0);
  // 末尾へスクロールし続け、描画済みの全カードに画像が付くまで待つ(カードは再描画で差し替わるのでDOMを毎回読む)。
  await expect.poll(async () => page.evaluate(() => {
    window.scrollTo(0, document.documentElement.scrollHeight);
    const cards = Array.from(document.querySelectorAll('.cand-card[data-cid]'));
    const withImg = cards.filter((c) => { const im = c.querySelector('img[data-refimgview]'); return im && /^data:image\/png/.test(im.getAttribute('src') || ''); });
    return cards.length > 0 && withImg.length === cards.length ? cards.length : -1;
  }), { timeout: 25000 }).toBeGreaterThan(0);
});
