const { defineConfig } = require('@playwright/test');

// Start backend/tests/integration_server.py against its disposable PostgreSQL
// fixture first. No route in this suite fulfills an application API response.
module.exports = defineConfig({
  testDir: './e2e-real',
  fullyParallel: false,
  workers: 1,
  globalTimeout: 240_000,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3199',
    channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: 'node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3199',
    url: 'http://127.0.0.1:3199',
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
