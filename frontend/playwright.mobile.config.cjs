const base = require('./playwright.config.cjs');

// Run the mocked regressions at a small touch/mobile viewport.
module.exports = {
  ...base,
  outputDir: "./test-results/mobile",
  use: { ...base.use, viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true },
};
