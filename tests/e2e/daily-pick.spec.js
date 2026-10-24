// @ts-check
// 今日のおすすめ(GET /api/daily-pick/latest)→動画作成タブの帯→カード押下で #top/#movieWorkUrl/前景画像が入る(設計 2026-10-24 §1)。
// 中身は合成データ。フック画像は r2_key 経由(/img/:key)で読む=dmm直リンクのCORS落ちを避ける経路を通す。
const { test, expect } = require('@playwright/test');

const SYNC = 'https://sync.e2e.invalid';
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC', 'base64');

function jstToday() { return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10); }
function pickDoc(date) {
  return { date, channel: 'acc3', items: [1, 2, 3].map((i) => ({
    rank: i, cid: 'd_e2e_pick' + i, title: 'おすすめ確認作品' + i, circle: 'e2eサークル' + i, price: 990, sales_n: 1000 * i,
    work_url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_pick' + i + '/',
    hook: { url: 'https://doujin-assets.dmm.co.jp/digital/comic/d_e2e_pick' + i + '/x.jpg', index: 1, r2_key: ('a' + i).repeat(32), note: '' },
    titles: [{ text: '題名案' + i + '-1', reason: '' }, { text: '題名案' + i + '-2', reason: '' }], avoid: [],
  })) };
}

test('今日のおすすめ帯に3件出て、押した作品と題名案が動画作成へ入る', async ({ page }) => {
  const doc = pickDoc(jstToday());
  let pickHits = 0, imgHits = 0, dmmHits = 0;
  await page.route(SYNC + '/**', (route) => {
    const p = new URL(route.request().url()).pathname;
    if (p === '/api/daily-pick/latest') { pickHits++; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(doc) }); }
    if (p.startsWith('/img/')) { imgHits++; return route.fulfill({ status: 200, contentType: 'image/png', headers: { 'access-control-allow-origin': '*' }, body: PNG }); }
    return route.abort();
  });
  await page.route('https://doujin-assets.dmm.co.jp/**', (route) => { dmmHits++; return route.abort(); });

  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((SYNC) => { localStorage.clear(); localStorage.setItem('sync2_url', SYNC); localStorage.setItem('sync2_token', 'e2e-token'); }, SYNC);
  await page.reload({ waitUntil: 'domcontentloaded' });

  const band = page.locator('#dailyPickBand');
  await expect(band).toBeVisible();
  await expect(band.locator('.dp-card')).toHaveCount(3);
  expect(pickHits).toBeGreaterThan(0);

  // 2件目の題名案2を選んで押す
  const card = band.locator('.dp-card').nth(1);
  await card.locator('input[type="radio"][value="1"]').check();
  await card.locator('.dp-go').click();
  await expect(page.locator('#top')).toHaveValue('題名案2-2');
  await expect(page.locator('#movieWorkUrl')).toHaveValue(doc.items[1].work_url);
  await expect(page.locator('#author')).toHaveValue('e2eサークル2');
  await expect(page.locator('#photoName')).not.toHaveText('未選択', { timeout: 15000 });
  expect(imgHits).toBeGreaterThan(0);
  expect(dmmHits).toBe(0); // r2_key が在る時は dmm 直リンクを読まない

  const done = await page.evaluate(() => Object.keys(JSON.parse(localStorage.getItem('daily_pick_done') || '{}')));
  expect(done).toEqual(['d_e2e_pick2']);
  const mark = await page.evaluate(() => JSON.parse(sessionStorage.getItem('daily_pick_active') || 'null'));
  expect(mark && mark.cid).toBe('d_e2e_pick2');
  await expect(band.locator('.dp-card').nth(1)).toContainText('作成済み');
});

test('前日の分しか無ければ帯を出さない', async ({ page }) => {
  const doc = pickDoc('2000-01-01');
  await page.route(SYNC + '/**', (route) => new URL(route.request().url()).pathname === '/api/daily-pick/latest'
    ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(doc) }) : route.abort());
  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((SYNC) => { localStorage.clear(); localStorage.setItem('sync2_url', SYNC); localStorage.setItem('sync2_token', 'e2e-token'); }, SYNC);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(async () => page.evaluate(() => !!localStorage.getItem('daily_pick_v1'))).toBe(true);
  await expect(page.locator('#dailyPickBand')).toBeHidden();
});
