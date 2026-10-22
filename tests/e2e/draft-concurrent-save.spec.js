// @ts-check
// 保存中のドラフトAがある間に新しいドラフトBを作ると、Aが一覧から消える件の再発防止(Chami 2026-10-22 20:10
// 「ドラフトで保存してる最中に新たなデータをドラフトしたら前のドラフト中のデータがドラフト欄から消えた」)。
// 旧実装は保存窓が boolean 1本で、Bが先に着地すると窓が閉じ、次のドラフトタブ操作が Stock.html へ破壊遷移して
// メモリ上にしか無いAの pending と動画blobを殺していた。
const { test, expect } = require('@playwright/test');

test('保存中のドラフトAは、後から作ったBが先に着地してもタブ操作で消えない', async ({ page }) => {
  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!(window.Go5Stock && window.Go5VideoIntegrity && window.Go5Idb));
  await page.evaluate(() => {
    localStorage.removeItem('go5_stock_meta');
    localStorage.removeItem('go5_stock_archive');
    if (window.Go5Sync) Go5Sync.configured = () => false;
    // 最初の動画書込み(=A)だけ、テストが放すまで着地させない(iPhoneの遅い保存の再現)。
    const realSet = Go5Idb.set.bind(Go5Idb);
    let videoWrites = 0;
    let releaseA;
    const gateA = new Promise((r) => { releaseA = r; });
    window.__releaseA = () => releaseA();
    Go5Idb.set = (key, value) => {
      if (String(key).startsWith('stock_v_') && ++videoWrites === 1) return gateA.then(() => realSet(key, value));
      return realSet(key, value);
    };
    const fire = (title) => document.dispatchEvent(new CustomEvent('video-created', {
      detail: {
        draft: true, title, name: title + '.mp4', account: 'acc1',
        blob: new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' })
      }
    }));
    fire('先に作ったA');
    fire('後に作ったB');
  });

  // Bだけ先に着地する。
  await page.waitForFunction(() => {
    const list = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
    return list.some((m) => m.title === '後に作ったB' && m.videoReadyAt);
  }, { timeout: 10000 });

  // 君の操作の再現: 動画作成タブへ戻り、もう一度ドラフトタブを押す。
  await page.evaluate(() => document.getElementById('tabMovie').click());
  await page.evaluate(() => document.getElementById('tabStock').click());
  await page.waitForTimeout(1500);
  expect(page.url()).toContain('index.html');
  await expect(page.locator('#pageStock')).toBeVisible();

  // Aの保存が終われば、AもBも一覧に残る。
  await page.evaluate(() => window.__releaseA());
  await page.waitForFunction(() => {
    const list = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
    return list.some((m) => m.title === '先に作ったA' && m.videoReadyAt);
  }, { timeout: 10000 });
  const titles = await page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]').map((m) => m.title));
  expect(titles).toEqual(expect.arrayContaining(['先に作ったA', '後に作ったB']));
  // 両方が着地したら保存窓は閉じる(以後のドラフトタブは通常どおり専用ページへ)。
  expect(await page.evaluate(() => window.__go5SaveInFlight)).toBe(false);
});
