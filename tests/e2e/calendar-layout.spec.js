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
