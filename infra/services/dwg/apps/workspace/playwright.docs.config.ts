import { defineConfig } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { docsExportRoot } from "./tests/support/repositoryOutputPaths.js";

const workspaceRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(workspaceRoot, "../..");
const frontendPort = Number(process.env.DWG_DOCS_FRONTEND_PORT ?? 4184);
const gatewayPort = Number(process.env.DWG_DOCS_GATEWAY_PORT ?? 4328);
process.env.DWG_EXPORT_MODE = "docs";

export default defineConfig({
  globalSetup: "./tests/support/exportRootGlobalSetup.ts",
  testDir: "./tests/docs",
  outputDir: resolve(repositoryRoot, "tests/visual/test-results/docs-captures"),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    colorScheme: "light",
    screenshot: "only-on-failure",
    trace: "retain-on-failure"
  },
  webServer: [
    {
      command: "npm run gateway",
      cwd: repositoryRoot,
      env: {
        ...process.env,
        DWG_GATEWAY_PORT: String(gatewayPort),
        DWG_EXPORT_MODE: "docs",
        // A browser run must never block on a native dialog.
        DWG_HOST_DIALOGS: "off",
        DWG_EXPORT_ROOT: docsExportRoot
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
