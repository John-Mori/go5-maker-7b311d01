// @ts-check
// デプロイ後スモーク(恒久-3・2026-07-18) — 公開URLの実物を検証する「フロント版 ?ping=1」。
// 狙い: 過去に最頻だったEクラス事故(キャッシュ/版ずれ/回帰)を、スマホ実機確認の前に機械で捕まえる。
//   - INC-28/36/44: 「直したのに反映されない」= 版ずれ・配信キャッシュ
//   - INC-41/95/101: デプロイ成功でも宛先/中身が別物
// 検証は「壊れていないこと」の薄く速い層。詳細な機能テストは tests/test_*.js(単体)が持つ。
const { test, expect } = require('@playwright/test');

const EXPECTED_VERSION = process.env.EXPECTED_VERSION || ''; // 例 "357"。CIが今回pushの版を渡す。

test.describe('go5-maker 公開URL スモーク', () => {
  test('ページが開き、タイトルとタブバーが出る', async ({ page }) => {
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(String(e)));

    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/5秒動画メーカー/);

    // タブバーが描画され、最低でも主要タブが存在する
    const tabs = page.locator('.tabbar .tab');
    await expect(tabs.first()).toBeVisible();
    const count = await tabs.count();
    expect(count, 'タブ数が想定より少ない=UI破損の疑い').toBeGreaterThanOrEqual(8);

    // 読み込み時のコンソールエラーはゼロであるべき
    await page.waitForTimeout(1500);
    expect(errors, 'ロード時のコンソール/ページエラー').toEqual([]);
  });

  test('全タブが例外なく切替わる(data-tab が追従する)', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });

    const ids = await page.$$eval('.tabbar .tab', (els) => els.map((e) => e.id).filter(Boolean));
    expect(ids.length).toBeGreaterThanOrEqual(8);
    for (const id of ids) {
      await page.locator('#' + id).click();
      const dataTab = await page.evaluate(() => document.documentElement.getAttribute('data-tab'));
      expect(dataTab, `#${id} クリック後に data-tab が更新されない`).toBe(id);
    }
    expect(errors, 'タブ切替中の例外').toEqual([]);
  });

  test('配信された ?v= が全て同一(=版ずれ・部分バンプの検知)', async ({ request }) => {
    const res = await request.get('index.html');
    expect(res.ok(), 'index.html が 200 で返らない').toBeTruthy();
    const html = await res.text();
    const versions = [...html.matchAll(/\?v=(\d+)/g)].map((m) => m[1]);
    expect(versions.length, 'アセットに ?v= が1つも無い').toBeGreaterThan(0);
    const uniq = [...new Set(versions)];
    expect(uniq, `版が混在=部分バンプ or 反映途中(混在した版: ${uniq.join(',')})`).toHaveLength(1);

    // CIが今回pushの版を渡していれば、公開物がその版に到達していることまで確認(伝播の閉ループ)
    if (EXPECTED_VERSION) {
      expect(uniq[0], `公開版(${uniq[0]}) が今回push版(${EXPECTED_VERSION})と不一致=未反映`).toBe(EXPECTED_VERSION);
    }
  });

  test('動画作成タブの中核UI(写真選択)が生きている', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#tabMovie').click();
    // 写真選択の file input が存在する(録画パイプラインの入口)
    const fileInput = page.locator('#pageMovie input[type="file"]').first();
    await expect(fileInput).toHaveCount(1);
  });
});
test.describe('候補ページの画像・投稿編集', () => {
  test('PC画像モーダルの矢印は左右対称の20%位置・2倍サイズで表示する', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 8; canvas.height = 8;
      canvas.getContext('2d').fillRect(0, 0, 8, 8);
      const image = canvas.toDataURL('image/png');
      window.Go5Cand.zoomImages([image, image], 0);
    });

    const prev = page.locator('.fz-zoom-nav.prev');
    const next = page.locator('.fz-zoom-nav.next');
    await expect(prev).toBeVisible();
    await expect(next).toBeVisible();
    const boxes = await page.evaluate(() => {
      const rect = (selector) => {
        const r = document.querySelector(selector).getBoundingClientRect();
        return { left: r.left, top: r.top, width: r.width, height: r.height, cx: r.left + r.width / 2 };
      };
      return {
        viewport: innerWidth,
        prev: rect('.fz-zoom-nav.prev'),
        next: rect('.fz-zoom-nav.next'),
        prevFont: getComputedStyle(document.querySelector('.fz-zoom-nav.prev')).fontSize,
        nextFont: getComputedStyle(document.querySelector('.fz-zoom-nav.next')).fontSize
      };
    });
    expect(boxes.prev.width).toBe(92);
    expect(boxes.prev.height).toBe(92);
    expect(boxes.next.width).toBe(92);
    expect(boxes.next.height).toBe(92);
    expect(boxes.prevFont).toBe('56px');
    expect(boxes.nextFont).toBe('56px');
    expect(Math.abs(boxes.prev.cx - boxes.viewport * 0.2)).toBeLessThanOrEqual(1);
    expect(Math.abs(boxes.next.cx - boxes.viewport * 0.8)).toBeLessThanOrEqual(1);
    expect(Math.abs(boxes.prev.cx + boxes.next.cx - boxes.viewport)).toBeLessThanOrEqual(1);

    // スマホは従来どおり、邪魔にならない46px・左右端10pxを維持する。
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 8; canvas.height = 8;
      canvas.getContext('2d').fillRect(0, 0, 8, 8);
      const image = canvas.toDataURL('image/png');
      window.Go5Cand.zoomImages([image, image], 0);
    });
    const mobile = await page.evaluate(() => {
      const read = (selector) => {
        const r = document.querySelector(selector).getBoundingClientRect();
        return { left: r.left, right: innerWidth - r.right, width: r.width, height: r.height };
      };
      return { prev: read('.fz-zoom-nav.prev'), next: read('.fz-zoom-nav.next') };
    });
    expect(mobile.prev).toEqual({ left: 10, right: 334, width: 46, height: 46 });
    expect(mobile.next).toEqual({ left: 334, right: 10, width: 46, height: 46 });
  });
  test('全体読込後にIDBへ届いた候補画像も、動画生成へ移動して消えない', async ({ page }) => {
    await page.addInitScript(() => {
      window.__candidateHydratedSeen = false;
      document.addEventListener('go5-candidate-images-hydrated', () => { window.__candidateHydratedSeen = true; });
    });
    const cid = 'tw_candidate_late_idb_keep';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => window.__candidateHydratedSeen), { timeout: 10000 }).toBe(true);
    await page.evaluate(async ({ cid }) => {
      const canvas = document.createElement('canvas');
      canvas.width = 8; canvas.height = 8;
      canvas.getContext('2d').fillStyle = '#ff00ff';
      canvas.getContext('2d').fillRect(0, 0, 8, 8);
      const selectedData = canvas.toDataURL('image/png');
      localStorage.setItem('cand_items', JSON.stringify([{
        cid, title: '遅れて届いた候補画像の保持テスト', isTwitter: true,
        twitterUrl: 'https://x.com/go5_test/status/78', addedAt: Date.now()
      }]));
      // 全体ハイドレート後にIDBだけへ届いた状態を再現。candidates.jsのメモリにはまだ無い。
      await Go5Idb.set('ref:' + cid, { imgs: [selectedData], img: selectedData, comment: '保持', memo: '', at: Date.now() });
      Go5Cand.render();
    }, { cid });

    await page.locator('[data-refimg="' + cid + '"]').click();
    await expect(page.locator('#refImgPreview img')).toBeVisible();
    await page.locator('#refImgToMovie').click();
    await page.waitForURL(/index\.html/);
    await expect.poll(() => page.evaluate(() => !!window.Go5PhotoRect?.()), { timeout: 10000 }).toBe(true);
    const kept = await page.evaluate(async ({ cid }) => {
      const rec = await Go5Idb.get('ref:' + cid);
      return { count: rec && rec.imgs ? rec.imgs.length : 0, comment: rec && rec.comment };
    }, { cid });
    expect(kept.count).toBe(1);
    expect(kept.comment).toBe('保持');
  });
  test('候補画像の全体展開が遅くても、作品単位で投稿編集が開き、画像も自動表示される', async ({ page }) => {
    const cid = 'tw_codex_candidate_ui';
    // iPhoneで候補画像の全体ハイドレートが遅い状態を決定的に再現する。
    // 押した作品1件のGo5Idb.getは遅延させないため、モーダルが全体処理から独立していることも検証できる。
    await page.route('**/candidates.js*', async (route) => {
      const response = await route.fetch();
      const original = await response.text();
      const delayedHydration = [
        '(function () {',
        '  var originalEntriesByPrefixes = Go5Idb.entriesByPrefixes.bind(Go5Idb);',
        '  window.__go5HydratePrefixes = [];',
        '  Go5Idb.entriesByPrefixes = function (prefixes) {',
        '    window.__go5HydratePrefixes.push((prefixes || []).slice());',
        '    return new Promise(function (resolve, reject) {',
        '      setTimeout(function () { originalEntriesByPrefixes(prefixes).then(resolve, reject); }, 1800);',
        '    });',
        '  };',
        '}());'
      ].join('\n');
      await route.fulfill({ response, body: delayedHydration + '\n' + original });
    });

    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    const image = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
    await page.evaluate(async ({ candidateCid, imageData }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid: candidateCid,
        title: '候補UI回帰テスト',
        isTwitter: true,
        twitterUrl: 'https://x.com/test/status/1',
        addedAt: Date.now(),
      }]));
      await new Promise((resolve, reject) => {
        const req = indexedDB.open('go5store', 1);
        req.onupgradeneeded = () => {
          if (!req.result.objectStoreNames.contains('kv')) req.result.createObjectStore('kv');
        };
        req.onerror = () => reject(req.error);
        req.onsuccess = () => {
          const db = req.result;
          const tx = db.transaction('kv', 'readwrite');
          tx.objectStore('kv').put({ imgs: [imageData], comment: '同期画像', memo: '', at: Date.now() }, 'ref:' + candidateCid);
          // 候補ページには不要な大きなドラフトBlob。同じDBに在っても候補ハイドレートの範囲外であることが重要。
          tx.objectStore('kv').put(new Blob([new Uint8Array(2 * 1024 * 1024)]), 'stock_v_candidate_regression');
          tx.oncomplete = () => { db.close(); resolve(); };
          tx.onerror = () => reject(tx.error);
        };
      });
    }, { candidateCid: cid, imageData: image });
    await page.reload({ waitUntil: 'domcontentloaded' });

    const editButton = page.locator('[data-refimg="' + cid + '"]');
    await expect(editButton).toBeVisible();

    // 一度開いて閉じた追加モーダルがDOMに残っていても、画像反映を止めない。
    await page.locator('#candAddOpen').click();
    await page.locator('.add-modal .fz-close').click();
    await expect(page.locator('.fz-overlay:has(.add-modal)')).toBeHidden();

    // innerHTML差し替え後のlistener無しボタンでも親の委譲で動き、全体展開(1.8秒)を待たず直接1件を読む。
    await editButton.evaluate((el) => el.replaceWith(el.cloneNode(true)));
    await page.locator('[data-refimg="' + cid + '"]').click();
    await expect(page.locator('.refimg-modal')).toBeVisible();
    await expect(page.locator('#refImgPreview img')).toBeVisible({ timeout: 1200 });
    await expect(page.locator('[data-refimgview="' + cid + '"]')).toBeVisible({ timeout: 1200 });

    // 全体展開が後から完了したら、ページ移動や候補タブの押し直し無しでカード画像も出る。
    await page.locator('#refImgCancel').click();
    await expect(page.locator('[data-refimgview="' + cid + '"]')).toBeVisible({ timeout: 5000 });
    const prefixes = await page.evaluate(() => window.__go5HydratePrefixes);
    expect(prefixes[0]).toEqual(['ref:']);
    expect(prefixes).not.toContainEqual(['ref:', 'bsky:']);
    expect(prefixes.flat()).not.toContain('stock_v_');
  });

  test('文字情報だけ同期された時もFANZA作品URLとX URLを再読込なしで表示する', async ({ page }) => {
    const cid = 'd_candidate_sync_text';
    const workUrl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_candidate_sync_text/';
    const xUrl = 'https://x.com/go5_test/status/22';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ cid }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid, title: '文字同期回帰テスト', isTwitter: false, url: '', addedAt: Date.now()
      }]));
    }, { cid });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('[data-refimg="' + cid + '"]')).toBeVisible();
    await expect(page.locator('a.vlink-work')).toHaveCount(0);

    await page.evaluate(({ cid, workUrl, xUrl }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid, title: '文字同期回帰テスト', isTwitter: false, url: workUrl, twitterUrl: xUrl, addedAt: Date.now()
      }]));
      document.dispatchEvent(new CustomEvent('go5-synced', { detail: { pulled: 0, pulledImg: 0, pulledCand: 1 } }));
    }, { cid, workUrl, xUrl });

    await expect(page.locator('a.vlink-work')).toHaveAttribute('href', workUrl);
    await expect(page.locator('a.vlink-sns')).toHaveAttribute('href', xUrl);
  });

  test('画像なしの文字保存は停止したIndexedDBを待たず即時完了する', async ({ page }) => {
    const cid = 'tw_candidate_text_only_save';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ cid }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid, title: '文字だけ保存回帰テスト', isTwitter: true, twitterUrl: '', addedAt: Date.now()
      }]));
    }, { cid });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('[data-refimg="' + cid + '"]').click();
    await expect(page.locator('.refimg-modal')).toBeVisible();
    await page.evaluate(() => {
      window.__go5IdbSetCalls = 0;
      Go5Idb.set = function () {
        window.__go5IdbSetCalls++;
        return new Promise(function () {}); // iOSでIDBが停止した状態を再現
      };
    });
    await page.locator('#refImgTwitter').fill('https://x.com/go5_test/status/33');
    await page.locator('#refImgComment').fill('文字だけなら待たずに保存');
    await page.locator('#refImgSave').click();

    await expect(page.locator('#refImgMsg')).toHaveText('保存しました', { timeout: 1500 });
    const saved = await page.evaluate(({ cid }) => ({
      text: JSON.parse(localStorage.getItem('cand_text') || '{}')[cid],
      idbSetCalls: window.__go5IdbSetCalls
    }), { cid });
    expect(saved.text.comment).toBe('文字だけなら待たずに保存');
    expect(saved.text.twitterUrl).toBe('https://x.com/go5_test/status/33');
    expect(saved.idbSetCalls).toBe(1); // cand_text durability mirror is best-effort and must not block UI
  });

  test('画像保存失敗時は入力を残し保存ボタンを再操作できる', async ({ page }) => {
    const cid = 'tw_candidate_image_save_failure';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ cid }) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid, title: '画像保存失敗回帰テスト', isTwitter: true, twitterUrl: '', addedAt: Date.now()
      }]));
    }, { cid });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('[data-refimg="' + cid + '"]').click();
    await expect(page.locator('.refimg-modal')).toBeVisible();
    await page.locator('#refImgFile').setInputFiles({
      name: 'tiny.png',
      mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLzWQAAAABJRU5ErkJggg==', 'base64')
    });
    await expect(page.locator('#refImgPreview img')).toBeVisible();
    await page.evaluate(() => {
      // 現仕様はIDB失敗時にlocalStorageへ画像を退避できれば成功扱い。真の保存失敗を作るため両方を止める。
      Go5Idb.set = function () { return Promise.reject(new Error('forced-save-fail')); };
      const realSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (String(key).indexOf('cand_refimg__') === 0) throw new DOMException('forced-fallback-fail', 'QuotaExceededError');
        return realSetItem.call(this, key, value);
      };
    });
    await page.locator('#refImgTwitter').fill('https://x.com/go5_test/status/44');
    await page.locator('#refImgSave').click();

    await expect(page.locator('.refimg-modal')).toBeVisible();
    await expect(page.locator('#refImgMsg')).toContainText('入力は残っています');
    await expect(page.locator('#refImgTwitter')).toHaveValue('https://x.com/go5_test/status/44');
    await expect(page.locator('#refImgSave')).toBeEnabled();
  });

  test('動画生成へ移動すると容量超過時も選択画像を復元し、前作品の画像を残さない', async ({ page }) => {
    const cid = 'tw_candidate_to_movie_image';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    const oldImage = await page.evaluate(async ({ cid }) => {
      const makeImage = (color) => {
        const canvas = document.createElement('canvas');
        canvas.width = 8; canvas.height = 8;
        canvas.getContext('2d').fillStyle = color;
        canvas.getContext('2d').fillRect(0, 0, 8, 8);
        return canvas.toDataURL('image/png');
      };
      const oldData = makeImage('#ff0000');
      const selectedData = makeImage('#00ff00');
      localStorage.setItem('movie_photo_cache', oldData);
      localStorage.setItem('cand_items', JSON.stringify([{
        cid, title: '候補から動画画像引継ぎ回帰テスト', isTwitter: true,
        twitterUrl: 'https://x.com/go5_test/status/55', addedAt: Date.now()
      }]));
      await Go5Idb.set('ref:' + cid, { imgs: [selectedData], img: selectedData, comment: '', memo: '', at: Date.now() });
      return oldData;
    }, { cid });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('[data-refimg="' + cid + '"]').click();
    await expect(page.locator('#refImgPreview img')).toBeVisible();

    // sessionStorage容量超過を強制し、軽いcid参照から同じ画像を復元できることを確認する。
    await page.evaluate(() => {
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) {
        if (this === sessionStorage && key === 'cand_to_movie_pending' && String(value).includes('"imgDataUrl":"data:image')) {
          throw new DOMException('forced quota', 'QuotaExceededError');
        }
        return originalSetItem.call(this, key, value);
      };
    });
    await page.locator('#refImgToMovie').click();
    await page.waitForURL(/index\.html/);

    await expect.poll(() => page.locator('#photo').evaluate((el) => el.files.length), { timeout: 10000 }).toBe(1);
    expect(await page.locator('#photo').evaluate((el) => el.files[0] && el.files[0].name)).toBe('candidate.jpg');
    await expect.poll(() => page.evaluate((oldData) => localStorage.getItem('movie_photo_cache') !== oldData, oldImage)).toBe(true);
    expect(await page.evaluate(() => sessionStorage.getItem('cand_to_movie_pending'))).toBeNull();
  });

  test('DataTransferが使えないiPhoneでも候補画像を前景へ反映する', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(window, 'DataTransfer', { configurable: true, writable: true, value: undefined });
    });
    const cid = 'tw_candidate_to_movie_ios_fallback';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(async ({ cid }) => {
      const canvas = document.createElement('canvas');
      canvas.width = 8; canvas.height = 8;
      canvas.getContext('2d').fillStyle = '#00ff00';
      canvas.getContext('2d').fillRect(0, 0, 8, 8);
      const selectedData = canvas.toDataURL('image/png');
      localStorage.setItem('cand_items', JSON.stringify([{
        cid, title: 'iPhone候補画像引継ぎ回帰テスト', isTwitter: true,
        twitterUrl: 'https://x.com/go5_test/status/56', addedAt: Date.now()
      }]));
      await Go5Idb.set('ref:' + cid, { imgs: [selectedData], img: selectedData, comment: '', memo: '', at: Date.now() });
    }, { cid });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('[data-refimg="' + cid + '"]').click();
    await expect(page.locator('#refImgPreview img')).toBeVisible();
    await page.locator('#refImgToMovie').click();
    await page.waitForURL(/index\.html/);

    await expect.poll(() => page.evaluate(() => !!window.Go5PhotoRect?.()), { timeout: 10000 }).toBe(true);
    const state = await page.evaluate(() => ({
      inputFiles: document.getElementById('photo').files.length,
      foregroundName: window.Go5ForegroundFile?.()?.name || '',
      label: document.getElementById('photoName').textContent
    }));
    expect(state.inputFiles).toBe(0);
    expect(state.foregroundName).toBe('candidate.jpg');
    expect(state.label).not.toBe('未選択');
  });
});
test.describe('動画作成中のチャンネル切替', () => {
  test('月詠みから宵桜へ切り替えても作品URLとセールラベルを維持する', async ({ page }) => {
    const workUrl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_sale_switch_test/';
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ workUrl }) => {
      localStorage.setItem('current_account', 'acc1');
      localStorage.removeItem('bsky_work_url__acc2');
      sessionStorage.setItem('cand_to_movie_pending', JSON.stringify({
        it: { cid: 'd_sale_switch_test', title: 'セール作品の切替テスト', author: 'テスト作者', listPrice: 1000, price: 500, discountPct: 50 },
        imgDataUrl: '', comment: 'セール作品', workUrl, imageCid: '', imageIndex: 0
      }));
    }, { workUrl });
    await page.reload({ waitUntil: 'domcontentloaded' });

    await expect(page.locator('#movieWorkUrl')).toHaveValue(workUrl);
    await expect(page.locator('#promoPosRow')).toBeVisible();
    await page.locator('#acctBtn2').click();
    await expect(page.locator('#acctBtn2')).toHaveClass(/active/);
    await expect(page.locator('#movieWorkUrl')).toHaveValue(workUrl);
    await expect(page.locator('#promoPosRow')).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('bsky_work_url__acc2'))).toBe(workUrl);
  });
});
test.describe('ドラフト軽量ページ', () => {
  test('iPhone幅で重い動画DOMを持たず、ドラフト投稿モードまで開ける', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/ドラフト.*5秒動画メーカー/);

    await page.evaluate(() => {
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('go5_stock_meta', JSON.stringify([{
        id: 'stk_e2e_light', ts: Date.now(), addedAt: Date.now(), account: 'acc1',
        label: 'ドラフト軽量ページ回帰', title: 'ドラフト軽量ページ回帰', author: 'test',
        bskyText: 'テスト本文', affiliateUrl: '', workUrl: '', videoName: 'test.mp4', videoId: 'vid_e2e_light', attrs: {}
      }]));
    });
    await page.reload({ waitUntil: 'domcontentloaded' });

    await expect(page.locator('[data-item-id="stk_e2e_light"]')).toBeVisible();
    const metrics = await page.evaluate(() => ({
      canvas: document.querySelectorAll('canvas').length,
      video: document.querySelectorAll('video').length,
      nodes: document.querySelectorAll('*').length,
      overflowX: document.documentElement.scrollWidth > window.innerWidth,
    }));
    expect(metrics.canvas).toBe(0);
    expect(metrics.video).toBe(0);
    expect(metrics.nodes, '専用ページへ本体DOMが混入している').toBeLessThan(300);
    expect(metrics.overflowX, 'iPhone幅で横にはみ出している').toBeFalsy();

    await page.locator('.stk-mode[data-id="stk_e2e_light"]').click();
    await expect(page.locator('#draftPostModal')).toBeVisible();
    await expect(page.locator('#draftXText')).toHaveValue('テスト本文');
    expect(errors, '軽量ドラフトのロード/投稿モードで例外').toEqual([]);
  });

  test('ドラフト投稿モードの即時投稿完了が投稿履歴へ実保存される', async ({ page }) => {
    const draftId = 'stk_e2e_complete_now';
    const videoId = 'acc1-20260812-1200-e2e1';
    const ytUrl = 'https://www.youtube.com/shorts/AbCdEfGhI12';
    await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ draftId, videoId }) => {
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('verify_manual__acc1', '[]');
      localStorage.setItem('short_hist__acc1', '[]');
      localStorage.setItem('go5_stock_archive', '[]');
      localStorage.setItem('go5_stock_meta', JSON.stringify([{
        id: draftId, ts: Date.now(), addedAt: Date.now(), account: 'acc1',
        label: '即時投稿完了の回帰', title: '即時投稿完了の回帰', author: 'test',
        bskyText: 'テスト本文', affiliateUrl: '', workUrl: '', videoName: 'test.mp4',
        videoId, attrs: {}
      }]));

    }, { draftId, videoId });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.evaluate(() => {
      // Drive保存の唯一の起点はドラフト作成確定時。投稿完了から再起動しないことをこの実物フローで固定する。
      window.__postCompleteDriveCalls = 0;
      if (window.Go5Drive) {
        Go5Drive.upload = () => { window.__postCompleteDriveCalls += 1; };
        Go5Drive.queueSave = () => { window.__postCompleteDriveCalls += 1; return Promise.resolve({ ok: true }); };
      }
    });    await expect.poll(() => page.evaluate(() => (
      typeof window.Go5History?.addCompletedPost
    ))).toBe('function');

    await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
    await expect(page.locator('#draftPostModal')).toBeVisible();
    await expect(page.locator('#draftPubNow')).toBeChecked();
    await page.locator('#draftYtUrl').fill(ytUrl);
    page.once('dialog', (dialog) => dialog.accept());
    await page.locator('#draftModalComplete').click();

    await expect.poll(async () => page.evaluate(({ draftId, videoId, ytUrl }) => {
      const hist = JSON.parse(localStorage.getItem('verify_manual__acc1') || '[]');
      const drafts = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      const archive = JSON.parse(localStorage.getItem('go5_stock_archive') || '[]');
      return {
        history: hist.some((x) => x.videoId === videoId && x.ytUrl === ytUrl),
        draftRemoved: !drafts.some((x) => x.id === draftId),
        archived: archive.some((x) => x.id === draftId),
      };
    }, { draftId, videoId, ytUrl })).toEqual({ history: true, draftRemoved: true, archived: true });
    expect(await page.evaluate(() => window.__postCompleteDriveCalls)).toBe(0);

    // ★投稿履歴は軽量ページ化で専用ページ StockLists.html へ分離済(Stock.html #tabVerify=data-nav)。
    //   旧アサートは index.html を期待していて 24h 全pushで赤=スモーク門が死んでいた(検証の妥当性側の穴)。
    await page.locator('#tabVerify').click();
    await expect(page).toHaveURL(/\/StockLists\.html$/);
    await expect(page.locator('.vrow-title').filter({ hasText: '即時投稿完了の回帰' })).toHaveCount(1);
  });

  test('history cap 200 keeps the newest completed draft', async ({ page }) => {
    const draftId = 'stk_e2e_complete_at_cap';
    const videoId = 'acc1-20260813-1200-cap1';
    const ytUrl = 'https://www.youtube.com/shorts/ZyXwVuTsR98';
    await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ draftId, videoId }) => {
      const fullHistory = Array.from({ length: 200 }, (_, i) => ({
        manual: true,
        id: 'm:old-' + i,
        ts: Date.now() - (i + 1) * 60000,
        title: 'old post ' + i,
        videoId: 'acc1-20260101-0000-old' + i
      }));
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('verify_manual__acc1', JSON.stringify(fullHistory));
      localStorage.setItem('short_hist__acc1', '[]');
      localStorage.setItem('go5_stock_archive', '[]');
      localStorage.setItem('go5_stock_meta', JSON.stringify([{
        id: draftId, ts: Date.now(), addedAt: Date.now(), account: 'acc1',
        label: 'history cap latest post', title: 'history cap latest post', author: 'test',
        bskyText: 'test body', affiliateUrl: '', workUrl: '', videoName: 'test.mp4',
        videoId, attrs: {}
      }]));
    }, { draftId, videoId });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect.poll(() => page.evaluate(() => typeof window.Go5History?.addCompletedPost)).toBe('function');

    await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
    await expect(page.locator('#draftPostModal')).toBeVisible();
    await page.locator('#draftYtUrl').fill(ytUrl);
    page.once('dialog', (dialog) => dialog.accept());
    await page.locator('#draftModalComplete').click();

    await expect.poll(async () => page.evaluate(({ draftId, videoId, ytUrl }) => {
      const hist = JSON.parse(localStorage.getItem('verify_manual__acc1') || '[]');
      const drafts = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      return {
        count: hist.length,
        newestPersisted: hist.some((x) => x.videoId === videoId && x.ytUrl === ytUrl),
        draftRemoved: !drafts.some((x) => x.id === draftId)
      };
    }, { draftId, videoId, ytUrl })).toEqual({ count: 200, newestPersisted: true, draftRemoved: true });
  });

  test('投稿履歴APIが未準備ならドラフトを消さず再試行できる', async ({ page }) => {
    const draftId = 'stk_e2e_complete_failclosed';
    const videoId = 'acc1-20260812-1201-e2e2';
    await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate(({ draftId, videoId }) => {
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('verify_manual__acc1', '[]');
      localStorage.setItem('short_hist__acc1', '[]');
      localStorage.setItem('go5_stock_archive', '[]');
      localStorage.setItem('go5_stock_meta', JSON.stringify([{
        id: draftId, ts: Date.now(), addedAt: Date.now(), account: 'acc1',
        label: '履歴未準備fail-closed', title: '履歴未準備fail-closed', author: 'test',
        bskyText: 'テスト本文', affiliateUrl: '', workUrl: '', videoName: 'test.mp4',
        videoId, attrs: {}
      }]));
    }, { draftId, videoId });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.locator('.stk-mode[data-id="' + draftId + '"]').click();
    await expect(page.locator('#draftPostModal')).toBeVisible();
    await page.evaluate(() => { window.Go5History = null; });

    const messages = [];
    page.on('dialog', async (dialog) => {
      if (dialog.type() === 'confirm') await dialog.accept();
      else { messages.push(dialog.message()); await dialog.accept(); }
    });
    await page.locator('#draftModalComplete').click();

    await expect.poll(async () => page.evaluate(({ draftId, videoId }) => {
      const hist = JSON.parse(localStorage.getItem('verify_manual__acc1') || '[]');
      const drafts = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      const archive = JSON.parse(localStorage.getItem('go5_stock_archive') || '[]');
      return {
        history: hist.some((x) => x.videoId === videoId),
        draftKept: drafts.some((x) => x.id === draftId),
        archived: archive.some((x) => x.id === draftId),
      };
    }, { draftId, videoId })).toEqual({ history: false, draftKept: true, archived: false });
    await expect(page.locator('#draftPostModal')).toBeVisible();
    expect(messages.join('\n')).toContain('投稿履歴の登録機能を読み込めませんでした');
  });

  test('本体のドラフトボタンは専用ページへ遷移する', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#tabStock').click();
    await expect(page).toHaveURL(/\/Stock\.html$/);
  });
});

test.describe('ドラフト投稿モードの短縮URL置換', () => {
  for (const accountCase of [
    { account: 'acc1', domain: '5mgl.com', suffix: 'tsukuyomi' },
    { account: 'acc2', domain: 'yoz2.com', suffix: 'yoizakura' },
  ]) {
    test('保存済みX本文の作品・セールURLを' + accountCase.domain + 'へ置換する', async ({ page }) => {
      const draftId = 'stk_e2e_short_' + accountCase.suffix;
      const workCode = 'work-' + accountCase.suffix;
      const saleCode = 'sale-' + accountCase.suffix;
      const workUrl = 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_short/';
      const saleUrl = 'https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=mens/';
      const placeholderText = [
        '続きが気になっちゃう一冊、みつけた📚', '', '(商品紹介短縮URL)', '',
        '🔥 大幅割引セール中の同人祭ページ 🔥', '(セール紹介短縮用URL)',
      ].join('\n');
      await page.route('https://' + accountCase.domain + '/api/shorten', async (route) => {
        let body = decodeURIComponent((route.request().postData() || '').replace(/^url=/, ''));
        try { body = decodeURIComponent(body); } catch (_) {}
        const code = body.includes('/campaign=') ? saleCode : workCode;
        await route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ short: 'https://' + accountCase.domain + '/' + code }),
        });
      });
      await page.addInitScript(({ account }) => {
        localStorage.setItem('current_account', account);
      }, { account: accountCase.account });
      await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
      await page.evaluate(({ account, draftId, workUrl, saleUrl, placeholderText }) => {
        localStorage.setItem('current_account', account);
        localStorage.setItem('fanza_af_id', 'e2e-affiliate-001');
        localStorage.setItem('disc_urls_seeded__' + account, '1');
        localStorage.setItem('bsky_discount_urls__' + account, JSON.stringify([{
          id: 'sale-' + account, name: 'E2Eセール', url: saleUrl, at: Date.now(),
        }]));
        localStorage.setItem('bsky_discount_selected__' + account, 'sale-' + account);
        localStorage.removeItem('bsky_discount_link_cache');
        localStorage.setItem('go5_stock_meta', JSON.stringify([{
          id: draftId, ts: Date.now(), addedAt: Date.now(), account,
          label: '短縮URL置換回帰', title: '短縮URL置換回帰', author: 'test',
          bskyText: placeholderText, affiliateUrl: '', workUrl, videoName: 'test.mp4',
          videoId: account + '-20260813-1835-short', attrs: {},
        }]));
        localStorage.setItem('go5_draft_post_' + draftId, JSON.stringify({ xText: placeholderText }));
      }, { account: accountCase.account, draftId, workUrl, saleUrl, placeholderText });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.locator('.stk-mode[data-id="' + draftId + '"]').click();
      await expect(page.locator('#draftPostModal')).toBeVisible();
      const diagnostics = await page.evaluate(() => ({
        account: localStorage.getItem('current_account'),
        af: localStorage.getItem('fanza_af_id'),
        go5MakeShort: typeof window.Go5MakeShort,
        saleFill: typeof window.__go5FillSalePlaceholderInText,
        workPH: window.BlueskyCore && window.BlueskyCore.hasWorkLinkPlaceholder('(商品紹介短縮URL)'),
        salePH: window.BlueskyCore && window.BlueskyCore.hasSaleLinkPlaceholder('(セール紹介短縮用URL)'),
        discUrls: localStorage.getItem('bsky_discount_urls__' + localStorage.getItem('current_account')),
      }));
      expect(diagnostics, JSON.stringify(diagnostics)).toMatchObject({
        account: accountCase.account, af: 'e2e-affiliate-001',
        go5MakeShort: 'function', saleFill: 'function', workPH: true, salePH: true,
      });
      await expect.poll(async () => {
        const value = await page.locator('#draftXText').inputValue();
        return {
          workPlaceholder: value.includes('(商品紹介短縮URL)'),
          salePlaceholder: value.includes('(セール紹介短縮用URL)'),
          domainCount: value.split('https://' + accountCase.domain + '/').length - 1,
        };
      }).toEqual({ workPlaceholder: false, salePlaceholder: false, domainCount: 2 });
      const replacedText = await page.locator('#draftXText').inputValue();
      expect(replacedText).toContain('https://' + accountCase.domain + '/' + workCode);
      expect(replacedText).toContain('https://' + accountCase.domain + '/' + saleCode);

      const persistedFinal = await page.evaluate((id) => {
        const saved = JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}');
        return saved.xText || '';
      }, draftId);
      expect(persistedFinal).not.toContain('(商品紹介短縮URL)');
      expect(persistedFinal).not.toContain('(セール紹介短縮用URL)');
      expect(persistedFinal.split('https://' + accountCase.domain + '/').length - 1).toBe(2);
    });
  }
});
