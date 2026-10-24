// @ts-check
// daily_pick予約投稿 β-3(設計_daily_pick予約投稿_20261024 §3): 公開枠の紐付けルールを本物の画面とカレンダーiframeで固定する。
//   おすすめ枠=カレンダーの空き枠を提案→確定、Bluesky時刻=枠−30分の表示とGASへ送る時刻が一致、
//   Bluesky予約済みの枠は二重に選べない(カレンダーにも種別が出る)、1日3本を超える4本目は確認で止まる、
//   予約できたら枠が「予約登録済」へ書き戻る(GASだけ差し替え)。
const { test, expect } = require('@playwright/test');

const GAS = 'https://gas.e2e.test/exec';

test('おすすめ枠→枠−30分で予約・同枠の二重選択拒否・4本目の確認・カレンダーが予約登録済へ', async ({ page, baseURL }) => {
  test.setTimeout(90000);
  const SITE = new URL(baseURL || 'http://127.0.0.1/').origin; // 本番スモークはPages上で走る=サイト自身は通す
  const draftId = 'stk_e2e_slot_rules';
  const posts = [];
  const dialogs = [];
  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (u.startsWith(GAS)) {
      if (route.request().method() === 'POST') {
        posts.push(JSON.parse(route.request().postData() || '{}'));
        return route.fulfill({ status: 200, headers: { 'access-control-allow-origin': '*' }, contentType: 'application/json', body: JSON.stringify({ ok: true, id: 'rsv_e2e_rules' }) });
      }
      const cb = new URL(u).searchParams.get('callback') || 'cb';
      return route.fulfill({ status: 200, contentType: 'application/javascript', body: cb + '(' + JSON.stringify({ ok: true, id: 'rsv_e2e_rules', status: 'pending' }) + ');' });
    }
    if (u.startsWith(SITE + '/') || /^https?:\/\/(127\.0\.0\.1|localhost)[:/]/.test(u)) return route.continue();
    return route.abort();
  });
  await page.goto('Stock.html', { waitUntil: 'domcontentloaded' });
  await page.evaluate(({ draftId, GAS }) => {
    localStorage.setItem('current_account', 'acc3');
    localStorage.setItem('bsky_gas_url', GAS);
    localStorage.setItem('fanza_af_id_bsky__acc3', 'bskyside-002');
    localStorage.setItem('hist_maint_at', String(Date.now()));
    localStorage.setItem('hist_metrics_at', String(Date.now()));
    localStorage.setItem('go5_stock_archive', '[]');
    localStorage.removeItem('sch_state_v1');
    localStorage.setItem('go5_stock_meta', JSON.stringify([{
      id: draftId, ts: Date.now(), addedAt: Date.now(), account: 'acc3',
      label: '枠ルール', title: '枠ルール', author: 'test', bskyText: 'テスト本文',
      affiliateUrl: 'https://al.fanza.co.jp/?lurl=https%3A%2F%2Fbook.dmm.co.jp%2Fproduct%2F1%2Fb_rules%2F&af_id=xside-990&ch=link_tool&ch_id=link',
      workUrl: 'https://book.dmm.co.jp/product/1/b_rules/', videoName: 'test.mp4',
      videoId: 'acc3-20261024-1200-rul1', attrs: {}, dailyPick: { date: '2026-10-24', cid: 'b_rules', rank: 1 }
    }]));
  }, { draftId, GAS });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.evaluate(() => typeof window.Go5ReserveDraftBskyThread)).toBe('function');
  await page.evaluate(() => { window.Go5FreshWorkInfo = () => Promise.resolve(null); });
  page.on('dialog', (d) => { dialogs.push(d.message()); d.accept(); });

  await page.locator(`.stk-mode[data-id="${draftId}"]`).click();
  await expect(page.locator('#draftPostModal')).toBeVisible();

  // ① おすすめ枠(daily_pick由来だけに出る)→カレンダーが空き枠を返す→確認で確定。
  await expect(page.locator('#draftSuggestSlot')).toBeVisible();
  await page.locator('#draftSuggestSlot').click();
  await expect.poll(() => dialogs.some((m) => m.indexOf('おすすめ枠：') === 0), { timeout: 30000 }).toBe(true);
  await expect(page.locator('#draftPickedSlot')).toContainText('選択中');
  const slot = await page.evaluate((id) => JSON.parse(localStorage.getItem('go5_draft_post_' + id) || '{}').pubSlot, draftId);
  expect(slot && slot.id).toBeTruthy();
  const slotMs = Date.parse(String(slot.scheduled_at).replace(' ', 'T'));
  expect(slotMs - 30 * 60000).toBeGreaterThan(Date.now());
  // Bluesky時刻=枠の30分前を表示。
  const tb = await page.evaluate((ms) => { const d = new Date(ms - 30 * 60000), p = (n) => (n < 10 ? '0' : '') + n; return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()); }, slotMs);
  await expect(page.locator('#draftPickedSlot')).toContainText('🦋Bluesky ' + tb + '(30分前)');

  // 同じ日に別ドラフトのBluesky予約が3本(うち1本は同じ枠)ある状態を作る。
  await page.evaluate(({ slot, slotMs }) => {
    const metas = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
    ['b1', 'b2', 'b3'].forEach((k, i) => {
      const id = 'stk_e2e_other_' + k;
      metas.push({ id, ts: Date.now(), addedAt: Date.now(), account: 'acc3', label: '他' + k, title: '他の予約' + k, videoId: 'acc3-o-' + k, attrs: {} });
      const ps = i === 0 ? slot : { id: 'slot_far_' + k, date: '2000-01-0' + (i + 1), time: '0' + i + ':00', scheduled_at: '2000-01-0' + (i + 1) + ' 0' + i + ':00' };
      localStorage.setItem('go5_draft_post_' + id, JSON.stringify({ pubMode: 'scheduled', pubSlot: ps, bskyReserveId: 'rsv_o_' + k, bskyReserveAt: new Date(slotMs - 30 * 60000 - i * 60000).toISOString() }));
    });
    localStorage.setItem('go5_stock_meta', JSON.stringify(metas));
  }, { slot, slotMs });

  // ② 同じ枠をカレンダーで選び直す=Bluesky予約済みの枠なので拒否(枠は変わらない)。
  await page.evaluate((s) => { window.postMessage({ source: 'sch-calendar', type: 'slot-picked', slot: Object.assign({}, s, { id: s.id }) }, '*'); }, slot);
  await expect.poll(() => dialogs.some((m) => m.indexOf('この枠は使用中です(Bluesky予約済み') === 0)).toBe(true);
  // ピッカーにも「Bluesky予約済み」の種別で出る。
  await page.locator('#draftPickSlot').click();
  await expect(page.frameLocator('#draftPickerFrame').locator('.taken-note', { hasText: 'Bluesky予約済み' }).first()).toBeVisible({ timeout: 20000 });
  await page.locator('#draftPickerClose').click();

  // ③ 4本目の予約=上限の確認が出る。承認すると枠−30分でGASへ届く。
  await page.locator('#draftBskyReserve').click();
  await expect(page.locator('#draftBskyStatus')).toContainText('予約済み');
  expect(dialogs.some((m) => /既に3本です\(1日3本まで\)。4本目を予約しますか/.test(m))).toBe(true);
  expect(posts.length).toBe(1);
  expect(Date.parse(posts[0].scheduled_at)).toBe(slotMs - 30 * 60000);
  expect(posts[0].slot_id).toBe(slot.id);

  // ④ カレンダーの枠(acc3)が「予約登録済」へ書き戻る。
  await expect.poll(() => page.evaluate((id) => {
    const st = JSON.parse(localStorage.getItem('sch_state_v1') || '{}');
    const s = st.slotData && st.slotData[id];
    return (s && s.exec && s.exec.acc3 && s.exec.acc3.status) || '';
  }, slot.id), { timeout: 20000 }).toBe('予約登録済');
});
