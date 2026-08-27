// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('投稿履歴のツリー設定', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      const videoId = 'acc1-20260827-1200-tree1';
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('bsky_gas_url', '');
      localStorage.setItem('hist_maint_at', String(Date.now()));
      localStorage.setItem('hist_metrics_at', String(Date.now()));
      localStorage.setItem('short_hist__acc1', JSON.stringify([{
        videoId, ts: Date.now(), title: 'ツリー計測テスト作品', account: 'acc1',
        ytUrl: 'https://youtu.be/AbCdEfGhI12',
        shortUrl: 'https://5mgl.com/parent1', workShortUrl: 'https://5mgl.com/work01'
      }]));
      localStorage.setItem('verify_manual__acc1', '[]');
      localStorage.setItem('verify_yt__acc1', '{}');
      localStorage.setItem('clicks_cache', JSON.stringify({ parent1: 2, work01: 4, tree01: 17 }));
      localStorage.setItem('yt_meta_cache', JSON.stringify({ AbCdEfGhI12: { title: 'YouTube動画の題名' } }));
      localStorage.setItem('fanza_af_id', 'sample-001');
      localStorage.removeItem('go5_tree_links_v1');
      sessionStorage.setItem('go5_manual_short_last__acc1', JSON.stringify({
        shortUrl: 'https://5mgl.com/tree01', affiliateOk: true, at: Date.now()
      }));
    });
    await page.route('https://5mgl.com/api/list**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, links: [
        { code: 'parent1', clicks: 2, today: 0, yesterday: 0, week: 0 }, { code: 'work01', clicks: 4, today: 0, yesterday: 0, week: 0 }, { code: 'tree01', clicks: 17, today: 8, yesterday: 5, week: 13 }
      ] }) });
    });
  });

  test('返信URLは短縮せず、表示名とピンク矢印クリック数を親履歴へ保存する', async ({ page }) => {
    await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.vrow').first()).toBeVisible();
    await page.locator('.vedit-btn').first().click();
    await expect(page.getByText('🌳 ツリー設定')).toBeVisible();
    await expect(page.locator('.vedit-heading')).toContainText('URL を編集YouTube動画の題名');
    const row = page.locator('.vedit-tree-row').first();
    await row.locator('.vedit-tree-name').fill('続編はこちら');
    await row.locator('.vedit-tree-post').fill('https://x.com/example/status/1234567890');
    await expect(row.locator('.vedit-tree-short')).toHaveValue('https://5mgl.com/tree01');
    await page.locator('#veditSave').click();

    const tree = page.locator('.vrow-tree-row').first();
    await expect(tree).toContainText('続編はこちら');
    await expect(tree).toContainText('今日 8');
    await expect(tree).toContainText('昨日 5');
    await expect(tree).toContainText('今週 13');
    await expect(tree.locator('a')).toHaveAttribute('href', 'https://x.com/example/status/1234567890');
    await expect(tree.locator('img').first()).toHaveAttribute('src', 'assets/icons/ic-cursor-pink.png');

    const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('go5_tree_links_v1') || '{}'));
    const rec = saved['acc1|v:acc1-20260827-1200-tree1'];
    expect(rec.trees).toHaveLength(1);
    expect(rec.trees[0]).toMatchObject({ name: '続編はこちら', postUrl: 'https://x.com/example/status/1234567890', shortUrl: 'https://5mgl.com/tree01' });
  });

  test('元作品URLをアフィ化し、チャンネルの新ドメインで短縮してからOKを表示する', async ({ page }) => {
    let destination = '';
    await page.route('https://5mgl.com/api/shorten', async (route) => {
      const body = route.request().postData() || '';
      destination = new URLSearchParams(body).get('url') || '';
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ short: 'https://5mgl.com/tree99', url: destination }) });
    });
    await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
    await page.locator('.vedit-btn').first().click();
    const row = page.locator('.vedit-tree-row').first();
    await row.locator('.vedit-tree-short').fill('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_123456/');
    await row.locator('.vedit-tree-shorten').click();
    await expect(row.locator('.vedit-tree-short')).toHaveValue('https://5mgl.com/tree99');
    await expect(row.locator('.vedit-tree-status')).toContainText('アフィリンクOK・短縮先OK');
    expect(destination).toContain('https://al.fanza.co.jp/');
    expect(new URL(destination).searchParams.get('af_id')).toBe('sample-001');
  });
  test('X/Bluesky投稿URLでない値は保存せず、モーダル内で理由を出す', async ({ page }) => {
    await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
    await page.locator('.vedit-btn').first().click();
    const row = page.locator('.vedit-tree-row').first();
    await row.locator('.vedit-tree-post').fill('https://example.com/not-a-social-post');
    await row.locator('.vedit-tree-short').fill('https://5mgl.com/tree01');
    await page.locator('#veditSave').click();
    await expect(page.locator('#veditError')).toContainText('返信ポストURLを確認');
    await expect(page.locator('#veditOverlay')).toBeVisible();
  });
});
