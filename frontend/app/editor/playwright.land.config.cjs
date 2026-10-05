const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({ testDir: './tests', testMatch: 'land-route.spec.cjs', workers: 1,
  use: { browserName: 'chromium', channel: 'chrome', headless: true, locale: 'ko-KR', viewport: { width: 1440, height: 900 } } });
