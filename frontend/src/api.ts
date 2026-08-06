import type { AlternativesResult, CadHandoff, DwgInspection, MassForm, PlanmRun } from "./types";

const API_ROOT = "/api/v1/planm/runs";

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
  return request<PlanmRun>(API_ROOT, {
    method: "POST",
    body: JSON.stringify({
      contract_version: "planm-run-create/v1",
      mass: {
        project_id: form.projectId,
        floors: form.floors,
        footprint_polygon: [
          [0, 0],
          [form.width, 0],
          [form.width, form.depth],
          [0, form.depth],
        ],
        site_edges: [{ edge_index: 0, kind: "street" }],
        access_candidates: [{ edge_index: 0, position: 0.5 }],
        use_mix: {
          neighborhood_commercial: form.commercialShare,
          office: officeShare,
        },
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
