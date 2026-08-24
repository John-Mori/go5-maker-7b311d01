// @ts-check
// 黒いサムネ/DL不能ドラフトの再発防止。
// 実物ページの video-created 境界へ故障Blobを投入し、二相コミットが fail-closed することを固定する。
const { test, expect } = require('@playwright/test');

async function ready(page) {
  await page.goto('index.html', { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => !!(window.Go5Stock && window.Go5VideoIntegrity && window.Go5Idb));
  await page.evaluate(() => {
    localStorage.removeItem('go5_stock_meta');
    localStorage.removeItem('go5_stock_archive');
  });
}

test.describe('ドラフト動画の完全性ゲート', () => {
  test('空Blobは一覧へ確定せず、ページに留まって明示エラーにする', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: {
          draft: true, title: '空動画回帰', name: 'empty.mp4', account: 'acc1',
          blob: new Blob([], { type: 'video/mp4' })
        }
      }));
    });

    await expect(page.locator('#go5SaveHold')).toBeVisible();
    await expect(page.locator('#go5SaveHoldMsg')).toContainText('空または不完全');
    await expect(page.locator('#go5SaveRetry')).toBeHidden();
    expect(page.url()).toContain('index.html');
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]'))).toEqual([]);
  });

  test('IDBがset成功を返しても読み戻せなければ正常ドラフトにしない', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      const realSet = Go5Idb.set.bind(Go5Idb);
      const realGet = Go5Idb.get.bind(Go5Idb);
      Go5Idb.set = (key, value) => String(key).startsWith('stock_v_') ? Promise.resolve() : realSet(key, value);
      Go5Idb.get = (key) => String(key).startsWith('stock_v_') ? Promise.resolve(null) : realGet(key);
      if (window.Go5Sync) Go5Sync.configured = () => false;
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: {
          draft: true, title: '読戻し失敗回帰', name: 'readback.mp4', account: 'acc1',
          blob: new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' })
        }
      }));
    });

    await expect(page.locator('#go5SaveHold')).toBeVisible();
    await expect(page.locator('#go5SaveHoldMsg')).toContainText('この端末にも雲にも確認できません');
    expect(page.url()).toContain('index.html');
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('go5_stock_meta') || '[]'))).toEqual([]);
  });

  test('書込み後に読める動画だけがメタ確定され、ドラフトページへ進む', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      if (window.Go5Sync) Go5Sync.configured = () => false;
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: {
          draft: true, title: '正常着地回帰', name: 'landed.mp4', account: 'acc1',
          blob: new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' })
        }
      }));
    });

    // ★2026-08-17のB設計で着地後はページ内ドラフト表示(#pageStock)へ切替=破壊遷移(location.href='Stock.html')は
    //   しない(8/15の未着地遷移=全滅の再発防止)。よって「ドラフトページへ進む」の実物は URL遷移ではなく
    //   「メタが videoReadyAt で確定し、ページ内ドラフト面が前面に出る」こと。旧 waitForURL(/Stock.html/) は
    //   この変更に取り残されて永久タイムアウトしていた(スモーク15連赤の唯一因・版ずれ検知を覆い隠していた)。
    await page.waitForFunction(() => {
      const list = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      return !!(list[0] && list[0].videoReadyAt);
    }, { timeout: 10000 });
    await expect(page.locator('#pageStock')).toBeVisible();
    const saved = await page.evaluate(async () => {
      const list = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      const meta = list[0] || null;
      const blob = meta ? await Go5Idb.get('stock_v_' + meta.id) : null;
      return { count: list.length, ready: !!(meta && meta.videoReadyAt), bytes: meta && meta.videoBytes, blobBytes: blob && blob.size };
    });
    expect(saved).toEqual({ count: 1, ready: true, bytes: 32 * 1024, blobBytes: 32 * 1024 });
  });

  test('ドラフト着地直後だけDrive保存を1回起動し、先に永続再送記録を残す', async ({ page }) => {
    await ready(page);
    await page.evaluate(() => {
      window.__draftDriveCalls = [];
      window.__draftDriveLegacyCalls = 0;
      const preview = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mNk+M/wHwAF/gL+3MxZ5wAAAABJRU5ErkJggg==';
      Go5Drive.folderIdFor = () => '';
      Go5Drive.checkSaved = () => Promise.resolve(false);
      Go5Drive.fetchPreview = () => Promise.resolve(preview);
      Go5Drive.fetchVideo = () => Promise.resolve(null);
      Go5Drive.queueSave = (opts) => {
        window.__draftDriveCalls.push({ videoId: opts.videoId, title: opts.title, channel: opts.channel });
        return Promise.resolve({ ok: true });
      };
      Go5Drive.upload = () => { window.__draftDriveLegacyCalls += 1; };
      Go5Sync.configured = () => true;
      Go5Sync.putBlobR2At = () => Promise.resolve('a'.repeat(64));
      Go5Sync.hasBlobR2At = () => Promise.resolve(true);
      Go5Sync.keyForName = () => Promise.resolve('a'.repeat(64));
      Go5Sync.getConfig = () => ({ url: 'https://sync.example.test' });
      Go5Sync.fetchBlobR2At = () => Promise.resolve(null);
      document.dispatchEvent(new CustomEvent('video-created', {
        detail: {
          draft: true, title: '作成時Drive保存回帰', name: 'draft-drive.mp4', account: 'acc1',
          videoId: 'acc1-20260825-1200-drive',
          blob: new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' })
        }
      }));
    });

    await expect.poll(() => page.evaluate(() => window.__draftDriveCalls.length), { timeout: 15000 }).toBe(1);
    const state = await page.evaluate(() => {
      const list = JSON.parse(localStorage.getItem('go5_stock_meta') || '[]');
      const meta = list[0];
      return {
        draftCount: list.length,
        call: window.__draftDriveCalls[0],
        legacyCalls: window.__draftDriveLegacyCalls,
        pending: !!(meta && localStorage.getItem('go5_drive_savejob_' + meta.id)),
        driveState: meta ? JSON.parse(localStorage.getItem('go5_drive_saved_' + meta.id) || 'null')?.state : null,
        draftId: meta?.id || ''
      };
    });
    expect(state.draftCount).toBe(1);
    expect(state.call).toEqual({ videoId: state.draftId, title: '作成時Drive保存回帰', channel: 'acc1' });
    expect(state.legacyCalls).toBe(0);
    expect(state.pending).toBe(true);
    expect(state.driveState).toBe('pending');
  });
  test('サイズだけ大きい破損mp4はブラウザの再生確認で拒否する', async ({ page }) => {
    await ready(page);
    const playable = await page.evaluate(() => Go5VideoIntegrity.probePlayable(
      new Blob([new Uint8Array(32 * 1024)], { type: 'video/mp4' }),
      { timeoutMs: 2000 }
    ));
    expect(playable).toBe(false);
  });

});
