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

test('受け箱の候補を cid 重複なしで🤖自動追加タブへ取り込み、出所未確認に印を付ける', async ({ page }) => {
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
    localStorage.setItem('cand_items', JSON.stringify([{ cid: inList.cid, title: '既に一覧に在る', url: inList.url, addedAt: Date.now() },
      { cid: 'd_e2e_oldgrok', title: '旧版で手動追加へ入ったGrok候補', url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_oldgrok/', addedAt: 1792000000000, source: 'grok_fanza' }]));
    localStorage.setItem('cand_del', JSON.stringify({ [deleted.cid]: Date.now() }));
    localStorage.setItem('cand_inbox_seen', JSON.stringify({ [seenOnly.cid]: Date.now() })); // 前に取り込んで消した等
  }, { SYNC, inList, deleted, seenOnly });
  await page.reload({ waitUntil: 'domcontentloaded' });

  const want = rows.length - 3 + 1; // 一覧に在る/削除済み/取り込み済みの3件は足さない→新規(rows-3)+旧版から移したGrok1件
  await expect.poll(async () => page.evaluate(() => JSON.parse(localStorage.getItem('cand_items__auto') || '[]').length)).toBe(want);
  expect(inboxHits).toBeGreaterThan(0);

  // 手動追加には手で足した分だけが残る。移したGrok候補は手動追加の墓標で union から戻らない
  const mainItems = await page.evaluate(() => JSON.parse(localStorage.getItem('cand_items') || '[]'));
  expect(mainItems.map((x) => x.cid)).toEqual([inList.cid]);
  expect(mainItems[0].title).toBe('既に一覧に在る'); // 既存は上書きしない
  const mainDel = await page.evaluate(() => JSON.parse(localStorage.getItem('cand_del') || '{}'));
  expect(Object.keys(mainDel)).toContain('d_e2e_oldgrok');

  const items = await page.evaluate(() => JSON.parse(localStorage.getItem('cand_items__auto') || '[]'));
  const cids = items.map((x) => x.cid);
  expect(new Set(cids).size).toBe(cids.length);             // cid重複なし
  expect(cids).not.toContain(deleted.cid);                  // 削除済みは湧かない
  expect(cids).not.toContain(seenOnly.cid);                 // 取り込み済みは二度入れない
  expect(cids).not.toContain(inList.cid);                   // 手動追加に在る作品は自動追加へ入れない
  expect(cids).toContain('d_e2e_oldgrok');
  for (const c of unverified) expect(items.find((x) => x.cid === c).postVerified).toBe(false);
  console.log('inbox=' + rows.length + ' imported=' + (want - 1) + ' total=' + items.length + ' unverified=' + unverified.join(','));

  // タブの並び: 🤖自動追加は 手動追加 の左。開くと全件にGrok自動の印、出所未確認の行にだけ⚠
  const order = await page.locator('.cand-tab[data-ct]').evaluateAll((els) => els.map((e) => e.getAttribute('data-ct')));
  expect(order.indexOf('auto')).toBe(order.indexOf('main') - 1);
  // 🤖はいらない(Chami 2026-10-20)=タブにもカードの印にも出さない
  await expect(page.locator('.cand-tab[data-ct="auto"]')).toHaveText('自動追加');
  await page.locator('.cand-tab[data-ct="auto"]').click();
  await expect(page.locator('.cand-card .fp-kind-grok')).toHaveCount(Math.min(want, 20));
  expect(await page.locator('#page-candidates, body').first().innerText()).not.toContain('🤖');
  await expect(page.locator('.fp-kind-unv')).toHaveCount(unverified.length);
  const verifiedTitle = rows.find((r) => r.postVerified !== false && r.cid !== inList.cid && r.cid !== deleted.cid).title;
  await expect(page.locator('.cand-card', { hasText: verifiedTitle }).locator('.fp-kind-unv')).toHaveCount(0);

  // 取り込んだ cid は端末に覚える。もう一度読んでも増えない
  const seen = await page.evaluate(() => Object.keys(JSON.parse(localStorage.getItem('cand_inbox_seen') || '{}')));
  for (const c of cids) if (c !== 'd_e2e_oldgrok') expect(seen).toContain(c);
  const again = await page.evaluate(() => window.Go5CandInbox.importNow());
  expect(again.added).toBe(0);
  const after = await page.evaluate(() => JSON.parse(localStorage.getItem('cand_items__auto') || '[]').length);
  expect(after).toBe(want);
});

test('Grok候補に元ポストのXリンクと画像を付ける(前の版で取り込んだ分も埋める)', async ({ page }) => {
  // 1x1の赤/青。元ポストの写真(pbs.twimg.com)の代わり。同じ中身だと1枚に寄るので色を分ける
  const RED = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC', 'base64');
  const BLUE = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYPgPAAEDAQAIicLsAAAAAElFTkSuQmCC', 'base64');
  const post = (n) => 'https://x.com/e2e_acct/status/90000000000000000' + n;
  const doc = { ok: true, items: [1, 2].map((i) => ({
    url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_src' + i + '/', cid: 'd_e2e_src' + i,
    title: '元ポスト確認作品' + i, author: 'e2e', thumb: '', price: 550, addedAt: 1792000000000 + i,
    source: 'grok_fanza', postVerified: true, sourcePost: post(i), sourceAcct: 'e2e_acct',
    sourceImgs: ['https://pbs.twimg.com/media/e2e_src' + i + '_a.jpg', 'https://pbs.twimg.com/media/e2e_src' + i + '_b.jpg'],
  })) };
  let imgHits = 0;
  await page.route('https://pbs.twimg.com/**', (route) => { imgHits++; return route.fulfill({ status: 200, contentType: 'image/png', headers: { 'access-control-allow-origin': '*' }, body: /_b\.jpg/.test(route.request().url()) ? BLUE : RED }); });
  await page.route(SYNC + '/**', (route) => new URL(route.request().url()).pathname === '/api/cand-inbox'
    ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(doc) }) : route.abort());

  await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate(({ SYNC, it }) => {
    localStorage.clear();
    localStorage.setItem('sync2_url', SYNC);
    localStorage.setItem('sync2_token', 'e2e-token');
    // v1069で取り込んだ形=twitterUrl 無し。2件目は今回の受け箱で新しく入る
    localStorage.setItem('cand_items__auto', JSON.stringify([{ url: it.url, cid: it.cid, title: it.title, addedAt: it.addedAt, source: 'grok_fanza', postVerified: true }]));
    localStorage.setItem('cand_inbox_seen', JSON.stringify({ [it.cid]: Date.now() }));
  }, { SYNC, it: doc.items[0] });
  await page.reload({ waitUntil: 'domcontentloaded' });

  await expect.poll(async () => page.evaluate(() => JSON.parse(localStorage.getItem('cand_items__auto') || '[]').map((x) => x.cid + '=' + (x.twitterUrl || '')).sort().join(' ')))
    .toBe(doc.items.map((x) => x.cid + '=' + x.sourcePost).join(' '));
  await expect.poll(async () => page.evaluate(() => Object.keys(JSON.parse(localStorage.getItem('cand_inbox_imgs') || '{}')).sort().join(' ')), { timeout: 20000 })
    .toBe('d_e2e_src1 d_e2e_src2');
  expect(imgHits).toBeGreaterThanOrEqual(4);

  await page.locator('.cand-tab[data-ct="auto"]').click();
  for (const it of doc.items) {
    const card = page.locator('.cand-card[data-cid="' + it.cid + '"]');
    await expect(card.locator('a.vlink-sns')).toHaveAttribute('href', it.sourcePost);
    await expect(card.locator('.cand-refimgs img.cand-refimg-thumb')).toHaveAttribute('title', /全2枚/); // カードは先頭1枚+枚数
  }

  // 画像を消した後に読み直しても戻さない(一度入れたcidは覚えている)
  await page.evaluate(() => window.Go5Cand && window.Go5Cand.refImgsSet && window.Go5Cand.refImgsSet('d_e2e_src1', []));
  await page.evaluate(() => window.Go5CandInbox.importNow());
  const n1 = await page.evaluate(() => JSON.parse(localStorage.getItem('cand_inbox_imgs') || '{}').d_e2e_src1);
  expect(n1).toBeTruthy();
});
