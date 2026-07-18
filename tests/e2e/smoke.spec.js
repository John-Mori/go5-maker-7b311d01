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
