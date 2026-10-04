const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: 'browser', testMatch: ['editor-platform.spec.ts', 'land-parcels.spec.ts'],
  use: { baseURL: 'http://127.0.0.1:5186', headless: true, channel: 'chrome' },
  webServer: {
    command: 'npm --prefix frontend/app/planm run dev -- --host 127.0.0.1 --port 5186 --strictPort',
    cwd: require('node:path').resolve(__dirname, '../..'),
    url: 'http://127.0.0.1:5186', reuseExistingServer: false,
    env: { EDITOR_BACKEND_URL: process.env.EDITOR_BACKEND_URL || 'http://127.0.0.1:8000' },
  },
});
