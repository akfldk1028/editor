import type { AgentId, AgentManifest } from "./types.js";

const AGENT_MANIFESTS = [
  {
    id: "orchestrator",
    displayName: "Inspection Orchestrator",
    purpose: "Build a bounded inspection plan, dispatch one specialist layer, and own completion or rejection.",
    execution: "hybrid",
    readiness: "active",
    allowedTools: [],
    inputKinds: ["inspection-request"],
    outputKinds: ["inspection-plan", "inspection-run"],
    evidencePolicy: "not-applicable",
    canDelegate: true,
    maxConcurrency: 1
  },
  {
    id: "drawing-index-agent",
    displayName: "Drawing Index Agent",
    purpose: "Open source drawings read-only, build the versioned CAD index, and surface unsupported content.",
    execution: "tool-driven",
    readiness: "active",
    allowedTools: [
      "cad.open_drawing",
      "cad.build_index",
      "cad.list_unsupported"
    ],
    inputKinds: ["drawing-path"],
    outputKinds: ["drawing-session", "index-summary", "unsupported-summary"],
    evidencePolicy: "pass-through",
    canDelegate: false,
    maxConcurrency: 1
  },
  {
    id: "search-agent",
    displayName: "CAD Search Agent",
    purpose: "Query indexed layers, types, text, and stable entity records using deterministic CAD tools.",
    execution: "tool-driven",
    readiness: "active",
    allowedTools: [
      "cad.get_layers",
      "cad.find_entities_by_layer",
      "cad.find_entities_by_type",
      "cad.find_text",
      "cad.get_entity"
    ],
    inputKinds: ["layer-check", "type-check", "text-check", "entity-check"],
    outputKinds: ["cad-tool-matches"],
    evidencePolicy: "required",
    canDelegate: false,
    maxConcurrency: 3
  },
  {
    id: "rule-check-agent",
    displayName: "Drawing Rule Check Agent",
    purpose: "Run deterministic closure, duplicate, area, clearance, and standards checks after geometry tools exist.",
    execution: "tool-driven",
    readiness: "planned",
    allowedTools: [],
    inputKinds: ["rule-check"],
    outputKinds: ["rule-findings"],
    evidencePolicy: "required",
    canDelegate: false,
    maxConcurrency: 3
  },
  {
    id: "evidence-agent",
    displayName: "Evidence Verification Agent",
    purpose: "Reject claims that lack stable entity identity, layer, type, handle, or bounding box evidence.",
    execution: "deterministic",
    readiness: "active",
    allowedTools: [],
    inputKinds: ["cad-tool-matches", "rule-findings"],
    outputKinds: ["evidence-verification"],
    evidencePolicy: "pass-through",
    canDelegate: false,
    maxConcurrency: 1
  },
  {
    id: "viewer-agent",
    displayName: "Viewer Action Agent",
    purpose: "Apply verified entity selection, highlight, and zoom after a viewer session adapter exists.",
    execution: "tool-driven",
    readiness: "planned",
    allowedTools: [],
    inputKinds: ["verified-entity-selection"],
    outputKinds: ["viewer-action-result"],
    evidencePolicy: "required",
    canDelegate: false,
    maxConcurrency: 1
  },
  {
    id: "report-agent",
    displayName: "Inspection Report Agent",
    purpose: "Write evidence-backed sidecar inspection reports after the report contract and writer exist.",
    execution: "hybrid",
    readiness: "planned",
    allowedTools: [],
    inputKinds: ["verified-findings", "inspection-limitations"],
    outputKinds: ["inspection-sidecar"],
    evidencePolicy: "required",
    canDelegate: false,
    maxConcurrency: 1
  }
] as const satisfies readonly AgentManifest[];

const AGENT_BY_ID = new Map<AgentId, AgentManifest>(
  AGENT_MANIFESTS.map((manifest) => [manifest.id, manifest])
);

export function listAgentManifests(): readonly AgentManifest[] {
  return AGENT_MANIFESTS;
}

export function getAgentManifest(id: AgentId): AgentManifest {
  const manifest = AGENT_BY_ID.get(id);
  if (!manifest) {
    throw new Error(`Unknown agent: ${id}`);
  }
  return manifest;
}
