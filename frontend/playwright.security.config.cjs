const { defineConfig } = require('@playwright/test');

// Start security_browser_server.py against its EMPTY disposable test database.
// Build frontend with NEXT_PUBLIC_API_URL=http://127.0.0.1:8199 first.
module.exports = defineConfig({
  testDir: './e2e-real',
  testMatch: 'auth-security.spec.cjs',
  fullyParallel: false,
  workers: 1,
  globalTimeout: 240_000,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3199',
    channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome',
    headless: true,
    trace: 'off', // Never retain authentication cookies or request bodies.
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
