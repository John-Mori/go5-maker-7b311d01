const { test, expect } = require('@playwright/test');

test('投稿履歴の画像後着は一覧DOMとスクロール位置を壊さない', async ({ page }) => {
  await page.goto('StockLists.html?history-stability=1', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.Go5Verify && window.Go5Verify.patchImages && window.Go5Cand && window.HistMerge);
  await page.waitForTimeout(2800); // 起動時の2.5秒背景便が終わってから試験用カードを置く

  const before = await page.evaluate(() => {
    const list = document.getElementById('ytClickList');
    list.innerHTML = '<div style="height:900px"></div>' +
      '<div class="vrow" data-hist-usedkey="stable-video" data-hist-refcid="stable-cid"><div class="vrow-body">stable</div><div class="vrow-foot"></div></div>' +
      '<div style="height:900px"></div>';
    const onePx = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
    window.Go5Cand.usedImgs = key => key === 'stable-video' ? [onePx] : [];
    window.Go5Cand.usedPrevCount = key => key === 'stable-video' ? 1 : 0;
    window.Go5Cand.usedImgKnown = () => true;
    window.Go5Cand.refImgs = () => [];
    window.scrollTo(0, 700);
    window.__historyStableRow = list.querySelector('[data-hist-usedkey="stable-video"]');
    return { y: window.scrollY, html: window.__historyStableRow.innerHTML };
  });

  await page.evaluate(() => window.Go5Verify.patchImages());
  await expect(page.locator('[data-hist-usedkey="stable-video"] .vrow-refimg')).toBeVisible();
  const after = await page.evaluate(() => ({
    sameNode: window.__historyStableRow === document.querySelector('[data-hist-usedkey="stable-video"]'),
    y: window.scrollY,
    hasOriginalBody: document.querySelector('[data-hist-usedkey="stable-video"] .vrow-body').textContent === 'stable'
  }));
  expect(after.sameNode).toBe(true);
  expect(after.hasOriginalBody).toBe(true);
  expect(Math.abs(after.y - before.y)).toBeLessThan(2);
});