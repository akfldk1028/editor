const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "browser_tests",
  timeout: 30000,
  use: { browserName: "chromium", headless: true },
});
