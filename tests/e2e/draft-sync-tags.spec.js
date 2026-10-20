// @ts-check
// 画面・同期エンジン・Workerは本物。Workerの保存先と外部の作品情報だけを差し替える。
const { test, expect } = require('@playwright/test');
const { memorySync } = require('../helpers/sync-worker.cjs');

async function device(browser, baseURL, server, file = 'Stock.html') {
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
  const page = await context.newPage();
  await page.goto(new URL(file, baseURL).href, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    // 実Chromeのデータは使わず、新しいcontextの偽設定だけで動かす。
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem('sync2_url', 'https://sync.example.test');
    localStorage.setItem('sync2_token', 'test-only');
    if (window.Go5Drive) Go5Drive.configured = () => false;
  });
  return { page, context };
}
async function sync(page) {
  await page.evaluate(async () => {
    if (Go5Sync.syncDraftsNow) return Go5Sync.syncDraftsNow();
    return Go5Sync.syncNow();
  });
}
async function rows(page) {
  return page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]'));
}

test('画像走査が停止中でもAの作成・編集・削除がBのドラフト画面に届く', async ({ browser, baseURL }) => {
  const server = memorySync();
  const A = await device(browser, baseURL, server, 'index.html');
  const B = await device(browser, baseURL, server);
  try {
    for (const p of [A.page, B.page]) await p.evaluate(() => {
      Go5Idb.entriesByPrefixesSettled = Go5Idb.keysPrefix = () => new Promise(() => {});
      Go5Sync.syncNow(); // 全同期の画像走査だけを止める。テキスト同期を止めてはならない。
    });
    await A.page.evaluate(() => document.dispatchEvent(new CustomEvent('video-created', { detail: {
      draft: true, title: '端末間ドラフト', name: 'sync.mp4', account: Go5Acct.current(),
      blob: new Blob([new Uint8Array(32768)], { type: 'video/mp4' })
    } })));
    await expect.poll(() => rows(A.page), { timeout: 6000 }).toHaveLength(1);
    const id = (await rows(A.page))[0].id;
    await expect.poll(() => server.state()?.blob || '', { timeout: 6000 }).toContain(id);
    await B.page.evaluate(() => { Go5Sync.syncNow(); });
    await expect(B.page.locator('.stk-mode[data-id="' + id + '"]')).toBeVisible({ timeout: 6000 });

    await A.page.locator('.stk-mode[data-id="' + id + '"]').click();
    await A.page.locator('#draftYtDescText').fill('端末Aで編集した説明');
    await expect.poll(() => server.state()?.blob || '', { timeout: 6000 }).toContain('端末Aで編集した説明');
    await B.page.evaluate(() => { Go5Sync.syncNow(); });
    await expect.poll(() => B.page.evaluate(id => localStorage.getItem('go5_draft_post_' + id), id), { timeout: 6000 }).toContain('端末Aで編集した説明');
    await B.page.locator('.stk-mode[data-id="' + id + '"]').click();
    await expect(B.page.locator('#draftYtDescText')).toHaveValue('端末Aで編集した説明');
    await B.page.locator('#draftModalClose').click();
    await A.page.locator('#draftModalClose').click();
    A.page.once('dialog', d => d.accept());
    await A.page.locator('.stk-del[data-id="' + id + '"]').click();
    await expect.poll(() => JSON.parse(server.state().blob).ls.go5_stock_del?.v || '', { timeout: 6000 }).toContain(id);
    await B.page.evaluate(() => { Go5Sync.syncNow(); });
    await expect(B.page.locator('.stk-mode[data-id="' + id + '"]')).toHaveCount(0, { timeout: 6000 });
    await sync(B.page);
    expect((await rows(B.page)).some(m => m.id === id)).toBe(false);
    expect(await B.page.evaluate(id => localStorage.getItem('go5_draft_post_' + id), id)).toBeNull();
  } finally { await A.context.close(); await B.context.close(); }
});

test('旧版の配列時刻は各行へ一度だけ移し、同時追加も両端末に残す', async ({ browser, baseURL }) => {
  const server = memorySync();
  await server.r2.put('state/sync-v1.json', JSON.stringify({ version: 1, blob: JSON.stringify({ ls: {
    go5_stock_meta: { t: 500, v: JSON.stringify([{ id: 'legacy', addedAt: 1, label: '旧版', account: 'acc3' }]) }
  }, idb: {} }) }));
  const A = await device(browser, baseURL, server), B = await device(browser, baseURL, server);
  try {
    await sync(A.page); await sync(B.page);
    expect((await rows(A.page))[0]._syncAt).toBe(500);
    for (const [name, p] of [['A', A.page], ['B', B.page]]) await p.evaluate(name => {
      const r = JSON.parse(localStorage.go5_stock_meta);
      r.push({ id: name, label: name + 'の新規', addedAt: Date.now(), account: 'acc3' });
      localStorage.setItem('go5_stock_meta', JSON.stringify(r));
    }, name);
    // 同じ版を読んだ2pushを同時にWorkerへ到着させ、競合後の再pullも通す。
    const original = server.fetch;
    let arrivals = 0, release;
    const gate = new Promise(resolve => { release = resolve; });
    server.fetch = async req => {
      if (new URL(req.url).pathname === '/api/push' && arrivals < 2) {
        arrivals++;
        if (arrivals === 2) release();
        await gate;
      }
      return original(req);
    };
    await Promise.all([sync(A.page), sync(B.page)]);
    expect(arrivals).toBe(2);
    await sync(A.page); await sync(B.page);
    const a = await rows(A.page), b = await rows(B.page);
    expect(a.map(m => m.id).sort()).toEqual(['A', 'B', 'legacy']);
    expect(b).toEqual(a);
    expect(a.find(m => m.id === 'legacy')._syncAt).toBe(500);
  } finally { await A.context.close(); await B.context.close(); }
});

test('別ドラフトの後の保存が、他端末で編集したドラフトを巻き戻さない', async ({ browser, baseURL }) => {
  const server = memorySync(), A = await device(browser, baseURL, server), B = await device(browser, baseURL, server);
  try {
    await A.page.evaluate(() => localStorage.setItem('go5_stock_meta', JSON.stringify([
      { id: 'one', addedAt: 1, label: '初期1', account: 'acc1' },
      { id: 'two', addedAt: 2, label: '初期2', account: 'acc1' }
    ])));
    await sync(A.page); await sync(B.page);
    await A.page.evaluate(() => { const r = JSON.parse(localStorage.go5_stock_meta); r[0].label = 'Aの編集'; localStorage.setItem('go5_stock_meta', JSON.stringify(r)); });
    await B.page.evaluate(() => { const r = JSON.parse(localStorage.go5_stock_meta); r[1].label = 'Bの編集'; localStorage.setItem('go5_stock_meta', JSON.stringify(r)); });
    await sync(B.page); await sync(A.page); await sync(B.page);
    expect((await rows(A.page)).map(m => m.label)).toEqual(['Aの編集', 'Bの編集']);
    expect((await rows(B.page)).map(m => m.label)).toEqual(['Aの編集', 'Bの編集']);
  } finally { await A.context.close(); await B.context.close(); }
});

test('容量不足の受信を成功扱いせず、空きが戻ったら同じドラフトを再取得する', async ({ browser, baseURL }) => {
  const server = memorySync(), A = await device(browser, baseURL, server), B = await device(browser, baseURL, server);
  try {
    await sync(B.page);
    await A.page.evaluate(() => localStorage.setItem('go5_stock_meta', JSON.stringify([{ id: 'quota', label: '再受信', account: 'acc3', addedAt: 1, thumbDataUrl: 'data:image/png;base64,large' }])));
    await sync(A.page);
    expect(JSON.parse(server.state().blob).ls.go5_stock_meta.v).not.toContain('base64');
    await B.page.evaluate(() => {
      const set = Storage.prototype.setItem;
      window.__failDraftWrite = true;
      Storage.prototype.setItem = function (key, value) {
        if (key === 'go5_stock_meta' && window.__failDraftWrite) throw new DOMException('test quota', 'QuotaExceededError');
        return set.call(this, key, value);
      };
    });
    const failed = await B.page.evaluate(() => Go5Sync.syncDraftsNow());
    expect(failed.ok).toBe(false);
    expect(failed.error).toContain('容量不足');
    expect(await rows(B.page)).toEqual([]);
    await B.page.evaluate(() => { window.__failDraftWrite = false; });
    await sync(B.page);
    await expect(B.page.locator('.stk-mode[data-id="quota"]')).toBeVisible();
  } finally { await A.context.close(); await B.context.close(); }
});

test('時計が遅い端末の投稿編集と削除も、受信済みの値より新しく扱う', async ({ browser, baseURL }) => {
  const server = memorySync(), A = await device(browser, baseURL, server), B = await device(browser, baseURL, server);
  try {
    await A.page.evaluate(() => localStorage.setItem('go5_draft_post_clock', JSON.stringify({ ytDesc: '受信前' })));
    await sync(A.page); await sync(B.page);
    await B.page.evaluate(() => {
      Date.now = () => 1000;
      localStorage.setItem('go5_draft_post_clock', JSON.stringify({ ytDesc: '遅い時計の編集' }));
    });
    await sync(B.page); await sync(A.page);
    expect(await A.page.evaluate(() => JSON.parse(localStorage.go5_draft_post_clock).ytDesc)).toBe('遅い時計の編集');
    await B.page.evaluate(() => localStorage.removeItem('go5_draft_post_clock'));
    await sync(B.page); await sync(A.page);
    expect(await A.page.evaluate(() => localStorage.getItem('go5_draft_post_clock'))).toBeNull();
  } finally { await A.context.close(); await B.context.close(); }
});

test('21件以上が同期された端末でも次のドラフト保存で既存行を切り捨てない', async ({ browser, baseURL }) => {
  const A = await device(browser, baseURL, memorySync(), 'index.html');
  try {
    await A.page.evaluate(() => {
      const list = Array.from({ length: 21 }, (_, i) => ({ id: 'keep-' + i, label: '既存' + i, account: Go5Acct.current(), addedAt: i + 1 }));
      localStorage.setItem('go5_stock_meta', JSON.stringify(list));
      document.dispatchEvent(new CustomEvent('video-created', { detail: {
        draft: true, title: '22件目', name: '22.mp4', account: Go5Acct.current(),
        blob: new Blob([new Uint8Array(32768)], { type: 'video/mp4' })
      } }));
    });
    await expect.poll(() => rows(A.page), { timeout: 6000 }).toHaveLength(22);
    expect((await rows(A.page)).filter(m => m.id.startsWith('keep-'))).toHaveLength(21);
  } finally { await A.context.close(); }
});

test('削除の墓標は古い端末の再送より強く、明示復元だけが墓標を越える', async ({ browser, baseURL }) => {
  const server = memorySync(), A = await device(browser, baseURL, server), B = await device(browser, baseURL, server);
  try {
    await A.page.evaluate(() => {
      localStorage.setItem('go5_stock_meta', JSON.stringify([{ id: 'restore', account: 'acc3', label: '復元対象', addedAt: 1 }]));
      Go5Stock.render();
    });
    await sync(A.page); await sync(B.page);
    A.page.once('dialog', d => d.accept());
    await A.page.locator('.stk-del[data-id="restore"]').click();
    await sync(A.page); await sync(B.page); await sync(A.page);
    expect(await rows(B.page)).toEqual([]);
    await A.page.evaluate(() => {
      localStorage.setItem('go5_stock_archive', JSON.stringify([{ id: 'restore', account: 'acc3', label: '復元対象', addedAt: 1, completedTs: 2 }]));
      Go5Stock.render();
    });
    await A.page.locator('#stkArchDetails summary').click();
    await A.page.locator('.stk-restore[data-id="restore"]').click();
    await sync(A.page); await sync(B.page);
    await expect(B.page.locator('.stk-mode[data-id="restore"]')).toBeVisible();
    const state = await B.page.evaluate(() => ({ row: JSON.parse(localStorage.go5_stock_meta)[0], del: JSON.parse(localStorage.go5_stock_del).restore }));
    expect(state.row.addedAt).toBeGreaterThan(state.del);
  } finally { await A.context.close(); await B.context.close(); }
});

async function enterInfo(page, cid, info) {
  await page.evaluate(({ cid, info }) => {
    FanzaCore.fetchFanzaInfo = () => Promise.resolve(Object.assign({ cid }, info));
    localStorage.setItem('fanza_worker_url', 'https://fanza.example.test');
    const e = document.getElementById('movieWorkUrl');
    e.value = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/';
    e.dispatchEvent(new Event('input', { bubbles: true }));
  }, { cid, info });
  await expect(page.locator('#movieWorkInfo')).toContainText(info.title);
}

test('候補で分かったタグは後着の部分情報で消えず、手動解除も保持する', async ({ browser, baseURL }) => {
  const A = await device(browser, baseURL, memorySync(), 'index.html');
  try {
    await A.page.evaluate(() => { Go5MovieAttrs.reset(); Go5MovieAttrs.applyGenres(['ハーレム'], 'd_123456', '総集編', '', '', true); });
    await expect(A.page.locator('#movieAttrHarem')).toBeChecked();
    await enterInfo(A.page, 'd_123456', { title: '部分取得', partial: true, genres: [], ai: false });
    await expect(A.page.locator('#movieAttrHarem')).toBeChecked();
    await expect(A.page.locator('#movieAttrSoshu')).toBeChecked();
    await A.page.locator('#movieAttrAi').uncheck();
    await A.page.evaluate(() => Go5MovieAttrs.applyGenres(['ハーレム'], 'd_123456', '総集編', '', '', true));
    await expect(A.page.locator('#movieAttrAi')).not.toBeChecked();
  } finally { await A.context.close(); }
});

test('同じブラウザの2タブでも適用済みcidを共有せず、それぞれに自動タグが付く', async ({ browser, baseURL }) => {
  const A = await device(browser, baseURL, memorySync(), 'index.html');
  const second = await A.context.newPage();
  try {
    await second.goto(new URL('index.html', baseURL).href, { waitUntil: 'domcontentloaded' });
    const info = { title: '共有作品', genres: ['ハーレム'] };
    await enterInfo(A.page, 'd_123458', info);
    await expect(A.page.locator('#movieAttrHarem')).toBeChecked();
    await enterInfo(second, 'd_123458', info);
    await expect(second.locator('#movieAttrHarem')).toBeChecked();
  } finally { await A.context.close(); }
});

test('作品URLを替えた直後に旧作品の応答が届いても、旧タグを持ち越さない', async ({ browser, baseURL }) => {
  const A = await device(browser, baseURL, memorySync(), 'index.html');
  try {
    await A.page.evaluate(() => {
      localStorage.setItem('fanza_worker_url', 'https://fanza.example.test');
      FanzaCore.fetchFanzaInfo = cid => new Promise(resolve => { window.__oldInfo = () => resolve({ cid, title: '旧作品', genres: ['ハーレム'] }); });
      const el = document.getElementById('movieWorkUrl');
      el.value = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_900001/';
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await A.page.waitForFunction(() => !!window.__oldInfo);
    await A.page.evaluate(() => {
      const el = document.getElementById('movieWorkUrl');
      FanzaCore.fetchFanzaInfo = cid => Promise.resolve({ cid, title: '次作品', genres: ['異世界'] });
      el.value = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_900002/';
      el.dispatchEvent(new Event('input', { bubbles: true }));
      window.__oldInfo(); // 次作品のデバウンス待ち500ms以内に到着させる。
    });
    await expect(A.page.locator('#movieWorkInfo')).toContainText('次作品');
    await expect(A.page.locator('#movieAttrHarem')).not.toBeChecked();
    await expect(A.page.locator('#movieAttrIsekai')).toBeChecked();
  } finally { await A.context.close(); }
});
