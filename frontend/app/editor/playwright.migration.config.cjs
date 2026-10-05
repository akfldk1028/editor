const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({ testDir: './tests', testMatch: ['land-route.spec.cjs', 'map-route.spec.cjs', 'dialogue-route.spec.cjs', 'agents-route.spec.cjs', 'flow-route.spec.cjs'], workers: 1, timeout: 120000,
  use: { browserName: 'chromium', channel: 'chrome', headless: true, locale: 'ko-KR', viewport: { width: 1440, height: 900 } } });
