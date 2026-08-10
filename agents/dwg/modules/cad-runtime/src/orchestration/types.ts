export type AgentId =
  | "orchestrator"
  | "drawing-index-agent"
  | "search-agent"
  | "rule-check-agent"
  | "evidence-agent"
  | "viewer-agent"
  | "report-agent";

export interface AgentManifest {
  id: AgentId;
  displayName: string;
  purpose: string;
  execution: "deterministic" | "tool-driven" | "hybrid";
  readiness: "active" | "planned";
  allowedTools: readonly string[];
  inputKinds: readonly string[];
  outputKinds: readonly string[];
  evidencePolicy: "required" | "pass-through" | "not-applicable";
  canDelegate: boolean;
  maxConcurrency: number;
}
