const { defineConfig, devices } = require("@playwright/test");
const { resolve } = require("node:path");

const repositoryRoot = resolve(__dirname, "../..");

module.exports = defineConfig({
  testDir: "browser",
  testMatch: "planm-run-ui.spec.js",
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    browserName: "chromium",
    headless: true,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "npm --prefix frontend run dev -- --host 127.0.0.1",
    cwd: repositoryRoot,
    url: "http://127.0.0.1:5173",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
