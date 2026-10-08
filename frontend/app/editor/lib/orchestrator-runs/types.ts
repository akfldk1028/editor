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

export interface RunSite {
  status: string
  code: string | null
  facts_known: number | null
  facts_total: number | null
  facts_missing: string[]
}

export interface OrdinanceReceipt {
  articles: string[]
  edition_id: string | null
  effective_date: string | null
  assessment_date: string | null
}

export interface RunLaw {
  status: string
  site_area_m2: number | null
  bcr_pct: number | null
  far_pct: number | null
  max_floors: number | null
  policy_id: string | null
  parcel_label: string | null
  building_type: string | null
  /** Null when Law sent none or the 8000-character communication cap cut it off (see `notes`). */
  ordinance: OrdinanceReceipt | null
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

/** The Orchestrator row of `GET /platform/status`, reduced to what a feed line needs. */
export interface OrchestratorConnection {
  state: 'up' | 'down' | 'invalid'
  agentsUp: number
  agentsTotal: number
}
