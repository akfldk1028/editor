import { defineConfig } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const workspaceRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(workspaceRoot, "../..");
const frontendPort = Number(process.env.DWG_LIVE_FRONTEND_PORT ?? 4183);
const gatewayPort = Number(process.env.DWG_LIVE_GATEWAY_PORT ?? 4327);

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "live-oauth-cli.spec.ts",
  outputDir: resolve(repositoryRoot, "tests/visual/test-results/live-oauth"),
  timeout: 300_000,
  expect: { timeout: 240_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    colorScheme: "light",
    screenshot: "off",
    trace: "off"
  },
  webServer: [
    {
      command: "npm run gateway",
      cwd: repositoryRoot,
      env: {
        ...process.env,
        DWG_HOST_DIALOGS: "off",
        DWG_GATEWAY_PORT: String(gatewayPort)
      },
      url: `http://127.0.0.1:${gatewayPort}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000
    },
    {
      command: "npm run dev",
      cwd: workspaceRoot,
      env: {
        ...process.env,
        DWG_FRONTEND_PORT: String(frontendPort),
        DWG_GATEWAY_PORT: String(gatewayPort)
      },
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 60_000
    }
  ],
  reporter: [["list"]]
});
