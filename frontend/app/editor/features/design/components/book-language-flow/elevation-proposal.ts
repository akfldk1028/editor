export interface SelectedMassIdentity {
  executionId: string;
  programHash: string;
  geometryHash: string;
  finalGeometryHash: string;
  visualHash: string;
  floorCapacityPlanHash: string;
  legalFloorFieldHash: string;
  actualGfaStopHash: string;
}

export interface ElevationProposalEvidence {
  status: string;
  previewUrl: string;
  sha256: string;
  provider: string;
  model: string;
  strategyId: string;
  primarySystem: string;
  presentationKind: string;
  authority: string;
  requestCount: number;
  retryCount: number;
  roofGuardStatus: string;
  roofGuardChangedPixels: number;
}

type UnknownRecord = Record<string, unknown>;

function record(value: unknown): UnknownRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : null;
}

export function extractElevationProposal(
  passport: unknown,
  selected: SelectedMassIdentity,
): ElevationProposalEvidence | null {
  const passportRecord = record(passport);
  const elevation = record(passportRecord?.elevation_evidence);
  const proposal = record(elevation?.image_proposal);
  const identity = record(proposal?.identity);
  const artifact = record(proposal?.artifact);
  const strategy = record(proposal?.strategy);
  const providerMetadata = record(proposal?.provider_metadata);
  const presentation = record(proposal?.presentation);
  const roofGuard = record(providerMetadata?.roof_semantic_guard);
  if (!proposal || !identity || !artifact || !strategy) return null;
  if (
    !selected.floorCapacityPlanHash
    || !selected.finalGeometryHash
    || !selected.visualHash
    || !selected.legalFloorFieldHash
    || !selected.actualGfaStopHash
    || passportRecord?.program_hash !== selected.programHash
    || passportRecord?.geometry_hash !== selected.geometryHash
    || passportRecord?.final_legal_geometry_hash
      !== selected.finalGeometryHash
    || passportRecord?.visual_hash !== selected.visualHash
    || passportRecord?.floor_capacity_plan_hash !== selected.floorCapacityPlanHash
    || passportRecord?.legal_floor_field_hash
      !== selected.legalFloorFieldHash
    || passportRecord?.candidate_actual_gfa_stop_hash
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
  const previewUrl = typeof artifact.preview_url === 'string'
    ? artifact.preview_url
    : '';
  if (!previewUrl.startsWith('/')) return null;
  return {
    status: typeof proposal.status === 'string' ? proposal.status : 'not_evaluated',
    previewUrl,
    sha256: typeof artifact.sha256 === 'string' ? artifact.sha256 : '',
    provider: typeof proposal.provider === 'string' ? proposal.provider : '',
    model: typeof providerMetadata?.model === 'string' ? providerMetadata.model : '',
    strategyId: typeof strategy.strategy_id === 'string' ? strategy.strategy_id : '',
    primarySystem: typeof strategy.primary_system === 'string'
      ? strategy.primary_system
      : '',
    presentationKind: typeof presentation?.kind === 'string'
      ? presentation.kind
      : 'legacy_facade_proposal',
    authority: typeof presentation?.authority === 'string'
      ? presentation.authority
      : 'generated_design_proposal',
    requestCount: typeof proposal.request_count === 'number'
      ? proposal.request_count
      : 0,
    retryCount: typeof proposal.retry_count === 'number'
      ? proposal.retry_count
      : 0,
    roofGuardStatus: typeof roofGuard?.status === 'string'
      ? roofGuard.status
      : 'not_recorded',
    roofGuardChangedPixels: typeof roofGuard?.changed_pixel_count === 'number'
      ? roofGuard.changed_pixel_count
      : 0,
  };
}
