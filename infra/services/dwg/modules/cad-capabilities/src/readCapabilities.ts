import {
  MAX_CAD_SEARCH_QUERY_CHARS,
  parseCadDrawingComparisonQuery,
  parseCadScheduleQuery,
  type CadEntityIndex,
  type CadEntityIndexItem,
  type CadEntityMatch
} from "@dwg/contracts";
import { compareCadDrawings, extractCadSchedule } from "@dwg/cad-query";

import type {
  CadCapabilityModule,
  CadCapabilityName,
  CadCapabilityRuntime,
  ReadCapabilityDependencies
} from "./contracts.js";

const readCapabilityNames = [
  "document.open",
  "document.describe",
  "query.layers",
  "query.entities",
  "query.text",
  "query.schedule",
  "query.compare"
] as const satisfies readonly CadCapabilityName[];

export function createReadCapabilityModule(
  deps: ReadCapabilityDependencies
): CadCapabilityModule {
  return {
    names: readCapabilityNames,
    async execute(name, input, signal) {
      requireNotAborted(signal);
      let result: unknown;
      switch (name) {
        case "document.open":
          result = await openDrawing(input, deps, signal);
          break;
        case "document.describe":
          result = describeDrawing(input, deps);
          break;
        case "query.layers":
          result = { layers: requireIndex(input, deps).layers };
          break;
        case "query.entities":
          result = queryEntities(input, deps);
          break;
        case "query.text":
          result = findText(input, deps);
          break;
        case "query.schedule":
          result = extractSchedule(input, deps, signal);
          break;
        case "query.compare":
          result = compareDrawings(input, deps, signal);
          break;
      }
      requireNotAborted(signal);
      return result;
    }
  };
}

export function composeCadCapabilityModules(
  modules: readonly CadCapabilityModule[]
): CadCapabilityRuntime {
  const routes = new Map<CadCapabilityName, CadCapabilityModule>();
  for (const module of modules) {
    for (const name of module.names) {
      if (routes.has(name)) {
        throw new Error(`Duplicate CAD capability name: ${name}`);
      }
      routes.set(name, module);
    }
  }

  return {
    async execute(name, input, signal) {
      const module = routes.get(name);
      if (!module) {
        throw new Error(`Unknown CAD capability: ${name}`);
      }
      return module.execute(name, input, signal);
    }
  };
}

async function openDrawing(
  input: unknown,
  deps: ReadCapabilityDependencies,
  signal?: AbortSignal
) {
  const index = await deps.open(asString(input, "path"), signal);
  return {
    drawingId: index.drawingId,
    source: index.source,
    warnings: index.unsupported.length > 0 ? ["unsupported-entities-present"] : []
  };
}

function describeDrawing(input: unknown, deps: ReadCapabilityDependencies) {
  const index = requireIndex(input, deps);
  return {
    drawingId: index.drawingId,
    indexUri: `cad://drawings/${index.drawingId}/index`,
    summary: index.summary,
    unsupported: index.unsupported
  };
}

function queryEntities(input: unknown, deps: ReadCapabilityDependencies) {
  const args = asArguments(input);
  const index = requireIndex(args, deps);

  if ("layer" in args) {
    const layer = asString(args, "layer");
    return {
      matches: index.entities
        .filter((entity) => entity.layer === layer)
        .map((entity) => toMatch(entity, "layer equals query"))
    };
  }
  if ("type" in args) {
    const type = asString(args, "type").toUpperCase();
    return {
      matches: index.entities
        .filter((entity) => entity.type.toUpperCase() === type)
        .map((entity) => toMatch(entity, "type equals query"))
    };
  }
  if ("entityIdOrHandle" in args) {
    const entityIdOrHandle = asString(args, "entityIdOrHandle");
    const entity = index.entities.find(
      (item) => item.id === entityIdOrHandle || item.handle === entityIdOrHandle
    );
    if (!entity) {
      throw new Error(`Entity not found: ${entityIdOrHandle}`);
    }
    return { entity };
  }
  throw new Error("Expected entity query: layer, type, or entityIdOrHandle");
}

function findText(input: unknown, deps: ReadCapabilityDependencies) {
  const args = asArguments(input);
  const index = requireIndex(args, deps);
  const query = asString(args, "query");
  if (query.length > MAX_CAD_SEARCH_QUERY_CHARS) {
    throw new Error(`query exceeds ${MAX_CAD_SEARCH_QUERY_CHARS} characters`);
  }
  if (args.regex === true && /[()]/.test(query)) {
    throw new Error("Regex grouping is not supported");
  }
  const regex = args.regex === true ? new RegExp(query, "i") : null;

  return {
    matches: index.entities
      .filter((entity) => entity.text !== null && (
        regex ? regex.test(entity.text) : entity.text.toLowerCase().includes(query.toLowerCase())
      ))
      .map((entity) => ({ ...toMatch(entity, "text contains query"), text: entity.text }))
  };
}

function extractSchedule(
  input: unknown,
  deps: ReadCapabilityDependencies,
  signal?: AbortSignal
) {
  const request = parseCadScheduleQuery(input);
  const index = requireDrawing(request.drawingId, deps);
  requireNotAborted(signal);
  return extractCadSchedule(index, {
    sourceHandles: groundedScheduleHandles(index, request.matches),
    yTolerance: request.yTolerance
  });
}

function groundedScheduleHandles(
  index: CadEntityIndex,
  matches: readonly CadEntityMatch[]
): string[] {
  const handles = new Set<string>();
  for (const match of matches) {
    if (match.handle === null) continue;
    const entity = index.entities.find((item) => item.handle === match.handle);
    if (!entity || !sameScheduleEvidence(entity, match)) continue;
    handles.add(match.handle);
  }
  return [...handles].sort();
}

function sameScheduleEvidence(
  entity: CadEntityIndexItem,
  match: CadEntityMatch
): boolean {
  return (
    entity.id === match.id &&
    entity.handle === match.handle &&
    entity.type === match.type &&
    entity.layer === match.layer &&
    entity.text === (match.text ?? null) &&
    JSON.stringify(entity.bbox) === JSON.stringify(match.bbox)
  );
}

function compareDrawings(
  input: unknown,
  deps: ReadCapabilityDependencies,
  signal?: AbortSignal
) {
  const request = parseCadDrawingComparisonQuery(input);
  const before = requireDrawing(request.beforeDrawingId, deps);
  requireNotAborted(signal);
  const after = requireDrawing(request.afterDrawingId, deps);
  requireNotAborted(signal);
  return compareCadDrawings(before, after, { signal });
}

function requireIndex(input: unknown, deps: ReadCapabilityDependencies): CadEntityIndex {
  return requireDrawing(asString(input, "drawingId"), deps);
}

function requireDrawing(drawingId: string, deps: ReadCapabilityDependencies): CadEntityIndex {
  const index = deps.get(drawingId);
  if (!index) {
    throw new Error(`Drawing not opened: ${drawingId}`);
  }
  return index;
}

function requireNotAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw new Error("CAD read operation was cancelled.");
  }
}

function toMatch(entity: CadEntityIndexItem, reason: string): CadEntityMatch {
  return {
    id: entity.id,
    handle: entity.handle,
    type: entity.type,
    layer: entity.layer,
    bbox: entity.bbox,
    reason,
    confidence: entity.bbox ? 1 : 0.5
  };
}

function asArguments(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Expected CAD capability input object");
  }
  return value as Record<string, unknown>;
}

function asString(input: unknown, name: string): string {
  const value = asArguments(input)[name];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Expected string argument: ${name}`);
  }
  return value;
}
