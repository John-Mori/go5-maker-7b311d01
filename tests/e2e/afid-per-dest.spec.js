const { test, expect } = require('@playwright/test');

// 出先別af_id(2026-10-21 三笘 msg 1562215078760292413):
// Bluesky投稿はchごとのBluesky用af_id(fanza_af_id_bsky__accN・空欄=fanza_af_id)、Xは fanza_af_id のまま。
// 短縮の転送先(=af_id込みURL)が出先で変わるので、短縮リンクも出先ごとに別になる。
const X_AF = 'e2e-x-001';
const BSKY_AF = 'e2e-bsky-002';

test.describe('出先別af_id', () => {
  test('Bluesky側はch別af_idで短縮・X側はfanza_af_idの生リンク・空欄chは既定へ戻る', async ({ page }) => {
    const acc = 'acc3';
    const saleUrl = 'https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=mens/';
    const domain = 'e2e-afid.example';
    const shortened = [];
    await page.route('**/api/shorten', async (route) => {
      const destination = new URLSearchParams(route.request().postData() || '').get('url') || '';
      shortened.push(destination);
      const code = /campaign%3Dgain/.test(destination) ? 'sale' : (/d_e2e_qa/.test(destination) ? 'work' : 'other' + shortened.length);
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ short: 'https://' + domain + '/' + code, url: destination }) });
    });
    await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ acc, saleUrl, domain, X_AF, BSKY_AF }) => {
      localStorage.setItem('current_account', acc);
      localStorage.setItem('short_worker_url__' + acc, 'https://' + domain);
      localStorage.setItem('fanza_af_id', X_AF);
      localStorage.setItem('fanza_af_id_bsky__' + acc, BSKY_AF);
      localStorage.removeItem('fanza_af_id_bsky__acc1');
      localStorage.setItem('disc_urls_seeded__' + acc, '1');
      localStorage.setItem('bsky_discount_urls__' + acc, JSON.stringify([{ id: 'sale-' + acc, name: 'E2Eセール', url: saleUrl, at: Date.now() }]));
      localStorage.setItem('bsky_discount_selected__' + acc, 'sale-' + acc);
      localStorage.removeItem('bsky_discount_link_cache');
    }, { acc, saleUrl, domain, X_AF, BSKY_AF });

    // 読み分けの正本
    const ids = await page.evaluate(() => ({ x: window.Go5AfIdFor('x'), b3: window.Go5AfIdFor('bsky', 'acc3'), b1: window.Go5AfIdFor('bsky', 'acc1') }));
    expect(ids).toEqual({ x: X_AF, b3: BSKY_AF, b1: X_AF });

    // Bluesky本文のセール行=Bluesky用af_idで包んで短縮
    const line = await page.evaluate(() => window.Go5SaleLineText());
    expect(line).toContain('https://' + domain + '/sale');
    const saleDest = shortened.find((u) => /campaign%3Dgain/.test(u)) || '';
    expect(new URL(saleDest).searchParams.get('af_id')).toBe(BSKY_AF);

    // X側(ドラフトX親文)は X用af_id の生リンクのまま
    const workAff = 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fwww.dmm.co.jp%2Fdc%2Fdoujin%2F-%2Fdetail%2F%3D%2Fcid%3Dd_e2e_x_only%2F&af_id=' + X_AF + '&ch=link_tool&ch_id=link';
    const xText = await page.evaluate((workAff) => window.__go5ComposeXTextForBskyText('X本文 紹介用短縮リンク\nセール中短縮リンク', workAff), workAff);
    expect(xText).toContain('af_id=' + X_AF);
    expect(xText).not.toContain(BSKY_AF);

    // 即アフィ(Bluesky用)の作品短縮=Bluesky用af_id
    await page.locator('#quickAffiBtn').click();
    await page.locator('#qaUrl').fill('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_qa/');
    await page.locator('.qa-go').click();
    await expect(page.locator('#qaOut')).toHaveValue('https://' + domain + '/work');
    const workDest = shortened.find((u) => /d_e2e_qa/.test(u)) || '';
    expect(new URL(workDest).searchParams.get('af_id')).toBe(BSKY_AF);
  });

  test('AFIリンクタブにch別のBluesky用af_id欄が出て、入力が保存される', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => { localStorage.removeItem('fanza_af_id_bsky__acc3'); window.Go5RenderBskyAfRows && window.Go5RenderBskyAfRows(); });
    await page.getByRole('button', { name: 'AFIリンク' }).click();
    const inp = page.locator('#afIdBsky-acc3');
    await expect(inp).toBeVisible();
    await expect(inp).toHaveAttribute('placeholder', '空欄=①と同じ');
    await inp.fill('e2e-bsky-777');
    await expect.poll(() => page.evaluate(() => localStorage.getItem('fanza_af_id_bsky__acc3'))).toBe('e2e-bsky-777');
    await inp.fill('');
    await expect.poll(() => page.evaluate(() => localStorage.getItem('fanza_af_id_bsky__acc3'))).toBe(null);
  });
});
