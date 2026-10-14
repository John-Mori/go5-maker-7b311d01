// @ts-check
const { test, expect } = require('@playwright/test');

const SHORT_BASE = 'https://e2e-short.example';
const VIDEO_SUFFIX = '-20260827-1200-tree1';

async function currentIdentity(page) {
  return page.evaluate((suffix) => {
    const account = window.Go5Acct.current();
    return { account, videoId: account + suffix };
  }, VIDEO_SUFFIX);
}

test.describe('投稿履歴のツリー設定', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ shortBase, videoSuffix }) => {
      const account = window.Go5Acct.current();
      const videoId = account + videoSuffix;
      localStorage.setItem('bsky_gas_url', '');
      localStorage.setItem('hist_maint_at', String(Date.now()));
      localStorage.setItem('hist_metrics_at', String(Date.now()));
      localStorage.setItem('short_worker_url__' + account, shortBase);
      localStorage.setItem('short_hist__' + account, JSON.stringify([{
        videoId, ts: Date.now(), title: 'ツリー計測テスト作品', account,
        ytUrl: 'https://youtu.be/AbCdEfGhI12',
        shortUrl: shortBase + '/parent1', workShortUrl: shortBase + '/work01'
      }]));
      localStorage.setItem('verify_manual__' + account, '[]');
      localStorage.setItem('verify_yt__' + account, '{}');
      localStorage.setItem('clicks_cache', JSON.stringify({ parent1: 2, work01: 4, tree01: 17 }));
      localStorage.setItem('yt_meta_cache', JSON.stringify({ AbCdEfGhI12: { title: 'YouTube動画の題名' } }));
      localStorage.setItem('fanza_af_id', 'sample-001');
      localStorage.removeItem('go5_tree_links_v1');
      sessionStorage.setItem('go5_manual_short_last__' + account, JSON.stringify({
        shortUrl: shortBase + '/tree01', affiliateOk: true, at: Date.now()
      }));
    }, { shortBase: SHORT_BASE, videoSuffix: VIDEO_SUFFIX });
    await page.route('**/api/list**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, links: [
        { code: 'parent1', clicks: 2, today: 0, yesterday: 0, week: 0 }, { code: 'work01', clicks: 4, today: 0, yesterday: 0, week: 0 }, { code: 'tree01', clicks: 17, today: 8, yesterday: 5, week: 13 }
      ] }) });
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
  });

  test('返信URLは短縮せず、表示名とピンク矢印クリック数を親履歴へ保存する', async ({ page }) => {
    const identity = await currentIdentity(page);
    await expect(page.locator('.vrow').first()).toBeVisible();
    await page.locator('.vedit-btn').first().click();
    await expect(page.getByText('🌳 ツリー設定')).toBeVisible();
    await expect(page.locator('.vedit-heading')).toContainText('URL を編集YouTube動画の題名');
    const row = page.locator('.vedit-tree-row').first();
    await row.locator('.vedit-tree-name').fill('続編はこちら');
    await row.locator('.vedit-tree-post').fill('https://x.com/example/status/1234567890');
    await expect(row.locator('.vedit-tree-short')).toHaveValue(SHORT_BASE + '/tree01');
    await page.locator('#veditSave').click();

    const tree = page.locator('.vrow-tree-row').first();
    await expect(tree).toContainText('続編はこちら');
    await expect(tree).toContainText('今日 8');
    await expect(tree).toContainText('昨日 5');
    await expect(tree).toContainText('今週 13');
    await expect(tree.locator('a')).toHaveAttribute('href', 'https://x.com/example/status/1234567890');
    await expect(tree.locator('img').first()).toHaveAttribute('src', 'assets/icons/ic-cursor-pink.png');

    const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('go5_tree_links_v1') || '{}'));
    const rec = saved[identity.account + '|v:' + identity.videoId];
    expect(rec.trees).toHaveLength(1);
    expect(rec.trees[0]).toMatchObject({ name: '続編はこちら', postUrl: 'https://x.com/example/status/1234567890', shortUrl: SHORT_BASE + '/tree01' });
  });

  test('元作品URLをアフィ化し、チャンネルの新ドメインで短縮してからOKを表示する', async ({ page }) => {
    let destination = '';
    await page.route(SHORT_BASE + '/api/shorten', async (route) => {
      const body = route.request().postData() || '';
      destination = new URLSearchParams(body).get('url') || '';
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ short: SHORT_BASE + '/tree99', url: destination }) });
    });
    await page.locator('.vedit-btn').first().click();
    const row = page.locator('.vedit-tree-row').first();
    await row.locator('.vedit-tree-short').fill('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_123456/');
    await row.locator('.vedit-tree-shorten').click();
    await expect(row.locator('.vedit-tree-short')).toHaveValue(SHORT_BASE + '/tree99');
    await expect(row.locator('.vedit-tree-status')).toContainText('アフィリンクOK・短縮先OK');
    expect(destination).toContain('https://al.fanza.co.jp/');
    expect(new URL(destination).searchParams.get('af_id')).toBe('sample-001');
  });
  test('X/Bluesky投稿URLでない値は保存せず、モーダル内で理由を出す', async ({ page }) => {
    await page.locator('.vedit-btn').first().click();
    const row = page.locator('.vedit-tree-row').first();
    await row.locator('.vedit-tree-post').fill('https://example.com/not-a-social-post');
    await row.locator('.vedit-tree-short').fill(SHORT_BASE + '/tree01');
    await page.locator('#veditSave').click();
    await expect(page.locator('#veditError')).toContainText('返信ポストURLを確認');
    await expect(page.locator('#veditOverlay')).toBeVisible();
  });

  test('ツリー2以降は返信URLなし・短縮前の作品URLだけでも仮保存し、開き直して保持する', async ({ page }) => {
    const identity = await currentIdentity(page);
    await page.locator('.vedit-btn').first().click();
    const first = page.locator('.vedit-tree-row').first();
    await first.locator('.vedit-tree-post').fill('https://x.com/example/status/1234567890');
    await first.locator('.vedit-tree-short').fill(SHORT_BASE + '/tree01');
    await page.locator('#veditTreeAdd').click();
    const second = page.locator('.vedit-tree-row').nth(1);
    await second.locator('.vedit-tree-name').fill('ツリー2仮保存');
    const rawWorkUrl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_654321/';
    await second.locator('.vedit-tree-short').fill(rawWorkUrl);
    await page.locator('#veditSave').click();

    const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('go5_tree_links_v1') || '{}'));
    const rec = saved[identity.account + '|v:' + identity.videoId];
    expect(rec.trees).toHaveLength(2);
    expect(rec.trees[1]).toMatchObject({ name: 'ツリー2仮保存', postUrl: '', shortUrl: rawWorkUrl });

    await page.locator('.vedit-btn').first().click();
    await expect(page.locator('.vedit-tree-row')).toHaveCount(2);
    await expect(page.locator('.vedit-tree-row').nth(1).locator('.vedit-tree-short')).toHaveValue(rawWorkUrl);
    await page.locator('#veditCancel').click();
    await expect(page.locator('.vrow-tree-row').nth(1)).toContainText('ツリー2仮保存');
    await expect(page.locator('.vrow-tree-row').nth(1).locator('a')).toHaveCount(0);
  });

  test('白/ピンクの日別クリックは短縮URLの日別計測を出し、前日に取った日別値は今日として出さない', async ({ page }) => {
    const account = (await currentIdentity(page)).account;
    await page.evaluate((acc) => {
      // 履歴の正本は Go5Hist(localStorageだけ書き換えても読込時に戻る)。前日23時投稿にする
      const key = 'short_hist__' + acc;
      const hist = window.Go5Hist ? window.Go5Hist.read(key) : JSON.parse(localStorage.getItem(key) || '[]');
      const y = new Date(); y.setDate(y.getDate() - 1); y.setHours(23, 0, 0, 0);
      hist[0].ts = y.getTime();
      if (window.Go5Hist) window.Go5Hist.write(key, hist); else localStorage.setItem(key, JSON.stringify(hist));
    }, account);
    await page.evaluate(() => {
      // 前日に取得した日別値(今日=累計・昨日=空)が残っている状況
      localStorage.setItem('delta_cache', JSON.stringify({ AbCdEfGhI12: { tv: 180, yv: null, wv: 180, tc: 5, yc: null, wc: 5, twc: 7, ywc: null, wwc: 7 } }));
      localStorage.setItem('delta_cache_day', '2000-1-1');
    });
    await page.unroute('**/api/list**');
    await page.route('**/api/list**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, links: [
        { code: 'parent1', clicks: 12, today: 3, yesterday: 9, week: 12 }, { code: 'work01', clicks: 6, today: 1, yesterday: 5, week: 6 }, { code: 'tree01', clicks: 17, today: 8, yesterday: 5, week: 13 }
      ] }) });
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    const segs = page.locator('.vrow').first().locator('.vrow-delta .dl-seg');
    await expect(segs.nth(0)).toHaveText(/今日\s*▶未\s*3\s*1/);
    await expect(segs.nth(1)).toHaveText(/昨日\s*▶未\s*9\s*5/);
    await expect(segs.nth(2)).toHaveText(/週\s*▶未\s*12\s*6/);
  });

  for (const width of [360, 375, 390, 414, 430]) {
    test(`癒やし倉庫の履歴カードは${width}px幅でツリー行がボタンへ重ならず、作品名が地に溶けない`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.evaluate(() => {
        const account = window.Go5Acct.current();
        localStorage.setItem('go5_tree_links_v1', JSON.stringify({ [account + '|v:' + account + '-20260827-1200-tree1']: { trees: [{ name: 'Bluesky子', postUrl: 'https://bsky.app/profile/x/post/abc', shortUrl: 'https://e2e-short.example/tree01' }] } }));
      });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.evaluate(() => { document.documentElement.setAttribute('data-account', 'acc3'); });
      const card = page.locator('.vrow').first();
      await expect(card.locator('.vrow-tree-row')).toContainText('今週');
      const m = await card.evaluate((el) => {
        const r = (s) => { const n = el.querySelector(s); return n ? n.getBoundingClientRect() : null; };
        const box = el.getBoundingClientRect();
        const foot = r('.vrow-foot'), tree = r('.vrow-tree-wrap');
        const outside = [...el.querySelectorAll('.vrow-foot *, .vrow-tree-wrap *, .vmetrics > *')]
          .filter((n) => { const b = n.getBoundingClientRect(); return b.width > 0 && b.right > box.right - 1; })
          .map((n) => n.className || n.tagName);
        const name = el.querySelector('.fanza-name-row');
        if (name) { name.style.display = ''; name.textContent = '作品名テスト'; }
        return { treeBelowFoot: tree.top >= foot.bottom - 1, outside, nameColor: name ? getComputedStyle(name).color : '' };
      });
      expect(m.treeBelowFoot, JSON.stringify(m)).toBeTruthy();
      expect(m.outside, JSON.stringify(m)).toEqual([]);
      expect(m.nameColor).not.toBe('rgb(203, 213, 225)');
    });
  }

  test('iPhone幅でも返信URLと貼り付けを同列にし、作品URL欄は同じ高さにする', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.vedit-btn').first().click();
    const row = page.locator('.vedit-tree-row').first();
    const layout = await row.evaluate((el) => {
      const post = el.querySelector('.vedit-tree-post');
      const postPaste = el.querySelector('.vedit-tree-paste-post');
      const short = el.querySelector('.vedit-tree-short');
      const stack = el.querySelector('.vedit-tree-btnstack');
      const a = post.getBoundingClientRect();
      const b = postPaste.getBoundingClientRect();
      const c = short.getBoundingClientRect();
      return {
        sameRow: Math.abs(a.top - b.top) < 2,
        sameHeight: Math.abs(a.height - c.height) < 2,
        postHeight: a.height,
        shortHeight: c.height,
        stackGap: parseFloat(getComputedStyle(stack).gap || '0'),
        overflow: el.scrollWidth > el.clientWidth + 1
      };
    });
    expect(layout.sameRow).toBeTruthy();
    expect(layout.sameHeight, JSON.stringify(layout)).toBeTruthy();
    expect(layout.stackGap).toBeLessThanOrEqual(4);
    expect(layout.overflow).toBeFalsy();
  });
});
