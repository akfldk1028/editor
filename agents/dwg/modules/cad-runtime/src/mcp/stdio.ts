import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { resolve } from "node:path";
import { mkdir } from "node:fs/promises";

import { createCadApplication } from "../application/createCadApplication.js";
import { createCadMcpServer } from "./createServer.js";
import {
  createRepositoryPaths,
  findRepositoryRoot
} from "../platform/repositoryPaths.js";
import { defaultProcessRunner } from "../providers/cli/processRunner.js";

const paths = createRepositoryPaths(findRepositoryRoot(import.meta.url));
const workspaceRoot = resolve(process.env.DWG_WORKSPACE ?? paths.repositoryRoot);
const exportRoot = resolve(
  process.env.DWG_EXPORT_ROOT ??
    resolve(paths.repositoryRoot, `tests/visual/test-results/export-roots/mcp-${process.pid}`)
);
await mkdir(exportRoot, { recursive: true });
const application = await createCadApplication({
  workspaceRoot,
  drawingPath: process.env.DWG_DRAWING_PATH,
  exportRoot,
  dwgVersionManifestPath: paths.dwgVersionManifest,
  processRunner: {
    async run(spec, signal) {
      const result = await defaultProcessRunner.run({
        command: spec.command,
        args: spec.args,
        cwd: spec.cwd,
        env: process.env,
        stdin: spec.stdin,
        signal
      });
      return {
        exitCode: result.exitCode ?? -1,
        stdout: result.stdout,
        stderr: result.stderr
      };
    }
  },
  clock: Date.now
});
const server = createCadMcpServer(application.capabilities, {
  requestDestinationGrant: (signal) => application.requestDestinationGrant(signal),
  createReportDownload: (input, signal) => application.createReportDownload(input, signal),
  consumeReportDownload: (downloadId) => application.consumeReportDownload(downloadId),
  displayDirectory: "Exports"
});
await server.connect(new StdioServerTransport());
