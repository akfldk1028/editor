import type {
  AlternativesResult,
  CadHandoff,
  DwgInspection,
  MassForm,
  PlanmRun,
  SprinklerState,
} from "./types";

const API_ROOT = "/api/v1/planm/runs";

/** Plate coordinates are chosen on a 0.1 m grid so the brief carries exact numbers. */
const snap = (value: number) => Math.round(value * 10) / 10;

/**
 * Every family starts at the origin and runs counter-clockwise, so edge 0 is
 * always the full-width street frontage the brief pins access to.
 */
export function footprintPolygon(form: MassForm): Array<[number, number]> {
  const width = snap(form.width);
  const depth = snap(form.depth);
  const cutX = snap(width * form.notchRatio);
  const cutY = snap(depth * form.notchRatio);
  const innerY = snap(depth - cutY);
  const rightX = snap(width - cutX);
  switch (form.shape) {
    case "l":
      return [
        [0, 0],
        [width, 0],
        [width, innerY],
        [rightX, innerY],
        [rightX, depth],
        [0, depth],
      ];
    case "t":
      return [
        [0, 0],
        [width, 0],
        [width, innerY],
        [rightX, innerY],
        [rightX, depth],
        [cutX, depth],
        [cutX, innerY],
        [0, innerY],
      ];
    case "u":
      return [
        [0, 0],
        [width, 0],
        [width, depth],
        [rightX, depth],
        [rightX, innerY],
        [cutX, innerY],
        [cutX, depth],
        [0, depth],
      ];
    default:
      return [
        [0, 0],
        [width, 0],
        [width, depth],
        [0, depth],
      ];
  }
}

const sprinklerFacts: Record<SprinklerState, Record<string, boolean>> = {
  unknown: {},
  none: { sprinklered: false, qualifying_sprinkler_protection: false },
  standard: { sprinklered: true, qualifying_sprinkler_protection: false },
  qualifying: { sprinklered: true, qualifying_sprinkler_protection: true },
};

/**
 * Only facts the brief actually asserts are sent. An unasserted fact stays out
 * of the payload so the screening reports it as unresolved instead of assumed.
 */
export function buildingCodeContext(form: MassForm): Record<string, unknown> | undefined {
  const asserted: Record<string, unknown> = {};
  if (form.jurisdiction) asserted.jurisdiction = form.jurisdiction;
  if (form.effectiveDate) asserted.effective_date = form.effectiveDate;
  if (form.travelLimit) asserted.travel_limit_classification = form.travelLimit;
  Object.assign(asserted, sprinklerFacts[form.sprinkler]);
  if (Object.keys(asserted).length === 0) return undefined;
  return { ...asserted, floor_facts: [] };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function createRun(form: MassForm): Promise<PlanmRun> {
  const officeShare = Math.max(0, 1 - form.commercialShare);
  const codeContext = buildingCodeContext(form);
  return request<PlanmRun>(API_ROOT, {
    method: "POST",
    body: JSON.stringify({
      contract_version: "planm-run-create/v1",
      mass: {
        project_id: form.projectId,
        floors: form.floors,
        footprint_polygon: footprintPolygon(form),
        site_edges: [{ edge_index: 0, kind: "street" }],
        access_candidates: [{ edge_index: 0, position: 0.5 }],
        use_mix: {
          neighborhood_commercial: form.commercialShare,
          office: officeShare,
        },
        ...(codeContext ? { building_code_context: codeContext } : {}),
      },
    }),
  });
}

export const getRun = (runId: string) => request<PlanmRun>(`${API_ROOT}/${runId}`);

export const getAlternatives = (runId: string) =>
  request<AlternativesResult>(`${API_ROOT}/${runId}/alternatives`);

export const approveAlternative = (runId: string, alternativeId: string) =>
  request<PlanmRun>(`${API_ROOT}/${runId}/approval`, {
    method: "POST",
    body: JSON.stringify({
      contract_version: "planm-approval/v1",
      alternative_id: alternativeId,
    }),
  });

export const previewUrl = (runId: string, alternativeId: string) =>
  `${API_ROOT}/${runId}/alternatives/${alternativeId}/preview`;

export const manifestUrl = (runId: string) =>
  `${API_ROOT}/${runId}/artifacts/planm-manifest.json`;

export const createCadHandoff = (runId: string) =>
  request<CadHandoff>(`${API_ROOT}/${runId}/dwg/handoff`, { method: "POST" });

export const inspectCadHandoff = (runId: string, layer = "F001_ROOMS") =>
  request<DwgInspection>(`${API_ROOT}/${runId}/dwg/inspection`, {
    method: "POST",
    body: JSON.stringify({
      contract_version: "planm-dwg-inspection-request/v1",
      layer,
    }),
  });

export const artifactUrl = (runId: string, relativePath: string) =>
  `${API_ROOT}/${runId}/artifacts/${relativePath}`;
