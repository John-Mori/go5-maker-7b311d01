// @ts-check
// iPhoneの端末保存(localStorage)が満杯の状態で、主要画面が例外なく開いて操作の起点が壊れないこと。
// 2026-10-23 朝の振り返り: 10/22〜23の言い直し・後退4件(v1087/v1088/v1089/v1090)は、
// どれも「Chamiの実機の状態(LS満杯・保存中にもう1本・画像0〜1枚)」をテストで作らずに出したのが原因だった。
// 個別のspecは症状ごとに作ってあるが、新しい変更は既定でこの状態を通らない。
// ここで「全setItemがQuotaExceededErrorを投げる」端末を作り、主要4画面を毎回通す。
const { test, expect } = require('@playwright/test');

function lsFull() {
  const orig = Storage.prototype.setItem;
  Storage.prototype.setItem = function (k, v) {
    if (this === window.localStorage) { const e = new Error('quota'); e.name = 'QuotaExceededError'; throw e; }
    return orig.call(this, k, v);
  };
}

const PAGES = ['index.html', 'KouhoLists.html', 'Stock.html', 'StockLists.html'];

test.describe('LS満杯のiPhone状態で主要画面が開く', () => {
  for (const path of PAGES) {
    test(`${path} が例外なく開き本文が出る`, async ({ page }) => {
      const errors = [];
      page.on('pageerror', (e) => errors.push(String(e)));
      await page.addInitScript(lsFull);
      await page.goto(path, { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('load');
      await page.waitForTimeout(1500);
      const textLen = await page.evaluate(() => (document.body && document.body.innerText || '').trim().length);
      expect(textLen, `${path} の本文が空`).toBeGreaterThan(0);
      expect(errors.filter((e) => /quota/i.test(e)), `${path} でLS満杯の例外が握られていない`).toEqual([]);
    });
  }

  test('候補タブ: LS満杯でも各サブタブへ切り替えられ、activeが1つだけ', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.addInitScript(lsFull);
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    const tabs = page.locator('.cand-tab[data-ct]');
    await expect(tabs.first()).toBeVisible();
    const ids = await tabs.evaluateAll((els) => els.map((e) => e.getAttribute('data-ct')));
    for (const id of ids) {
      await page.locator(`.cand-tab[data-ct="${id}"]`).click();
      await expect(page.locator(`.cand-tab.active[data-ct="${id}"]`)).toBeVisible();
      await expect(page.locator('.cand-tab.active')).toHaveCount(1);
    }
    expect(errors.filter((e) => /quota/i.test(e))).toEqual([]);
  });
});
