const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests/browser",
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
      url: "http://127.0.0.1:8000/docs",
      reuseExistingServer: false,
      timeout: 30000,
    },
    {
      command: "npm --prefix agents/dwg run gateway",
      url: "http://127.0.0.1:4317/api/health",
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: "npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      timeout: 30000,
    },
  ],
});
