export interface LanguageAxisItem {
  id: string;
  label: string;
  [key: string]: unknown;
}

export type ExplorationAuthority = 'book' | 'engineered' | 'experimental' | 'observed';
export type MassExecutionMode =
  | 'exact_replay'
  | 'fresh_synthesis'
  | 'explicit_program'
  | 'legacy_unspecified';

export interface ExplorationGraphNode {
  id: string;
  kind: string;
  stage: string;
  label: string;
  authority: ExplorationAuthority;
  evidence_ids: string[];
  visible: boolean;
  attributes: Record<string, unknown>;
}

export interface ExplorationGraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  scope: 'execution' | 'evidence' | 'detail' | 'feedback';
  authority: ExplorationAuthority;
}

export interface BookExplorationGraph {
  schema_version: string;
  graph_id: string;
  root_node_ids: string[];
  stage_order: string[];
  catalog_stage_order: string[];
  authority_order: ExplorationAuthority[];
  source_documents: Array<{ id: string; label: string; path: string; sha256: string }>;
  nodes: ExplorationGraphNode[];
  edges: ExplorationGraphEdge[];
  counts: Record<string, number>;
  contracts: Record<string, boolean>;
}

export interface OutcomeGraphNode {
  id: string;
  kind: string;
  label: string;
  attributes: Record<string, unknown>;
}

export interface OutcomeGraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
}

export interface OutcomeGraphSlice {
  schema_version: string;
  status: 'ready' | 'not_found';
  pnu: string;
  root_node_ids: string[];
  nodes: OutcomeGraphNode[];
  edges: OutcomeGraphEdge[];
  counts?: Record<string, number>;
  contracts?: Record<string, boolean>;
}

export interface MassExecutionStage {
  id: string;
  label: string;
  status: 'passed' | 'failed' | 'evaluated' | 'not_evaluated' | 'cache_hit' | 'live_scored' | 'needs_evidence' | 'accepted' | 'rejected';
  required_for_final: boolean;
  node_ids: string[];
  evidence: Record<string, unknown>;
}

export interface MassActivationNode {
  id: string;
  source_id?: string;
  column: string;
  label: string;
  kind: string;
  operator?: string;
  status: string;
  activation: number;
  evidence: Record<string, unknown>;
}

export interface MassExecutionPassport {
  schema_version: string;
  mass_id: string;
  program_name: string;
  program_hash: string;
  structural_hash: string;
  geometry_hash: string;
  visual_hash: string;
  floor_capacity_plan_hash: string;
  final_legal_geometry_hash?: string;
  legal_floor_field_hash?: string;
  candidate_actual_gfa_stop_hash?: string;
  candidate_actual_gfa_stop_certificate?: CandidateActualGfaStopCertificate;
  status: string;
  full_flow_complete: boolean;
  truth_policy: {
    unevaluated_is_never_pass: boolean;
    internal_neuron_claim: boolean;
    causal_program_trace: boolean;
    visual_activation_uses_materialized_evidence_only: boolean;
  };
  stages: MassExecutionStage[];
  activation_graph: {
    schema_version: string;
    internal_neuron_claim: boolean;
    causal_program_trace: boolean;
    nodes: MassActivationNode[];
    edges: Array<{
      id: string;
      source: string;
      target: string;
      relation: string;
      activation: number;
    }>;
  };
  elevation_evidence?: {
    image_proposal?: Record<string, unknown>;
    multi_view_proposal?: Record<string, unknown>;
    [key: string]: unknown;
  };
  agent_collaboration?: {
    final_status: string;
    identity: {
      execution_id: string;
      program_hash: string;
      geometry_hash: string;
      pnu: string;
    };
    evidence: Array<{
      evidence_id: string;
      agent: string;
      status: string;
      summary: string;
      evidence: Record<string, unknown>;
    }>;
    handoffs: Array<Record<string, unknown>>;
  };
  retrieved_references?: Array<{
    id: string;
    source_id: string;
    title: string;
    source: string;
    source_url: string;
    preview_url: string;
    selection_role: string;
    matched_tags: string[];
    program_match_tier: string;
    reference_collection: string;
    score: number | null;
    retrieval_order: number;
    used_by_vlm: boolean;
  }>;
  reference_truth_policy?: {
    retrieved_is_not_vlm_input: boolean;
    active_visual_reference_edge_requires_recorded_vlm_submission: boolean;
    retrieval_launches_paid_vlm: boolean;
  };
  reference_retrieval?: {
    source: string;
    collection_count: number;
    image_count: number;
    project_count: number;
    program_id: string;
    building_type: string;
    geometry_family: string;
    intent_tags: string[];
    query_role: string;
    current_mass_causality: string;
  };
}

export interface CandidateActualGfaStopCertificate {
  schema_version?: string;
  status: string;
  hard_pass: boolean;
  program_hash: string;
  final_geometry_hash: string;
  visual_hash: string;
  legal_floor_field_hash: string;
  candidate_actual_gfa_stop_hash: string;
  selected_floor_count: number;
  achieved_gfa_m2?: number;
  target_gfa_m2?: number;
  [key: string]: unknown;
}

export interface ExecutedMassRecord {
  archive_key: string;
  index: number;
  variant_id: string;
  label: string;
  operation_label: string;
  source_sequence: string;
  execution_mode?: MassExecutionMode;
  source_run_id?: string;
  source_mass_index?: number;
  run_id: string;
  program_type: string;
  program_label: string;
  program_hash: string;
  geometry_hash: string;
  visual_hash: string;
  final_geometry_hash?: string;
  final_legal_geometry_hash?: string;
  legal_floor_field_hash?: string;
  candidate_actual_gfa_stop_hash?: string;
  candidate_actual_gfa_stop_certificate?: CandidateActualGfaStopCertificate;
  candidate_floor_count?: number;
  candidate_target_gfa_m2?: number;
  achieved_gfa_m2?: number;
  dsl: string;
  node_count: number;
  operator_path: string[];
  book_principle_id: string;
  book_scope: string;
  book_orientation: string;
  capacity_alternative_id: string;
  capacity_target_utilization: number | null;
  capacity_achieved_utilization: number | null;
  far_pct: number | null;
  bcr_pct?: number | null;
  total_floor_area_m2?: number | null;
  num_floors?: number | null;
  floor_height_m?: number | null;
  floor_contract_hash?: string;
  floor_capacity_plan_hash?: string;
  parking_required?: number | null;
  parking_provided?: number | null;
  elevation_status?: string;
  matrix_convention?: string;
  floor_matrix_stack?: Array<{
    node_id: string;
    matrix4: number[][];
  }>;
  score: number | null;
  hard_pass: boolean;
  geometry_ready?: boolean;
  vlm_evaluated: boolean;
  preview_url: string;
  passport_url: string;
  image_role: 'actual_run_candidate_render' | 'single_mass_execution_render';
}

export interface ExecutedMassRun {
  run_id: string;
  created_at: string;
  pnu: string;
  site_context_status?: 'site_bound' | 'source_gate_only' | 'unresolved';
  selected_mass_count: number;
  status: 'selected_mass_ready' | 'single_mass_ready' | 'completed_without_selected_mass' | 'running' | 'failed' | 'aborted_memory_pressure' | 'unknown';
  replayable: boolean;
  run_type?: 'portfolio' | 'single_execution';
  execution_mode?: MassExecutionMode;
  source_run_id?: string;
  source_mass_index?: number;
  geometry_hash?: string;
  thumbnail_url?: string;
  full_flow_status?: string;
  vlm_status?: string;
  vlm_hard_pass?: boolean;
  floor_capacity_plan_hash?: string;
}

export interface SingleMassExecutionResponse {
  execution_id: string;
  execution_mode: Exclude<MassExecutionMode, 'legacy_unspecified'>;
  source_run_id: string;
  source_mass_index: number;
  archive_run_id: string;
  status: string;
  geometry_ready: boolean;
  full_flow_status: string;
  program_hash: string;
  geometry_hash: string;
  floor_capacity_plan_hash: string;
  timings_ms: Record<string, number>;
  preview_url: string;
  passport_url: string;
  manifest_url: string;
}

export interface SingleMassVlmReviewResponse {
  schema_version: 'arr.maas.single_execution_vlm_review.v1';
  execution_id: string;
  archive_run_id: string;
  status: string;
  hard_pass: boolean;
  full_flow_status: string;
  model: string;
  response_id: string;
  cache_hit: boolean;
  concept_scores: Record<string, number>;
  critic_actions: string[];
  rationale: string;
  reference_count: number;
  cost_observation: {
    reference_limit: number;
    max_http_attempts: number;
    retries: number;
    candidate_cache_hit: boolean;
    usage: { input_tokens: number; output_tokens: number; total_tokens: number };
  };
}

export interface ExecutedMassManifest {
  editor_provenance?: { kind: string; execution_verified: boolean };
  schema_version: string;
  run_id: string;
  pnu: string;
  run_status: string;
  numeric_status: string;
  source_archive: string;
  mass_count: number;
  selected_run_id: string;
  run_count: number;
  archive_revision: string;
  publishable_20?: boolean;
  publishable_target_count?: number;
  publishable_20_manifest?: {
    status?: string;
    target_count?: number;
    typed_failure_deficits?: Array<Record<string, unknown>>;
    shared_legal_floor_field_hash?: string;
    shared_legal_floor_field_hash_count?: number;
    candidate_actual_gfa_stop_valid_count?: number;
    candidate_actual_gfa_stop_hashes?: string[];
    candidate_floor_count_distribution?: Record<string, number>;
  };
  runs: ExecutedMassRun[];
  book_images_included: false;
  image_authority: string;
  portfolio_vlm_audit: {
    status?: string;
    hard_pass?: boolean;
    candidate_count?: number;
    visible_family_count?: number;
    dominant_family_share?: number;
    failure_reasons?: string[];
    model?: string;
    response_id?: string;
    cache_hit?: boolean;
  };
  masses: ExecutedMassRecord[];
}

export interface CreativeMassCandidate {
  run_id: string;
  candidate_id: string;
  program_hash: string;
  geometry_hash: string;
  render_png: string;
  candidate_json: string;
  render_url: string;
  family: string;
  form_class: string;
  capacity_band: string;
  storeys: number;
  legal_status: 'not_evaluated';
  morphology_distance: number;
}

export interface CreativeMassCard {
  selectionKey: string;
  portfolioRunId: string;
  candidateId: string;
  programHash: string;
  geometryHash: string;
  renderUrl: string;
  family: string;
  formClass: string;
  capacityBand: string;
  storeys: number;
  legalStatus: 'not_evaluated';
  morphologyDistance: number;
}

export interface CreativePortfolioGraph {
  schema_version: string;
  root_node_ids: string[];
  nodes: Array<{
    id: string;
    kind: string;
    identity: string;
    attributes: Record<string, unknown>;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    kind: string;
  }>;
}

export interface CreativePortfolioManifest {
  schema_version: string;
  run_type: 'creative_portfolio';
  run_id: string;
  pnu: string;
  created_at: string;
  status: string;
  choice_pool: true;
  candidate_count: number;
  legal_review_status: 'not_evaluated';
  paid_vlm_request_count: number;
  board: Record<string, unknown>;
  board_png: string;
  filter_facets: Record<string, Array<{ value: string; count: number }>>;
  morphology_evidence: Record<string, unknown>;
  candidates: CreativeMassCandidate[];
  graph: CreativePortfolioGraph;
  runs: Array<{
    run_id: string;
    run_type: 'creative_portfolio';
    created_at: string;
    candidate_count: number;
    pnu: string;
    legal_review_status: 'not_evaluated';
  }>;
  contracts: {
    executed_mass_manifest_coercion: false;
    law_evidence_fabricated: false;
    parking_evidence_fabricated: false;
    elevation_evidence_fabricated: false;
    certified_capacity_fabricated: false;
    asset_root: string;
  };
}

export interface MaasLanguageSystemManifest {
  schema_version: string;
  system_id: string;
  source: {
    page_count: number;
    principle_count: number;
    authority: string;
    bundle: {
      schema_version: string;
      document_count: number;
      documents: Array<{
        role: string;
        filename: string;
        path: string;
        purpose: string;
        line_count: number;
        sha256: string;
      }>;
    };
  };
  geometry_language_contract: {
    schema_version: string;
    definition: string;
    type_invariant: string;
    recursive_grammar: string[];
    shape_count: number;
    shapes: Array<{
      index: number;
      family: string;
      name: string;
      feature: string;
      recommended: string;
      risk: string;
      primitive_operators: string[];
      operators: string[];
      minimum_program: string;
      compile_status: string;
      gate_pass: boolean;
      geometry_hash: string;
      program_cost: Record<string, number>;
    }>;
    graph: {
      stage_order: string[];
      nodes: Array<{
        id: string;
        kind: string;
        stage: string;
        label: string;
        attributes: Record<string, unknown>;
      }>;
      edges: Array<{ source: string; target: string; kind: string }>;
    };
  };
  semantic_order: string[];
  exploration_graph: BookExplorationGraph;
  form_bank_contract: {
    schema_version: string;
    stage_order: string[];
    program_conditioned: boolean;
    program_count: number;
    dominant_solid_authority: string;
    program_role: string;
    vlm_role: string;
  };
  base_volume_contract: {
    rule: string;
    canonical_base_model: string;
    affine_representation: string;
    examples: Array<{
      base_volume: string;
      base_seed: string;
      reads_as: string;
    }>;
  };
  reference_context: {
    source: string;
    available: boolean;
    collection_count: number;
    image_count: number;
    transfer_contract: string;
    pipeline_order: string[];
    live_vlm_policy: {
      reference_images_per_request: number;
      process_request_cap: number;
      retry_count: number;
      launch_mode: string;
    };
  };
  axes: {
    base_volumes: LanguageAxisItem[];
    orientations: LanguageAxisItem[];
    base_seeds: LanguageAxisItem[];
    chassis: LanguageAxisItem[];
    principles: LanguageAxisItem[];
    variations: LanguageAxisItem[];
    programs: LanguageAxisItem[];
    capacity_alternatives: LanguageAxisItem[];
    hard_gates: LanguageAxisItem[];
    live_vlm: LanguageAxisItem[];
  };
  counts: {
    base_models: number;
    base_volumes: number;
    orientations: number;
    base_seeds: number;
    chassis: number;
    principles: number;
    variations: number;
    programs: number;
    capacity_alternatives: number;
    base_seed_scope_instances: number;
    book_variant_paths: number;
    program_conditioned_paths: number;
    capacity_conditioned_paths: number;
    theoretical_language_paths: number;
    universal_form_programs: number;
    declared_search_units: number;
    declared_execution_edges: number;
  };
  count_formula: string;
  compatibility_contract: Record<string, boolean>;
}
