// @ts-check
// daily_pick予約投稿 β-2(設計_daily_pick予約投稿_20261024 §2): 投稿モードから親+返信をGASの無人予約へ渡す。
//   公開枠の30分前の時刻・acc3・返信はBluesky用af_id・返信画像つきで届くこと、
//   予約が出た後に投稿モードを開き直すと親/返信URLが埋まることを本物の画面で固定する(GASだけ差し替え)。
const { test, expect } = require('@playwright/test');

const GAS = 'https://gas.e2e.test/exec';

test('投稿モードのBluesky予約がacc3・枠の30分前・Bluesky用af_idでGASへ届き、開き直すとURLが埋まる', async ({ page, baseURL }) => {
  const SITE = new URL(baseURL || 'http://127.0.0.1/').origin; // 本番スモークはPages上で走る=サイト自身は通す
  const draftId = 'stk_e2e_bsky_reserve';
  const title = '予約で親と返信を出す';
  const posts = [];
  let phase = 'pending';
  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (u.startsWith(GAS)) {
      if (route.request().method() === 'POST') {
        posts.push(JSON.parse(route.request().postData() || '{}'));
        return route.fulfill({ status: 200, headers: { 'access-control-allow-origin': '*' }, contentType: 'application/json', body: JSON.stringify({ ok: true, id: 'rsv_e2e_1' }) });
      }
      const cb = new URL(u).searchParams.get('callback') || 'cb';
      const d = phase === 'posted'
        ? { ok: true, id: 'rsv_e2e_1', status: 'posted', parentUrl: 'https://bsky.app/profile/e2e/post/rp1', replyUrl: 'https://bsky.app/profile/e2e/post/rr1' }
        : { ok: true, id: 'rsv_e2e_1', status: 'pending' };
      return route.fulfill({ status: 200, contentType: 'application/javascript', body: cb + '(' + JSON.stringify(d) + ');' });
    }
    if (u.startsWith(SITE + '/') || /^https?:\/\/(127\.0\.0\.1|localhost)[:/]/.test(u)) return route.continue();
    return route.abort(); // 短縮worker等の外部は落とす=返信は生のアフィリンク(af_id差し替え済み)になる
  });
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate(({ draftId, title, GAS }) => {
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem('bsky_gas_url', GAS);
    localStorage.setItem('fanza_af_id', 'xside-990');
    localStorage.setItem('fanza_af_id_bsky__acc3', 'bskyside-002');
    localStorage.setItem('hist_maint_at', String(Date.now()));
    localStorage.setItem('hist_metrics_at', String(Date.now()));
    localStorage.setItem('go5_stock_archive', '[]');
    localStorage.setItem('go5_stock_meta', JSON.stringify([{
      id: draftId, ts: Date.now(), addedAt: Date.now(), account: 'acc3',
      label: title, title, author: 'test', bskyText: 'テスト本文',
      affiliateUrl: 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fbook.dmm.co.jp%2Fproduct%2F1%2Fb_e2e%2F&af_id=xside-990&ch=link_tool&ch_id=link',
      workUrl: 'https://book.dmm.co.jp/product/1/b_e2e/', videoName: 'test.mp4',
      videoId: 'acc3-20261024-1200-rsv1', attrs: {}
    }]));
  }, { draftId, title, GAS });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => typeof window.Go5ReserveDraftBskyThread)).toBe('function');
  await page.evaluate(() => { window.Go5FreshWorkInfo = () => Promise.resolve(null); });

  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await expect(page.locator('#draftPostModal')).toBeVisible();
  await expect(page.locator('#draftBskyReserve')).toBeVisible();
  page.on('dialog', (d) => d.accept());
  // 枠なしでは予約しない。
  await page.locator('#draftBskyReserve').click();
  await expect(page.locator('#draftBskyStatus')).toContainText('公開枠を選んでください');
  expect(posts.length).toBe(0);

  // カレンダーの枠選択(slot-picked)を送る=2時間後の枠。
  const slotMs = await page.evaluate(() => {
    const d = new Date(Date.now() + 2 * 3600000); d.setSeconds(0, 0);
    const p = (n) => String(n).padStart(2, '0');
    const at = d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    window.postMessage({ source: 'sch-calendar', type: 'slot-picked', slot: { id: 'slot_e2e_1', date: at.slice(0, 10), time: at.slice(11), role: 'メイン', scheduled_at: at } }, '*');
    return d.getTime();
  });
  await expect(page.locator('#draftPickedSlot')).toContainText('選択中');
  await page.locator('#draftBskyReserve').click();
  await expect(page.locator('#draftBskyStatus')).toContainText('予約済み');

  expect(posts.length).toBe(1);
  const p = posts[0];
  expect(p.type).toBe('reserve');
  expect(p.channel).toBe('acc3');
  expect(Date.parse(p.scheduled_at)).toBe(slotMs - 30 * 60000);
  expect(p.slot_id).toBe('slot_e2e_1');
  expect(p.text).toBe(title);
  expect(p.meta.videoId).toBe('acc3-20261024-1200-rsv1');
  expect(p.meta.pillar).toBe('bsky');
  expect(p.meta.draftId).toBe(draftId);
  expect(p.thread.reply_text).toContain('af_id=bskyside-002');
  expect(p.thread.reply_text).not.toContain('xside-990');
  expect(p.thread.reply_image).toMatch(/^data:image\//);
  expect(p.thread.delay_ms).toBeGreaterThanOrEqual(3000);
  expect(p.thread.delay_ms).toBeLessThanOrEqual(10000);
  const saved = await page.evaluate((id) => JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}'), draftId);
  expect(saved.bskyReserveId).toBe('rsv_e2e_1');

  // GAS側で親+返信が出た後に開き直す=URLがドラフトへ戻る。
  phase = 'posted';
  await page.locator('#draftModalClose').click();
  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await expect(page.locator('#draftBskyStatus')).toContainText('投稿済み');
  await expect.poll(() => page.evaluate((id) => {
    const s = JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}');
    return [s.bskyParentUrl, s.bskyReplyUrl];
  }, draftId)).toEqual(['https://bsky.app/profile/e2e/post/rp1', 'https://bsky.app/profile/e2e/post/rr1']);
});
