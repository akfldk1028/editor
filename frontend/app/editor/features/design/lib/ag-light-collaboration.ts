import type { AGLightReview } from '../components/ag-light-flow/types';
import type { DesignEvidence } from './api-client';
import type { GeoJSONFeature, SetbackGeometriesMap } from './types';

export const COLLABORATION_STEPS = [
  { label: '1 법규', agent: 'law_graph_agent', output: 'Graph DB 조항·제약·누락 evidence' },
  { label: '2 주차', agent: 'parking_agent', output: '법정대수·연접·전면도로/차로 검토' },
  { label: '3 MassDSL', agent: 'massdsl_agent', output: '법규·주차 evidence를 verb sequence로 구조화' },
  { label: '4 매스/디자인', agent: 'maas_geometry_agent', output: '법규를 만족하는 MAAS 형태·repair 근거' },
  { label: '5 문법검토', agent: 'grammar_critic_agent', output: '도형언어·section connector·evidence 완결성 검토' },
  { label: '6 최종검토', agent: 'review_agent', output: '통과/보류/실패와 남은 리스크' },
];

export type AgentTrace = AGLightReview & {
  refs: string[];
  formula?: string;
  decision: string;
};

const asRecord = (value: unknown): Record<string, unknown> => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
);

const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const asString = (value: unknown): string | undefined => (
  typeof value === 'string' && value.trim() ? value.trim() : undefined
);

const asNumber = (value: unknown): number | undefined => (
  typeof value === 'number' && Number.isFinite(value) ? value : undefined
);

const getNested = (source: unknown, path: string[]): unknown => (
  path.reduce<unknown>((current, key) => asRecord(current)[key], source)
);

const uniqueStrings = (values: unknown[], limit = 4): string[] => (
  Array.from(new Set(values
    .flatMap((value) => Array.isArray(value) ? value : [value])
    .map((value) => typeof value === 'string' ? value.trim() : '')
    .filter(Boolean)))
    .slice(0, limit)
);

const compactText = (value: unknown, fallback = '-'): string => {
  const text = typeof value === 'string'
    ? value
    : value == null
      ? ''
      : JSON.stringify(value);
  if (!text) return fallback;
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
};

const formatMetric = (value: number | undefined): string => (
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '-'
);

const extractVerbSequence = (...sources: unknown[]): string[] => uniqueStrings(
  sources.flatMap((source) => asArray(source).map((item) => {
    if (typeof item === 'string') return item;
    const record = asRecord(item);
    return asString(record.verb) || asString(record.operation) || asString(record.name) || '';
  })),
  8,
);

export const statusColor = (status: AGLightReview['status']): string => {
  if (status === 'pass') return '#5eead4';
  if (status === 'fail') return '#fca5a5';
  if (status === 'check') return '#fbbf24';
  return '#93c5fd';
};

export const getMassLegalStatus = (
  evidence: DesignEvidence | null,
  massGeojson: GeoJSONFeature | null,
): string => {
  const props = asRecord(massGeojson?.properties);
  return asString(evidence?.final_status) || asString(props.legal_status) || 'unknown';
};

export const buildAgentTrace = (
  reviews: AGLightReview[],
  evidence: DesignEvidence | null,
  massGeojson: GeoJSONFeature | null,
  setbackGeometries?: SetbackGeometriesMap | null
): AgentTrace[] => {
  const props = asRecord(massGeojson?.properties);
  const evidenceCandidate = asRecord(evidence?.candidate);
  const checks = asArray(evidence?.checks).map(asRecord);
  const legal = asRecord(evidence?.legal);
  const lawArticles = asArray(legal.law_articles).map(asRecord);
  const graphProjection = asRecord(legal.graph_projection);
  const parking = asRecord(props.parking_precheck);
  const parkingFromEvidence = asRecord(getNested(evidence, ['mobility', 'parking', 'precheck']));
  const sourceParking = Object.keys(parking).length ? parking : parkingFromEvidence;
  const requiredCount = asRecord(sourceParking.required_count);
  const layout = asRecord(sourceParking.layout_candidate);
  const layoutFormula = asRecord(layout.layout_formula);
  const maasModel = asRecord(props.maas_model || evidenceCandidate.maas_model);
  const massdslProposal = asRecord(props.massdsl_proposal || maasModel.massdsl_proposal);
  const grammarReview = asRecord(props.grammar_review || maasModel.grammar_review);
  const massdslSourceRefs = asRecord(massdslProposal.source_refs);
  const designQuality = asRecord(props.design_quality || maasModel.design_quality);
  const sectionProfile = asRecord(props.section_profile || maasModel.section_profile);
  const datum = asRecord(getNested(setbackGeometries, ['datum_result']));
  const sunlightEnvelope = asRecord(getNested(setbackGeometries, ['sunlight_envelope']));
  const massShape = asString(props.mass_shape) || asString(maasModel.operator) || asString(props.algorithm) || 'maas_legal_envelope';
  const verbSequence = extractVerbSequence(props.maas_verb_sequence, maasModel.verb_sequence);
  const lawRefs = uniqueStrings([
    lawArticles.map((article) => article.full_id || article.title || article.ref_id),
    checks.map((check) => asArray(asRecord(check.basis).law_articles)),
    checks.map((check) => asArray(check.evidence_refs)),
  ], 5);
  const lawCheckRefs = uniqueStrings(
    checks.map((check) => {
      const key = asString(check.key);
      const status = asString(check.status);
      return key ? `${key}${status ? `:${status}` : ''}` : '';
    }),
    5,
  );
  const finalDecision = asRecord(evidence?.final_decision);
  const missingDecisionEvidence = uniqueStrings(asArray(finalDecision.missing_evidence), 4);
  const parkingCheck = asRecord(checks.find((check) => check.key === 'parking_loading_and_mobility.parking_required_count') || {});
  const parkingRefs = uniqueStrings([
    requiredCount.selected_rule_id,
    requiredCount.base_rule_id,
    requiredCount.source_ordinance,
    requiredCount.source_appendix,
    parkingCheck.evidence_refs,
    asArray(asRecord(parkingCheck.basis).law_articles),
  ], 5);
  const qualityParts = [
    asNumber(designQuality.score) !== undefined ? `quality ${asNumber(designQuality.score)?.toFixed(3)}` : '',
    asString(designQuality.source),
    verbSequence.length ? `verbs ${verbSequence.join('->')}` : '',
    asString(sectionProfile.kind) ? `section ${asString(sectionProfile.kind)}` : '',
  ].filter(Boolean);

  const reviewByAgent = new Map(reviews.map((review) => [review.agent, review]));
  const lawReview = reviewByAgent.get('law_graph_agent') || reviewByAgent.get('law_agent');
  const parkingReview = reviewByAgent.get('parking_agent');
  const massdslReview = reviewByAgent.get('massdsl_agent');
  const maasReview = reviewByAgent.get('maas_geometry_agent');
  const grammarCriticReview = reviewByAgent.get('grammar_critic_agent');
  const reviewAgent = reviewByAgent.get('review_agent') || reviewByAgent.get('design_critic');
  const legalMetrics = asRecord(maasModel.legal_metrics);
  const optimizerBackend = asRecord(designQuality.optimizer_backend);
  const datumParts = [
    asNumber(datum.datum_elevation_m) !== undefined ? `datum ${asNumber(datum.datum_elevation_m)?.toFixed(2)}m` : '',
    asNumber(datum.parcel_datum_m) !== undefined ? `parcel ${asNumber(datum.parcel_datum_m)?.toFixed(2)}m` : '',
    asNumber(datum.road_datum_m) !== undefined ? `road ${asNumber(datum.road_datum_m)?.toFixed(2)}m` : '',
    asNumber(datum.neighbor_datum_m) !== undefined ? `neighbor ${asNumber(datum.neighbor_datum_m)?.toFixed(2)}m` : '',
  ].filter(Boolean);
  const sunlightParts = [
    sunlightEnvelope.applies !== undefined ? `sunlight applies=${String(sunlightEnvelope.applies)}` : '',
    sunlightEnvelope.slope !== undefined ? `slope ${String(sunlightEnvelope.slope)}` : '',
    asNumber(sunlightEnvelope.datum_elevation_m) !== undefined ? `sunlight datum ${asNumber(sunlightEnvelope.datum_elevation_m)?.toFixed(2)}m` : '',
  ].filter(Boolean);

  return [
    {
      ...(lawReview || { agent: 'law_graph_agent', label: '법규', status: 'check' as const, summary: '법규 근거 확인', detail: '' }),
      agent: 'law_graph_agent',
      refs: lawRefs.length ? lawRefs : (lawCheckRefs.length ? lawCheckRefs : ['ARR legal constraint checks']),
      formula: graphProjection.available === true ? `Graph DB law refs ${graphProjection.resolved_count ?? lawRefs.length}건` : 'ARR constraint/evidence bundle',
      decision: compactText([
        `status=${getMassLegalStatus(evidence, massGeojson)}`,
        missingDecisionEvidence.length ? `missing=${missingDecisionEvidence.join(', ')}` : '',
      ].filter(Boolean).join(' · '), '법규 check/final_decision 기반'),
    },
    {
      ...(parkingReview || { agent: 'parking_agent', label: '주차', status: 'check' as const, summary: '주차 근거 확인', detail: '' }),
      agent: 'parking_agent',
      refs: parkingRefs.length ? parkingRefs : ['parking_precheck.required_count/layout_candidate'],
      formula: compactText(requiredCount.rounding_rule || layoutFormula.module || layoutFormula.schema_version || layout.layout_formula, 'parking formula 확인 필요'),
      decision: compactText({
        required: requiredCount.required_spaces,
        provided: layout.provided_spaces,
        status: layout.status || sourceParking.status,
        strategy: sourceParking.selected_strategy || sourceParking.strategy || props.parking_strategy,
      }),
    },
    {
      ...(massdslReview || { agent: 'massdsl_agent', label: 'MassDSL', status: 'info' as const, summary: 'MassDSL proposal 검증', detail: '' }),
      agent: 'massdsl_agent',
      refs: uniqueStrings([
        asString(massdslProposal.schema_version),
        asString(massdslProposal.proposal_id),
        verbSequence,
        asString(massdslSourceRefs.source_geometry_status),
        asNumber(massdslSourceRefs.source_surface_count) !== undefined
          ? `source surfaces ${asNumber(massdslSourceRefs.source_surface_count)}`
          : '',
      ], 8),
      formula: compactText({
        validation: massdslProposal.validation_status,
        intent: asRecord(massdslProposal.intent),
        constraints: asRecord(massdslProposal.constraints),
      }, 'MassDSL proposal contract'),
      decision: compactText(massdslProposal.rationale || 'MassDSL proposal evidence 확인'),
    },
    {
      ...(maasReview || { agent: 'maas_geometry_agent', label: '매스/기하', status: 'info' as const, summary: 'MAAS 매스 알고리즘 검증', detail: '' }),
      agent: 'maas_geometry_agent',
      refs: uniqueStrings([
        massShape,
        verbSequence,
        asString(designQuality.source),
        asString(optimizerBackend.source),
        asString(datum.elevation_source),
        '건축법 시행령 §86',
        '건축법 시행령 §119',
      ], 8),
      formula: compactText([
        qualityParts.join(' · ') || 'MAAS legal morphology ranking',
        datumParts.join(' · '),
        sunlightParts.join(' · '),
      ].filter(Boolean).join(' | '), 'MAAS + datum/sunlight evidence'),
      decision: compactText({
        shape: massShape,
        far: props.far ?? legalMetrics.far,
        bcr: props.bcr ?? legalMetrics.bcr,
        height: props.height ?? legalMetrics.height,
        quality: designQuality.score,
        volumes: asArray(maasModel.volumes).length || asArray(props.mass_volumes).length,
        floor_groups: asArray(maasModel.floor_groups || props.floor_groups).length,
      }),
    },
    {
      ...(grammarCriticReview || { agent: 'grammar_critic_agent', label: '문법검토', status: 'check' as const, summary: '도형언어/evidence 검토', detail: '' }),
      agent: 'grammar_critic_agent',
      refs: uniqueStrings([
        asString(grammarReview.schema_version),
        asString(grammarReview.family),
        asArray(grammarReview.verbs),
        asArray(grammarReview.issues),
      ], 8),
      formula: compactText({
        section_language: grammarReview.has_section_language,
        source_surfaces: grammarReview.has_source_surface_contract,
        parking_evidence: grammarReview.has_parking_evidence,
        volume_count: grammarReview.volume_count,
        surface_count: grammarReview.surface_count,
      }, 'grammar critic evidence'),
      decision: compactText({
        status: grammarReview.status,
        issues: asArray(grammarReview.issues),
      }),
    },
    {
      ...(reviewAgent || { agent: 'review_agent', label: '최종검토', status: 'check' as const, summary: '최종 검토', detail: '' }),
      agent: 'review_agent',
      refs: uniqueStrings([
        finalDecision.status,
        missingDecisionEvidence,
        lawCheckRefs,
        parkingRefs,
      ], 8),
      formula: 'law_graph + parking + MAAS geometry evidence 종합',
      decision: compactText({
        status: getMassLegalStatus(evidence, massGeojson),
        missing: missingDecisionEvidence,
        hard_failures: asArray(evidence?.hard_failures).length,
        open_issues: asArray(evidence?.open_issues).length,
      }),
    },
  ];
};

export const makeAgentReviews = (
  evidence: DesignEvidence | null,
  massGeojson: GeoJSONFeature | null,
  setbackGeometries?: SetbackGeometriesMap | null
): AGLightReview[] => {
  const props = asRecord(massGeojson?.properties);
  const evidenceCandidate = asRecord(evidence?.candidate);
  const parking = asRecord(props.parking_precheck);
  const evidenceParking = asRecord(evidenceCandidate.parking_precheck);
  const layoutCandidate = asRecord(parking.layout_candidate);
  const evidenceLayoutCandidate = asRecord(evidenceParking.layout_candidate);
  const requiredCount = asRecord(parking.required_count);
  const evidenceRequiredCount = asRecord(evidenceParking.required_count);
  const sourceParking = Object.keys(parking).length > 0 ? parking : evidenceParking;
  const requiredParking = asNumber(sourceParking.required)
    ?? asNumber(sourceParking.required_spaces)
    ?? asNumber(requiredCount.required_spaces)
    ?? asNumber(evidenceRequiredCount.required_spaces)
    ?? asNumber(layoutCandidate.required_spaces)
    ?? asNumber(evidenceLayoutCandidate.required_spaces);
  const providedParking = asNumber(sourceParking.provided)
    ?? asNumber(sourceParking.provided_spaces)
    ?? asNumber(layoutCandidate.provided_spaces)
    ?? asNumber(evidenceLayoutCandidate.provided_spaces);
  const parkingStrategy = String(
    sourceParking.selected_strategy
    || sourceParking.strategy
    || layoutCandidate.strategy
    || evidenceLayoutCandidate.strategy
    || evidenceCandidate.parking_strategy
    || props.parking_strategy
    || 'unknown',
  );
  const finalStatus = String(evidence?.final_status || props.legal_status || 'evidence_loaded');
  const hardFailures = asArray(evidence?.hard_failures);
  const missingEvidence = asArray(evidence?.missing_evidence);
  const openIssues = asArray(evidence?.open_issues);
  const datum = asRecord(getNested(setbackGeometries, ['datum_result']));
  const sunlightEnvelope = asRecord(getNested(setbackGeometries, ['sunlight_envelope']));
  const sunlightApplies = Object.keys(sunlightEnvelope).length > 0
    && sunlightEnvelope.applies !== false
    && sunlightEnvelope.enabled !== false;
  const datumElevation = asNumber(datum.datum_elevation_m)
    ?? asNumber(datum.sunlight_datum_m)
    ?? asNumber(datum.average_level_m)
    ?? asNumber(datum.elevation_m)
    ?? asNumber(datum.parcel_datum_m);
  const datumSource = typeof datum.elevation_source === 'string' ? datum.elevation_source : 'datum_result';
  const far = asNumber(props.far);
  const bcr = asNumber(props.bcr);
  const height = asNumber(props.height);
  const massShape = asString(props.mass_shape) || asString(asRecord(props.maas_model).operator) || asString(props.algorithm) || 'maas_legal_envelope';
  const designQuality = asRecord(props.design_quality || asRecord(props.maas_model).design_quality);
  const designQualityScore = asNumber(props.design_quality_score) ?? asNumber(designQuality.score);
  const verbSequence = extractVerbSequence(props.maas_verb_sequence, asRecord(props.maas_model).verb_sequence);
  const sectionProfile = asRecord(props.section_profile || asRecord(props.maas_model).section_profile);
  const sectionKind = asString(sectionProfile.kind);
  const sectionHint = asString(sectionProfile.render_hint);

  const parkingStatus: AGLightReview['status'] = requiredParking && providedParking !== undefined
    ? (providedParking >= requiredParking ? 'pass' : 'fail')
    : 'check';
  const lawStatus: AGLightReview['status'] = hardFailures.length > 0 || finalStatus.toLowerCase().includes('fail')
    ? 'fail'
    : (missingEvidence.length > 0 || openIssues.length > 0 ? 'check' : 'pass');
  const maasStatus: AGLightReview['status'] = lawStatus === 'fail' ? 'check' : 'pass';
  const reviewStatus: AGLightReview['status'] = lawStatus === 'fail' || parkingStatus === 'fail'
    ? 'fail'
    : (lawStatus === 'check' || parkingStatus === 'check' ? 'check' : 'pass');

  return [
    {
      agent: 'law_graph_agent',
      label: '법규',
      status: lawStatus,
      summary: `최종 ${finalStatus}`,
      detail: `hard ${hardFailures.length} · missing ${missingEvidence.length} · issue ${openIssues.length}`,
    },
    {
      agent: 'parking_agent',
      label: '주차',
      status: parkingStatus,
      summary: requiredParking !== undefined && providedParking !== undefined
        ? `${providedParking}/${requiredParking}대 · ${parkingStrategy}`
        : '주차 산정 근거 확인 필요',
      detail: '소규모 배치는 전면도로 이용 가능성을 별도 connector 없이 선형 주차면으로 검토',
    },
    {
      agent: 'maas_geometry_agent',
      label: '매스/기하',
      status: maasStatus,
      summary: `${massShape} · FAR ${formatMetric(far)} · BCR ${formatMetric(bcr)} · H ${formatMetric(height)}m`,
      detail: [
        designQualityScore !== undefined ? `quality ${designQualityScore.toFixed(3)}` : 'quality 확인 필요',
        verbSequence.length ? `verbs ${verbSequence.join('->')}` : 'verb sequence 없음',
        sectionKind ? `section ${sectionKind}${sectionHint ? ` (${sectionHint})` : ''}` : 'section profile 없음',
        datumElevation !== undefined ? `${datumSource} ${datumElevation.toFixed(2)}m` : 'datum_result 확인 필요',
        sunlightApplies ? '§86 envelope 적용' : '정북 envelope 없음/적용 외',
      ].join(' · '),
    },
    {
      agent: 'review_agent',
      label: '최종검토',
      status: reviewStatus,
      summary: reviewStatus === 'pass' ? '법규·주차·MAAS evidence 통합 통과' : '남은 evidence/리스크 확인 필요',
      detail: `law ${lawStatus} · parking ${parkingStatus} · maas ${maasStatus} · hard ${hardFailures.length} · missing ${missingEvidence.length}`,
    },
  ];
};
