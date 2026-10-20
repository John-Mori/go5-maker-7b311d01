// @ts-check
// 候補検索は2文字以上で絞り込む(Chami 2026-10-21「2文字以上で結果が出るで問題ない」)。
//   1文字=絞り込まない(一覧そのまま)/2文字=一致だけ/クリア=元の一覧に戻る。入力要素は作り直さない。
const { test, expect } = require('@playwright/test');

const N = 12;
function seedItems_() {
  const now = Date.now();
  const items = [];
  for (let i = 0; i < N; i++) {
    const cid = 'd_min2_' + i;
    items.push({
      cid,
      title: (i < 3 ? '桜の作品' : '梅の作品') + i,
      author: 'サークル' + (i % 2),
      url: 'https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=' + cid + '/',
      addedAt: now - i
    });
  }
  return items;
}

test.describe('candidate search requires 2+ characters', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('KouhoLists.html', { waitUntil: 'domcontentloaded' });
    await page.evaluate((items) => {
      localStorage.setItem('current_account', 'acc1');
      localStorage.setItem('cand_items', JSON.stringify(items));
      localStorage.removeItem('cand_hidden__main');
      const text = {};
      items.forEach((it, i) => { text[it.cid] = { comment: 'コメント' + i, memo: (i % 4 === 0 ? 'ほしい' : 'みおくり'), twitterUrl: '', urls2: [], at: Date.now() }; });
      localStorage.setItem('cand_text', JSON.stringify(text));
    }, seedItems_());
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('#candCardList .cand-card')).toHaveCount(N);
    // 起動直後は画像ハイドレート完了の背景 render()(bgRenderNow_)が一覧の外枠を一度作り直す(改修前から同じ)。
    //   その後に検索欄を触る=実際の操作と同じ順にして、入力要素の同一性を検索処理だけで検証する。
    await page.waitForTimeout(1500);
  });

  test('1 char does not filter, 2 chars filters, clear restores (work search)', async ({ page }) => {
    const input = page.locator('#candWorkSearch');
    const cards = page.locator('#candCardList .cand-card');
    const result = page.locator('#candWorkSearchResult');
    await input.click();
    const elBefore = await input.evaluate((el) => { window.__min2El = el; return true; });
    expect(elBefore).toBe(true);

    // 1文字: 絞り込まない。デバウンス(250ms)を越えて待っても件数は変わらない。
    await input.type('桜');
    await page.waitForTimeout(700);
    await expect(cards).toHaveCount(N);
    await expect(result).toHaveText('2文字以上で絞り込みます');

    // 2文字: 一致した3件だけ。
    await input.type('の');
    await expect(cards).toHaveCount(3);
    await expect(result).toContainText('3件表示 / ' + N + '件中');
    await expect(page.locator('#candCardList .cand-card', { hasText: '梅の作品' })).toHaveCount(0);

    // 入力要素は同じまま・フォーカスも残る(IME/キャレット保護)。
    const same = await page.evaluate(() => document.getElementById('candWorkSearch') === window.__min2El && document.activeElement === window.__min2El);
    expect(same).toBe(true);

    // 1文字へ戻す: 全件へ戻る。
    await input.press('Backspace');
    await expect(cards).toHaveCount(N);

    // 2文字で絞ってからクリア: 元の一覧に戻る。
    await input.fill('梅の');
    await expect(cards).toHaveCount(N - 3);
    await page.locator('#candWorkSearchClear').click();
    await expect(input).toHaveValue('');
    await expect(cards).toHaveCount(N);
    await expect(result).toHaveText('');
  });

  test('Enter applies immediately and whitespace-only counts as empty', async ({ page }) => {
    const input = page.locator('#candWorkSearch');
    const cards = page.locator('#candCardList .cand-card');
    await input.fill('桜の');
    await input.press('Enter');
    await expect(cards).toHaveCount(3);
    // 前後空白だけでは絞り込まない(trim後0文字=検索なし)。
    await input.fill('  ');
    await expect(cards).toHaveCount(N);
    // 「1文字+空白」もtrim後1文字=絞り込まない。
    await input.fill(' 桜 ');
    await page.waitForTimeout(700);
    await expect(cards).toHaveCount(N);
  });

  test('memo search also requires 2 chars and matches comment/memo', async ({ page }) => {
    const memo = page.locator('#candMemoSearch');
    const cards = page.locator('#candCardList .cand-card');
    await memo.type('ほ');
    await page.waitForTimeout(700);
    await expect(cards).toHaveCount(N);
    await memo.type('し');
    await expect(cards).toHaveCount(3); // i%4===0 → 0,4,8
    await page.locator('#candMemoSearchClear').click();
    await expect(cards).toHaveCount(N);
  });

  test('IME composition does not repaint until commit', async ({ page }) => {
    const input = page.locator('#candWorkSearch');
    const cards = page.locator('#candCardList .cand-card');
    await input.click();
    await page.evaluate(() => {
      const el = /** @type {HTMLInputElement} */ (document.getElementById('candWorkSearch'));
      el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
      el.value = 'さくらの';
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: 'さくらの', inputType: 'insertCompositionText', isComposing: true }));
    });
    await page.waitForTimeout(600);
    await expect(cards).toHaveCount(N); // 変換中は描き直さない
    await page.evaluate(() => {
      const el = /** @type {HTMLInputElement} */ (document.getElementById('candWorkSearch'));
      el.value = '桜の';
      el.dispatchEvent(new InputEvent('input', { bubbles: true, data: '桜の', inputType: 'insertFromComposition', isComposing: true }));
      el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '桜の' }));
    });
    await expect(cards).toHaveCount(3);
    const alive = await page.evaluate(() => document.activeElement === document.getElementById('candWorkSearch'));
    expect(alive).toBe(true);
  });
});
