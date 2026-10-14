// @ts-check
// 自動収集の受け箱(GET /api/cand-inbox)→本命タブ取り込み。cid重複除け・墓標尊重・出所未確認バッジを通す。
// 中身は既定で合成データ。実データで通す時は CAND_INBOX_JSON=<publish_cand_inbox.py --out の出力> を渡す
// (実データの題名はrepoへ入れない)。
const fs = require('fs');
const { test, expect } = require('@playwright/test');

const SYNC = 'https://sync.e2e.invalid';

function inboxDoc() {
  if (process.env.CAND_INBOX_JSON) return JSON.parse(fs.readFileSync(process.env.CAND_INBOX_JSON, 'utf8'));
  const items = [];
  for (let i = 1; i <= 6; i++) {
    items.push({
      url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_inbox' + i + '/', cid: 'd_e2e_inbox' + i,
      title: '受け箱確認作品' + i, author: 'e2e', thumb: '', price: 550, addedAt: 1792000000000 + i,
      source: 'grok_fanza', postVerified: i !== 3,
    });
  }
  return { ok: true, items };
}

test('受け箱の候補を cid 重複なしで本命タブへ取り込み、出所未確認に印を付ける', async ({ page }) => {
  const doc = inboxDoc();
  const rows = doc.items;
  const verified = rows.filter((r) => r.postVerified !== false);
  const inList = verified[0], deleted = verified[1], seenOnly = verified[2];
  const unverified = rows.filter((r) => r.postVerified === false).map((r) => r.cid);
  expect(unverified.length).toBeGreaterThan(0);

  let inboxHits = 0;
  await page.route(SYNC + '/**', (route) => {
    if (new URL(route.request().url()).pathname === '/api/cand-inbox') {
      inboxHits++;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(doc) });
    }
    return route.abort(); // 状態同期などは通さない(このテストは取り込みだけを見る)
  });

  await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate(({ SYNC, inList, deleted, seenOnly }) => {
    localStorage.clear();
    localStorage.setItem('sync2_url', SYNC);
    localStorage.setItem('sync2_token', 'e2e-token');
    localStorage.setItem('cand_items', JSON.stringify([{ cid: inList.cid, title: '既に一覧に在る', url: inList.url, addedAt: Date.now() }]));
    localStorage.setItem('cand_del', JSON.stringify({ [deleted.cid]: Date.now() }));
    localStorage.setItem('cand_inbox_seen', JSON.stringify({ [seenOnly.cid]: Date.now() })); // 前に取り込んで消した等
  }, { SYNC, inList, deleted, seenOnly });
  await page.reload({ waitUntil: 'domcontentloaded' });

  const want = rows.length - 2; // 一覧に在る/削除済み/取り込み済みの3件は足さない→既存1+新規(rows-3)
  await expect.poll(async () => page.evaluate(() => JSON.parse(localStorage.getItem('cand_items') || '[]').length)).toBe(want);
  expect(inboxHits).toBeGreaterThan(0);

  const items = await page.evaluate(() => JSON.parse(localStorage.getItem('cand_items') || '[]'));
  const cids = items.map((x) => x.cid);
  expect(new Set(cids).size).toBe(cids.length);             // cid重複なし
  expect(cids).not.toContain(deleted.cid);                  // 削除済みは湧かない
  expect(cids).not.toContain(seenOnly.cid);                 // 取り込み済みは二度入れない
  expect(items.find((x) => x.cid === inList.cid).title).toBe('既に一覧に在る'); // 既存は上書きしない
  for (const c of unverified) expect(items.find((x) => x.cid === c).postVerified).toBe(false);
  console.log('inbox=' + rows.length + ' imported=' + (want - 1) + ' total=' + items.length + ' unverified=' + unverified.join(','));

  // 一覧の見分け: 出所未確認の行にだけバッジ
  await expect(page.locator('.fp-kind-unv')).toHaveCount(unverified.length);
  const verifiedTitle = rows.find((r) => r.postVerified !== false && r.cid !== inList.cid && r.cid !== deleted.cid).title;
  await expect(page.locator('.cand-card', { hasText: verifiedTitle }).locator('.fp-kind-unv')).toHaveCount(0);

  // 取り込んだ cid は端末に覚える。もう一度読んでも増えない
  const seen = await page.evaluate(() => Object.keys(JSON.parse(localStorage.getItem('cand_inbox_seen') || '{}')));
  for (const c of cids) if (c !== inList.cid) expect(seen).toContain(c);
  const again = await page.evaluate(() => window.Go5CandInbox.importNow());
  expect(again.added).toBe(0);
  const after = await page.evaluate(() => JSON.parse(localStorage.getItem('cand_items') || '[]').length);
  expect(after).toBe(want);
});
