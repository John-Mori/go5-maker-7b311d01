// @ts-check
// 同期で届いた🔥セール案内URL・📝テンプレ帳が、開いたままの端末の画面へ描き直されること
// (Chami msg 1561049482962010206「現在文を保存しても保存されない」「セール用短縮URLを登録しても…準備中になる」)。
// 画面・同期エンジン・Workerは本物。Workerの保存先だけメモリへ差し替える。
const { test, expect } = require('@playwright/test');
const { memorySync } = require('../helpers/sync-worker.cjs');

async function device(browser, baseURL, server) {
  const context = await browser.newContext();
  const origin = new URL(baseURL).origin;
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin === 'https://sync.example.test') {
      const response = await server.fetch(new Request(req.url(), {
        method: req.method(), headers: req.headers(), body: req.postData() || undefined
      }));
      return route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers), body: Buffer.from(await response.arrayBuffer()) });
    }
    if (url.origin === origin || url.protocol === 'data:' || url.protocol === 'blob:') return route.continue();
    return route.abort();
  });
  await context.addInitScript(() => {
    // 実Chromeのデータは使わず、新しいcontextの偽設定だけで動かす。
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem('sync2_url', 'https://sync.example.test');
    localStorage.setItem('sync2_token', 'test-only');
  });
  const page = await context.newPage();
  await page.goto(new URL('index.html', baseURL).href, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => { if (window.Go5Drive) Go5Drive.configured = () => false; });
  return { page, context };
}
const sync = page => page.evaluate(() => Go5Sync.syncNow());

test('他端末で追加したセールURLとテンプレが、開いたままの端末の一覧へ出て選択も揃う', async ({ browser, baseURL }) => {
  const server = memorySync();
  const A = await device(browser, baseURL, server), B = await device(browser, baseURL, server);
  try {
    await sync(A.page); await sync(B.page);
    // 端末A: 画面からセールURLを追加し、本文をテンプレ保存する。
    A.page.on('dialog', d => d.accept('秋テンプレ'));
    await A.page.evaluate(() => {
      document.getElementById('discUrlName').value = '秋セール';
      document.getElementById('discUrlInput').value = 'https://xdgh3.com/odXX';
      document.getElementById('discUrlAddBtn').click();
      document.getElementById('bskyText').value = '秋の本文';
    });
    await A.page.evaluate(() => document.getElementById('bskyTplSave').click());
    await expect(A.page.locator('#bskyTplHint')).toContainText('として保存しました');
    await sync(A.page);
    await expect.poll(() => server.state()?.blob || '').toContain('秋テンプレ');

    // 端末B: 再読込せずに同期だけ受け取る。
    await sync(B.page);
    await expect(B.page.locator('#discUrlList')).toContainText('秋セール');
    await expect(B.page.locator('#discUrlList label', { hasText: '秋セール' }).locator('input[type=radio]')).toBeChecked();
    await expect(B.page.locator('#bskyTplSel option', { hasText: '秋テンプレ' })).toHaveCount(1);
  } finally { await A.context.close(); await B.context.close(); }
});
