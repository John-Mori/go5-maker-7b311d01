// @ts-check
// 「セール中のみ」がなかなか反応しない番犬(Chami msg 1561149383263785023「セール中のみのボタンがなかなか反応しないの直して」)。
//   📚全候補は一覧をWorkerのカタログから引く。押した瞬間に画面を作り直して読み直しを待ち、
//   さらに押す前の(セール無しの)読み込みが後から返ると、絞った一覧を上書きしていた。
//   S-1 押した直後(Workerの返事を待たず)に、表示中のセール外カードが消える
//   S-2 押す前の遅い返事が後から来ても、絞った一覧を上書きしない
const { test, expect } = require('@playwright/test');

const FAKE = 'https://fake-worker.invalid';
const card = (cid, title, sale) => ({
  cid, title, url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/', date: '2026-10-01',
  listPrice: 1000, price: sale ? 500 : 1000, discountPct: sale ? 50 : 0
});

test('全候補の「セール中のみ」は押した直後に効き、古い返事で戻らない', async ({ page }) => {
  const allowedOrigin = new URL(process.env.BASE_URL || 'https://john-mori.github.io/go5-maker-7b311d01/').origin;
  let unfilteredCalls = 0;
  await page.route('**/*', async (route) => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin === allowedOrigin) return route.continue();
    if (url.origin !== FAKE) return route.abort();
    if (url.pathname === '/api/candidate-catalog' && req.method() === 'GET') {
      const sale = url.searchParams.get('sale') === '1';
      const items = sale ? [card('d_sale_1', 'セール作品A', true)]
        : [card('d_sale_1', 'セール作品A', true), card('d_full_1', '定価作品B', false), card('d_full_2', '定価作品C', false)];
      // 初回(セール無し)は速く返す。2回目以降のセール無しは「押す前に出ていた遅い読み込み」役で4秒待たせる。
      const delay = sale ? 2500 : (unfilteredCalls++ === 0 ? 0 : 4000);
      await new Promise(r => setTimeout(r, delay));
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, items, total: items.length, page: 1, pages: 1, progress: null }) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
  await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((FAKE) => {
    localStorage.setItem('fanza_worker_url', FAKE);
    localStorage.setItem('fanza_shared_secret', 'test-only');
  }, FAKE);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.cand-tab[data-ct="all"]').click();
  const list = page.locator('#candCardList');
  await expect(list.locator('.cand-card')).toHaveCount(3);

  // 押す前の読み込み(セール無し・遅い)を走らせておく=ページサイズの変更などで起きる再読込の役。
  await page.evaluate(() => { const s = document.getElementById('candPageSizeSel'); if (s) s.dispatchEvent(new Event('change')); });
  await page.waitForTimeout(100);

  await page.locator('#candFilterSale').check();
  // S-1: Workerの返事(2.5秒)より前に、セール外のカードが消えている
  await expect(list.locator('.cand-card:visible')).toHaveCount(1, { timeout: 800 });
  await expect(list.locator('.cand-card:visible')).toContainText('セール作品A');
  // S-2: 押す前の遅い返事(4秒)が来た後も絞ったまま
  await page.waitForTimeout(4500);
  await expect(list.locator('.cand-card:visible')).toHaveCount(1);
  await expect(page.locator('#candFilterSale')).toBeChecked();
});
