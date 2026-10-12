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
  /** The A2A task and context the call ran as (door, 2026-10-12); absent on older records. */
  a2a_task_id?: string | null
  a2a_context_id?: string | null
  redacted?: boolean
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
  /** What the run asks the person for (door `pending_fields`, e.g. `building_type`); answered by a new run with the condition set. */
  pending_fields?: string[]
  pending_note?: string | null
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
  /** The 용도지역 split behind the caps; null for a single zone or when Law sent none. */
  zone_split?: ZoneSplit | null
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
  /** Fields the run is waiting on (empty when none). */
  pending_fields?: string[]
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

/** How the backend's router decided: a skill called now, a goal handed off, or a question back to the user. */
export interface AskRoute {
  /** 'answer': the Orchestrator replied itself; its words are `instruction`. 'agent': a registered agent without a
   * role module owns the question; `delegate` carries its card and the Orchestrator's instruction. */
  kind: 'skill' | 'goal' | 'ask' | 'answer' | 'agent'
  agent: string | null
  skill: string | null
  goal: string | null
  confidence: number
  reason: string
  choices: { agent: string; label: string }[]
  /** Who decided: a deterministic pattern, the Orchestrator's model judgment, the keyword fallback, or the user's pick. */
  decided_by?: 'pattern' | 'llm' | 'rules' | 'user'
  /** What the Orchestrator told the chosen agent (Magentic-One `instruction_or_question`); null when rules decided. */
  instruction?: string | null
}

export type LawAnswerBody =
  | { kind: 'search'; items: LawSearchItem[]; total: number; degraded: boolean; legal_evidence: LegalEvidence | null }
  | {
      kind: 'ordinance'
      ordinance: { name: string | null; ordinance_id: string | null; edition_id: string | null; effective_date: string | null; url: string | null }
      matches: { article: string | null; title: string | null; text: string | null }[]
      legal_evidence: LegalEvidence | null
    }
  | SiteLocateBody

/** A typed address or PNU, located by the editor's own geocoder (`site_locate`): the parcel for the map to open and select. */
export interface SiteLocateBody {
  kind: 'site'
  query: string
  pnu: string | null
  address: string | null
  coordinates: { x: number; y: number } | null
  error: string | null
}

/** `POST /platform/ask` — one of three shapes by `route.kind`, every key always present. */
export interface AskAnswer {
  question: string
  route: AskRoute
  /** `skill`: the agent and tool that answered, and its answer. */
  agent: string | null
  tool: string | null
  trace_id: string | null
  version: string | null
  answer: LawAnswerBody | null
  /** `goal`: the catalog goal this question belongs to (its owners, whether the door takes it). */
  handoff: { goal: string; label: string; owners: string[]; available: boolean } | null
  /** `agent`: the registered agent the question belongs to, in its own card's words; `available` = its card answered. */
  delegate?: { agent: string; label: string; description: string | null; instruction: string | null; skills: { id: string; name: string }[]; available: boolean } | null
  /** The review item the question was about (law artifact), echoed with the lot and date it was asked for. */
  clause?: { item_id: string; title: string; pnu: string | null; assessment_date: string | null } | null
}

/** What the conversation says about a Law Agent land analysis (`POST /platform/law-analysis`); the artifact shows the rest. */
/** How the parcel was divided between its 용도지역 for 제84조 and what was excluded as boundary tolerance (disclosed). */
export interface ZoneSplit {
  areas_m2: Record<string, number>
  excluded_slivers: { zone: string; area_m2: number; width_m: number; share: number; reason: string; folded_into: string }[]
  uncovered_m2: number
  notes: string[]
  removed_zones?: string[]
}

export interface LandAnalysisSummary {
  zones: string[]
  unmatched_zones: string[]
  zone_areas_m2: Record<string, number>
  zone_split?: ZoneSplit | null
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

/** One goal the product can ask the Orchestrator for (`GET /platform/capabilities`). */
/** `GET /platform/host/status`: every agent's state from the host's last tick (agent ids). */
/** One agent of the Orchestrator's catalog (`GET /platform/agents`): registered or not, reachable or not, and the skills it declares. */
export interface AgentSummary {
  agent_id: string
  label: string
  capabilities: string[]
  implementation_status: string
  connection_status: string
  checked_at: string | null
  evidence_ref: string | null
  /** The agent's own words from its A2A card; absent or null when the card was unreachable. */
  description?: string | null
  skills?: { id: string; name: string; description: string }[] | null
}

/** One task an agent still holds (official A2A ListTasks via `GET /platform/agents/{agent}/tasks`): the request it got and its full, uncut reply. */
export interface AgentTask {
  id: string
  context_id: string | null
  state: string
  at: string | null
  tool: string | null
  request_text: string
  response_text: string
}

/** One recorded call of the 협업 장부 (`GET /platform/ledger/hops`): OpenTelemetry GenAI names, A2A facts, the texts as GenAI messages. */
export interface HopMessage { role: string; parts: { type: string; content: string }[] }
export interface Hop {
  id: number
  trace_id: string
  span_id: string
  parent_span_id: string | null
  ts_start: string
  ts_end: string | null
  operation: 'invoke_agent' | 'execute_tool' | 'start_run'
  from_agent: string
  to_agent: string
  tool: string | null
  status: 'OK' | 'ERROR' | 'UNSET'
  error_type: string | null
  state: string | null
  elapsed_ms: number | null
  conversation_id: string | null
  run_id: string | null
  task_id: string | null
  project: string | null
  branch: string | null
  hop: number | null
  source: 'agent' | 'orchestrator' | 'editor'
  input_messages: HopMessage[] | null
  output_messages: HopMessage[] | null
  attrs: Record<string, unknown>
  recorded_at: string
}

export interface HostStatus {
  at: string | null
  daemon: { pid: number | null; stale: boolean }
  agents: Record<string, { state: 'up' | 'down' | 'starting' | 'restarting' | 'gave_up' | 'absent'; up: boolean | null; lease_until: string | null; idle_in_s: number | null }>
}

/** `POST /platform/host/ensure`: who came up, who did not, how long it took. */
export interface EnsureAnswer {
  requested: string[]
  up: string[]
  failed: { agent: string; error: string }[]
  waited_s: number
  lease_until: string | null
}

export interface Goal {
  id: string
  label: string
  /** The owner sequence the Orchestrator's flow walks, in order. */
  owners: string[]
  inputs: string[]
  optional: string[]
  /** The editor door accepts it today. */
  available: boolean
  /** The conversation shows it as a choice after a site is selected (when also available). */
  offer: boolean
}

export interface Capabilities {
  goals: Goal[]
  conversation: { ask: boolean; law_analysis: boolean }
  source: string
}

/** The Orchestrator row of `GET /platform/status`, reduced to what a feed line needs. */
export interface OrchestratorConnection {
  state: 'up' | 'down' | 'invalid'
  agentsUp: number
  agentsTotal: number
}
