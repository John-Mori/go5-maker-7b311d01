// @ts-check
// 📝テンプレ帳「現在文に更新」が同期で元に戻らないこと(Chami msg 1561044298865189074「更新しても元に戻る」)。
// 画面・同期エンジン・Workerは本物。Workerの保存先だけメモリへ差し替える。
const { test, expect } = require('@playwright/test');
const { memorySync } = require('../helpers/sync-worker.cjs');

const KEY = 'bsky_tpl_book__acc3';

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
const tplText = (page, name) => page.evaluate(([k, n]) => (JSON.parse(localStorage.getItem(k) || '[]').find(t => t.name === n) || {}).text, [KEY, name]);

test('現在文に更新した本文は、古い本文を持つ端末の後発同期でも元に戻らない', async ({ browser, baseURL }) => {
  const server = memorySync();
  await server.r2.put('state/sync-v1.json', JSON.stringify({ version: 1, blob: JSON.stringify({ ls: {
    [KEY]: { t: 500, v: JSON.stringify([{ name: 'テンプレ暫定', text: '旧本文', at: 100 }]) }
  }, idb: {} }) }));
  const A = await device(browser, baseURL, server), B = await device(browser, baseURL, server);
  try {
    await sync(A.page); await sync(B.page);
    await expect.poll(() => tplText(A.page, 'テンプレ暫定')).toBe('旧本文');
    await expect.poll(() => tplText(B.page, 'テンプレ暫定')).toBe('旧本文');

    // 端末A: テンプレを選び、本文を書き換えて「現在文に更新」。
    await A.page.evaluate(() => {
      const sel = document.getElementById('bskyTplSel');
      // 画面のドロップダウンは起動時に作られるため、同期で届いた帳を読み直させる。
      const book = JSON.parse(localStorage.getItem('bsky_tpl_book__acc3'));
      sel.innerHTML = '<option value="">(選択)</option>' + book.map((t, i) => '<option value="' + i + '">' + t.name + '</option>').join('');
      sel.value = '0';
      document.getElementById('bskyText').value = '新本文';
      document.getElementById('bskyTplApply').click();
    });
    await expect(A.page.locator('#bskyTplHint')).toContainText('を今の本文で更新しました');
    await sync(A.page);
    await expect.poll(() => server.state()?.blob || '').toContain('新本文');

    // 端末B: Aの更新を受け取る前に、帳の別テンプレを保存＝キーの保存時刻はBが新しい(古い本文を抱えたまま)。
    await B.page.evaluate(k => {
      const book = JSON.parse(localStorage.getItem(k));
      book.push({ name: '別テンプレ', text: 'B側', at: Date.now() });
      localStorage.setItem(k, JSON.stringify(book));
    }, KEY);
    await sync(B.page);
    await sync(A.page);

    expect(await tplText(A.page, 'テンプレ暫定')).toBe('新本文');
    expect(await tplText(B.page, 'テンプレ暫定')).toBe('新本文');
    expect(await tplText(A.page, '別テンプレ')).toBe('B側');
  } finally { await A.context.close(); await B.context.close(); }
});
