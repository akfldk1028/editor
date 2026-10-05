import type {
  CreativeMassCard,
  ExecutedMassManifest,
  ExecutedMassRecord,
  MassExecutionPassport,
} from '../../lib/language-system-types';

export function CreativeMassEvidence({ mass }: { mass: CreativeMassCard }) {
  return (
    <aside className="book-evidence book-evidence--creative" aria-label="Pre-legal creative MASS evidence">
      <header>
        <span>PRE-LEGAL CREATIVE MASS</span>
        <strong>{mass.candidateId}</strong>
      </header>
      <img src={mass.renderUrl} alt={`${mass.candidateId} creative MASS`} />
      <dl className="book-evidence__attributes">
        <div><dt>FAMILY</dt><dd>{mass.family}</dd></div>
        <div><dt>FORM CLASS</dt><dd>{mass.formClass}</dd></div>
        <div><dt>CAPACITY BAND</dt><dd>{mass.capacityBand}</dd></div>
        <div><dt>STOREYS</dt><dd>{mass.storeys}</dd></div>
        <div><dt>LEGAL STATUS</dt><dd>{mass.legalStatus.replaceAll('_', ' ').toUpperCase()}</dd></div>
        <div><dt>MORPHOLOGY DISTANCE</dt><dd>{mass.morphologyDistance.toFixed(6)}</dd></div>
        <div><dt>PROGRAM HASH</dt><dd>{mass.programHash.slice(0, 18)}</dd></div>
        <div><dt>GEOMETRY HASH</dt><dd>{mass.geometryHash.slice(0, 18)}</dd></div>
      </dl>
      <p>
        This choice-pool card is pre-legal. Execute, paid VLM, law, parking,
        elevation, and certified passport actions remain unavailable.
      </p>
    </aside>
  )
}
import { ArchitecturalRenderEvidence } from './ArchitecturalRenderEvidence';
import { MultiViewElevationEvidence } from './MultiViewElevationEvidence';
import { extractElevationProposal } from './elevation-proposal';
import { extractMultiViewElevation } from './multi-view-elevation';
import { executionActionCopy, executionRunCopy } from './execution-mode';

interface ExecutedMassEvidenceProps {
  archive: ExecutedMassManifest;
  mass: ExecutedMassRecord;
  passport: MassExecutionPassport | null;
  passportError: string;
  onExecute: () => void;
  executionState: 'idle' | 'running' | 'complete' | 'failed';
  executionError: string;
  onVlmReview: () => void;
  vlmReviewState: 'idle' | 'running' | 'complete' | 'failed';
  vlmReviewError: string;
}

function percent(value: number | null): string {
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : 'NOT RECORDED';
}

function referenceCount(passport: MassExecutionPassport | null): number {
  const vlm = passport?.stages.find((stage) => stage.id === 'vlm');
  const inputs = vlm?.evidence.image_inputs;
  if (!inputs || typeof inputs !== 'object' || Array.isArray(inputs)) return 0;
  const references = (inputs as { references?: unknown }).references;
  return Array.isArray(references) ? references.length : 0;
}

function scoreMean(evidence: Record<string, unknown> | undefined): string {
  const scores = evidence?.concept_scores;
  if (!scores || typeof scores !== 'object' || Array.isArray(scores)) return 'NOT RECORDED';
  const values = Object.values(scores).filter((value): value is number => typeof value === 'number');
  if (!values.length) return 'NOT RECORDED';
  return (values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(4);
}

function criticActions(evidence: Record<string, unknown> | undefined): string {
  const actions = evidence?.critic_actions;
  return Array.isArray(actions) && actions.length
    ? actions.map(String).join(' · ')
    : 'NONE RECORDED';
}

interface ElevationViewEvidence {
  view: string;
  preview_url: string;
  sha256: string;
}

const EXPECTED_GEOMETRY_VIEWS = ['front', 'right', 'back', 'left', 'top', 'axon'] as const;

function elevationViews(passport: MassExecutionPassport | null): ElevationViewEvidence[] {
  const node = passport?.activation_graph?.nodes.find(
    (candidate) => candidate.id === 'elevation:result'
      && candidate.status === 'generated'
      && candidate.evidence.artifact_exists === true,
  );
  const views = node?.evidence.views;
  if (!Array.isArray(views)) return [];
  return views.flatMap((value) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
    const row = value as Record<string, unknown>;
    const view = typeof row.view === 'string' ? row.view : '';
    const previewUrl = typeof row.preview_url === 'string' ? row.preview_url : '';
    if (!view || !previewUrl.startsWith('/')) return [];
    return [{
      view,
      preview_url: previewUrl,
      sha256: typeof row.sha256 === 'string' ? row.sha256 : '',
    }];
  });
}

function passportDisplayStatus(
  passport: MassExecutionPassport | null,
): string {
  if (!passport) return 'LOADING';
  return passport.status.replaceAll('_', ' ').toUpperCase();
}

export function ExecutedMassEvidence({
  archive,
  mass,
  passport,
  passportError,
  onExecute,
  executionState,
  executionError,
  onVlmReview,
  vlmReviewState,
  vlmReviewError,
}: ExecutedMassEvidenceProps) {
  const vlmStage = passport?.stages.find((stage) => stage.id === 'vlm');
  const selectorStage = passport?.stages.find((stage) => stage.id === 'selector');
  const vlmProgramFit = vlmStage?.evidence.program_fit_hard_pass;
  const cost = vlmStage?.evidence.cost_observation as {
    max_http_attempts?: number;
    usage?: { total_tokens?: number };
  } | undefined;
  const specialistEvidence = passport?.agent_collaboration?.evidence ?? [];
  const generatedElevations = elevationViews(passport);
  const generatedElevationNames = new Set(generatedElevations.map((view) => view.view));
  const hasCompleteGeometryViewSet = generatedElevations.length === EXPECTED_GEOMETRY_VIEWS.length
    && EXPECTED_GEOMETRY_VIEWS.every((view) => generatedElevationNames.has(view));
  const executionId = archive.selected_run_id.startsWith('single-execution:')
    ? archive.selected_run_id.slice('single-execution:'.length)
    : (passport?.agent_collaboration?.identity?.execution_id ?? '');
  const imageProposal = extractElevationProposal(passport, {
    executionId,
    programHash: mass.program_hash,
    geometryHash: mass.geometry_hash,
    finalGeometryHash: (
      mass.final_geometry_hash ?? mass.final_legal_geometry_hash ?? ''
    ),
    visualHash: mass.visual_hash ?? '',
    floorCapacityPlanHash: mass.floor_capacity_plan_hash ?? '',
    legalFloorFieldHash: mass.legal_floor_field_hash ?? '',
    actualGfaStopHash: mass.candidate_actual_gfa_stop_hash ?? '',
  });
  const multiViewProposal = extractMultiViewElevation(passport, {
    executionId,
    programHash: mass.program_hash,
    geometryHash: mass.geometry_hash,
    finalGeometryHash: (
      mass.final_geometry_hash ?? mass.final_legal_geometry_hash ?? ''
    ),
    visualHash: mass.visual_hash ?? '',
    floorCapacityPlanHash: mass.floor_capacity_plan_hash ?? '',
    legalFloorFieldHash: mass.legal_floor_field_hash ?? '',
    actualGfaStopHash: mass.candidate_actual_gfa_stop_hash ?? '',
  });
  const replayCopy = executionActionCopy();

  return (
    <aside className="book-evidence executed-mass-evidence">
      <div className="book-evidence__heading">
        <span>ACTUAL EXECUTED MASS · {executionRunCopy(mass.execution_mode)} · {mass.variant_id}</span>
        <h4>{mass.label}</h4>
        <code>{mass.geometry_hash}</code>
      </div>
      <div className="book-evidence__sources geometry-contract__preview">
        <figure>
          <img src={mass.preview_url} alt={`${mass.label} actual compiler MASS`} />
          <figcaption>
            <strong>ACTUAL COMPILER MASS</strong>
            <span>GEOMETRY AUTHORITY · BOOK raster 0 · {archive.run_id}</span>
          </figcaption>
        </figure>
      </div>
      {imageProposal && (
        <ArchitecturalRenderEvidence
          massLabel={mass.label}
          proposal={imageProposal}
        />
      )}
      {multiViewProposal && (
        <MultiViewElevationEvidence
          massLabel={mass.label}
          proposal={multiViewProposal}
        />
      )}
      {generatedElevations.length > 0 && (
        <section className="executed-mass-evidence__elevations">
          <header>
            {hasCompleteGeometryViewSet
              ? `6-VIEW GEOMETRY VERIFICATION · ${generatedElevations.length} VIEWS`
              : `GEOMETRY VIEW EVIDENCE INCOMPLETE · ${generatedElevations.length} / ${EXPECTED_GEOMETRY_VIEWS.length} VIEWS`}
          </header>
          <div>
            {generatedElevations.map((view) => (
              <figure key={`${view.view}:${view.preview_url}`}>
                <img
                  src={view.preview_url}
                  alt={`${mass.label} ${view.view} elevation`}
                />
                <figcaption>
                  <strong>{view.view.toUpperCase()}</strong>
                  <code>{view.sha256.slice(0, 12)}</code>
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}
      <div className="executed-mass-evidence__execute">
        <button
          type="button"
          onClick={onExecute}
          disabled={executionState === 'running'}
          aria-label="Replay exact selected MASS AST"
        >
          <span>{executionState === 'running' ? 'REPLAYING AST / GATE / PNG' : replayCopy.label}</span>
          <strong>{executionState === 'complete' ? 'REPLAY RUN ADDED TO THIS GRAPH' : replayCopy.detail}</strong>
        </button>
        {executionError && <p role="alert">{executionError}</p>}
        {archive.selected_run_id.startsWith('single-execution:') && (
          <button
            type="button"
            onClick={onVlmReview}
            disabled={vlmReviewState === 'running'}
            aria-label="Run bounded paid VLM"
          >
            <span>{vlmReviewState === 'running' ? 'REVIEWING GENERATED MASS' : 'RUN BOUNDED PAID VLM'}</span>
            <strong>{vlmReviewState === 'complete' ? 'PASSPORT + GRAPH UPDATED' : '1 MASS · MAX 3 REFERENCES · 0 RETRIES'}</strong>
          </button>
        )}
        {vlmReviewError && <p role="alert">{vlmReviewError}</p>}
      </div>
      <dl className="book-evidence__attributes">
        <div><dt>PNU</dt><dd>{archive.pnu}</dd></div>
        <div><dt>OPERATION</dt><dd>{mass.operation_label}</dd></div>
        <div><dt>BOOK RULE</dt><dd>{mass.book_principle_id}</dd></div>
        <div><dt>BASE VOLUME</dt><dd>{mass.book_scope}</dd></div>
        <div><dt>PROGRAM</dt><dd>{mass.program_label || mass.program_type}</dd></div>
        <div><dt>EXECUTION MODE</dt><dd>{executionRunCopy(mass.execution_mode)}</dd></div>
        <div><dt>FAR</dt><dd>{mass.far_pct == null ? 'NOT RECORDED' : `${mass.far_pct.toFixed(3)}%`}</dd></div>
        <div><dt>BCR</dt><dd>{mass.bcr_pct == null ? 'NOT RECORDED' : `${mass.bcr_pct.toFixed(3)}%`}</dd></div>
        <div><dt>GFA</dt><dd>{mass.total_floor_area_m2 == null ? 'NOT RECORDED' : `${mass.total_floor_area_m2.toFixed(3)}m²`}</dd></div>
        <div>
          <dt>FLOORS</dt>
          <dd>
            {mass.num_floors == null
              ? 'NOT RECORDED'
              : `${mass.num_floors} FLOORS${mass.floor_height_m == null ? '' : ` · ${mass.floor_height_m.toFixed(3)}m`}`}
          </dd>
        </div>
        <div><dt>PARKING REQUIRED / PROVIDED</dt><dd>{mass.parking_required == null || mass.parking_provided == null ? 'NOT RECORDED' : `${mass.parking_required} / ${mass.parking_provided}`}</dd></div>
        <div><dt>ELEVATION</dt><dd>{mass.elevation_status?.replaceAll('_', ' ').toUpperCase() || 'NOT EVALUATED'}</dd></div>
        <div><dt>MATRIX PROVENANCE</dt><dd>{mass.floor_matrix_stack?.length ? `${mass.matrix_convention || 'matrix4'} · ${mass.floor_matrix_stack.length} TRANSFORMS` : 'NOT RECORDED'}</dd></div>
        <div><dt>CAPACITY ALT</dt><dd>{mass.capacity_alternative_id}</dd></div>
        <div><dt>TARGET / ACHIEVED</dt><dd>{percent(mass.capacity_target_utilization)} / {percent(mass.capacity_achieved_utilization)}</dd></div>
        <div><dt>GEOMETRY READY</dt><dd>{mass.geometry_ready === false ? 'FAIL' : 'PASS'}</dd></div>
        <div><dt>FULL HARD GATES</dt><dd>{mass.hard_pass ? 'PASS' : 'PENDING / FAIL'}</dd></div>
        <div><dt>VLM</dt><dd>{vlmStage?.status?.replaceAll('_', ' ').toUpperCase() ?? 'LOADING'}</dd></div>
        <div><dt>VLM PROGRAM FIT</dt><dd>{typeof vlmProgramFit === 'boolean' ? (vlmProgramFit ? 'PASS' : 'FAIL') : 'NOT RECORDED'}</dd></div>
        <div><dt>VLM VISUAL MEAN</dt><dd>{scoreMean(vlmStage?.evidence)}</dd></div>
        <div><dt>VLM INPUTS</dt><dd>{referenceCount(passport)} REFERENCES + GENERATED MASS</dd></div>
        <div><dt>VLM ACTIONS</dt><dd>{criticActions(vlmStage?.evidence)}</dd></div>
        <div><dt>VLM RESPONSE</dt><dd>{String(vlmStage?.evidence.response_id || 'NOT RECORDED')}</dd></div>
        <div><dt>VLM TOKENS</dt><dd>{cost?.usage?.total_tokens?.toLocaleString() ?? 'NOT RECORDED'}</dd></div>
        <div><dt>VLM HTTP CEILING</dt><dd>{cost?.max_http_attempts ?? 'NOT RECORDED'}</dd></div>
        <div><dt>SELECTOR</dt><dd>{selectorStage?.status?.toUpperCase() ?? 'LOADING'}</dd></div>
        <div><dt>PASSPORT</dt><dd>{passport ? passportDisplayStatus(passport) : (passportError || 'LOADING')}</dd></div>
        <div><dt>FLOOR CONTRACT</dt><dd>{mass.floor_contract_hash || 'NOT RECORDED'}</dd></div>
        <div><dt>FLOOR CAPACITY PLAN</dt><dd>{mass.floor_capacity_plan_hash || 'NOT RECORDED'}</dd></div>
        <div><dt>PROGRAM HASH</dt><dd>{mass.program_hash.slice(0, 18)}</dd></div>
        <div><dt>GEOMETRY HASH</dt><dd>{mass.geometry_hash.slice(0, 18)}</dd></div>
      </dl>
      {specialistEvidence.length > 0 && (
        <div className="geometry-contract__passport geometry-contract__passport--summary">
          <span>SPECIALIST COLLABORATION</span>
          <dl className="book-evidence__attributes">
            {specialistEvidence.map((row) => (
              <div key={row.evidence_id}>
                <dt>{row.agent.replaceAll('_', ' ').toUpperCase()}</dt>
                <dd>{row.status.replaceAll('_', ' ').toUpperCase()}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <div className="geometry-contract__passport geometry-contract__passport--summary">
        <span>SINGLE GRAPH AUTHORITY</span>
        <p>The central graph is the only causal view. Every bright edge is backed by this MASS passport; unevaluated VLM nodes remain inactive.</p>
      </div>
      <div className="geometry-contract__program">
        <span>ARCHIVED EXECUTED GEOMETRY DSL · {mass.node_count} NODES</span>
        <pre>{mass.dsl}</pre>
      </div>
    </aside>
  );
}
