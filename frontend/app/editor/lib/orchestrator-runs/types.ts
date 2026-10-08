/**
 * Orchestrator runs as the editor backend serves them (`/api/v1/platform/...`): the run door, the
 * project bindings, and the parsed `results` contract of `modules/platform/run_results/parse.py`.
 * Shared by every artifact slice; slices never import these from each other.
 */

export interface Communication {
  id: string
  task_id: string
  tool: string
  agent: string | null
  state: string
  request_text: string | null
  response_text: string | null
  transport: 'a2a' | 'unknown'
  truncated: boolean
}

export interface Communications {
  communications: Communication[]
  communications_available: boolean
  communications_truncated: boolean
}

export interface RunSummary extends Communications {
  run_id: string
  request_id: string
  owner_project_id: string
  branch_id: string
  goal: string
  status: string
  receipt_task_ids: string[]
  pending_input: boolean
  /** W3C trace id (32 hex) of the submission; only the editor's POST answer carries it. */
  trace_id?: string
}

export interface RunContext {
  scene_revision: number
  source_versions: Record<string, number>
}

/** What the editor door accepts today (schemas/platform.py `RunCreate.supported_request`), minus specialist reviews. */
export type RunRequest =
  | { goal: 'health' }
  | { goal: 'limits'; pnu: string; building_type?: string; assessment_date?: string; parcels?: string[] }

export interface ProjectBinding {
  project_id: string
  owner_project_id: string
  branch_id: string
  scene_id: string
  scene_revision: number
  scene_project_id: string | null
}

/** One agent step of a run, in communication order. */
export interface RunStep {
  task_id: string | null
  agent: string | null
  tool: string | null
  state: string
  summary: string | null
  truncated: boolean
}

/** One of the Site Agent's eight site facts (`sitecontextagent/facts.py` SITE_KEYS) as read from its `state_patch`. */
export interface SiteFact {
  /** `site.boundary`, `site.roads`, `site.access`, `site.north`, `site.terrain`, `site.utilities`, `site.hazards`, `site.context`. */
  key: string
  /** measured · derived · estimated · unknown */
  confidence: string | null
  source: string | null
  as_of: string | null
  /** "면적 1,006.65㎡", "접도 5건 · 폭 15m, 20m" … */
  summary: string | null
}

export interface RunSite {
  status: string
  code: string | null
  facts_known: number | null
  facts_total: number | null
  facts_missing: string[]
  /** The facts readable in the answer (a cut answer keeps the first ones). */
  facts: SiteFact[]
}

export interface OrdinanceSource {
  name: string | null
  ordinance_id: string | null
  edition_id: string | null
  effective_date: string | null
  url: string | null
}

export interface OrdinanceReceipt {
  articles: string[]
  edition_id: string | null
  effective_date: string | null
  assessment_date: string | null
  sources: OrdinanceSource[]
  limitations: string[]
}

export interface RunLaw {
  status: string
  site_area_m2: number | null
  bcr_pct: number | null
  far_pct: number | null
  max_floors: number | null
  /** 건폐율 × 대지면적 and 용적률 × 대지면적, as Law computed them. */
  ground_capacity_m2: number | null
  far_capacity_m2: number | null
  zones: string[]
  national_bcr_ceiling_pct: number | null
  national_far_ceiling_pct: number | null
  articles: { bcr: string | null; far: string | null; height: string | null }
  height: { status: string | null; limit_m: number | null }
  policy_id: string | null
  parcel_label: string | null
  building_type: string | null
  /** Null when Law sent none or the 8000-character communication cap cut it off (see `notes`). */
  ordinance: OrdinanceReceipt | null
  evidence: { floor_height_m: number | null; datum_measured: boolean | null; frontage_grade: string | null; legal_floor_section_count: number | null }
  sources: { title: string | null; date: string | null }[]
  findings: { finding: string | null; recommended_action: string | null; missing_evidence: string[]; assessment_date: string | null }[]
  truncated: boolean
}

export interface ReviewAction {
  finding: string | null
  raised_by: string | null
  category: string | null
  recommended_action: string | null
  recommended_agents: string[]
  evidence: unknown
}

export interface RunReview {
  status: string
  code: string | null
  missing_evidence: string[]
  actions: ReviewAction[]
}

/** `GET /runs/{id}/results` — every key always present; unknown → null. */
export interface RunResults {
  run_id: string | null
  status: string
  goal: string | null
  pending_input: boolean
  truncated: boolean
  request: { pnu: string | null; parcels: string[]; building_type: string | null; assessment_date: string | null } | null
  steps: RunStep[]
  site: RunSite | null
  law: RunLaw | null
  review: RunReview | null
  missing_evidence_all: string[]
  notes: string[]
  raw: { communications: number; keys: Record<string, number> }
}

/** `GET /projects/{id}/runs/latest`: the run as `GET /runs/{id}` gives it, plus its parsed results. */
export interface RunWithResults extends RunSummary {
  results: RunResults
}

/** A statute passage the Law Agent's `law_search` found (the :8011 statute graph). */
export interface LawSearchItem {
  id: string | null
  law: string | null
  /** 법률 · 시행령 · 시행규칙 … */
  kind: string | null
  article: string | null
  text: string | null
}

export interface LegalEvidence {
  assessment_date: string | null
  currency_status: string | null
  coverage_status: string | null
  reason: string | null
}

/** `POST /platform/ask` — the Law Agent's answer to a typed question, in the backend's one shape. */
export interface AskAnswer {
  question: string
  tool: string
  agent: 'law'
  trace_id: string
  version: string | null
  answer:
    | { kind: 'search'; items: LawSearchItem[]; total: number; degraded: boolean; legal_evidence: LegalEvidence | null }
    | {
        kind: 'ordinance'
        ordinance: { name: string | null; ordinance_id: string | null; edition_id: string | null; effective_date: string | null; url: string | null }
        matches: { article: string | null; title: string | null; text: string | null }[]
        legal_evidence: LegalEvidence | null
      }
}

/** What the conversation says about a Law Agent land analysis (`POST /platform/law-analysis`); the artifact shows the rest. */
export interface LandAnalysisSummary {
  zones: string[]
  unmatched_zones: string[]
  zone_areas_m2: Record<string, number>
  restrictions: string[]
  assessment_status: string | null
  permit_compliance_verified: boolean
  missing_evidence: string[]
}

/** `POST /platform/law-analysis` without the full `analysis` (the law slice types that part). */
export interface LandAnalysisAnswer {
  pnu: string
  agent: 'law'
  trace_id: string
  version: string | null
  /** The parcel's caps from `law_parcel_limits` (district policy / ordinance, area-weighted); null when that call failed. */
  limits: RunLaw | null
  limits_error: string | null
  summary: LandAnalysisSummary
}

/** The Orchestrator row of `GET /platform/status`, reduced to what a feed line needs. */
export interface OrchestratorConnection {
  state: 'up' | 'down' | 'invalid'
  agentsUp: number
  agentsTotal: number
}
