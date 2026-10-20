// 投稿編集: この作品の画像レコード読取(IDB)が返ってこない端末でも、モーダルは数秒で開いて
// コメント/URLを編集できること。確認前でも画像は足せるが、保存済みの列は確認してから後ろへつなぐ=既存画像を消す保存を作らない。
// (Chami実機報告2026-10-18「投稿編集を押しても読み込み中で編集できない」・2026-10-20「後入れもできひん」)
const { test, expect } = require('@playwright/test');

const CID = 'd_noimg_refedit_slow';
const RED = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC', 'base64');
const BLUE_URL = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC';

// この作品のrefキー読取だけを保留にする(iOSでIDBが詰まった状態の再現)。__heldRef の関数で後から返せる。
// カード描画時の先読みも同じ読取を共有するため、ページのスクリプトより先に差し込む。
// opts.seed=保存済みの画像を1枚入れておく(全体展開も止め、カード側からは見えない状態にする)
async function setup(page, opts) {
  opts = opts || {};
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate(async ({ cid, seed }) => {
    localStorage.setItem('cand_items', JSON.stringify([{ cid, title: '画像なし投稿編集作品', url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/', addedAt: Date.now() }]));
    if (seed) await window.Go5Idb.set('ref:' + cid, { imgs: [seed], img: seed, comment: '', memo: '', twitterUrl: '', at: 1 });
  }, { cid: CID, seed: opts.seed || '' });
  await page.addInitScript(({ cid, holdHydrate }) => {
    var api;
    window.__heldRef = [];
    Object.defineProperty(window, 'Go5Idb', {
      configurable: true,
      get: function () { return api; },
      set: function (v) {
        api = v;
        var orig = v.getResult;
        v.getResult = function (key) {
          if (String(key).indexOf(cid) < 0 || window.__refFree) return orig.apply(v, arguments);
          var args = arguments;
          return new Promise(function (resolve) { window.__heldRef.push(function () { resolve(orig.apply(v, args)); }); });
        };
        if (holdHydrate) ['entries', 'entriesPrefix', 'entriesByPrefixes', 'entriesByPrefixesSettled'].forEach(function (k) {
          if (typeof v[k] === 'function') v[k] = function () { return new Promise(function () {}); };
        });
      }
    });
  }, { cid: CID, holdHydrate: !!opts.seed });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-refimg="' + CID + '"]')).toBeVisible();
}
function release(page) { return page.evaluate(() => { window.__refFree = true; (window.__heldRef || []).splice(0).forEach(function (f) { f(); }); }); }

test('画像読取が返らなくても投稿編集が開き、コメントを編集・保存できる', async ({ page }) => {
  await setup(page);
  await page.locator('[data-refimg="' + CID + '"]').click();
  const comment = page.locator('#refImgComment');
  await expect(comment).toBeEditable({ timeout: 5000 });
  await expect(page.locator('#refImgPreview')).toContainText('保存済みの画像を確認中');
  // 確認前でも画像を足せる(後入れできないと止まる)
  await expect(page.locator('#refImgPaste')).toBeEnabled();
  await expect(page.locator('#refImgFile')).toBeEnabled();
  await comment.fill('読込待ちでも書ける');
  await page.locator('#refImgSave').click();
  await expect(page.locator('#refImgMsg')).toHaveText('保存しました');
  const saved = await page.evaluate((cid) => (JSON.parse(localStorage.getItem('cand_text') || '{}')[cid] || {}).comment, CID);
  expect(saved).toBe('読込待ちでも書ける');
});

test('保留された読取が後から返れば、画像欄が通常表示に戻る', async ({ page }) => {
  await setup(page);
  await page.locator('[data-refimg="' + CID + '"]').click();
  await expect(page.locator('#refImgComment')).toBeEditable({ timeout: 5000 });
  await release(page);
  await expect(page.locator('#refImgPreview')).toContainText('画像は未保存です', { timeout: 5000 });
  await expect(page.locator('#refImgClear')).toBeEnabled();
});

test('確認前に足した画像は、保存済みの画像を消さずに前へ足して保存する', async ({ page }) => {
  await setup(page, { seed: BLUE_URL });
  await page.locator('[data-refimg="' + CID + '"]').click();
  await expect(page.locator('#refImgComment')).toBeEditable({ timeout: 5000 });
  await page.locator('#refImgFile').setInputFiles({ name: 'add.png', mimeType: 'image/png', buffer: RED });
  await expect(page.locator('#refImgMsg')).toContainText('1枚を追加しました');
  await expect(page.locator('#refImgPreview')).toContainText('確認後、この後ろに並びます');
  await page.locator('#refImgSave').click();
  await expect(page.locator('#refImgMsg')).toHaveText('保存済みの画像を確認してから保存中…');
  await release(page);
  await expect(page.locator('#refImgMsg')).toHaveText('保存しました', { timeout: 10000 });
  const imgs = await page.evaluate((cid) => window.Go5Cand.refImgs(cid), CID);
  expect(imgs.length).toBe(2);
  expect(imgs[1]).toBe(BLUE_URL); // 保存済みの1枚は後ろに残る
  expect(imgs[0]).not.toBe(BLUE_URL);
});
