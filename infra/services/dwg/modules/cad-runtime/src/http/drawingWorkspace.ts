import type {
  CadEntityIndex,
  InspectionCheck,
  InspectionRun
} from "@dwg/contracts";
import type { CadCapabilityRuntime } from "@dwg/cad-capabilities";

import { buildCadIndexForPath, executeCadTool } from "../application/cad-tools/runtime.js";
import { resolveWorkspaceCadPath } from "../application/drawing-access/workspacePath.js";
import {
  createInspectionOrchestrator,
  type OrchestrationCadRuntime
} from "../orchestration/orchestrator.js";

export { resolveWorkspaceCadPath as resolveWorkspaceDrawingPath }
  from "../application/drawing-access/workspacePath.js";

export interface DrawingWorkspace {
  getIndex(): Promise<CadEntityIndex>;
  inspect(checks: readonly InspectionCheck[], signal?: AbortSignal): Promise<InspectionRun>;
}

export function createDrawingWorkspace(
  workspaceRoot: string,
  configuredPath: string,
  capabilities: CadCapabilityRuntime,
  getCurrentIndex?: () => CadEntityIndex,
  getCurrentDrawingPath?: () => string | null
): DrawingWorkspace {
  const drawingPath = resolveWorkspaceCadPath(workspaceRoot, configuredPath);

  const runtime: OrchestrationCadRuntime = {
    call: (name, args, signal) => executeCadTool(capabilities, name, args, signal)
  };
  const orchestrator = createInspectionOrchestrator(runtime);
  return {
    getIndex: async () => getCurrentIndex ? getCurrentIndex() : buildCadIndexForPath(drawingPath),
    inspect: (checks, signal) => orchestrator.run({
      path: getCurrentDrawingPath?.() ?? drawingPath,
      checks
    }, signal)
  };
}
