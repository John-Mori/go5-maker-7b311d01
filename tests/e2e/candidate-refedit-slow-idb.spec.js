// 投稿編集: この作品の画像レコード読取(IDB)が返ってこない端末でも、モーダルは数秒で開いて
// コメント/URLを編集できること。画像の追加・削除は読取確認まで止め、既存画像を消す保存を作らない。
// (Chami実機報告2026-10-18「投稿画像が保存されていない作品で、投稿編集を押しても読み込み中で編集できない」)
const { test, expect } = require('@playwright/test');

const CID = 'd_noimg_refedit_slow';

// この作品のrefキー読取だけを保留にする(iOSでIDBが詰まった状態の再現)。__heldRef の関数で後から返せる。
// カード描画時の先読みも同じ読取を共有するため、ページのスクリプトより先に差し込む。
async function setup(page) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate((cid) => {
    localStorage.setItem('cand_items', JSON.stringify([{ cid, title: '画像なし投稿編集作品', url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/', addedAt: Date.now() }]));
  }, CID);
  await page.addInitScript((cid) => {
    var api;
    window.__heldRef = [];
    Object.defineProperty(window, 'Go5Idb', {
      configurable: true,
      get: function () { return api; },
      set: function (v) {
        api = v;
        var orig = v.getResult;
        v.getResult = function (key) {
          if (String(key).indexOf(cid) < 0) return orig.apply(v, arguments);
          var args = arguments;
          return new Promise(function (resolve) { window.__heldRef.push(function () { resolve(orig.apply(v, args)); }); });
        };
      }
    });
  }, CID);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-refimg="' + CID + '"]')).toBeVisible();
}

test('画像読取が返らなくても投稿編集が開き、コメントを編集・保存できる', async ({ page }) => {
  await setup(page);
  await page.locator('[data-refimg="' + CID + '"]').click();
  const comment = page.locator('#refImgComment');
  await expect(comment).toBeEditable({ timeout: 5000 });
  // 画像確認前は画像の追加・削除を止める(既存画像を空で上書きしない)
  await expect(page.locator('#refImgPaste')).toBeDisabled();
  await expect(page.locator('#refImgClear')).toBeDisabled();
  await expect(page.locator('#refImgFile')).toBeDisabled();
  await comment.fill('読込待ちでも書ける');
  await page.locator('#refImgSave').click();
  await expect(page.locator('#refImgMsg')).toHaveText('保存しました');
  const saved = await page.evaluate((cid) => (JSON.parse(localStorage.getItem('cand_text') || '{}')[cid] || {}).comment, CID);
  expect(saved).toBe('読込待ちでも書ける');
});

test('保留された読取が後から返れば、画像操作が使えるようになる', async ({ page }) => {
  await setup(page);
  await page.locator('[data-refimg="' + CID + '"]').click();
  await expect(page.locator('#refImgComment')).toBeEditable({ timeout: 5000 });
  await expect(page.locator('#refImgPaste')).toBeDisabled();
  await page.evaluate(() => { (window.__heldRef || []).forEach(function (f) { f(); }); });
  await expect(page.locator('#refImgPaste')).toBeEnabled({ timeout: 5000 });
  await expect(page.locator('#refImgClear')).toBeEnabled();
  await expect(page.locator('#refImgFile')).toBeEnabled();
  await expect(page.locator('#refImgPreview')).toContainText('画像は未保存です');
});
