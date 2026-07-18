// @ts-check
// Playwright設定 — 恒久-3 デプロイ後スモーク(2026-07-18)。
// 対象は「公開URLの実物」。ローカルサーバは立てない(GitHub Pagesの配信結果そのものを検証する)。
const { defineConfig, devices } = require('@playwright/test');

const BASE_URL = process.env.BASE_URL || 'https://john-mori.github.io/go5-maker-7b311d01/';

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0, // 公開直後の伝播ゆらぎに備え軽くリトライ
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    // モバイル実機に近い縦長ビューポート(このアプリの主戦場はiPhone)
    viewport: { width: 390, height: 844 },
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } } },
  ],
});
