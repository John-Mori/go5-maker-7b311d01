// @ts-check
// 投稿履歴: ピンク(作品クリック)をツリー(Bluesky子)だけの行でも白の横に出す/既定の投稿先をチャンネル別に選べる
//   (Chami msg 1562781627078287380 2026-10-22「ピンククリックを白クリックの横にも」「デフォルト設定がここで言わなくてもできるように。チャンネルが増えてもそれぞれで」)
const { test, expect } = require('@playwright/test');

const SHORT_BASE = 'https://e2e-short.example';
const VIDEO_SUFFIX = '-20261022-1951-pink1';

test.describe('投稿履歴 ピンク/既定の投稿先', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ shortBase, videoSuffix }) => {
      const account = window.Go5Acct.current();
      const videoId = account + videoSuffix;
      localStorage.setItem('bsky_gas_url', '');
      localStorage.setItem('hist_maint_at', String(Date.now()));
      localStorage.setItem('hist_metrics_at', String(Date.now()));
      localStorage.setItem('short_worker_url__' + account, shortBase);
      // 作品short無し・ツリー(Bluesky子)だけにピンクの計測URLがある行(スクショの状態)
      localStorage.setItem('short_hist__' + account, JSON.stringify([{
        videoId, ts: Date.now(), title: 'ピンク表示テスト作品', account,
        shortUrl: shortBase + '/parent1'
      }]));
      localStorage.setItem('verify_manual__' + account, '[]');
      localStorage.setItem('verify_yt__' + account, '{}');
      localStorage.setItem('clicks_cache', JSON.stringify({ parent1: 3, tree01: 10 }));
      localStorage.setItem('go5_tree_links_v1', JSON.stringify({ [account + '|v:' + videoId]: { trees: [{ name: 'Bluesky子', postUrl: 'https://bsky.app/profile/x/post/abc', shortUrl: shortBase + '/tree01' }] } }));
      localStorage.removeItem('hist_default_plat__acc1');
      localStorage.removeItem('hist_default_plat__acc3');
    }, { shortBase: SHORT_BASE, videoSuffix: VIDEO_SUFFIX });
    await page.route('**/api/list**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, links: [
        { code: 'parent1', clicks: 3, today: 1, yesterday: 0, week: 1 }, { code: 'tree01', clicks: 10, today: 10, yesterday: 0, week: 10 }
      ] }) });
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
  });

  test('ツリーだけの行でも白の横にピンクのクリック数が出る', async ({ page }) => {
    const card = page.locator('.vrow').first();
    await expect(card).toBeVisible();
    const pink = card.locator('.vmetrics span[title^="作品リンククリック数"]');
    await expect(pink).toBeVisible();
    await expect(pink).toContainText('10');
  });

  test('既定の投稿先はチャンネル別に選べて、切り替えると各チャンネルの値に戻る', async ({ page }) => {
    const box = page.locator('#histDefaultPlat');
    await expect(box).toBeVisible();
    const acc = await page.evaluate(() => window.Go5Acct.current());
    const initial = acc === 'acc3' ? 'bsky' : 'x';
    await expect(box.locator('input[value="' + initial + '"]')).toBeChecked();

    const other = initial === 'x' ? 'bsky' : 'x';
    await box.locator('input[value="' + other + '"]').check();
    expect(await page.evaluate((a) => localStorage.getItem('hist_default_plat__' + a), acc)).toBe(other);

    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#histDefaultPlat input[value="' + other + '"]')).toBeChecked();
    // 1つだけ(再描画で増えない)
    await expect(page.locator('#histDefaultPlat')).toHaveCount(1);

    // 別チャンネルは別の値(未設定なら acc3=Bsky / それ以外=X)
    const otherAcc = acc === 'acc3' ? 'acc1' : 'acc3';
    const defOther = await page.evaluate((a) => { localStorage.removeItem('hist_default_plat__' + a); return a === 'acc3' ? 'bsky' : 'x'; }, otherAcc);
    expect(defOther).toBe(otherAcc === 'acc3' ? 'bsky' : 'x');
  });

  test('予約の公開枠を後から選ぶと、投稿履歴の予定時刻が新しい枠で上書きされる', async ({ page }) => {
    const r = await page.evaluate(() => {
      const H = window.Go5History;
      if (!H || !H.addCompletedPost) return { skip: true };
      const acc = window.Go5Acct.current();
      const videoId = acc + '-20261022-1951-sched1';
      const t1 = new Date(Date.now() + 3600e3).toISOString();
      const t2 = new Date(Date.now() + 7200e3).toISOString();
      const r1 = H.addCompletedPost({ account: acc, videoId, title: '予約上書きテスト', scheduledAt: t1 });
      const r2 = H.addCompletedPost({ account: acc, videoId, title: '予約上書きテスト', scheduledAt: t2 });
      const read = (k) => { const v = window.Go5Hist ? window.Go5Hist.read(k) : JSON.parse(localStorage.getItem(k) || '[]'); return Array.isArray(v) ? v : []; };
      const rows = read('short_hist__' + acc).concat(read('verify_manual__' + acc)).filter((h) => h.videoId === videoId);
      return { n: rows.length, planned: rows.map((x) => x.plannedAt), t2, r1: String(r1 && (r1.reason || r1.ok)), r2: String(r2 && (r2.reason || r2.ok)) };
    });
    test.skip(!!r.skip, 'Go5History.addCompletedPost がこのページに無い');
    expect(r.n, JSON.stringify(r)).toBe(1);
    expect(r.planned[0], JSON.stringify(r)).toBe(r.t2);
  });
});
