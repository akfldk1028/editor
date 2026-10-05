import type {
  AutoConstraintsResult,
  DesignData,
  DesignJob,
  FloorPlanResult,
  FloorPlanRoom,
  GeoJSONFeature,
  InteractivePreviewResult,
  InteractiveOperationResult,
  InteractivePatchResult,
  MaasAestheticResult,
  MaasLegalVariantsResult,
  SiteBoundaryResult,
} from './types';
import type {
  CreativePortfolioManifest,
  ExecutedMassManifest,
  MaasLanguageSystemManifest,
  OutcomeGraphSlice,
  SingleMassExecutionResponse,
} from './language-system-types';
import type { MassPortfolioManifest } from './mass-portfolio-types';
import { fetchMASDialogue, toAGLightMessages } from './mas-dialogue';
import { toDesignConstraints } from './land-constraints';

export const BASE = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/design`;
const AG_LIGHT_BASE = `${BASE}/collaboration`;

export interface AgLightHealth {
  service: string;
  status: boolean;
  timestamp?: string;
  components?: {
    bus?: { connected_agents?: string[]; log_count?: number };
    memory?: { decisions?: string[]; events_count?: number };
    mcp?: Record<string, unknown>;
  };
}

export interface AgLightBusEvent {
  timestamp: string;
  from_agent: string;
  to_agent: string;
  message: string;
  event_type?: string;
  metadata?: Record<string, unknown>;
}

export interface DesignEvidence {
  final_status?: string;
  summary?: Record<string, unknown>;
  checks?: Array<Record<string, unknown>>;
  hard_failures?: unknown[];
  missing_evidence?: unknown[];
  open_issues?: unknown[];
  non_negotiable?: Record<string, unknown>;
  domain_status_counts?: Record<string, Record<string, number> | number>;
  [key: string]: unknown;
}

export async function createJob(params: {
  site_polygon: object;
  pnu?: string;
  address?: string;
  constraints?: object[];
  job_spec?: object;
}, signal?: AbortSignal): Promise<DesignJob> {
  const res = await fetch(`${BASE}/jobs/`, {
    signal,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error((await res.json()).error || res.statusText);
  return res.json();
}

export async function getJob(jobId: string): Promise<DesignJob> {
  const res = await fetch(`${BASE}/jobs/${jobId}/`);
  if (!res.ok) throw new Error('Job not found');
  return res.json();
}

export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`${BASE}/jobs/${jobId}/cancel/`, { method: 'POST' });
  if (!res.ok) throw new Error('설계 실행을 취소하지 못했습니다.');
}

export async function runJob(jobId: string): Promise<void> {
  const res = await fetch(`${BASE}/jobs/${jobId}/run/`, { method: 'POST' });
  if (!res.ok) throw new Error('Job run failed');
}

export async function getJobResults(jobId: string) {
  const res = await fetch(`${BASE}/jobs/${jobId}/results/`);
  if (!res.ok) throw new Error('Results not found');
  return res.json();
}

export async function getDesignEvidence(jobId: string, designId: number): Promise<DesignEvidence> {
  const res = await fetch(`${BASE}/jobs/${jobId}/results/${designId}/evidence/`);
  if (!res.ok) throw new Error((await res.json()).error || 'Evidence not found');
  return res.json();
}

export async function getAgLightHealth(): Promise<AgLightHealth> {
  const res = await fetch(`${AG_LIGHT_BASE}/health`);
  if (!res.ok) throw new Error('AG-light health check failed');
  return res.json();
}

export async function getMaasLanguageSystem(
  signal?: AbortSignal,
): Promise<MaasLanguageSystemManifest> {
  const res = await fetch(`${BASE}/maas/language-system/`, { signal });
  if (!res.ok) throw new Error('MAAS language system manifest fetch failed');
  return res.json();
}

export async function getMaasOutcomeGraphSlice(
  pnu: string,
  signal?: AbortSignal,
  geometryHash?: string,
  runId?: string,
): Promise<OutcomeGraphSlice> {
  const query = new URLSearchParams({ pnu, depth: '3', max_nodes: '180' });
  if (geometryHash) query.set('geometry_hash', geometryHash);
  if (runId) query.set('run_id', runId);
  const res = await fetch(`${BASE}/maas/outcome-graph/?${query}`, { signal });
  if (!res.ok) throw new Error('MAAS outcome graph slice fetch failed');
  return res.json();
}

export function getGeometryShapePreviewUrl(index: number): string {
  return `${BASE}/maas/geometry-shapes/${index}/`;
}

export async function getGeometryShapePassport(
  index: number,
  signal?: AbortSignal,
): Promise<import('./language-system-types').MassExecutionPassport> {
  const res = await fetch(`${BASE}/maas/geometry-shapes/${index}/passport/`, { signal });
  if (!res.ok) throw new Error('MASS execution passport fetch failed');
  return res.json();
}

export async function getExecutedMassManifest(
  signal?: AbortSignal,
  runId?: string,
): Promise<ExecutedMassManifest> {
  const query = runId ? `?${new URLSearchParams({ run_id: runId })}` : '';
  const res = await fetch(`${BASE}/maas/executed-masses/${query}`, { signal });
  if (!res.ok) throw new Error('실제 실행 MASS 아카이브를 불러오지 못했습니다.');
  return res.json();
}

export async function getCreativeMassPortfolio(
  runId?: string,
  signal?: AbortSignal,
): Promise<CreativePortfolioManifest> {
  const query = runId
    ? `?${new URLSearchParams({ run_id: runId })}`
    : '';
  const res = await fetch(`${BASE}/maas/creative-portfolios/${query}`, {
    signal,
  });
  if (!res.ok) {
    throw new Error('Creative MASS portfolio fetch failed');
  }
  return res.json();
}

export async function getMassPortfolioEvaluations(
  runId?: string,
  signal?: AbortSignal,
): Promise<MassPortfolioManifest> {
  const query = runId ? `?${new URLSearchParams({ run_id: runId })}` : '';
  const res = await fetch(`${BASE}/maas/portfolio-evaluations/${query}`, { signal });
  if (!res.ok) throw new Error('MASS portfolio evaluations fetch failed');
  return res.json();
}

export function getExecutedMassPreviewUrl(index: number): string {
  return `${BASE}/maas/executed-masses/${index}/`;
}

export async function getExecutedMassPassport(
  index: number,
  signal?: AbortSignal,
  runId?: string,
): Promise<import('./language-system-types').MassExecutionPassport> {
  const query = runId ? `?${new URLSearchParams({ run_id: runId })}` : '';
  const res = await fetch(`${BASE}/maas/executed-masses/${index}/passport/${query}`, { signal });
  if (!res.ok) throw new Error('실제 실행 MASS 여권을 불러오지 못했습니다.');
  return res.json();
}

export async function executeArchivedMass(
  sourceRunId: string,
  sourceMassIndex: number,
): Promise<SingleMassExecutionResponse> {
  const res = await fetch(`${BASE}/maas/single-executions/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      source_run_id: sourceRunId,
      source_mass_index: sourceMassIndex,
    }),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.error || 'Selected MASS execution failed');
  }
  return res.json();
}

export async function executeArchivedMassAndLoad(
  sourceRunId: string,
  sourceMassIndex: number,
): Promise<{
  execution: SingleMassExecutionResponse;
  archive: ExecutedMassManifest;
}> {
  const execution = await executeArchivedMass(sourceRunId, sourceMassIndex);
  const archive = await getExecutedMassManifest(undefined, execution.archive_run_id);
  return { execution, archive };
}

export async function reviewSingleMassWithVlm(
  executionId: string,
  referenceLimit = 3,
): Promise<import('./language-system-types').SingleMassVlmReviewResponse> {
  const res = await fetch(`${BASE}/maas/single-executions/${encodeURIComponent(executionId)}/vlm-review/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reference_limit: Math.max(0, Math.min(3, referenceLimit)) }),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.error || 'Bounded paid VLM review failed');
  }
  return res.json();
}

export async function getAgLightBusLog(limit = 50): Promise<AgLightBusEvent[]> {
  return toAGLightMessages(await fetchMASDialogue()).slice(-limit).map(message => ({
    ...message, timestamp: message.timestamp || '',
  }));
}

export async function sendAgLightBusMessage(params: {
  from_agent: string;
  to_agent: string;
  message: string;
  event_type?: string;
  metadata?: Record<string, unknown>;
}): Promise<void> {
  const res = await fetch(`${AG_LIGHT_BASE}/bus/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error('AG-light bus send failed');
}

export async function getSiteBoundary(pnu: string, signal?: AbortSignal): Promise<SiteBoundaryResult> {
  const res = await fetch(`${BASE}/site-boundary/`, {
    signal,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pnu }),
  });
  if (!res.ok) {
    const payload = await res.json();
    throw new Error(payload.error || payload.detail || 'Boundary fetch failed');
  }
  return res.json();
}

export async function getAutoConstraints(params: {
  pnu?: string;
  zones?: string[];
  address?: string;
  site_polygon?: object;
  building_type?: string;
  include_law_articles?: boolean;
}, signal?: AbortSignal): Promise<AutoConstraintsResult> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/analyze`, {
    signal,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      input: params.pnu || params.address || '',
      input_type: params.pnu ? 'pnu' : params.address ? 'address' : 'raw',
      zones: params.zones || [], geometry: params.site_polygon,
      building_type: params.building_type || '', include_law: params.include_law_articles ?? true,
    }),
  });
  if (!res.ok) throw new Error((await res.json()).error || 'Constraint generation failed');
  return toDesignConstraints(await res.json(), params.building_type);
}

export async function generateFloorPlan(params: {
  footprint_geojson: object;
  coordinate_frame?: 'wgs84' | 'local_meters';
  rooms: FloorPlanRoom[];
  cell_size?: number;
  algorithm?: string;
  options?: { num_generations?: number; population_size?: number };
}, signal?: AbortSignal): Promise<FloorPlanResult> {
  const res = await fetch(`${BASE}/floor-plan/`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error((await res.json()).error || 'Floor plan generation failed');
  return res.json();
}

export interface ConstraintsParams {
  site_polygon: object;
  bcr_limit_pct?: number;
  far_limit_pct?: number;
  height_limit_m?: number;
  adjacent_setback_m?: number;
  north_setback_m?: number;
  road_setback_m?: number;
  sunlight_slope?: number;
  sunlight_base_height_m?: number;
}

export interface ConstraintsResult {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: { type: string; coordinates: unknown };
    properties: {
      kind: string;
      label?: string;
      color?: string;
      stroke_width?: number;
      stroke_dasharray?: number[];
      fill_opacity?: number;
      metadata?: Record<string, unknown>;
    };
  }>;
  metadata?: { generator?: string; version?: string };
}

export async function visualizeConstraints(params: ConstraintsParams): Promise<ConstraintsResult> {
  const res = await fetch(`${BASE}/constraints/visualize/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error((await res.json()).error || 'Constraints visualize failed');
  return res.json();
}

export async function createInteractivePatch(params: {
  message: string;
  selected_design?: DesignData | null;
  mass_geojson?: GeoJSONFeature | null;
  constraints?: object[];
}, signal?: AbortSignal): Promise<InteractivePatchResult> {
  const res = await fetch(`${BASE}/interactive/patch/`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error((await res.json()).error || 'Interactive patch failed');
  return res.json();
}

export async function createInteractivePreview(params: {
  patch_plan: InteractivePatchResult;
  selected_design: DesignData;
  site_polygon: object;
  site_area_m2: number;
  constraints?: object[];
  building_type?: string;
  algorithm?: string;
}, signal?: AbortSignal): Promise<InteractivePreviewResult> {
  const res = await fetch(`${BASE}/interactive/preview/`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error((await res.json()).error || 'Interactive preview failed');
  return res.json();
}

export async function applyInteractiveOperation(params: {
  mass_geojson: GeoJSONFeature;
  site_polygon: object;
  operation: object;
  constraints?: object[];
  building_type?: string;
  sunlight_envelope?: object | null;
  setback_geometries?: object | null;
}, signal?: AbortSignal): Promise<InteractiveOperationResult> {
  const res = await fetch(`${BASE}/interactive/operation/`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error((await res.json()).error || 'Interactive operation failed');
  return res.json();
}

export async function createMaasLegalVariants(params: {
  mass_geojson: GeoJSONFeature;
  site_polygon: object;
  constraints?: object[];
  building_type?: string;
  max_variants?: number;
  sunlight_envelope?: object | null;
  setback_geometries?: object | null;
  include_interactive_seed?: boolean;
  preferred_operator?: string | null;
  pnu?: string | null;
  parking_options?: object | null;
}, signal?: AbortSignal): Promise<MaasLegalVariantsResult> {
  const res = await fetch(`${BASE}/maas/legal-variants/`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error((await res.json()).error || 'MAAS variants failed');
  return res.json();
}

export async function createMaasAesthetic(params: {
  job_id: string;
  design_id: number;
  provider?: 'placeholder' | 'gpt-image' | 'nano-banana';
  style?: string;
  attach_to_evidence?: boolean;
}, signal?: AbortSignal): Promise<MaasAestheticResult> {
  const res = await fetch(`${BASE}/jobs/${params.job_id}/results/${params.design_id}/aesthetic/`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      provider: params.provider || 'placeholder',
      style: params.style,
      attach_to_evidence: params.attach_to_evidence ?? true,
    }),
  });
  if (!res.ok) throw new Error((await res.json()).error || 'MAAS aesthetic generation failed');
  return res.json();
}
