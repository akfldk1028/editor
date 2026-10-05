export interface DesignJob {
  id: string;
  pnu: string;
  address: string;
  status: 'pending' | 'running' | 'complete' | 'failed' | 'cancelled';
  generation_count: number;
  max_generations: number;
  population_size: number;
  site_area_m2: number | null;
  constraints: Constraint[];
  created_at: string | null;
  completed_at: string | null;
  error: string;
}

export interface Constraint {
  name: string;
  type: 'Constraint';
  Requirement: string;
  val: number;
  unit: string;
  label: string;
}

export interface DesignData {
  id: number;
  uid?: string;
  generation: number;
  parents: [number | null, number | null];
  feasible: boolean;
  inputs: number[][];
  objectives: number[];
  penalty: number;
  rank: number;
  elite: number;
  /** Algorithm name — set in "all" mode (multi-algorithm) */
  algorithm?: string;
}

export interface MaasAestheticResult {
  status: 'pass' | 'fail' | 'needs_provider' | string;
  job: {
    provider: string;
    mode: string;
    evidence_policy?: {
      legal_status_effect?: string;
      must_not_change?: string[];
      may_change?: string[];
    };
    prompt?: {
      prompt?: string;
      negative_prompt?: string;
    };
  };
  reference: {
    asset_id: string;
    uri: string;
    url?: string;
    media_type: string;
    metadata?: Record<string, unknown>;
  } | null;
  provider_result: {
    provider: string;
    status: string;
    assets: Array<{
      asset_id?: string;
      uri?: string;
      url?: string;
      media_type?: string;
      role?: string;
      legal_status_effect?: string;
      metadata?: {
        view?: string;
        source_asset_id?: string;
        [key: string]: unknown;
      };
    }>;
    metadata?: Record<string, unknown>;
    issues?: Array<{ code?: string; message?: string }>;
  } | null;
  job_validation?: { status: string; issues?: Array<{ code?: string; message?: string }> };
  provider_validation?: { status: string; issues?: Array<{ code?: string; message?: string }> };
}

export interface DesignResult {
  design_id: number;
  generation: number;
  inputs: number[][];
  outputs: Record<string, unknown>;
  ranking: number | null;
  crowding_distance: number | null;
  is_feasible: boolean;
  is_pareto_optimal: boolean;
  mass_geojson: GeoJSONFeature | null;
}

export interface GeoJSONFeature {
  type: 'Feature';
  geometry: {
    type: string;
    coordinates: number[][][];
  };
  properties: {
    height: number;
    num_floors: number;
    floor_height?: number;
    building_type?: string;
    mass_shape?: string;
    maas_concept?: string;
    footprint_area: number;
    floor_area: number;
    bcr: number;
    far: number;
    design_id?: number;
    design_uid?: string;
    generation?: number;
    objectives?: number[];
    algorithm?: string;
    variant_id?: string;
    maas_score?: number;
    design_quality_score?: number;
    design_quality?: MaasDesignQuality;
    diversity_score?: number;
    source_iou?: number;
    notes?: string[];
    operation_history?: Array<Record<string, unknown>>;
    mass_execution_passport?: import('./language-system-types').MassExecutionPassport;
    // Canonical MAAS object: one integrated source for morphology, legal audit,
    // and agent-readable architectural language.
    maas_model?: {
      algorithm: 'maas_legal_envelope';
      operator: string;
      verb_sequence: Array<{
        verb: string;
        params?: Record<string, unknown>;
      }>;
      volumes: Array<{
        band: number;
        bottom_height: number;
        top_height: number;
        role?: string;
        geometry: { type: string; coordinates: number[][][] };
      }>;
      floor_plates: Array<{
        floor: number;
        top_height: number;
        area: number;
        geometry: { type: string; coordinates: number[][][] };
      }>;
      floor_groups?: FloorGroup[];
      legal_metrics?: Record<string, number | undefined>;
      design_quality?: MaasDesignQuality;
      section_profile?: GeoJSONFeature['properties']['section_profile'];
    };
    // MAAS legal-envelope floor-by-floor massing
    floor_plates?: Array<{
      floor: number;
      top_height: number;
      area: number;
      geometry: { type: string; coordinates: number[][][] };
    }>;
    floor_groups?: FloorGroup[];
    // Legal floor plates compressed into display volumes so MAAS morphology
    // reads as architectural massing instead of a per-floor stair stack.
    mass_volumes?: Array<{
      band: number;
      bottom_height: number;
      top_height: number;
      role?: string;
      geometry: { type: string; coordinates: number[][][] };
    }>;
    maas_verb_sequence?: Array<{
      verb: string;
      params?: Record<string, unknown>;
    }>;
    section_profile?: {
      kind: 'diagonal_connector' | 'diagonal_connect' | 'terrace_ribbon' | 'sloped_roof' | 'sloped_roof_mass' | string;
      source?: string;
      operator?: string;
      render_hint?: string;
      axis?: string;
      side?: string;
      upper_ratio?: number;
      distance_ratio?: number;
      lower_floor_fraction?: number;
      width_ratio?: number;
      depth_ratio?: number;
      x_ratio?: number;
      y_ratio?: number;
    };
    // Step-back (two-tier) massing
    step_floor?: number;
    upper_scale?: number;
    lower_height?: number;
    upper_geometry?: { type: string; coordinates: number[][][] };
  };
}

export interface MaasDesignQuality {
  source: 'arr.maas.design_quality.v1';
  score: number;
  components: {
    capacity: number;
    diversity: number;
    compactness: number;
    plate_profile: number;
    sequence_richness: number;
  };
  sequence_metrics: {
    source: 'arr.maas.sequence_metrics.v1';
    parsimony: number;
    unique_verb_count: number;
    verb_set: string[];
    plan_verbs: string[];
    section_verbs: string[];
    has_plan_operation: boolean;
    has_section_operation: boolean;
    reference_comparison?: {
      jaccard: number;
      token_f1: number;
      ordered_lcs: number;
      lcs_score: number;
    };
  };
  optimizer_backend: {
    name: string;
    source?: string;
    status: string;
    backend?: Record<string, unknown>;
    absorbed_pattern?: Record<string, unknown>;
  };
  legal_truth: string;
}

export interface FloorGroup {
  group: number;
  start_floor: number;
  end_floor: number;
  floor_count: number;
  bottom_height: number;
  top_height: number;
  area: number;
  far_contribution: number;
  cumulative_far: number;
  geometry: { type: string; coordinates: number[][][] };
  source_floor_plates?: number[];
  program_packing?: {
    stage: 'post_legal_floor_group_packing';
    algorithm: 'circle_grid_packing';
    constraint_source: 'maas_legal_envelope';
    typical_floor_area: number;
    cell_size: number;
    status: 'pending' | 'ok' | 'failed' | 'skipped_small_footprint' | 'skipped_small_program';
    result_count?: number;
    rooms: Array<{
      name: string;
      area: number;
      adjacency?: string[];
    }>;
    grid?: {
      rows: number;
      cols: number;
      cell_size: number;
      active_cells: number;
    };
    best_metrics?: {
      adjacency_score?: number;
      area_error?: number;
      compactness?: number;
    };
    preview_summary?: {
      room_count: number;
      room_names: string[];
      adjacency_score: number;
      area_error: number;
      compactness: number;
    };
    best_floor_plan?: {
      type: 'FeatureCollection';
      features: Array<{
        type: 'Feature';
        properties: {
          room_code?: number;
          room_name?: string;
          color?: string;
          area_m2?: number;
          [key: string]: unknown;
        };
        geometry: {
          type: string;
          coordinates: unknown;
        };
      }>;
    } | null;
    error?: string;
  };
}

export interface SSEEvent {
  type: 'started' | 'generation' | 'complete' | 'error' | 'cancelled';
  generation?: number;
  max_generations?: number;
  population_size?: number;
  pareto_count?: number;
  pareto_front?: DesignData[];
  best?: DesignData | null;
  best_geojson?: GeoJSONFeature | null;
  pareto_geojson?: GeoJSONFeature[];
  feasible_count?: number;
  total_designs?: number;
  total_evaluated?: number;
  generations?: number;
  message?: string;
  objectives?: { name: string; goal: string }[];
  scatter?: [number, number, boolean, number][]; // [obj0, obj1, feasible, generation]
}

export interface SetbackGeometry {
  geometry: { type: string; coordinates: number[][][] };
  distance_m: number;
  label: string;
}

/**
 * setback_geometries 응답 dict — heterogeneous values:
 *   - 일반 키 (buildable_area, north_setback, ...) → SetbackGeometry
 *   - sunlight_envelope, daylight_diagonal_envelope → SunlightEnvelope (from land/lib/types)
 *   - datum_result → DatumResultDict (envelope 없는 zone에서도 datum 표시용)
 *
 * `as unknown as` 캐스팅 회피용. Phase 2C+ datum metadata 4 필드 포함.
 */
import type { SunlightEnvelope } from '../../land-map/lib/types';

/** Phase 2D — envelope과 독립적인 datum 정보 (정북일조 미적용 zone 표시용). */
export interface DatumResultDict {
  elevation_m: number;
  case: string | null;
  basis: string | null;
  elevation_source: 'open_meteo' | 'copernicus_glo30' | 'ngii_lidar_1m' | 'ngii_5m' | 'ngii_local_dem' | 'failed' | null;
  parcel_datum_m?: number | null;
  road_datum_m?: number | null;
  neighbor_datum_m?: number | null;
  neighbor_avg_datum_m?: number | null;
  parcel_segments?: DatumBoundarySegment[] | null;
  road_samples?: DatumPointSample[] | null;
  neighbor_segments?: DatumBoundarySegment[] | null;
  split_bands?: Array<{
    band_index: number;
    min_elevation_m: number;
    max_elevation_m: number;
    datum_m: number;
    length_m: number;
    sample_count: number;
    basis: string;
  }> | null;
  split_polygons?: DatumResultDict['split_bands'];
  notes?: string[] | null;
}

export interface DatumBoundarySegment {
  midpoint_lng?: number | null;
  midpoint_lat?: number | null;
  length_m?: number | null;
  elevation_m?: number | null;
  midpoint_elev_m?: number | null;
}

export interface DatumPointSample {
  lng?: number | null;
  lat?: number | null;
  elevation_m?: number | null;
  elev_m?: number | null;
  dist_m?: number | null;
  weight?: number | null;
}

export interface RoadFrontageDict {
  roadWidthM?: number | null;
  road_width_m?: number | null;
  sharedEdge?: unknown;
  shared_edge?: unknown;
  roadCenterline?: unknown;
  road_centerline?: unknown;
}

export interface NeighborParcelDict {
  sharedEdge?: unknown;
  shared_edge?: unknown;
  [key: string]: unknown;
}

export type SetbackGeometriesMap =
  Record<string, SetbackGeometry | SunlightEnvelope | DatumResultDict | null | undefined> & {
    sunlight_envelope?: SunlightEnvelope | null;
    daylight_diagonal_envelope?: SunlightEnvelope | null;
    datum_result?: DatumResultDict | null;
    road_frontages?: RoadFrontageDict[] | null;
    neighbor_parcels?: NeighborParcelDict[] | null;
  };

export interface LawArticle {
  full_id: string;
  content: string;
  law_name: string;
  law_type: string;
  similarity: number;
}

export interface LawSearchResult {
  articles: { query: string; results: LawArticle[] }[];
  total_count: number;
  errors: string[];
}

export interface AutoConstraintsResult {
  zones: string[];
  regulations: {
    bcr_pct: number | null;
    far_pct: number | null;
    height_limit_m: number | null;
    adjacent_setback_m: number | null;
  };
  constraints: Constraint[];
  setback_geometries?: SetbackGeometriesMap;
  law_articles?: LawSearchResult;
  building_type?: string;
}

export interface SiteBoundaryResult {
  pnu: string;
  geometry: {
    type: string;
    coordinates: number[][][];
  };
  area_m2: number;
  valid: boolean;
  errors: string[];
}

// ── Floor Plan Types ──

export interface FloorPlanRoom {
  name: string;
  area: number;
  adjacency: string[];
}

export interface FloorPlanMetrics {
  adjacency_score: number;
  area_error: number;
  compactness: number;
}

export interface FloorPlanDesign {
  design_id: number;
  metrics: FloorPlanMetrics;
  floor_plan: {
    type: 'FeatureCollection';
    features: {
      type: 'Feature';
      properties: {
        room_code: number;
        room_name: string;
        color: string;
        area_m2: number;
      };
      geometry: {
        type: string;
        coordinates: number[][][];
      };
    }[];
  };
}

export interface FloorPlanResult {
  algorithm?: string;
  grid_info: {
    rows: number;
    cols: number;
    cell_size: number;
    active_cells: number;
  };
  rooms: FloorPlanRoom[];
  num_results: number;
  results: FloorPlanDesign[];
}

export interface InteractivePatchCandidate {
  id: string;
  title: string;
  intent: string;
  patch: Record<string, unknown>;
  constraints: string[];
  expected_effects: string[];
  risks: string[];
}

export interface InteractivePatchResult {
  mode: 'dry_run';
  user_text: string;
  selected_design_id: number | null;
  interpreted_intents: string[];
  candidates: InteractivePatchCandidate[];
  notes: string[];
}

export interface InteractivePreviewCandidate {
  id: string;
  title: string;
  intent: string;
  feasible: boolean;
  penalty: number;
  inputs: number[][];
  outputs: number[];
  metrics: Record<string, number>;
  mass_geojson: GeoJSONFeature | null;
  notes: string[];
}

export interface InteractivePreviewResult {
  mode: 'preview';
  selected_design_id: number | null;
  algorithm: string;
  building_type: string;
  candidates: InteractivePreviewCandidate[];
  notes: string[];
  a2ui_messages?: Array<Record<string, unknown>>;
}

export interface MaasLegalVariantsResult {
  mode: 'maas_legal_variants';
  algorithm: 'maas_morphology' | 'maas_legal_envelope';
  count: number;
  source_repair_actions: string[];
	  constraints: {
	    bcr_limit: number;
	    far_limit: number;
	    height_limit: number;
	    max_seed_floors?: number;
	    has_buildable_footprint?: boolean;
	    has_floor_plate_stack?: boolean;
	  };
  feature_collection: {
    type: 'FeatureCollection';
    features: GeoJSONFeature[];
  };
  rejected: Array<Record<string, unknown>>;
  agent_reviews?: Array<Record<string, unknown>>;
  agent_trace?: Array<Record<string, unknown>>;
  a2ui_messages?: Array<Record<string, unknown>>;
  massdsl_proposals?: Array<Record<string, unknown>>;
  grammar_review?: Record<string, unknown> | null;
  grammar_reviews?: Array<Record<string, unknown>>;
  notes: string[];
}

export interface InteractiveOperationResult {
  mode: 'interactive_operation';
  operation: Record<string, unknown>;
  normalized_operation?: Record<string, unknown>;
  feature: GeoJSONFeature;
  metrics: Record<string, number | string | unknown>;
  agent_reviews?: Array<{
    agent: string;
    status: string;
    summary: string;
    metrics?: Record<string, unknown>;
  }>;
  a2ui_messages?: Array<Record<string, unknown>>;
  notes: string[];
}
