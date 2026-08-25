// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('単体短縮リンク発行', () => {
  for (const accountCase of [
    { account: 'acc1', channel: '月詠み色恋劇場', domain: '5mgl.com', code: 'reply-tsukuyomi' },
    { account: 'acc2', channel: '宵桜艶帖', domain: 'yoz2.com', code: 'reply-yoizakura' },
  ]) {
    test(accountCase.channel + 'は専用ドメインのURLだけを発行する', async ({ page }) => {
      const longUrl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_manual_short/';
      let canonicalCalls = 0;
      let legacyCalls = 0;
      await page.addInitScript(() => {
        localStorage.setItem('current_account', 'acc1');
        // 旧共通上書きが残っていても、既知2chのドメインを1本へ潰してはいけない。
        localStorage.setItem('short_worker_url', 'https://legacy-short.invalid');
        Object.defineProperty(navigator, 'clipboard', {
          configurable: true,
          value: { writeText: async (value) => { window.__manualCopied = value; } },
        });
      });
      await page.route('https://' + accountCase.domain + '/api/shorten', async (route) => {
        canonicalCalls++;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ short: 'https://' + accountCase.domain + '/' + accountCase.code }),
        });
      });
      await page.route('https://legacy-short.invalid/api/shorten', async (route) => {
        legacyCalls++;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ short: 'https://legacy-short.invalid/wrong-domain' }),
        });
      });

      await page.goto('index.html', { waitUntil: 'domcontentloaded' });
      await page.locator('#tabAffi').click();
      await page.locator('#manualShortAccount').selectOption(accountCase.account);
      await expect(page.locator('#manualShortDomain')).toHaveText('発行ドメイン: ' + accountCase.domain);
      await page.locator('#manualUrl').fill(longUrl);
      await page.locator('#manualShortBtn').click();

      const expected = 'https://' + accountCase.domain + '/' + accountCase.code;
      await expect(page.locator('#manualOut')).toHaveText(expected);
      await expect(page.locator('#manualOut')).toHaveAttribute('data-url', expected);
      expect(await page.locator('#manualOut').textContent()).not.toMatch(/計測|\(|\)/);
      await page.locator('#manualCopy').click();
      await expect.poll(() => page.evaluate(() => window.__manualCopied || '')).toBe(expected);
      expect(canonicalCalls).toBe(1);
      expect(legacyCalls).toBe(0);
    });
  }
});