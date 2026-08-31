const { defineConfig, devices } = require("@playwright/test");
const { resolve } = require("node:path");

const repositoryRoot = resolve(__dirname, "../..");

module.exports = defineConfig({
  testDir: "browser",
  testMatch: "planm-live.spec.js",
  timeout: 120000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    ...devices["Desktop Chrome"],
    headless: true,
  },
  webServer: [
    {
      command: "python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000",
      cwd: resolve(repositoryRoot, "products/plan"),
      url: "http://127.0.0.1:8000/docs",
      reuseExistingServer: false,
      timeout: 30000,
    },
    {
      command: "npm run gateway",
      cwd: resolve(repositoryRoot, "products/dwg"),
      url: "http://127.0.0.1:4317/api/health",
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174",
      cwd: resolve(repositoryRoot, "products/plan/frontend"),
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      timeout: 30000,
    },
  ],
});
