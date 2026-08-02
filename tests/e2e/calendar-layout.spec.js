// @ts-check
const { test, expect } = require('@playwright/test');

test.describe('desktop calendar layout', () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test('keeps every slot readable at 1.2x scale', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#calBtn').click();

    const frame = page.frameLocator('#calFrame');
    const slots = frame.locator('.slot');
    await expect(slots).toHaveCount(210);

    const frameWidth = await page.locator('#calFrame').evaluate((el) => el.getBoundingClientRect().width);
    expect(frameWidth).toBeGreaterThan(1300);

    const result = await slots.evaluateAll((els) => {
      const intersects = (a, b) =>
        a.left < b.right - 0.5 && a.right > b.left + 0.5 &&
        a.top < b.bottom - 0.5 && a.bottom > b.top + 0.5;
      const failures = [];
      for (const slot of els) {
        const parts = Array.from(slot.children);
        const cells = parts.filter((el) => el.classList.contains('cell'));
        const prio = parts.find((el) => el.classList.contains('prio'));
        if (cells.length !== 2 || !prio) { failures.push('slot structure'); continue; }

        const groups = [[...cells, prio], ...cells.map((cell) => Array.from(cell.children))];
        for (const group of groups) {
          for (let i = 0; i < group.length; i++) {
            for (let j = i + 1; j < group.length; j++) {
              if (intersects(group[i].getBoundingClientRect(), group[j].getBoundingClientRect())) {
                failures.push('contents overlap');
              }
            }
          }
          for (const child of group) {
            if (child.scrollWidth > child.clientWidth + 1) failures.push('contents clipped');
          }
        }
      }
      return {
        failures: failures.slice(0, 10),
        zoom: getComputedStyle(document.body).zoom,
        columns: getComputedStyle(document.querySelector('.week-grid')).gridTemplateColumns.split(' ').length,
      };
    });

    expect(result.zoom).toBe('1.2');
    expect(result.columns).toBe(7);
    expect(result.failures).toEqual([]);
  });
  test('reloads the iframe state after cloud sync', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#calBtn').click();
    const frame = page.frameLocator('#calFrame');
    await expect(frame.locator('.slot')).toHaveCount(210);
    await expect(frame.locator('.slot').first().locator('.cell').first()).toHaveClass(/pending/);

    const slot = await frame.locator('body').evaluate(() => {
      const firstDate = document.querySelector('.week-head').textContent.slice(0, 10);
      return { id: window.SCH.gen.slotId(firstDate, 0), date: firstDate };
    });
    await page.evaluate(({ id, date }) => {
      localStorage.setItem('sch_state_v1', JSON.stringify({
        overrides: {},
        slotData: {
          [id]: {
            id, date, title: '同期テスト', updated_at: new Date().toISOString(),
            exec: {
              acc1: { status: '公開済', post_url: 'https://example.com/post', exec_updated_at: new Date().toISOString() },
              acc2: { status: '未着手' },
            },
          },
        },
      }));
      document.dispatchEvent(new CustomEvent('go5-synced', { detail: { pulled: 1 } }));
    }, slot);

    await expect(frame.locator('.slot').first().locator('.cell').first()).toHaveClass(/done/);
  });

  test('keeps execution timestamps and auto-publish isolated by account', async ({ page }) => {
    await page.goto('schedule/index.html', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('.slot')).toHaveCount(210);

    const result = await page.locator('body').evaluate(async () => {
      const oldStamp = '2026-08-01T00:00:00.000Z';
      localStorage.setItem('sch_state_v1', JSON.stringify({
        overrides: {},
        slotData: {
          edit: {
            id: 'edit', title: '旧題', notes: '旧メモ', updated_at: oldStamp,
            exec: {
              acc1: { status: '公開済', video_id: 'acc1-video', url: 'https://acc1.example/', exec_updated_at: oldStamp },
              acc2: { status: '未着手' },
            },
          },
          auto: {
            id: 'auto', updated_at: oldStamp,
            exec: {
              acc1: { status: '予約登録済', exec_updated_at: oldStamp },
              acc2: { status: '予約登録済', exec_updated_at: oldStamp },
            },
          },
        },
      }));
      const testStore = window.SCH.createStore();
      await testStore.init();
      await testStore.upsertSlot({
        id: 'edit', title: '新題', notes: '新メモ',
        status: '公開済', video_id: 'acc1-video', url: 'https://acc1.example/',
      }, 'acc1');
      await testStore.saveSlots({ auto: { status: '公開済' } }, 'acc1');
      return JSON.parse(localStorage.getItem('sch_state_v1'));
    });

    expect(result.slotData.edit.title).toBe('新題');
    expect(result.slotData.edit.exec.acc1.exec_updated_at).toBe('2026-08-01T00:00:00.000Z');
    expect(result.slotData.auto.exec.acc1.status).toBe('公開済');
    expect(result.slotData.auto.exec.acc2.status).toBe('予約登録済');
  });

  test('writes a posted result only to the specified account', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#calBtn').click();
    const frame = page.frameLocator('#calFrame');
    await expect(frame.locator('.slot')).toHaveCount(210);

    const slot = await frame.locator('body').evaluate(() => {
      const firstDate = document.querySelector('.week-head').textContent.slice(0, 10);
      return { id: window.SCH.gen.slotId(firstDate, 0), date: firstDate };
    });
    await page.evaluate(({ id, date }) => {
      localStorage.setItem('sch_state_v1', JSON.stringify({
        overrides: {},
        slotData: {
          [id]: {
            id, date, title: 'アカウント分離テスト', updated_at: '2026-08-01T00:00:00.000Z',
            exec: {
              acc1: {
                status: '公開済',
                video_id: 'acc1-video',
                post_url: 'https://acc1.example/post',
                exec_updated_at: '2026-08-01T00:00:00.000Z',
              },
              acc2: {
                status: '予約登録済',
                video_id: 'acc2-video',
                exec_updated_at: '2026-08-01T00:00:00.000Z',
              },
            },
          },
        },
      }));
      document.dispatchEvent(new CustomEvent('go5-synced', { detail: { pulled: 1 } }));
    }, slot);
    await expect(frame.locator('.slot').first().locator('.cell').first()).toHaveClass(/done/);

    await page.evaluate(({ id }) => {
      document.getElementById('calFrame').contentWindow.postMessage({
        target: 'sch-calendar',
        type: 'slot-writeback',
        id,
        account: 'acc2',
        status: '公開済',
        post_url: 'https://acc2.example/post',
      }, '*');
    }, slot);

    await expect.poll(async () => page.evaluate(({ id }) => {
      const state = JSON.parse(localStorage.getItem('sch_state_v1'));
      return state.slotData[id].exec.acc2.status;
    }, slot)).toBe('公開済');
    const saved = await page.evaluate(({ id }) => JSON.parse(localStorage.getItem('sch_state_v1')).slotData[id], slot);
    expect(saved.exec.acc1.post_url).toBe('https://acc1.example/post');
    expect(saved.exec.acc1.video_id).toBe('acc1-video');
    expect(saved.exec.acc2.post_url).toBe('https://acc2.example/post');
    expect(saved.exec.acc2.video_id).toBe('acc2-video');
  });
});

test.describe('mobile calendar layout', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('keeps the existing single-column scale', async ({ page }) => {
    await page.goto('index.html', { waitUntil: 'domcontentloaded' });
    await page.locator('#calBtn').click();
    const frame = page.frameLocator('#calFrame');
    await expect(frame.locator('.slot')).toHaveCount(210);

    const result = await frame.locator('body').evaluate((body) => ({
      zoom: getComputedStyle(body).zoom,
      columns: getComputedStyle(body.querySelector('.week-grid')).gridTemplateColumns.split(' ').length,
      accWidth: getComputedStyle(body.querySelector('.slot .acc')).width,
    }));
    expect(result.zoom === '1' || result.zoom === 'normal').toBeTruthy();
    expect(result.columns).toBe(1);
    expect(result.accWidth).toBe('34px');
  });
});
