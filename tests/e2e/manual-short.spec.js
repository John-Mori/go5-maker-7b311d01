// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('単体短縮リンク発行', () => {
  for (const accountCase of [
    { account: 'acc1', channel: '月詠み色恋劇場', domain: '5mgl.com', code: 'reply-tsukuyomi' },
    { account: 'acc2', channel: '宵桜艶帖', domain: 'yoz2.com', code: 'reply-yoizakura' },
    { account: 'acc3', channel: '癒やし倉庫', domain: 'xdgh3.com', code: 'reply-iyashi' },
  ]) {
    // 2026-10-18 Chami決定(5Sec軍議 msg 1561272541387948148)「ピンククリックはもう計測する必要もない、
    //   短縮リンク化はYouTube→Twitterとかのところだけ」。作品URLは短縮せず al.fanza のアフィリンクをそのまま出す。
    test(accountCase.channel + 'は作品URLを短縮せずアフィリンク(al.fanza)のまま出す', async ({ page }) => {
      const longUrl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_manual_short/';
      let workShortenCalls = 0;
      await page.addInitScript(() => {
        localStorage.setItem('current_account', 'acc1');
        localStorage.setItem('fanza_af_id', 'test-affiliate-990');
        localStorage.setItem('short_worker_url', 'https://legacy-short.invalid');
        Object.defineProperty(navigator, 'clipboard', {
          configurable: true,
          value: { writeText: async (value) => { window.__manualCopied = value; } },
        });
      });
      await page.route(/https:\/\/(?:5mgl\.com|yoz2\.com|xdgh3\.com|legacy-short\.invalid)\/api\/shorten/, async (route) => {
        const destination = new URLSearchParams(route.request().postData() || '').get('url') || '';
        if (destination.includes('d_e2e_manual_short')) workShortenCalls++;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ short: 'https://' + accountCase.domain + '/' + accountCase.code, url: destination }),
        });
      });

      await page.goto('index.html', { waitUntil: 'domcontentloaded' });
      await page.locator('#tabAffi').click();
      // 旧2chは運用画面から隠しただけ。テスト内だけ選択肢を戻す。
      await page.locator('#manualShortAccount').evaluate((select, accountCase) => {
        if (select.querySelector('option[value="' + accountCase.account + '"]')) return;
        const option = document.createElement('option');
        option.value = accountCase.account;
        option.textContent = accountCase.channel;
        select.appendChild(option);
      }, accountCase);
      await page.locator('#manualShortAccount').selectOption(accountCase.account);
      await expect(page.locator('#manualAffiliateOn')).toBeChecked();
      await page.locator('#manualUrl').fill(longUrl);
      await page.locator('#manualShortBtn').click();

      await expect(page.locator('#manualOut')).toHaveAttribute('data-url', /^https:\/\/al\.fanza\.co\.jp\//);
      const out = await page.locator('#manualOut').getAttribute('data-url');
      const affiliate = new URL(out || '');
      expect(affiliate.hostname).toBe('al.fanza.co.jp');
      expect(affiliate.searchParams.get('af_id')).toBe('test-affiliate-990');
      expect(affiliate.searchParams.get('lurl')).toBe(longUrl);
      await expect(page.locator('#manualAffStatus')).toContainText('アフィリンクOK・短縮なし');
      await page.locator('#manualCopy').click();
      await expect.poll(() => page.evaluate(() => window.__manualCopied || '')).toBe(out);
      expect(workShortenCalls).toBe(0);
      // 投稿文の自動挿入・X欄・ドラフトが通る共通の口も、作品/セール一覧は短縮しない。X投稿URLは従来どおり短縮へ回す。
      const viaCore = await page.evaluate(async () => {
        const w = await window.Go5MakeShort('https://al.fanza.co.jp/?lurl=https%3A%2F%2Fwww.dmm.co.jp%2F&af_id=test-affiliate-990&ch=link_tool&ch_id=link');
        const sale = await window.Go5MakeShort('https://www.dmm.co.jp/dc/doujin/-/list/=/sort=ranking/');
        return { w, sale, noShortX: window.isNoShortDestUrl('https://x.com/a/status/1'), noShortBsky: window.isNoShortDestUrl('https://bsky.app/profile/a/post/b') };
      });
      expect(viaCore.w.noShort).toBe(true);
      expect(viaCore.w.shareUrl).toMatch(/^https:\/\/al\.fanza\.co\.jp\//);
      expect(viaCore.sale.shareUrl).toBe('https://www.dmm.co.jp/dc/doujin/-/list/=/sort=ranking/');
      expect(viaCore.noShortX).toBe(false);
      expect(viaCore.noShortBsky).toBe(false);
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

  // 2026-10-17 X投稿URLをアフィ包み(al.fanza?lurl=x.com)で短縮した6本がFANZAの400で行き止まりだった。
  //   アフィにチェックが入ったままでもDMM/FANZA以外は包まず、そのURLのまま短縮して止めない。
  test('X投稿URLはアフィにチェックがあっても包まずに短縮する', async ({ page }) => {
    const xUrl = 'https://x.com/healingbooks_/status/2110751884915147239?s=46';
    const saved = [];
    await page.addInitScript(() => {
      localStorage.setItem('current_account', 'acc3');
      localStorage.setItem('fanza_af_id', 'test-affiliate-990');
    });
    await page.route('https://xdgh3.com/api/shorten', async (route) => {
      const destination = new URLSearchParams(route.request().postData() || '').get('url') || '';
      // 画面が自動で出すキャンペーン短縮は数えない(手入力のX投稿URLの分だけ)。
      if (destination.includes('healingbooks_')) saved.push(destination);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ short: 'https://xdgh3.com/x-post', url: destination }),
      });
    });
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#tabAffi').click();
    await expect(page.locator('#manualAffiliateOn')).toBeChecked();
    await page.locator('#manualUrl').fill(xUrl);
    await page.locator('#manualShortBtn').click();
    await expect(page.locator('#manualOut')).toHaveText('https://xdgh3.com/x-post');
    await expect(page.locator('#manualAffStatus')).toContainText('DMM/FANZA以外');
    expect(saved).toEqual([xUrl]);
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
