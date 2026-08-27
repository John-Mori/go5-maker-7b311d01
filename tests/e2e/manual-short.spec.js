// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('単体短縮リンク発行', () => {
  for (const accountCase of [
    { account: 'acc1', channel: '月詠み色恋劇場', domain: '5mgl.com', code: 'reply-tsukuyomi' },
    { account: 'acc2', channel: '宵桜艶帖', domain: 'yoz2.com', code: 'reply-yoizakura' },
  ]) {
    test(accountCase.channel + 'はアフィリンクを検証して専用ドメインだけを発行する', async ({ page }) => {
      const longUrl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_manual_short/';
      let canonicalCalls = 0;
      let legacyCalls = 0;
      let savedDestination = '';
      await page.addInitScript(() => {
        localStorage.setItem('current_account', 'acc1');
        localStorage.setItem('fanza_af_id', 'test-affiliate-990');
        // 旧共通上書きが残っていても、既知2chのドメインを1本へ潰してはいけない。
        localStorage.setItem('short_worker_url', 'https://legacy-short.invalid');
        Object.defineProperty(navigator, 'clipboard', {
          configurable: true,
          value: { writeText: async (value) => { window.__manualCopied = value; } },
        });
      });
      await page.route('https://' + accountCase.domain + '/api/shorten', async (route) => {
        const body = new URLSearchParams(route.request().postData() || '');
        const destination = body.get('url') || '';
        if (destination.includes('d_e2e_manual_short')) { canonicalCalls++; savedDestination = destination; }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ short: 'https://' + accountCase.domain + '/' + accountCase.code, url: destination }),
        });
      });
      await page.route('https://legacy-short.invalid/api/shorten', async (route) => {
        legacyCalls++;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ short: 'https://legacy-short.invalid/wrong-domain', url: longUrl }),
        });
      });

      await page.goto('index.html', { waitUntil: 'domcontentloaded' });
      await page.locator('#tabAffi').click();
      await page.locator('#manualShortAccount').selectOption(accountCase.account);
      await expect(page.locator('#manualAffiliateOn')).toBeChecked();
      await expect(page.locator('#manualShortDomain')).toHaveText('発行ドメイン: ' + accountCase.domain);
      await page.locator('#manualUrl').fill(longUrl);
      await page.locator('#manualShortBtn').click();

      const expected = 'https://' + accountCase.domain + '/' + accountCase.code;
      await expect(page.locator('#manualOut')).toHaveText(expected);
      await expect(page.locator('#manualOut')).toHaveAttribute('data-url', expected);
      await expect(page.locator('#manualAffStatus')).toContainText('アフィリンクOK');
      const affiliate = new URL(savedDestination);
      expect(affiliate.hostname).toBe('al.fanza.co.jp');
      expect(affiliate.searchParams.get('af_id')).toBe('test-affiliate-990');
      expect(affiliate.searchParams.get('lurl')).toBe(longUrl);
      expect(await page.locator('#manualOut').textContent()).not.toMatch(/計測|\(|\)/);
      await page.locator('#manualCopy').click();
      await expect.poll(() => page.evaluate(() => window.__manualCopied || '')).toBe(expected);
      expect(canonicalCalls).toBe(1);
      expect(legacyCalls).toBe(0);
    });
  }

  test('チェックを外した場合だけ生URLをそのまま短縮し、アフィリンクなしを明示する', async ({ page }) => {
    const longUrl = 'https://example.com/reply-guide';
    let savedDestination = '';
    await page.addInitScript(() => {
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('fanza_af_id', 'test-affiliate-990');
    });
    await page.route('https://5mgl.com/api/shorten', async (route) => {
      savedDestination = new URLSearchParams(route.request().postData() || '').get('url') || '';
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ short: 'https://5mgl.com/raw01', url: savedDestination }) });
    });
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#tabAffi').click();
    await page.locator('#manualAffiliateOn').uncheck();
    await page.locator('#manualUrl').fill(longUrl);
    await page.locator('#manualShortBtn').click();
    await expect(page.locator('#manualOut')).toHaveText('https://5mgl.com/raw01');
    await expect(page.locator('#manualAffStatus')).toContainText('アフィリンクなし');
    expect(savedDestination).toBe(longUrl);
  });

  test('アフィIDが無い場合は誤った短縮リンクを発行しない', async ({ page }) => {
    let calls = 0;
    await page.addInitScript(() => localStorage.setItem('current_account', 'acc1'));
    await page.route('https://5mgl.com/api/shorten', async (route) => { calls++; await route.abort(); });
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#tabAffi').click();
    await page.locator('#manualUrl').fill('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_no_aff_id/');
    await page.locator('#manualShortBtn').click();
    await expect(page.locator('#manualAffStatus')).toContainText('アフィリンクNG');
    await expect(page.locator('#manualOut')).not.toHaveAttribute('data-url', /.+/);
    expect(calls).toBe(0);
  });
});
