const { test, expect } = require('@playwright/test');

// 即アフィの投稿文にも、投稿モード(composePostText)と同じセール行を入れる
// (Chami 2026-10-18 5Sec軍議 msg 1561277829524492381)。
// セール一覧・作品リンクは自前ドメインで短縮して本文へそのまま載せる
// (Chami 2026-10-21「ただのリンクにするくらいなら短縮リンクにしてピンククリック計測しよか」=10-18の「短縮せずal.fanzaのまま」を撤回)。
test.describe('即アフィのセール行', () => {
  for (const acc of ['acc1', 'acc2', 'acc3']) {
    test('投稿モードの本文末尾のセール行と一致し、作品・セールとも短縮URLで出る(' + acc + ')', async ({ page }) => {
      const saleUrl = 'https://www.dmm.co.jp/dc/doujin/-/list/=/campaign=gain/section=mens/';
      const domain = 'e2e-short-' + acc + '.example';
      const shortened = []; // workerへ渡した転送先(順不同)
      await page.route('**/api/shorten', async (route) => {
        const destination = new URLSearchParams(route.request().postData() || '').get('url') || '';
        shortened.push(destination);
        const code = /campaign%3Dgain/.test(destination) ? 'sale' : (/d_e2e_qa/.test(destination) ? 'work' : 'other' + shortened.length);
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ short: 'https://' + domain + '/' + code, url: destination }) });
      });
      await page.goto('StockLists.html', { waitUntil: 'domcontentloaded' });
      await page.evaluate(({ acc, saleUrl, domain }) => {
        localStorage.setItem('current_account', acc);
        localStorage.setItem('short_worker_url__' + acc, 'https://' + domain);
        localStorage.setItem('fanza_af_id', 'e2e-affiliate-001');
        localStorage.setItem('disc_urls_seeded__' + acc, '1');
        localStorage.setItem('bsky_discount_urls__' + acc, JSON.stringify([{ id: 'sale-' + acc, name: 'E2Eセール', url: saleUrl, at: Date.now() }]));
        localStorage.setItem('bsky_discount_selected__' + acc, 'sale-' + acc);
        localStorage.removeItem('bsky_discount_link_cache');
      }, { acc, saleUrl, domain });
      // StockLists は読込時に acc3 へ固定するため、再読込せず(acctId() は都度読み)選んだアカウントで検証する
      const line = await page.evaluate(() => window.Go5SaleLineText());
      expect(line).toMatch(new RegExp('^.+\\nhttps://' + domain.replace(/\./g, '\\.') + '/sale$'));
      expect(line).not.toContain('al.fanza');
      expect(line).not.toContain('【リンク】');
      // 短縮の転送先=自分のaf_idで包んだセール一覧のアフィリンク
      const saleDest = shortened.find((u) => /campaign%3Dgain/.test(u)) || '';
      expect(new URL(saleDest).hostname).toBe('al.fanza.co.jp');
      expect(new URL(saleDest).searchParams.get('lurl')).toBe(saleUrl);
      expect(new URL(saleDest).searchParams.get('af_id')).toBe('e2e-affiliate-001');
      // 投稿モード側と同じ行が本文末尾に付く
      const composed = await page.evaluate(() => {
        const t = document.getElementById('bskyText'); if (t) t.value = 'テスト本文';
        return window.__go5ComposePostText();
      });
      expect(composed.endsWith(line), composed).toBe(true);
      expect(composed).not.toContain('【リンク】');
      // 同じ状態でも X 側(ドラフトX親文=__go5ComposeXTextForBskyText)は生のal.fanzaのまま・短縮APIを呼ばない(10-18運用据え置き)。
      const callsBeforeX = shortened.length;
      const workAff = 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fwww.dmm.co.jp%2Fdc%2Fdoujin%2F-%2Fdetail%2F%3D%2Fcid%3Dd_e2e_x_only%2F&af_id=e2e-affiliate-001&ch=link_tool&ch_id=link';
      const xText = await page.evaluate((workAff) => window.__go5ComposeXTextForBskyText('X本文 紹介用短縮リンク\nセール中短縮リンク', workAff), workAff);
      expect(xText).toContain(workAff);
      expect(xText).toMatch(/https:\/\/al\.fanza\.co\.jp\/\?lurl=https%3A%2F%2Fwww\.dmm\.co\.jp%2Fdc%2Fdoujin%2F-%2Flist%2F%3D%2Fcampaign%3Dgain/);
      expect(xText).not.toContain(domain);
      expect(xText).not.toContain('【リンク】');
      expect(shortened.length).toBe(callsBeforeX);
      expect(shortened.some((u) => /d_e2e_x_only/.test(u))).toBe(false);
      // 即アフィの画面
      await page.locator('#quickAffiBtn').click();
      await page.locator('#qaUrl').fill('https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=d_e2e_qa/');
      await page.locator('.qa-go').click();
      await expect.poll(() => page.locator('#qaPost').inputValue()).toContain(line);
      await expect(page.locator('#qaOut')).toHaveValue('https://' + domain + '/work');
      const post = await page.locator('#qaPost').inputValue();
      expect(post.endsWith(line)).toBe(true);
      expect(post).toContain('https://' + domain + '/work');
      expect(post).not.toContain('al.fanza');
      expect(post).not.toContain('【リンク】');
      const workDest = shortened.find((u) => /d_e2e_qa/.test(u)) || '';
      expect(new URL(workDest).hostname).toBe('al.fanza.co.jp');
      expect(new URL(workDest).searchParams.get('af_id')).toBe('e2e-affiliate-001');
    });
  }
});
