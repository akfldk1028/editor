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
 * always the street frontage the brief pins access to.
 *
 * `cutWidth` and `cutDepth` measure the material removed from the top of the
 * plate, which is what lets a brief reproduce a measured sweep footprint
 * exactly: L removes one corner, T removes both and keeps the stem between
 * them, U removes a centred notch. `sloped` removes the same corner as L along
 * a diagonal, and `chamfered` takes `cutWidth` as the chamfer on all four.
 */
export function footprintPolygon(form: MassForm): Array<[number, number]> {
  const width = snap(form.width);
  const depth = snap(form.depth);
  const cutWidth = snap(Math.min(form.cutWidth, width));
  const cutDepth = snap(Math.min(form.cutDepth, depth));
  const innerY = snap(depth - cutDepth);
  switch (form.shape) {
    case "l": {
      const rightX = snap(width - cutWidth);
      return [
        [0, 0],
        [width, 0],
        [width, innerY],
        [rightX, innerY],
        [rightX, depth],
        [0, depth],
      ];
    }
    case "t": {
      const side = snap(cutWidth / 2);
      const rightX = snap(width - side);
      return [
        [0, 0],
        [width, 0],
        [width, innerY],
        [rightX, innerY],
        [rightX, depth],
        [side, depth],
        [side, innerY],
        [0, innerY],
      ];
    }
    case "u": {
      const leftX = snap((width - cutWidth) / 2);
      const rightX = snap(width - leftX);
      return [
        [0, 0],
        [width, 0],
        [width, depth],
        [rightX, depth],
        [rightX, innerY],
        [leftX, innerY],
        [leftX, depth],
        [0, depth],
      ];
    }
    case "sloped": {
      const rightX = snap(width - cutWidth);
      return [
        [0, 0],
        [width, 0],
        [width, innerY],
        [rightX, depth],
        [0, depth],
      ];
    }
    case "chamfered": {
      const chamfer = snap(Math.min(cutWidth, width / 2, depth / 2));
      return [
        [chamfer, 0],
        [snap(width - chamfer), 0],
        [width, chamfer],
        [width, snap(depth - chamfer)],
        [snap(width - chamfer), depth],
        [chamfer, depth],
        [0, snap(depth - chamfer)],
        [0, chamfer],
      ];
    }
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
