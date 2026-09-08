import type {
  InspectionCheck,
  InspectionEvent,
  InspectionRun
} from "@dwg/contracts";

import type { CadToolMatch } from "../domain/cad-index/types.js";
import {
  verifyMatches
} from "./evidenceVerifier.js";
import type { AgentId } from "./types.js";

type ToolArguments = Record<string, unknown>;

export interface OrchestrationCadRuntime {
  call(name: string, args: ToolArguments, signal?: AbortSignal): Promise<unknown>;
}

export interface InspectionRequest {
  path: string;
  checks: readonly InspectionCheck[];
}

export function createInspectionOrchestrator(
  runtime: OrchestrationCadRuntime
) {
  return {
    async run(request: InspectionRequest, signal?: AbortSignal): Promise<InspectionRun> {
      requireNotAborted(signal);
      const events: InspectionEvent[] = [];
      const pushEvent = (
        agentId: AgentId,
        action: string,
        status: InspectionEvent["status"]
      ) => {
        events.push({
          sequence: events.length + 1,
          agentId,
          action,
          status
        });
      };

      pushEvent("orchestrator", "plan", "planned");

      const opened = asRecord(
        await runtime.call("cad.open_drawing", { path: request.path }, signal)
      );
      const drawingId = asRequiredString(opened.drawingId, "drawingId");
      const warnings = asStringArray(opened.warnings);
      pushEvent("drawing-index-agent", "open-drawing", "completed");

      await runtime.call("cad.build_index", { drawingId }, signal);
      pushEvent("drawing-index-agent", "build-index", "completed");

      const unsupportedResult = asRecord(
        await runtime.call("cad.list_unsupported", { drawingId }, signal)
      );
      warnings.push(...formatUnsupported(unsupportedResult.unsupported));

      const matchGroups = await runWithConcurrency(
        request.checks,
        3,
        async (check) => runSearchCheck(runtime, drawingId, check, signal)
      );
      for (const check of request.checks) {
        pushEvent("search-agent", `search-${check.kind}`, "completed");
      }

      const verification = verifyMatches(matchGroups.flat());
      pushEvent(
        "evidence-agent",
        "verify-evidence",
        verification.status === "accepted" ? "completed" : "rejected"
      );

      if (verification.status === "rejected") {
        pushEvent("orchestrator", "reject", "rejected");
        return {
          status: "rejected",
          drawingId,
          events,
          findings: [],
          issues: verification.issues,
          warnings
        };
      }

      pushEvent("orchestrator", "complete", "completed");
      return {
        status: "completed",
        drawingId,
        events,
        findings: verification.matches,
        issues: [],
        warnings
      };
    }
  };
}

async function runSearchCheck(
  runtime: OrchestrationCadRuntime,
  drawingId: string,
  check: InspectionCheck,
  signal?: AbortSignal
): Promise<CadToolMatch[]> {
  let name: string;
  let args: ToolArguments;

  switch (check.kind) {
    case "layer":
      name = "cad.find_entities_by_layer";
      args = { drawingId, layer: check.value };
      break;
    case "type":
      name = "cad.find_entities_by_type";
      args = { drawingId, type: check.value };
      break;
    case "text":
      name = "cad.find_text";
      args = {
        drawingId,
        query: check.value,
        regex: check.regex ?? false
      };
      break;
  }

  requireNotAborted(signal);
  const result = asRecord(await runtime.call(name, args, signal));
  if (!Array.isArray(result.matches)) {
    throw new Error(`Expected matches array from ${name}`);
  }
  return result.matches as CadToolMatch[];
}

function requireNotAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw signal.reason;
}

async function runWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  operation: (item: T) => Promise<R>
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let nextIndex = 0;

  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await operation(items[index]);
    }
  }

  const workerCount = Math.min(limit, items.length);
  await Promise.all(
    Array.from({ length: workerCount }, () => worker())
  );
  return results;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Expected CAD tool result object");
  }
  return value as Record<string, unknown>;
}

function asRequiredString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Expected CAD tool string field: ${name}`);
  }
  return value;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

function formatUnsupported(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => {
    const record = asRecord(item);
    return [
      "unsupported",
      String(record.type ?? "UNKNOWN"),
      String(record.count ?? 0),
      String(record.reason ?? "unspecified")
    ].join(":");
  });
}
