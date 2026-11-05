const { defineConfig } = require('@playwright/test');

// The parent task starts the disposable HTTPS gateway, private PostgreSQL/backend,
// and frontend3199. Build with NEXT_PUBLIC_API_URL=https://api.proppulse.test:3443.
module.exports = defineConfig({
  testDir: './e2e-real',
  testMatch: 'production-https.spec.cjs',
  fullyParallel: false,
  workers: 1,
  globalTimeout: 240_000,
  timeout: 100_000,
  expect: { timeout: 10_000 },
  reporter: 'list',
  use: {
    baseURL: 'https://app.proppulse.test:3443',
    channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome',
    headless: true,
    // Disposable local self-signed certificate only; production must use a valid CA.
    ignoreHTTPSErrors: true,
    launchOptions: { args: ['--host-resolver-rules=MAP app.proppulse.test 127.0.0.1,MAP api.proppulse.test 127.0.0.1', '--no-proxy-server'] },
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
});
