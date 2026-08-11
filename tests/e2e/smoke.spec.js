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
  test('閉じた追加モーダル後も同期画像が出て、DOM差し替え後も投稿編集が開く', async ({ page }) => {
    const cid = 'tw_codex_candidate_ui';
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate((candidateCid) => {
      localStorage.setItem('cand_items', JSON.stringify([{
        cid: candidateCid,
        title: '候補UI回帰テスト',
        isTwitter: true,
        twitterUrl: 'https://x.com/test/status/1',
        addedAt: Date.now(),
      }]));
    }, cid);
    await page.reload({ waitUntil: 'domcontentloaded' });

    const editButton = page.locator('[data-refimg="' + cid + '"]');
    await expect(editButton).toBeVisible();

    // 一度開いて閉じると .add-modal 自体はDOMに残る。この状態でも背景同期を止めてはいけない。
    await page.locator('#candAddOpen').click();
    await page.locator('.add-modal .fz-close').click();
    await expect(page.locator('.fz-overlay:has(.add-modal)')).toBeHidden();

    const image = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
    await page.evaluate(async ({ candidateCid, imageData }) => {
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
          tx.oncomplete = () => { db.close(); resolve(); };
          tx.onerror = () => reject(tx.error);
        };
      });
      document.dispatchEvent(new CustomEvent('go5-synced', { detail: { pulledImg: 1 } }));
    }, { candidateCid: cid, imageData: image });

    await expect(page.locator('[data-refimgview="' + cid + '"]')).toBeVisible();

    // 非同期描画によるinnerHTML差し替えを模擬。複製ボタンには個別listenerが無くても親の委譲で動く。
    await editButton.evaluate((el) => el.replaceWith(el.cloneNode(true)));
    await page.locator('[data-refimg="' + cid + '"]').click();
    await expect(page.locator('.refimg-modal')).toBeVisible();
    await expect(page.locator('#refImgPreview img')).toBeVisible();
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

  test('本体のドラフトボタンは専用ページへ遷移する', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#tabStock').click();
    await expect(page).toHaveURL(/\/Stock\.html$/);
  });
});
