import type { SelectedMassIdentity } from './elevation-proposal';

const FACADE_VIEWS = ['front', 'right', 'back', 'left'] as const;

type FacadeView = typeof FACADE_VIEWS[number];
type UnknownRecord = Record<string, unknown>;

export interface MultiViewElevationView {
  view: FacadeView;
  previewUrl: string;
  sha256: string;
  provider: string;
  model: string;
}

export interface MultiViewElevationIssue {
  code: string;
  views: string[];
  message: string;
}

export interface MultiViewElevationEvidence {
  status: string;
  strategyId: string;
  primarySystem: string;
  views: MultiViewElevationView[];
  deterministicStatus: string;
  criticStatus: string;
  criticResponseId: string;
  issues: MultiViewElevationIssue[];
  paidRequestAttemptCount: number;
  retryCount: number;
}

function record(value: unknown): UnknownRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

function issueRows(value: unknown): MultiViewElevationIssue[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const row = record(item);
    if (!row) return [];
    return [{
      code: typeof row.code === 'string' ? row.code : 'unclassified_issue',
      views: Array.isArray(row.views) ? row.views.map(String) : [],
      message: typeof row.message === 'string' ? row.message : '',
    }];
  });
}

export function extractMultiViewElevation(
  passport: unknown,
  selected: SelectedMassIdentity,
): MultiViewElevationEvidence | null {
  const passportRecord = record(passport);
  const elevation = record(passportRecord?.elevation_evidence);
  const proposal = record(elevation?.multi_view_proposal);
  const identity = record(proposal?.identity);
  const strategy = record(proposal?.strategy);
  const artifacts = record(proposal?.artifacts);
  const gate = record(proposal?.deterministic_gate);
  const critic = record(proposal?.critic);
  if (!passportRecord || !proposal || !identity || !strategy || !artifacts) {
    return null;
  }
  if (
    !selected.floorCapacityPlanHash
    || !selected.finalGeometryHash
    || !selected.visualHash
    || !selected.legalFloorFieldHash
    || !selected.actualGfaStopHash
    || passportRecord.program_hash !== selected.programHash
    || passportRecord.geometry_hash !== selected.geometryHash
    || passportRecord.final_legal_geometry_hash
      !== selected.finalGeometryHash
    || passportRecord.visual_hash !== selected.visualHash
    || passportRecord.floor_capacity_plan_hash !== selected.floorCapacityPlanHash
    || passportRecord.legal_floor_field_hash
      !== selected.legalFloorFieldHash
    || passportRecord.candidate_actual_gfa_stop_hash
      !== selected.actualGfaStopHash
    || identity.execution_id !== selected.executionId
    || identity.program_hash !== selected.programHash
    || identity.geometry_hash !== selected.geometryHash
    || identity.final_geometry_hash !== selected.finalGeometryHash
    || identity.final_legal_geometry_hash !== selected.finalGeometryHash
    || identity.visual_hash !== selected.visualHash
    || identity.floor_capacity_plan_hash !== selected.floorCapacityPlanHash
    || identity.legal_floor_field_hash !== selected.legalFloorFieldHash
    || identity.candidate_actual_gfa_stop_hash
      !== selected.actualGfaStopHash
  ) {
    return null;
  }

  const views = FACADE_VIEWS.flatMap((view) => {
    const viewRecord = record(artifacts[view]);
    const viewIdentity = record(viewRecord?.identity);
    const artifact = record(viewRecord?.artifact);
    const providerMetadata = record(viewRecord?.provider_metadata);
    if (
      !viewRecord
      || !viewIdentity
      || !artifact
      || viewRecord.view !== view
      || viewIdentity.execution_id !== selected.executionId
      || viewIdentity.program_hash !== selected.programHash
      || viewIdentity.geometry_hash !== selected.geometryHash
      || viewIdentity.final_geometry_hash !== selected.finalGeometryHash
      || viewIdentity.final_legal_geometry_hash
        !== selected.finalGeometryHash
      || viewIdentity.visual_hash !== selected.visualHash
      || viewIdentity.floor_capacity_plan_hash
        !== selected.floorCapacityPlanHash
      || viewIdentity.legal_floor_field_hash
        !== selected.legalFloorFieldHash
      || viewIdentity.candidate_actual_gfa_stop_hash
        !== selected.actualGfaStopHash
      || viewIdentity.view !== view
    ) {
      return [];
    }
    const previewUrl = typeof artifact.preview_url === 'string'
      ? artifact.preview_url
      : '';
    const sha256 = typeof artifact.sha256 === 'string' ? artifact.sha256 : '';
    if (!previewUrl.startsWith('/') || !sha256) return [];
    return [{
      view,
      previewUrl,
      sha256,
      provider: typeof viewRecord.provider === 'string' ? viewRecord.provider : '',
      model: typeof providerMetadata?.model === 'string'
        ? providerMetadata.model
        : '',
    }];
  });
  if (views.length !== FACADE_VIEWS.length) return null;

  return {
    status: typeof proposal.status === 'string' ? proposal.status : 'not_evaluated',
    strategyId: typeof strategy.strategy_id === 'string'
      ? strategy.strategy_id
      : '',
    primarySystem: typeof strategy.primary_system === 'string'
      ? strategy.primary_system
      : '',
    views,
    deterministicStatus: typeof gate?.status === 'string'
      ? gate.status
      : 'not_evaluated',
    criticStatus: typeof critic?.status === 'string'
      ? critic.status
      : 'not_evaluated',
    criticResponseId: typeof critic?.response_id === 'string'
      ? critic.response_id
      : '',
    issues: [
      ...issueRows(gate?.issues),
      ...issueRows(critic?.issues),
    ],
    paidRequestAttemptCount:
      typeof proposal.paid_request_attempt_count === 'number'
        ? proposal.paid_request_attempt_count
        : 0,
    retryCount: typeof proposal.retry_count === 'number'
      ? proposal.retry_count
      : 0,
  };
}
