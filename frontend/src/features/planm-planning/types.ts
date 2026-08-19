export type RunStatus =
  | "queued"
  | "running"
  | "needs_input"
  | "retryable"
  | "blocked"
  | "delivered"
  | "approved";

export interface PlanmRun {
  contract_version: "planm-run/v1";
  run_id: string;
  project_id: string;
  status: RunStatus;
  stage: string;
  approved_alternative_id: string | null;
  violations: Array<{ code: string; message: string }>;
  unresolved_facts?: string[];
}

export interface Alternative {
  alternative_id: string;
  strategy: string;
  rank: number;
  score: number;
  accepted: boolean;
  internal_validation: string;
  render_validation: string;
  regulatory_screening: string;
}

export interface RejectedFamily {
  family: string;
  reasons: string[];
}

export interface AlternativesResult {
  project_id: string;
  accepted_count: number;
  accepted_alternative_ids: string[];
  alternatives: Alternative[];
  rejected_families?: RejectedFamily[];
}

/**
 * Shape families the plate builder can emit. Between them they cover every
 * footprint `resources/scripts/sweep_alternatives.py` measures: `u` carries the
 * notched plate as well, and `sloped` is the diagonal form of `l`.
 */
export type ShapeFamily = "rectangle" | "l" | "t" | "u" | "sloped" | "chamfered";

export type TravelLimit = "general_30" | "qualified_50" | "highrise_residential_40";

/** Sprinkler facts the screening reads. "unknown" asserts nothing. */
export type SprinklerState = "unknown" | "none" | "standard" | "qualifying";

export interface MassForm {
  projectId: string;
  floors: number;
  width: number;
  depth: number;
  shape: ShapeFamily;
  /** Plan width of the material removed from the top of the plate, in metres. */
  cutWidth: number;
  /** Depth of that removal from the top edge, in metres. */
  cutDepth: number;
  commercialShare: number;
  jurisdiction: string;
  effectiveDate: string;
  travelLimit: TravelLimit | "";
  sprinkler: SprinklerState;
}

export interface CadHandoff {
  contract_version: "planm-cad-handoff/v1";
  alternative_id: string;
  drawing_path: string;
  source_floor_count: number;
  entity_count: number;
  units: "meters";
  dwg_validation: "not_checked" | "passed";
}

export interface DwgInspection {
  contract_version: "planm-dwg-inspection/v1";
  alternative_id: string;
  drawing_path: string;
  layer: string;
  status: "passed";
  evidence: {
    warning_codes: string[];
    result: {
      matches: Array<{
        id: string;
        handle: string | null;
        type: string;
        layer: string;
        bbox: { min: number[]; max: number[] } | null;
        reason: string;
        confidence: number;
      }>;
    };
  };
}
