import { readFile } from "node:fs/promises";
import { extname } from "node:path";

import {
  type CadCapabilityRuntime
} from "@dwg/cad-capabilities";
import type { CadEntityIndex } from "@dwg/contracts";

import { buildIndexFromDxfFileName } from "../../parsers/dxf/dxfIndexer.js";
import { buildIndexFromDwgFile } from "../../parsers/dwg/acadSharpIndexer.js";
type ToolArguments = Record<string, unknown>;

export interface CadToolRuntime {
  call(name: string, args: ToolArguments, signal?: AbortSignal): Promise<any>;
}

export function createCadToolRuntime(
  runtime: CadCapabilityRuntime
): CadToolRuntime {
  return {
    call(name, args, signal) {
      return executeCadTool(runtime, name, args, signal);
    }
  };
}

export async function executeCadTool(
  runtime: CadCapabilityRuntime,
  name: string,
  args: ToolArguments,
  signal?: AbortSignal
): Promise<unknown> {
  switch (name) {
    case "cad.open_drawing":
      return runtime.execute("document.open", args, signal);
    case "cad.build_index": {
      const description = await runtime.execute("document.describe", args, signal) as {
        drawingId: string;
        indexUri: string;
        summary: unknown;
      };
      return {
        drawingId: description.drawingId,
        indexUri: description.indexUri,
        summary: description.summary
      };
    }
    case "cad.get_layers":
      return runtime.execute("query.layers", args, signal);
    case "cad.find_entities_by_layer":
    case "cad.find_entities_by_type":
    case "cad.get_entity":
      return runtime.execute("query.entities", args, signal);
    case "cad.find_text":
      return runtime.execute("query.text", args, signal);
    case "cad.list_unsupported": {
      const description = await runtime.execute("document.describe", args, signal) as {
        unsupported: unknown;
      };
      return { unsupported: description.unsupported };
    }
    case "cad_export_report":
      return runtime.execute("export.report", args, signal);
    case "cad_export_drawing":
      return runtime.execute("export.drawing", args, signal);
    case "cad_get_export_verification":
      return runtime.execute("verification.get", args, signal);
    case "cad_request_export_destination":
      throw new Error("MCP_ELICITATION_UNSUPPORTED");
    default:
      throw new Error(`Unknown CAD tool: ${name}`);
  }
}

export async function buildCadIndexForPath(
  path: string,
  signal?: AbortSignal
): Promise<CadEntityIndex> {
  if (signal?.aborted) {
    throw signal.reason;
  }
  const extension = extname(path).toLowerCase();
  if (extension === ".dwg") {
    return buildIndexFromDwgFile(path);
  }
  if (extension === ".dxf") {
    return buildIndexFromDxfFileName(await readFile(path, "utf8"), path);
  }
  throw new Error(`Unsupported drawing format: ${extension || "(none)"}`);
}
