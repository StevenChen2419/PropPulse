const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './e2e', testMatch: 'cloudflare-compatibility.spec.cjs', workers: 1,
  reporter: 'list', timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:3199', channel: 'chrome', headless: true },
});
