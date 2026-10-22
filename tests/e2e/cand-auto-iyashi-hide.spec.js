// @ts-check
// 自動追加タブで「癒し非表示」をONにすると全件消える件の再発防止(Chami 2026-10-23 03:49
// 「自動追加タブでは癒やし非表示にしたら全部表示されなくなる」)。
// 自動追加はXの元ポスト由来で画像0〜1枚が普通。癒し非表示に含まれる「画像2枚未満は隠す」を自動追加に掛けていた。
// 手動追加では従来どおり画像1枚の作品を隠す(投稿できない作品を隠すという本来の意図は残す)。
const { test, expect } = require('@playwright/test');

const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

test('自動追加タブは癒し非表示ONでも画像1枚の作品を隠さない(手動追加は隠す)', async ({ page }) => {
  await page.route('https://sync.e2e.invalid/**', (route) => route.abort());
  await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate(({ PNG }) => {
    localStorage.clear();
    const item = (cid, title) => ({ cid, title, url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/', addedAt: Date.now(), source: 'grok_fanza' });
    const auto = [item('d_e2e_auto1', '自動1'), item('d_e2e_auto2', '自動2'), item('d_e2e_auto3', '自動3')];
    localStorage.setItem('cand_items__auto', JSON.stringify(auto));
    localStorage.setItem('cand_items', JSON.stringify([{ cid: 'd_e2e_main1', title: '手動1枚', url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_main1/', addedAt: Date.now() }]));
    for (const cid of ['d_e2e_auto1', 'd_e2e_auto2', 'd_e2e_auto3', 'd_e2e_main1']) {
      localStorage.setItem('cand_refimg__' + cid, JSON.stringify({ imgs: [PNG] })); // 元ポストの写真1枚=Grok取り込みの典型
    }
    localStorage.setItem('cand_hide_posted', JSON.stringify({ acc3: true }));
    localStorage.setItem('cand_active_tab', 'auto');
    sessionStorage.setItem('cand_active_tab', 'auto');
  }, { PNG });
  await page.reload({ waitUntil: 'domcontentloaded' });

  await page.locator('.cand-tab[data-ct="auto"]').click();
  await expect(page.locator('.cand-hide-grid [data-hide-ch="acc3"][data-hide-val="1"]')).toHaveClass(/active/);
  await expect(page.locator('#candList .cand-card')).toHaveCount(3);

  await page.locator('.cand-tab[data-ct="main"]').click();
  await expect(page.locator('#candList')).toContainText('現在の表示条件に合う候補がありません');
  await expect(page.locator('#candList .cand-card')).toHaveCount(0);
});
