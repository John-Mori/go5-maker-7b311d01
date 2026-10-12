// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('単体短縮リンク発行', () => {
  for (const accountCase of [
    { account: 'acc1', channel: '月詠み色恋劇場', domain: '5mgl.com', code: 'reply-tsukuyomi' },
    { account: 'acc2', channel: '宵桜艶帖', domain: 'yoz2.com', code: 'reply-yoizakura' },
    { account: 'acc3', channel: '癒やし倉庫', domain: 'xdgh3.com', code: 'reply-iyashi' },
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
      // 旧2chは運用画面から隠しただけ。テスト内だけ選択肢を戻し、保持された
      // ドメイン定義とアフィ検証経路が消えていないことを直接確認する。
      await page.locator('#manualShortAccount').evaluate((select, accountCase) => {
        const option = document.createElement('option');
        option.value = accountCase.account;
        option.textContent = accountCase.channel;
        select.appendChild(option);
      }, accountCase);
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

  // 2026-10-12 癒やし倉庫(acc3)に xdgh3.com が入ったので「未設定」前提をやめた(v988以降 smoke が赤だった)。
  //   ドメインが空の時に元URLのまま返す守りは tests/test_worker_base.js(workerBase 単体)で固定している。
  test('表示中chに追従し、旧共通上書きがあっても旧ドメインへ落ちない', async ({ page }) => {
    const longUrl = 'https://example.com/reply-guide';
    let legacyCalls = 0;
    let ownCalls = 0;
    await page.addInitScript(() => {
      localStorage.setItem('current_account', 'acc3');
      localStorage.setItem('fanza_af_id', 'test-affiliate-990');
      localStorage.removeItem('short_worker_url__acc3');
      localStorage.setItem('short_worker_url', 'https://legacy-short.invalid');
    });
    await page.route(/https:\/\/(?:5mgl\.com|yoz2\.com|legacy-short\.invalid)\/api\/shorten/, async (route) => {
      legacyCalls++;
      await route.abort();
    });
    await page.route('https://xdgh3.com/api/shorten', async (route) => {
      // 画面は表示中chのキャンペーン短縮も自動で発行するので、手入力URLの分だけ数える。
      if (new URLSearchParams(route.request().postData() || '').get('url') === longUrl) ownCalls++;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ short: 'https://xdgh3.com/reply-guide', url: longUrl }),
      });
    });
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#tabAffi').click();
    await expect(page.locator('#manualShortAccount')).toHaveValue(await page.evaluate(() => window.getCurrentAccount()));
    await expect(page.locator('#manualShortDomain')).toHaveText('発行ドメイン: xdgh3.com');
    await page.locator('#manualAffiliateOn').uncheck();
    await page.locator('#manualUrl').fill(longUrl);
    await page.locator('#manualShortBtn').click();
    await expect(page.locator('#manualOut')).toHaveText('https://xdgh3.com/reply-guide');
    expect(ownCalls).toBe(1);
    expect(legacyCalls).toBe(0);
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
