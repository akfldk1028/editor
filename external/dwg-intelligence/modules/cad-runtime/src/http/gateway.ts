import { basename, dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { mkdir } from "node:fs/promises";

import {
  createWindowsHostDialogProvider,
  type HostDialogProvider
} from "@dwg/host-dialogs";

import type { CadApplication } from "../application/createCadApplication.js";
import { createCadApplication } from "../application/createCadApplication.js";
import { createChatService } from "../application/chat/chatService.js";
import { createProviderRegistry, getProviderStatuses } from "../providers/providerRegistry.js";
import { defaultProcessRunner } from "../providers/cli/processRunner.js";
import {
  createRepositoryPaths,
  createRuntimePaths,
  findRepositoryRoot
} from "../platform/repositoryPaths.js";
import {
  createActiveApplicationProxy,
  createDrawingSessionRegistry
} from "../application/sessions/sessionRegistry.js";
import { createDrawingSessionRoutes } from "./drawingSessionGateway.js";
import { createDrawingWorkspace } from "./drawingWorkspace.js";
import { createExportCapabilityRoutes } from "./exportCapabilityGateway.js";
import { createProviderGateway } from "./providerGateway.js";
import { createSkillGatewayRoutes } from "./skillGateway.js";

export interface CadGatewayServerOptions {
  workspaceRoot?: string;
  drawingPath?: string;
  skillRoot?: string;
  capabilityVersion?: string;
  application?: CadApplication;
  /** Supplies host dialogs. Omitted in headless runs, where the export root serves destinations. */
  dialogs?: HostDialogProvider;
}

export async function createCadGatewayServer(options: CadGatewayServerOptions = {}) {
  const paths = createRepositoryPaths(findRepositoryRoot(import.meta.url));
  const runtimePaths = createRuntimePaths(paths, process.env.DWG_WORKSPACE, process.env.DWG_DRAWING_PATH);
  const workspace = options.workspaceRoot ?? runtimePaths.workspace;
  const drawingPath = options.drawingPath ?? runtimePaths.drawingPath;
  const exportRoot = resolve(
    process.env.DWG_EXPORT_ROOT ??
      resolve(paths.repositoryRoot, `tests/visual/test-results/export-roots/gateway-${process.pid}`)
  );
  await mkdir(exportRoot, { recursive: true });
  const hostProcessRunner = {
    async run(spec: {
      command: string;
      args: string[];
      cwd: string;
      stdin?: string;
    }, signal?: AbortSignal) {
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
  };
  const application = options.application ?? await createCadApplication({
    workspaceRoot: workspace,
    drawingPath,
    exportRoot,
    dwgVersionManifestPath: paths.dwgVersionManifest,
    cadIoHostProjectPath: paths.cadIoHostProject,
    destinationSelector: options.dialogs
      ? { request: (signal) => options.dialogs!.chooseDirectory(signal) }
      : undefined,
    processRunner: hostProcessRunner
  });
  // Every route resolves through the active session rather than a captured
  // application, so opening or switching a drawing needs no route rebuild.
  const registry = createDrawingSessionRegistry({
    first: { displayName: basename(drawingPath), application }
  });
  const active = createActiveApplicationProxy(registry);
  const drawingWorkspace = createDrawingWorkspace(
    workspace,
    drawingPath,
    active.capabilities,
    () => active.currentIndex(),
    () => active.currentDrawingPath()
  );
  const providers = createProviderRegistry(workspace);
  const chatService = createChatService({
    providers,
    loadActiveIndex: async () => active.currentIndex()
  });
  const skills = createSkillGatewayRoutes({
    skillRoot: options.skillRoot ?? resolve(paths.repositoryRoot, "skills"),
    capabilities: active.capabilities,
    capabilityVersion: options.capabilityVersion
  });
  const exports = createExportCapabilityRoutes(active);
  const sessions = createDrawingSessionRoutes({
    registry,
    dialogs: options.dialogs,
    async openSession(canonicalPath, displayName) {
      // The dialog already produced a canonical path a person chose, so the
      // opened drawing is its own workspace root: it may sit anywhere.
      registry.add({
        displayName,
        application: await createCadApplication({
          workspaceRoot: dirname(canonicalPath),
          drawingPath: basename(canonicalPath),
          exportRoot,
          dwgVersionManifestPath: paths.dwgVersionManifest,
          cadIoHostProjectPath: paths.cadIoHostProject,
          destinationSelector: options.dialogs
            ? { request: (signal) => options.dialogs!.chooseDirectory(signal) }
            : undefined,
          processRunner: hostProcessRunner
        })
      });
    }
  });

  return createProviderGateway({
    getDrawing: () => drawingWorkspace.getIndex(),
    inspect: ({ checks }, signal) => drawingWorkspace.inspect(checks, signal),
    getStatuses: () => getProviderStatuses(providers),
    chat: (request, signal) => chatService.chat(request, signal),
    edit: (name, input, signal) => active.capabilities.execute(name, input, signal),
    additionalRoute: async (request, response, pathname, signal) => {
      if (await sessions.handle(request, response, pathname, signal)) return true;
      if (await exports.handle(request, response, pathname, signal)) return true;
      return skills.handle(request, response, pathname, signal);
    }
  });
}

if (isEntrypoint()) {
  // Only the long-running local gateway can show a dialog. Test and headless
  // processes construct the server directly and supply none, which keeps the
  // export root serving destinations and hides the open control.
  const server = await createCadGatewayServer({
    dialogs: process.platform === "win32" && process.env.DWG_HOST_DIALOGS !== "off"
      ? createWindowsHostDialogProvider({ runner: defaultProcessRunner })
      : undefined
  });
  const port = Number(process.env.DWG_GATEWAY_PORT ?? 4317);
  server.listen(port, "127.0.0.1", () => {
    console.log(`DWG provider gateway listening on http://127.0.0.1:${port}`);
  });
  const shutdown = () => server.close(() => process.exit(0));
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

function isEntrypoint(): boolean {
  const entry = process.argv[1];
  return entry !== undefined && import.meta.url === pathToFileURL(resolve(entry)).href;
}
