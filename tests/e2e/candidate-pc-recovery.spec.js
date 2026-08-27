// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('PC candidate recovery invariants', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
  });

  test('search remains available and can recover a hidden candidate', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    const search = page.locator('#candWorkSearch');
    await expect(search).toBeVisible();
    await expect(search).toHaveAttribute('aria-label', '作品検索(全候補・部分一致)');

    const hiddenCid = 'd_pc_search_hidden_recovery';
    const hiddenTitle = 'PC検索救出専用作品';
    await page.evaluate(({ hiddenCid, hiddenTitle }) => {
      localStorage.setItem('cand_items', JSON.stringify([
        {
          cid: hiddenCid,
          title: hiddenTitle,
          url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + hiddenCid + '/',
          addedAt: Date.now()
        },
        {
          cid: 'd_pc_search_other',
          title: '検索対象外の作品',
          url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_pc_search_other/',
          addedAt: Date.now() - 1
        }
      ]));
      localStorage.setItem('cand_hidden__main', JSON.stringify([hiddenCid]));
    }, { hiddenCid, hiddenTitle });
    await page.reload({ waitUntil: 'domcontentloaded' });

    await expect(page.locator('.cand-card', { hasText: hiddenTitle })).toHaveCount(0);
    await page.locator('#candWorkSearch').fill('検索救出専用');
    const recovered = page.locator('.cand-card', { hasText: hiddenTitle });
    await expect(recovered).toBeVisible();
    await expect(recovered.getByRole('button', { name: '👁 再表示' })).toBeVisible();
    await expect(page.locator('.cand-card', { hasText: '検索対象外の作品' })).toHaveCount(0);
  });

  test('doujin and Books checkboxes filter cards and visible count', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      localStorage.setItem('cand_items', JSON.stringify([
        {
          cid: 'd_kind_filter', title: '同人フィルター確認作品',
          url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_kind_filter/', addedAt: Date.now()
        },
        {
          cid: 'b_kind_filter', title: 'Booksフィルター確認作品',
          url: 'https://book.dmm.com/detail/b_kind_filter/', addedAt: Date.now() - 1
        }
      ]));
    });
    await page.reload({ waitUntil: 'domcontentloaded' });

    const doujin = page.locator('#candFilterDoujin');
    const books = page.locator('#candFilterBooks');
    const doujinCard = page.locator('.cand-card', { hasText: '同人フィルター確認作品' });
    const booksCard = page.locator('.cand-card', { hasText: 'Booksフィルター確認作品' });
    await expect(doujin).toBeVisible();
    await expect(books).toBeVisible();
    await expect(doujinCard).toBeVisible();
    await expect(booksCard).toBeVisible();

    const positions = await page.evaluate(() => {
      const group = document.querySelector('.cand-kind-filter').getBoundingClientRect();
      const posted = document.querySelector('#candHidePosted1').getBoundingClientRect();
      return { groupRight: group.right, postedLeft: posted.left };
    });
    expect(positions.groupRight).toBeLessThanOrEqual(positions.postedLeft);

    await doujin.check();
    await expect(doujinCard).toBeVisible();
    await expect(booksCard).toHaveCount(0);
    await expect(page.locator('#candList > p.hint').first()).toContainText('1件');

    await books.check();
    await expect(doujinCard).toBeVisible();
    await expect(booksCard).toBeVisible();

    await doujin.uncheck();
    await expect(doujinCard).toHaveCount(0);
    await expect(booksCard).toBeVisible();
    await expect(page.locator('#candList > p.hint').first()).toContainText('1件');

    await books.uncheck();
    await expect(doujinCard).toBeVisible();
    await expect(booksCard).toBeVisible();
  });
  test('a synced candidate image appears without navigating away or reloading', async ({ page }) => {
    const cid = 'd_pc_synced_image_exact_key';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ cid }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid,
        title: 'PC同期画像即時反映作品',
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/',
        addedAt: Date.now()
      }]));
    }, { cid });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-refimg="' + cid + '"]')).toBeVisible();
    await expect(page.locator('[data-refimgview="' + cid + '"]')).toHaveCount(0);

    await page.evaluate(async ({ cid }) => {
      const canvas = document.createElement('canvas');
      canvas.width = 8;
      canvas.height = 8;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#00cc66';
      ctx.fillRect(0, 0, 8, 8);
      const image = canvas.toDataURL('image/png');
      await Go5Idb.set('ref:' + cid, {
        imgs: [image],
        img: image,
        comment: 'PC sync',
        memo: '',
        at: Date.now()
      });
      document.dispatchEvent(new CustomEvent('go5-synced', {
        detail: { pulled: 0, pulledCand: 0, pulledImg: 1, pulledImgKeys: ['ref:' + cid] }
      }));
    }, { cid });

    await expect(page.locator('[data-refimgview="' + cid + '"]')).toBeVisible();
  });
  test('new candidate shares one metadata request and flushes immediately for another device', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      localStorage.setItem('fanza_worker_url', 'https://worker.invalid');
      localStorage.setItem('fanza_shared_secret', 'test-only');
      window.__pcCandidateFetchCalls = 0;
      window.__pcCandidateAiCalls = 0;
      window.__pcCandidateFlushCalls = 0;
      window.__pcCandidateResolve = null;
      window.FanzaCore.fetchFanzaInfo = (_cid, _url, _secret, _src, opts) => {
        if (opts && opts.checkAi) {
          window.__pcCandidateAiCalls++;
          return Promise.resolve({ title: 'PC取得一本化テスト作品', ai: false, aiChecked: true });
        }
        window.__pcCandidateFetchCalls++;
        return new Promise((resolve) => { window.__pcCandidateResolve = resolve; });
      };
      window.Go5Sync.flushSync = () => {
        window.__pcCandidateFlushCalls++;
        return Promise.resolve({ ok: true });
      };
      window.Go5Sync.syncCandidatesNow = window.Go5Sync.flushSync;
    });

    await page.locator('#candAddOpen').click();
    await page.locator('#candUrl').fill('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_pc_singleflight/');
    await page.locator('#candAddClose').click();

    await expect.poll(() => page.evaluate(() => window.__pcCandidateFetchCalls)).toBe(1);
    await expect.poll(() => page.evaluate(() => window.__pcCandidateFlushCalls)).toBe(1);
    await expect(page.locator('.cand-card', { hasText: '取得中です' })).toBeVisible();

    await page.evaluate(() => {
      window.__pcCandidateResolve({
        title: 'PC取得一本化テスト作品', author: 'test', releaseDate: '2026-08-25',
        thumb: 'https://example.invalid/thumb.jpg', genres: ['同人'], floor: '同人',
        listPrice: 1000, price: 500, discountPct: 50, reviewCount: 1, reviewAvg: 5
      });
    });
    await expect(page.locator('.cand-card', { hasText: 'PC取得一本化テスト作品' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => window.__pcCandidateFetchCalls)).toBe(1);
  });
  test('add and close still shows the merged-work notice for a duplicate', async ({ page }) => {
    const cid = 'd_pc_duplicate_close_notice';
    const workUrl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/';
    await page.addInitScript(({ candidateCid, url }) => {
      localStorage.setItem('cand_items', JSON.stringify([{ cid: candidateCid, url, title: '統合案内テスト', addedAt: 1 }]));
    }, { candidateCid: cid, url: workUrl });
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });

    await page.locator('#candAddOpen').click();
    await page.locator('#candUrl').fill(workUrl);
    await page.locator('#candAddClose').click();

    await expect(page.locator('.fz-overlay:has(.add-modal)')).toBeHidden();
    await expect(page.locator('.dup-overlay')).toBeVisible();
    await expect(page.locator('#dupTitleText')).toHaveText('同じ作品が既に追加されているので統合');
    await expect(page.locator('#candPageMsg')).toContainText('同じ作品が既に追加されているので統合');
  });
  test('LS quota fallback still flushes a new candidate after the IDB mirror is durable', async ({ page }) => {
    const cid = 'd_pc_quota_candidate_sync';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      localStorage.setItem('fanza_worker_url', 'https://worker.invalid');
      localStorage.setItem('fanza_shared_secret', 'test-only');
      window.__quotaCandidateFlushCalls = 0;
      window.FanzaCore.fetchFanzaInfo = () => new Promise(() => {});
      window.Go5Sync.flushSync = () => {
        window.__quotaCandidateFlushCalls++;
        return Promise.resolve({ ok: true });
      };
      window.Go5Sync.syncCandidatesNow = window.Go5Sync.flushSync;
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (this === localStorage && key === 'cand_items') {
          throw new DOMException('forced candidate quota', 'QuotaExceededError');
        }
        return originalSetItem.call(this, key, value);
      };
    });

    await page.locator('#candAddOpen').click();
    await page.locator('#candUrl').fill('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/');
    await page.locator('#candAddClose').click();

    await expect.poll(() => page.evaluate(() => window.__quotaCandidateFlushCalls)).toBe(1);
    await expect(page.locator('.cand-card', { hasText: '取得中です' })).toBeVisible();
    await expect.poll(() => page.evaluate(async (candidateCid) => {
      const r = await Go5Idb.getResult('meta:candlist:cand_items');
      return !!(r && r.ok && Array.isArray(r.value) && r.value.some((it) => it && it.cid === candidateCid));
    }, cid)).toBe(true);
  });

  test('a received candidate list in the IDB fallback appears immediately without reload', async ({ page }) => {
    const oldCid = 'd_phone_existing_candidate';
    const newCid = 'd_phone_received_candidate';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ oldCid }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid: oldCid,
        title: '既存候補',
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + oldCid + '/',
        addedAt: 1
      }]));
    }, { oldCid });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.cand-card', { hasText: '既存候補' })).toBeVisible();

    await page.evaluate(async ({ oldCid, newCid }) => {
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (this === localStorage && key === 'cand_items') {
          throw new DOMException('forced receiver quota', 'QuotaExceededError');
        }
        return originalSetItem.call(this, key, value);
      };
      await Go5Idb.set('meta:candlist:cand_items', [
        {
          cid: newCid,
          title: '別端末から届いた新規候補',
          url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + newCid + '/',
          addedAt: 2
        },
        {
          cid: oldCid,
          title: '既存候補',
          url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + oldCid + '/',
          addedAt: 1
        }
      ]);
      document.dispatchEvent(new CustomEvent('go5-candidate-list-applied', {
        detail: { key: 'cand_items', storage: 'idb' }
      }));
    }, { oldCid, newCid });

    await expect(page.locator('.cand-card', { hasText: '別端末から届いた新規候補' })).toBeVisible();
  });
  test('candidate fast lane receives a cloud row before any image prefix scan', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    const result = await page.evaluate(async () => {
      const oldRow = {
        cid: 'd_fast_existing', title: '既存候補',
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_fast_existing/', addedAt: 1
      };
      const newRow = {
        cid: 'd_fast_phone_receive', title: '画像走査前に届く候補',
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_fast_phone_receive/', addedAt: 2
      };
      localStorage.setItem('cand_items', JSON.stringify([oldRow]));
      localStorage.setItem('sync2_url', 'https://sync.test');
      localStorage.setItem('sync2_token', 'test-token');
      Go5Idb.entriesByPrefixesSettled = () => { throw new Error('image scan must not run in candidate fast lane'); };
      const remote = { fmt: 2, ls: { cand_items: { t: 200, v: JSON.stringify([newRow, oldRow]) } }, idb: {} };
      window.fetch = async (url) => {
        if (String(url).endsWith('/api/pull')) {
          return new Response(JSON.stringify({ ok: true, version: 7, blob: JSON.stringify(remote) }), {
            status: 200, headers: { 'Content-Type': 'application/json' }
          });
        }
        throw new Error('unexpected network call: ' + url);
      };
      const started = Date.now();
      const syncResult = await Go5Sync.syncCandidatesNow();
      return { elapsed: Date.now() - started, syncResult };
    });

    expect(result.elapsed).toBeLessThan(3000);
    expect(result.syncResult.ok).toBe(true);
    await expect(page.locator('.cand-card', { hasText: '画像走査前に届く候補' })).toBeVisible();
  });

  test('candidate fast lane pushes a PC row without waiting for image hashing', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    const result = await page.evaluate(async () => {
      const oldRow = {
        cid: 'd_fast_push_old', title: '既存候補',
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_fast_push_old/', addedAt: 1
      };
      const newRow = {
        cid: 'd_fast_push_new', title: 'PCから即送信する候補',
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_fast_push_new/', addedAt: 2
      };
      localStorage.setItem('cand_items', JSON.stringify([newRow, oldRow]));
      localStorage.setItem('sync2_url', 'https://sync.test');
      localStorage.setItem('sync2_token', 'test-token');
      Go5Idb.entriesByPrefixesSettled = () => new Promise(() => {});
      const remote = { fmt: 2, ls: { cand_items: { t: 100, v: JSON.stringify([oldRow]) } }, idb: { 'ref:keep': { t: 1, v: {} } } };
      let pushed = null;
      window.fetch = async (url, init) => {
        if (String(url).endsWith('/api/pull')) {
          return new Response(JSON.stringify({ ok: true, version: 7, blob: JSON.stringify(remote) }), {
            status: 200, headers: { 'Content-Type': 'application/json' }
          });
        }
        if (String(url).endsWith('/api/push')) {
          const envelope = JSON.parse(init.body);
          pushed = JSON.parse(envelope.blob);
          return new Response(JSON.stringify({ ok: true, version: 8 }), {
            status: 200, headers: { 'Content-Type': 'application/json' }
          });
        }
        throw new Error('unexpected network call: ' + url);
      };
      const started = Date.now();
      const syncResult = await Go5Sync.syncCandidatesNow();
      return {
        elapsed: Date.now() - started,
        syncResult,
        pushedCids: JSON.parse(pushed.ls.cand_items.v).map((it) => it.cid),
        keptRemoteImage: !!pushed.idb['ref:keep']
      };
    });

    expect(result.elapsed).toBeLessThan(3000);
    expect(result.syncResult.ok).toBe(true);
    expect(result.pushedCids).toContain('d_fast_push_new');
    expect(result.keptRemoteImage).toBe(true);
  });

  test('全候補の作品を手動追加へ移し、手動追加タブへ即時反映する', async ({ page }) => {
    const cid = 'd_move_all_to_manual';
    const title = '全候補から選んだ作品';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ cid, title }) => {
      localStorage.setItem('cand_items', '[]');
      localStorage.setItem('cand_tabs', JSON.stringify([{ id: 'picked', name: '候補元リスト' }]));
      localStorage.setItem('cand_items__picked', JSON.stringify([{
        cid, title,
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/',
        author: '回帰試験サークル',
        addedAt: 1
      }]));
    }, { cid, title });
    await page.reload({ waitUntil: 'domcontentloaded' });

    await page.locator('.cand-tab[data-ct="all"]').click();
    const card = page.locator('.cand-card', { hasText: title });
    await expect(card).toBeVisible();
    await card.getByRole('button', { name: '手動追加へ', exact: true }).click();
    await expect(card.getByRole('button', { name: '✅ 手動追加済み', exact: true })).toBeVisible();

    await expect.poll(() => page.evaluate((candidateCid) => {
      return (JSON.parse(localStorage.getItem('cand_items') || '[]') || []).some((it) => it && it.cid === candidateCid);
    }, cid)).toBe(true);

    await page.locator('.cand-tab[data-ct="main"]').click();
    await expect(page.locator('.cand-card', { hasText: title })).toBeVisible();
  });

  test('画像取得がstalledになっても自動再試行を継続して画像へ回復する', async ({ page }) => {
    const cid = 'd_ref_retry_never_give_up';
    const title = '自動再試行で回復する作品';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ cid, title }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid, title,
        url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/',
        addedAt: Date.now()
      }]));
      localStorage.setItem('cand_text', JSON.stringify({
        [cid]: { memo: '画像がある作品', comment: '', twitterUrl: '', urls2: [], at: Date.now() }
      }));
    }, { cid, title });

    await page.route('**/js/candidates.js*', async (route) => {
      const response = await route.fetch();
      let body = await response.text();
      body = body.replace(
        'return n >= 3 && !!sinceMs && (nowMs - sinceMs) >= 20000;',
        'return n >= 3 && !!sinceMs && (nowMs - sinceMs) >= 50;'
      );
      body = body.replace(
        'delay: stalled ? 30000 : Math.min(12000, 3000 * Math.pow(2, Math.max(0, Number(n || 0) - 1)))',
        'delay: stalled ? 40 : Math.min(40, 20 * Math.pow(2, Math.max(0, Number(n || 0) - 1)))'
      );
      const shim = `
        (function () {
          var original = Go5Idb.getResult.bind(Go5Idb);
          var target = 'ref:${cid}';
          var image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
          Go5Idb.getResult = function (key) {
            if (key !== target) return original(key);
            window.__refRetryAttempts = (window.__refRetryAttempts || 0) + 1;
            if (window.__refRetryAttempts <= 4) return Promise.resolve({ ok: false, value: null, error: new Error('forced transient failure') });
            return Promise.resolve({ ok: true, value: { imgs: [image], img: image, memo: '画像がある作品', at: Date.now() } });
          };
        })();
      `;
      await route.fulfill({ response, body: shim + body });
    });

    await page.reload({ waitUntil: 'domcontentloaded' });
    const card = page.locator('.cand-card', { hasText: title });
    await expect(card).toBeVisible();
    await expect(card.locator('[data-refimgview="' + cid + '"]')).toBeVisible({ timeout: 4000 });
    await expect.poll(() => page.evaluate(() => window.__refRetryAttempts || 0)).toBeGreaterThanOrEqual(5);
  });

  test('circle bulk add accepts id, maker URL and product URL, then persists and syncs', async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      localStorage.setItem('fanza_worker_url', 'https://worker.invalid');
      localStorage.setItem('fanza_shared_secret', 'test-only');
      localStorage.setItem('cand_items', '[]');
      window.__bulkFlushCalls = 0;
      window.Go5Sync.syncCandidatesNow = () => { window.__bulkFlushCalls++; return Promise.resolve({ ok: true }); };
      window.Go5Sync.flushSync = window.Go5Sync.syncCandidatesNow;
      window.FanzaCore.fetchFanzaInfo = () => Promise.resolve({
        title: '作品URLから解決する作品', author: '作品URLサークル', authorId: '16180'
      });
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (url, opts) => {
        const text = String(url);
        if (text.includes('/api/fanza-maker-list')) {
          const makerId = String(JSON.parse((opts && opts.body) || '{}').makerId || '');
          return new Response(JSON.stringify({ ok: true, items: [{
            cid: 'd_bulk_' + makerId, title: '一括追加 ' + makerId,
            url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_bulk_' + makerId + '/',
            makerName: 'サークル ' + makerId, thumb: '', genres: ['コミック']
          }] }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        if (text.includes('/api/candidate-catalog')) {
          return new Response(JSON.stringify({ ok: true, imported: 1, progress: {} }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        return originalFetch(url, opts);
      };
    });

    await page.locator('#candAddOpen').click();
    const input = page.locator('#candBulkSrc');
    const add = page.locator('#candBulkAdd');
    for (const source of [
      '31415',
      'https://www.dmm.co.jp/dc/doujin/-/list/=/article=maker/id=27182/',
      'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_product_resolve/'
    ]) {
      await input.fill(source);
      await add.click();
      await expect(input).toHaveValue('');
      await expect(page.locator('#candBulkMsg')).toContainText('1件を追加しました');
      await expect(add).toBeEnabled();
      await page.waitForTimeout(550);
    }

    await expect.poll(() => page.evaluate(() => {
      return (JSON.parse(localStorage.getItem('cand_items') || '[]') || []).map((it) => it.cid).sort();
    })).toEqual(['d_bulk_16180', 'd_bulk_27182', 'd_bulk_31415']);
    await expect.poll(() => page.evaluate(() => window.__bulkFlushCalls)).toBe(3);
  });

  test('circle bulk add survives localStorage quota by confirming the IDB mirror', async ({ page }) => {
    const cid = 'd_bulk_quota_42424';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      localStorage.setItem('fanza_worker_url', 'https://worker.invalid');
      localStorage.setItem('fanza_shared_secret', 'test-only');
      localStorage.setItem('cand_items', '[]');
      window.__bulkQuotaFlushCalls = 0;
      window.Go5Sync.syncCandidatesNow = () => { window.__bulkQuotaFlushCalls++; return Promise.resolve({ ok: true }); };
      window.Go5Sync.flushSync = window.Go5Sync.syncCandidatesNow;
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (url, opts) => {
        if (String(url).includes('/api/fanza-maker-list')) {
          return new Response(JSON.stringify({ ok: true, items: [{
            cid: 'd_bulk_quota_42424', title: '容量超過でも残る一括候補',
            url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_bulk_quota_42424/',
            makerName: '容量テストサークル', thumb: ''
          }] }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        if (String(url).includes('/api/candidate-catalog')) {
          return new Response(JSON.stringify({ ok: true, imported: 1, progress: {} }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        return originalFetch(url, opts);
      };
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (this === localStorage && key === 'cand_items') throw new DOMException('forced quota', 'QuotaExceededError');
        return originalSetItem.call(this, key, value);
      };
    });

    await page.locator('#candAddOpen').click();
    await page.locator('#candBulkSrc').fill('42424');
    await page.locator('#candBulkAdd').click();
    await expect(page.locator('#candBulkMsg')).toContainText('1件を追加しました');
    await expect.poll(() => page.evaluate(async (candidateCid) => {
      const r = await Go5Idb.getResult('meta:candlist:cand_items');
      return !!(r && r.ok && Array.isArray(r.value) && r.value.some((it) => it && it.cid === candidateCid));
    }, cid)).toBe(true);
    await expect.poll(() => page.evaluate(() => window.__bulkQuotaFlushCalls)).toBe(1);
  });});
