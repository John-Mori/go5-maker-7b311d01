// @ts-check
// 🔥セール案内URLは、名前とURLを入れて欄を離れただけで一覧へ○付きで出ること
// (Chami msg 1561054969539465236「セールにラジオボタンつけて。出てない」=iPhoneで＋追加のタップが空振りし入力欄に残った)。
const { test, expect } = require('@playwright/test');

test('名前とURLを入れて欄を離れると、＋追加を押さなくても一覧に○付きで出る', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem('disc_urls_seeded__acc3', '1'); // 既定のセールページ無し=Chamiの癒やし倉庫と同じ空の一覧から
  });
  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.locator('#tabPost').click();
  await page.locator('#discUrlsDetails > summary').click();
  await expect(page.locator('#discUrlList')).toContainText('未登録');
  await page.locator('#discUrlName').fill('秋セール');
  await page.locator('#discUrlInput').fill('https://xdgh3.com/odXX');
  await page.locator('#discUrlInput').blur();
  const row = page.locator('#discUrlList label', { hasText: '秋セール' });
  await expect(row.locator('input[type=radio]')).toBeChecked();
  await expect(page.locator('#discUrlInput')).toHaveValue('');
  // 続けて＋追加を押しても二重に入らない
  await page.locator('#discUrlAddBtn').click();
  await expect(page.locator('#discUrlList label')).toHaveCount(1);
  // 名前だけ入れて離れた時は勝手に足さない
  await page.locator('#discUrlName').fill('冬セール');
  await page.locator('#discUrlName').blur();
  await expect(page.locator('#discUrlList label')).toHaveCount(1);
});

// 同じセールが2件被っていたら1件に畳み、同じURLを入れ直しても増えない
// (Chami msg 1561077224172429414「セールが同じやつ二つ被ってるから片方消して」)。
test('同じURLのセールが2件あると開いた時に1件へ畳まれ、捨てた側へ削除墓標が立つ・同じURLは追加し直しても増えない', async ({ page }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem('dup_seeded')) return;
    sessionStorage.setItem('dup_seeded', '1');
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem('disc_urls_seeded__acc3', '1');
    localStorage.setItem('bsky_discount_urls__acc3', JSON.stringify([
      { id: 'dnew', name: '秋セール', url: 'https://xdgh3.com/odXX', at: 1760700000000 },
      { id: 'dold', name: '秋セール', url: 'https://xdgh3.com/odXX', at: 1760600000000 },
      { id: 'dwin', name: '冬セール', url: 'https://xdgh3.com/winter', at: 1760500000000 }
    ]));
    localStorage.setItem('bsky_discount_selected__acc3', 'dnew');
  });
  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.locator('#tabPost').click();
  await page.locator('#discUrlsDetails > summary').click();
  await expect(page.locator('#discUrlList label')).toHaveCount(2);
  await expect(page.locator('#discUrlList label', { hasText: '秋セール' }).locator('input[type=radio]')).toBeChecked();
  const st = await page.evaluate(() => ({
    urls: JSON.parse(localStorage.getItem('bsky_discount_urls__acc3')).map((e) => e.id),
    del: Object.keys(JSON.parse(localStorage.getItem('bsky_discount_del__acc3') || '{}')),
    sel: localStorage.getItem('bsky_discount_selected__acc3'),
  }));
  expect(st.urls).toEqual(['dold', 'dwin']);
  expect(st.del).toEqual(['dnew']);
  expect(st.sel).toBe('dold');
  // 同じURLをもう一度入れても増えず、既存の方が選ばれる
  await page.locator('#discUrlName').fill('秋セール2');
  await page.locator('#discUrlInput').fill('https://xdgh3.com/odXX/');
  await page.locator('#discUrlAddBtn').click();
  await expect(page.locator('#discUrlList label')).toHaveCount(2);
  await expect(page.locator('#discUrlHint')).toContainText('登録済み');
  // 再読込しても2件のまま
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('#tabPost').click();
  await page.locator('#discUrlsDetails > summary').click();
  await expect(page.locator('#discUrlList label')).toHaveCount(2);
});
