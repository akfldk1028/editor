import { requiredValue } from '../lib/required-value';
import React, { useEffect, useState } from 'react';
import type {
  Constraint,
  DesignData,
  GeoJSONFeature,
  InteractivePreviewCandidate,
  InteractivePreviewResult,
  InteractivePatchResult,
  MaasAestheticResult,
  SetbackGeometriesMap,
} from '../lib/types';
import {
  applyInteractiveOperation,
  createInteractivePatch,
  createInteractivePreview,
  createMaasAesthetic,
  createMaasLegalVariants,
  getAgLightBusLog,
  getAgLightHealth,
  getDesignEvidence,
  sendAgLightBusMessage,
} from '../lib/api-client';
import type { AgLightBusEvent, AgLightHealth } from '../lib/api-client';
import {
  buildAgentTrace,
  COLLABORATION_STEPS,
  getMassLegalStatus,
  makeAgentReviews,
  statusColor,
  type AgentTrace,
} from '../lib/ag-light-collaboration';
import type { AGLightReview } from './ag-light-flow/types';
import A2UISurfaceRenderer from './A2UISurfaceRenderer';
import AGLightFlow from './ag-light-flow/AGLightFlow';
import DirectAgentChatPanel from './DirectAgentChatPanel';

interface Props {
  jobId?: string | null;
  design: DesignData;
  massGeojson: GeoJSONFeature | null;
  constraints: Constraint[];
  sitePolygon: object | null;
  siteArea: number | null;
  pnu?: string | null;
  buildingType: string;
  algorithm: string;
  sunlightEnvelope?: object | null;
  setbackGeometries?: SetbackGeometriesMap | null;
  onPreviewCandidate: (feature: GeoJSONFeature | null) => void;
  onAestheticGenerated?: (result: MaasAestheticResult | null, style?: string) => void;
}

const EXAMPLES = [
  '북측 상부를 4단으로 자연스럽게 후퇴시켜줘. 용적률은 5% 이상 잃지 말고.',
  '도로 쪽 저층부를 포디움처럼 더 강하게 만들어줘.',
  '코어가 가운데라 답답해. 동측 외곽으로 붙일 수 있는지 봐줘.',
];

const formatMetric = (value: number | undefined): string => (
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '-'
);

const InteractiveDesignPanel: React.FC<Props> = ({
  jobId,
  design,
  massGeojson,
  constraints,
  sitePolygon,
  siteArea,
  pnu,
  buildingType,
  algorithm,
  sunlightEnvelope,
  setbackGeometries,
  onPreviewCandidate,
  onAestheticGenerated,
}) => {
  const [message, setMessage] = useState('');
  const [result, setResult] = useState<InteractivePatchResult | null>(null);
  const [preview, setPreview] = useState<InteractivePreviewResult | null>(null);
  const [activePreviewId, setActivePreviewId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [operationLoading, setOperationLoading] = useState(false);
  const [aestheticLoading, setAestheticLoading] = useState(false);
  const [aestheticProvider, setAestheticProvider] = useState<'placeholder' | 'gpt-image' | 'nano-banana'>('placeholder');
  const [aestheticStyle, setAestheticStyle] = useState(
    'premium contemporary Korean residential facade, warm brick and limestone base, deep shadow window reveals, disciplined vertical window rhythm, refined metal balconies, elegant ground floor entrance, realistic architectural competition quality'
  );
  const [aesthetic, setAesthetic] = useState<MaasAestheticResult | null>(null);
  const [agHealth, setAgHealth] = useState<AgLightHealth | null>(null);
  const [agBusLog, setAgBusLog] = useState<AgLightBusEvent[]>([]);
  const [agReviews, setAgReviews] = useState<AGLightReview[]>([]);
  const [agTrace, setAgTrace] = useState<AgentTrace[]>([]);
  const [agLoading, setAgLoading] = useState(false);
  const [agError, setAgError] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState('law_graph_agent');
  const [error, setError] = useState('');

  useEffect(() => {
    setResult(null);
    setPreview(null);
    setActivePreviewId(null);
    setAesthetic(null);
    setAgReviews([]);
    setAgTrace([]);
    setAgError('');
    onAestheticGenerated?.(null);
    setError('');
    onPreviewCandidate(null);
  }, [design.id, onAestheticGenerated, onPreviewCandidate]);

  useEffect(() => {
    let cancelled = false;
    const refreshAgLight = async () => {
      try {
        const [health, log] = await Promise.all([
          getAgLightHealth(),
          getAgLightBusLog(20),
        ]);
        if (!cancelled) {
          setAgHealth(health);
          setAgBusLog(log);
          setAgError('');
        }
      } catch (e) {
        if (!cancelled) setAgError(e instanceof Error ? e.message : 'AG-light 연결 실패');
      }
    };
    refreshAgLight();
    return () => {
      cancelled = true;
    };
  }, [design.id]);

  const runAgLightReview = async () => {
    if (!jobId) {
      setAgError('저장된 최적화 job이 있어야 AG-light 검토를 실행할 수 있습니다.');
      return;
    }
    const rawDesignId = massGeojson?.properties?.design_id;
    const evidenceDesignId = typeof rawDesignId === 'number' ? rawDesignId : design.id;
    setAgLoading(true);
    setAgError('');
    try {
      const evidence = await getDesignEvidence(jobId, evidenceDesignId);
      const reviews = makeAgentReviews(evidence, massGeojson, setbackGeometries);
      const trace = buildAgentTrace(reviews, evidence, massGeojson, setbackGeometries);
      const metadata = {
        job_id: jobId,
        design_id: evidenceDesignId,
        source: 'arr_design_ui',
        final_status: getMassLegalStatus(evidence, massGeojson),
      };
      const handoffTargets: Record<string, string> = {
        law_graph_agent: 'parking_agent',
        parking_agent: 'maas_geometry_agent',
        maas_geometry_agent: 'review_agent',
        review_agent: 'design_orchestrator',
      };
      for (const review of reviews) {
        const agentTrace = trace.find((item) => item.agent === review.agent);
        await sendAgLightBusMessage({
          from_agent: review.agent,
          to_agent: handoffTargets[review.agent] || 'design_orchestrator',
          event_type: 'agent_reasoning_handoff',
          message: `${review.label}: ${review.summary} · 공식 ${agentTrace?.formula || 'n/a'} · 근거 ${agentTrace?.refs.join(', ') || 'none'} · 판단 ${agentTrace?.decision || review.detail}`,
          metadata: {
            ...metadata,
            status: review.status,
            label: review.label,
            refs: agentTrace?.refs || [],
            formula: agentTrace?.formula,
            decision: agentTrace?.decision,
          },
        });
      }
      setAgReviews(reviews);
      setAgTrace(trace);
      const [health, log] = await Promise.all([
        getAgLightHealth(),
        getAgLightBusLog(40),
      ]);
      setAgHealth(health);
      setAgBusLog(log);
    } catch (e) {
      const fallbackReviews = makeAgentReviews(null, massGeojson, setbackGeometries);
      const fallbackTrace = buildAgentTrace(fallbackReviews, null, massGeojson, setbackGeometries);
      setAgReviews(fallbackReviews);
      setAgTrace(fallbackTrace);
      setAgError(e instanceof Error ? e.message : 'AG-light 검토 실패');
    } finally {
      setAgLoading(false);
    }
  };

  const sendDirectAgentMessage = async (targetAgent: string, directMessage: string) => {
    const rawDesignId = massGeojson?.properties?.design_id;
    const evidenceDesignId = typeof rawDesignId === 'number' ? rawDesignId : design.id;
    await sendAgLightBusMessage({
      from_agent: 'user',
      to_agent: targetAgent,
      message: directMessage,
      metadata: {
        source: 'arr_design_ui_direct_agent_command',
        job_id: jobId,
        design_id: evidenceDesignId,
        building_type: buildingType,
        algorithm,
      },
    });
    const [health, log] = await Promise.all([
      getAgLightHealth(),
      getAgLightBusLog(40),
    ]);
    setAgHealth(health);
    setAgBusLog(log);
  };

  const submit = async () => {
    const trimmed = message.trim();
    if (!trimmed) return;
    setLoading(true);
    setError('');
    try {
      const patch = await createInteractivePatch({
        message: trimmed,
        selected_design: design,
        mass_geojson: massGeojson,
        constraints,
      });
      setResult(patch);
      setPreview(null);
      setActivePreviewId(null);
      onPreviewCandidate(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '수정 후보 생성 실패');
    } finally {
      setLoading(false);
    }
  };

  const buildPreview = async () => {
    if (!result || !sitePolygon || !siteArea) {
      setError('부지 정보가 있어야 수정안 미리보기를 계산할 수 있습니다.');
      return;
    }
    setPreviewLoading(true);
    setError('');
    try {
      const computed = await createInteractivePreview({
        patch_plan: result,
        selected_design: design,
        site_polygon: sitePolygon,
        site_area_m2: siteArea,
        constraints,
        building_type: buildingType,
        algorithm: design.algorithm || (algorithm === 'all' ? undefined : algorithm),
      });
      setPreview(computed);
      const first = computed.candidates.find(c => c.mass_geojson)?.mass_geojson || null;
      const firstId = computed.candidates.find(c => c.mass_geojson)?.id || null;
      setActivePreviewId(firstId);
      onPreviewCandidate(first);
    } catch (e) {
      setError(e instanceof Error ? e.message : '미리보기 계산 실패');
    } finally {
      setPreviewLoading(false);
    }
  };

  const buildMaasVariants = async () => {
    if (!massGeojson || !sitePolygon) {
      setError('선택된 매스와 부지 정보가 있어야 MAAS 후보를 계산할 수 있습니다.');
      return;
    }
    setPreviewLoading(true);
    setError('');
    try {
      const computed = await createMaasLegalVariants({
        mass_geojson: massGeojson,
        site_polygon: sitePolygon,
        constraints,
        building_type: buildingType,
        max_variants: 6,
        sunlight_envelope: sunlightEnvelope,
        setback_geometries: setbackGeometries,
      });
      const candidates = computed.feature_collection.features.map((feature, index) => {
        const props = feature.properties;
        const variantId = typeof props.variant_id === 'string' ? props.variant_id : `maas_${index + 1}`;
        const notes = Array.isArray(props.notes) ? props.notes.map(String) : [];
        return {
          id: variantId,
          title: `${variantId} · ${props.mass_shape || 'MAAS variant'}`,
          intent: 'maas_morphology',
          feasible: true,
          penalty: 0,
          inputs: design.inputs,
          outputs: [],
          metrics: {
            far: props.far,
            bcr: props.bcr,
            height: props.height,
            maas_score: typeof props.maas_score === 'number' ? props.maas_score : 0,
          },
          mass_geojson: feature,
          notes,
        };
      });
      const nextPreview = {
        mode: 'preview' as const,
        selected_design_id: design.id,
        algorithm: computed.algorithm,
        building_type: buildingType,
        candidates,
        notes: computed.notes,
      };
      setResult(null);
      setPreview(nextPreview);
      const first = candidates.find(c => c.mass_geojson)?.mass_geojson || null;
      const firstId = candidates.find(c => c.mass_geojson)?.id || null;
      setActivePreviewId(firstId);
      onPreviewCandidate(first);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'MAAS 후보 계산 실패');
    } finally {
      setPreviewLoading(false);
    }
  };

  const selectPreview = (candidate: InteractivePreviewCandidate) => {
    setActivePreviewId(candidate.id);
    onPreviewCandidate(candidate.mass_geojson);
  };

  const applyOperation = async (operation: object) => {
    if (!massGeojson || !sitePolygon) {
      setError('조작할 매스와 부지 정보가 필요합니다.');
      return;
    }
    setOperationLoading(true);
    setError('');
    try {
      const result = await applyInteractiveOperation({
        mass_geojson: massGeojson,
        site_polygon: sitePolygon,
        operation,
        constraints,
        building_type: buildingType,
        sunlight_envelope: sunlightEnvelope,
        setback_geometries: setbackGeometries,
      });
      const props = result.feature.properties;
	      const agentNotes = (result.agent_reviews || []).map(review => `${review.agent}: ${review.status} · ${review.summary}`);
	      const candidate = {
        id: `op_${Date.now()}`,
        title: `Push/Pull · FAR ${formatMetric(props.far)} / BCR ${formatMetric(props.bcr)}`,
        intent: 'push_pull_operation',
        feasible: true,
        penalty: 0,
        inputs: design.inputs,
        outputs: [],
        metrics: {
          far: props.far,
          bcr: props.bcr,
          height: props.height,
        },
        mass_geojson: result.feature,
	        notes: [...agentNotes, ...result.notes],
	      };
	      setPreview({
	        mode: 'preview',
	        selected_design_id: design.id,
	        algorithm: 'maas_legal_envelope',
	        building_type: buildingType,
	        candidates: [candidate],
	        notes: [...agentNotes, ...result.notes],
	        a2ui_messages: result.a2ui_messages,
	      });
      setActivePreviewId(candidate.id);
      onPreviewCandidate(result.feature);
    } catch (e) {
      setError(e instanceof Error ? e.message : '매스 조작 실패');
    } finally {
      setOperationLoading(false);
    }
  };

  const generateAesthetic = async () => {
    if (!jobId) {
      setError('저장된 최적화 job이 있어야 외관 이미지를 생성할 수 있습니다.');
      return;
    }
    if (!massGeojson?.properties?.design_id) {
      setError('현재 선택 후보의 MAAS 매스 geometry를 찾을 수 없습니다. 다른 후보를 선택한 뒤 다시 시도하세요.');
      return;
    }
    const massDesignId = massGeojson?.properties?.design_id;
    const aestheticDesignId = typeof massDesignId === 'number' ? massDesignId : design.id;
    setAestheticLoading(true);
    setError('');
    onAestheticGenerated?.(null, aestheticStyle);
    try {
      const result = await createMaasAesthetic({
        job_id: jobId,
        design_id: aestheticDesignId,
        provider: aestheticProvider,
        style: aestheticStyle,
        attach_to_evidence: true,
      });
      setAesthetic(result);
      onAestheticGenerated?.(result, aestheticStyle);
    } catch (e) {
      setError(e instanceof Error ? e.message : '외관 이미지 생성 실패');
    } finally {
      setAestheticLoading(false);
    }
  };

  return (
    <div style={{
      marginTop: 0,
      padding: 10,
      borderRadius: 8,
      border: '1px solid rgba(96,200,255,0.16)',
      background: 'rgba(15,23,42,0.92)',
      minHeight: 'calc(100vh - 72px)',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 8,
        alignItems: 'center',
        marginBottom: 8,
      }}>
        <div>
          <div style={{ color: '#dbeafe', fontSize: 12, fontWeight: 700 }}>
            상호소통 설계 수정
          </div>
          <div style={{ color: '#64748b', fontSize: 10, marginTop: 2 }}>
            대화형 수정 · MAAS 법규 후보
          </div>
        </div>
        <span style={{
          color: '#60c8ff',
          fontSize: 10,
          border: '1px solid rgba(96,200,255,0.24)',
          borderRadius: 999,
          padding: '2px 7px',
          whiteSpace: 'nowrap',
        }}>
          안 {design.id}
        </span>
      </div>

      <div style={{
        marginBottom: 10,
        padding: 9,
        borderRadius: 8,
        border: '1px solid rgba(34,197,94,0.18)',
        background: 'rgba(6,78,59,0.16)',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
          marginBottom: 7,
        }}>
          <div>
            <div style={{ color: '#d1fae5', fontSize: 11, fontWeight: 800 }}>
              AG-light React Flow
            </div>
            <div style={{ color: '#6b7280', fontSize: 9, marginTop: 2 }}>
              JSON_MODULES 법규 · 주차 · MassDSL · 매스 · 문법검토 · 최종검토 협업 그래프
            </div>
          </div>
          <span style={{
            color: agHealth?.status ? '#5eead4' : '#fbbf24',
            fontSize: 9,
            border: '1px solid rgba(94,234,212,0.18)',
            borderRadius: 999,
            padding: '2px 7px',
            whiteSpace: 'nowrap',
          }}>
            {agHealth?.status ? `ON · log ${agHealth.components?.bus?.log_count ?? agBusLog.length}` : 'CHECK'}
          </span>
        </div>
        <div
          data-testid="ag-light-collaboration-method"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
            gap: 6,
            marginBottom: 8,
          }}
        >
          {COLLABORATION_STEPS.map((step) => (
            <button
              key={step.agent}
              type="button"
              onClick={() => setSelectedAgentId(step.agent)}
              style={{
                minHeight: 58,
                padding: '7px 8px',
                borderRadius: 7,
                border: selectedAgentId === step.agent
                  ? '1px solid rgba(94,234,212,0.5)'
                  : '1px solid rgba(148,163,184,0.14)',
                background: selectedAgentId === step.agent
                  ? 'rgba(20,184,166,0.14)'
                  : 'rgba(2,6,23,0.38)',
                textAlign: 'left',
                cursor: 'pointer',
              }}
            >
              <div style={{ color: selectedAgentId === step.agent ? '#99f6e4' : '#bfdbfe', fontSize: 10, fontWeight: 900 }}>
                {step.label}
              </div>
              <div style={{ color: '#60a5fa', fontSize: 9, marginTop: 2, fontFamily: 'ui-monospace, monospace' }}>
                {step.agent}
              </div>
              <div style={{ color: '#94a3b8', fontSize: 9, lineHeight: 1.3, marginTop: 3 }}>
                {step.output}
              </div>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={runAgLightReview}
          disabled={agLoading || !jobId || !massGeojson}
          style={{
            width: '100%',
            padding: '8px 0',
            borderRadius: 7,
            border: '1px solid rgba(94,234,212,0.24)',
            cursor: agLoading || !jobId || !massGeojson ? 'default' : 'pointer',
            fontSize: 11,
            fontWeight: 800,
            background: agLoading || !jobId || !massGeojson ? 'rgba(255,255,255,0.03)' : 'rgba(20,184,166,0.14)',
            color: agLoading || !jobId || !massGeojson ? '#64748b' : '#99f6e4',
          }}
        >
          {agLoading ? '협업 검토 중...' : '현재 안 AG-light 검토 시작'}
        </button>
        <AGLightFlow
          reviews={agReviews}
          messages={agBusLog}
          status={agHealth?.status ? 'complete' : 'idle'}
          pnu={pnu}
          selectedAgentId={selectedAgentId}
          onSelectAgent={setSelectedAgentId}
        />
        <DirectAgentChatPanel
          selectedAgentId={selectedAgentId}
          onSelectedAgentChange={setSelectedAgentId}
          onSend={sendDirectAgentMessage}
          helperText="선택한 agent에게 직접 명령을 보내고 최근 bus에 반영합니다."
        />
        {agError && (
          <div style={{ marginTop: 6, color: '#fbbf24', fontSize: 10, lineHeight: 1.4 }}>
            {agError}
          </div>
        )}
        {agTrace.length > 0 && (
          <div
            data-testid="ag-light-reasoning-trace"
            style={{
              marginTop: 8,
              padding: 8,
              borderRadius: 8,
              border: '1px solid rgba(96,165,250,0.16)',
              background: 'rgba(2,6,23,0.38)',
            }}
          >
            <div style={{ color: '#bfdbfe', fontSize: 10, fontWeight: 800, marginBottom: 6 }}>
              Agent reasoning trace
            </div>
            {agTrace.map(trace => (
              <div
                key={`trace-${trace.agent}`}
                data-testid={`ag-light-trace-${trace.agent}`}
                style={{
                  marginTop: 6,
                  padding: '7px 8px',
                  borderRadius: 7,
                  border: '1px solid rgba(148,163,184,0.12)',
                  background: 'rgba(15,23,42,0.58)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <span style={{ color: statusColor(trace.status), fontSize: 10, fontWeight: 900 }}>
                    {trace.label}
                  </span>
                  <span style={{ color: '#64748b', fontSize: 9, fontFamily: 'ui-monospace, monospace' }}>
                    {trace.agent}
                  </span>
                </div>
                <div style={{ marginTop: 4, color: '#e2e8f0', fontSize: 10, fontWeight: 700, lineHeight: 1.35 }}>
                  {trace.summary}
                </div>
                <div style={{ marginTop: 4, color: '#94a3b8', fontSize: 9, lineHeight: 1.45 }}>
                  <span style={{ color: '#5eead4', fontWeight: 800 }}>참조</span>
                  {' '}
                  {trace.refs.length ? trace.refs.join(' · ') : '근거 없음'}
                </div>
                <div style={{ marginTop: 3, color: '#94a3b8', fontSize: 9, lineHeight: 1.45 }}>
                  <span style={{ color: '#fbbf24', fontWeight: 800 }}>공식</span>
                  {' '}
                  {trace.formula || '공식/룰 텍스트 없음'}
                </div>
                <div style={{ marginTop: 3, color: '#cbd5e1', fontSize: 9, lineHeight: 1.45 }}>
                  <span style={{ color: '#93c5fd', fontWeight: 800 }}>판단</span>
                  {' '}
                  {trace.decision}
                </div>
              </div>
            ))}
          </div>
        )}
        {agReviews.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 5 }}>
            {agReviews.map(review => (
              <div
                key={review.agent}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '54px 1fr',
                  gap: 7,
                  padding: '6px 7px',
                  borderRadius: 7,
                  border: '1px solid rgba(148,163,184,0.12)',
                  background: 'rgba(2,6,23,0.36)',
                }}
              >
                <div style={{ color: statusColor(review.status), fontSize: 10, fontWeight: 800 }}>
                  {review.label}
                </div>
                <div>
                  <div style={{ color: '#dbeafe', fontSize: 10, fontWeight: 700, lineHeight: 1.35 }}>
                    {review.summary}
                  </div>
                  <div style={{ color: '#64748b', fontSize: 9, lineHeight: 1.35, marginTop: 2 }}>
                    {review.detail}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        {agBusLog.length > 0 && (
          <div style={{
            marginTop: 8,
            paddingTop: 7,
            borderTop: '1px solid rgba(148,163,184,0.12)',
          }}>
            <div style={{ color: '#94a3b8', fontSize: 9, marginBottom: 5 }}>
              최근 bus
            </div>
            {agBusLog.slice(-3).reverse().map((event, index) => (
              <div key={`${event.timestamp}-${index}`} style={{ color: '#64748b', fontSize: 9, lineHeight: 1.45 }}>
                <span style={{ color: '#93c5fd' }}>{event.from_agent}</span>
                {' -> '}
                <span>{event.to_agent}</span>
                {' · '}
                {event.message.slice(0, 58)}{event.message.length > 58 ? '...' : ''}
              </div>
            ))}
          </div>
        )}
      </div>

      <textarea
        value={message}
        onChange={e => setMessage(e.target.value)}
        placeholder="예: 북측 상부를 더 부드럽게 후퇴시켜줘. 용적률은 5% 이상 잃지 말고."
        rows={3}
        style={{
          width: '100%',
          boxSizing: 'border-box',
          resize: 'vertical',
          minHeight: 68,
          borderRadius: 7,
          border: '1px solid #243244',
          background: '#020617',
          color: '#cbd5e1',
          padding: 8,
          fontSize: 11,
          lineHeight: 1.45,
          outline: 'none',
        }}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 7 }}>
        {EXAMPLES.map(example => (
          <button
            key={example}
            type="button"
            onClick={() => setMessage(example)}
            style={{
              textAlign: 'left',
              border: 'none',
              borderRadius: 6,
              padding: '5px 7px',
              background: 'rgba(255,255,255,0.035)',
              color: '#94a3b8',
              fontSize: 10,
              cursor: 'pointer',
            }}
          >
            {example}
          </button>
        ))}
      </div>

      <button
        type="button"
        onClick={submit}
        disabled={loading || !message.trim()}
        style={{
          width: '100%',
          marginTop: 8,
          padding: '8px 0',
          borderRadius: 7,
          border: 'none',
          cursor: loading || !message.trim() ? 'default' : 'pointer',
          fontSize: 11,
          fontWeight: 700,
          background: loading || !message.trim()
            ? 'rgba(96,200,255,0.08)'
            : 'rgba(96,200,255,0.16)',
          color: loading || !message.trim() ? '#64748b' : '#7dd3fc',
        }}
      >
        {loading ? '후보 생성 중...' : '수정 후보 만들기'}
      </button>

      <button
        type="button"
        onClick={buildMaasVariants}
        disabled={previewLoading || !massGeojson || !sitePolygon}
        style={{
          width: '100%',
          marginTop: 7,
          padding: '8px 0',
          borderRadius: 7,
          border: '1px solid rgba(94,234,212,0.22)',
          cursor: previewLoading || !massGeojson || !sitePolygon ? 'default' : 'pointer',
          fontSize: 11,
          fontWeight: 700,
          background: previewLoading || !massGeojson || !sitePolygon
            ? 'rgba(255,255,255,0.03)'
            : 'rgba(20,184,166,0.12)',
          color: previewLoading || !massGeojson || !sitePolygon ? '#64748b' : '#5eead4',
        }}
      >
        {previewLoading ? 'MAAS 계산 중...' : 'MAAS 법규 후보 바로 만들기'}
      </button>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
        gap: 6,
        marginTop: 7,
      }}>
	        {[
	          ['층+', { type: 'push_pull_face', target: { kind: 'top' }, delta_floors: 1 }],
	          ['층-', { type: 'push_pull_face', target: { kind: 'top' }, delta_floors: -1 }],
	          ['폭+', { type: 'scale_footprint', factor: 1.08 }],
	          ['폭-', { type: 'scale_footprint', factor: 0.92 }],
	        ].map(([label, op]) => (
          <button
            key={label as string}
            type="button"
            onClick={() => applyOperation(op as object)}
            disabled={operationLoading || !massGeojson || !sitePolygon}
            title="법규 envelope로 즉시 보정하고 FAR/BCR을 다시 계산합니다."
            style={{
              borderRadius: 7,
              border: '1px solid rgba(148,163,184,0.18)',
              padding: '7px 0',
              background: operationLoading ? 'rgba(255,255,255,0.03)' : 'rgba(15,23,42,0.86)',
              color: operationLoading ? '#64748b' : '#cbd5e1',
              fontSize: 11,
              fontWeight: 700,
              cursor: operationLoading || !massGeojson || !sitePolygon ? 'default' : 'pointer',
            }}
          >
            {label as string}
          </button>
        ))}
	      </div>

	      <div style={{
	        display: 'grid',
	        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
	        gap: 6,
	        marginTop: 6,
	      }}>
	        {[0, 1, 2, 3].map(edgeIndex => (
	          <button
	            key={edgeIndex}
	            type="button"
	            onClick={() => applyOperation({
	              type: 'offset_edge',
	              target: { kind: 'side', edge_index: edgeIndex },
	              delta_m: 1.5,
	            })}
	            disabled={operationLoading || !massGeojson || !sitePolygon}
	            title={`${edgeIndex + 1}번 외곽 edge를 1.5m 밀고 법규 envelope로 보정합니다.`}
	            style={{
	              borderRadius: 7,
	              border: '1px solid rgba(94,234,212,0.18)',
	              padding: '7px 0',
	              background: operationLoading ? 'rgba(255,255,255,0.03)' : 'rgba(20,184,166,0.08)',
	              color: operationLoading ? '#64748b' : '#99f6e4',
	              fontSize: 10,
	              fontWeight: 700,
	              cursor: operationLoading || !massGeojson || !sitePolygon ? 'default' : 'pointer',
	            }}
	          >
	            E{edgeIndex + 1}+
	          </button>
	        ))}
	      </div>

      <div style={{
        marginTop: 10,
        padding: 9,
        borderRadius: 8,
        border: '1px solid rgba(167,139,250,0.18)',
        background: 'rgba(30,20,54,0.26)',
      }}>
        <div style={{ color: '#ddd6fe', fontSize: 11, fontWeight: 800, marginBottom: 3 }}>
          외관 이미지 생성
        </div>
        <div style={{ color: '#8b95a7', fontSize: 10, lineHeight: 1.45, marginBottom: 7 }}>
          법규 매스는 고정하고 재료, 창호 리듬, 분위기만 생성합니다.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 6 }}>
          <select
            value={aestheticProvider}
            onChange={e => setAestheticProvider(e.target.value as 'placeholder' | 'gpt-image' | 'nano-banana')}
            style={{
              width: '100%',
              borderRadius: 7,
              border: '1px solid #312e81',
              background: '#020617',
              color: '#c4b5fd',
              padding: '7px 8px',
              fontSize: 11,
              outline: 'none',
            }}
          >
            <option value="placeholder">Reference only</option>
            <option value="gpt-image">GPT Image</option>
            <option value="nano-banana">Nano Banana</option>
          </select>
          <textarea
            value={aestheticStyle}
            onChange={e => setAestheticStyle(e.target.value)}
            rows={2}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              resize: 'vertical',
              borderRadius: 7,
              border: '1px solid #312e81',
              background: '#020617',
              color: '#cbd5e1',
              padding: 8,
              fontSize: 10,
              lineHeight: 1.4,
              outline: 'none',
            }}
          />
          <button
            type="button"
            onClick={generateAesthetic}
            disabled={aestheticLoading || !jobId || !massGeojson}
            style={{
              width: '100%',
              padding: '8px 0',
              borderRadius: 7,
              border: '1px solid rgba(167,139,250,0.28)',
              cursor: aestheticLoading || !jobId || !massGeojson ? 'default' : 'pointer',
              fontSize: 11,
              fontWeight: 800,
              background: aestheticLoading || !jobId || !massGeojson ? 'rgba(255,255,255,0.03)' : 'rgba(124,58,237,0.18)',
              color: aestheticLoading || !jobId || !massGeojson ? '#64748b' : '#c4b5fd',
            }}
          >
            {aestheticLoading ? '외관 생성 중...' : '매스 기반 외관 생성'}
          </button>
        </div>
        {aesthetic && (
          <div style={{ marginTop: 8 }}>
            <div style={{ color: aesthetic.status === 'fail' ? '#fca5a5' : '#a7f3d0', fontSize: 10, marginBottom: 6 }}>
              {aesthetic.provider_result?.provider || aesthetic.job.provider} · {aesthetic.status}
              {aesthetic.provider_result?.status ? ` / ${aesthetic.provider_result.status}` : ''}
              {((aesthetic.provider_result?.metadata?.texture_bake as { status?: string } | undefined)?.status === 'skipped'
                || aesthetic.provider_result?.issues?.some(issue => issue.code === 'projection_panels_not_texture_ready')) ? ' / mesh skipped' : ''}
            </div>
            {aesthetic.reference?.url && (
              <a href={aesthetic.reference.url} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                <img
                  src={aesthetic.reference.url}
                  alt="Locked MAAS reference render"
                  style={{ width: '100%', borderRadius: 7, border: '1px solid rgba(148,163,184,0.16)', background: '#f8fafc' }}
                />
              </a>
            )}
            {aesthetic.provider_result?.assets?.[0]?.url && (
              <a href={aesthetic.provider_result.assets[0].url} target="_blank" rel="noreferrer" style={{ display: 'block', marginTop: 7 }}>
                <img
                  src={aesthetic.provider_result.assets[0].url}
                  alt="Generated facade concept"
                  style={{ width: '100%', borderRadius: 7, border: '1px solid rgba(148,163,184,0.16)' }}
                />
              </a>
            )}
            {aesthetic.provider_result?.issues?.length ? (
              <div style={{ color: '#fbbf24', fontSize: 10, lineHeight: 1.45, marginTop: 6 }}>
                {requiredValue(requiredValue(aesthetic.provider_result.issues[0]).message) || requiredValue(requiredValue(aesthetic.provider_result.issues[0]).code)}
              </div>
            ) : null}
            <div style={{ color: '#64748b', fontSize: 9, lineHeight: 1.45, marginTop: 6 }}>
              legal_status_effect: {aesthetic.job.evidence_policy?.legal_status_effect || 'none'}
            </div>
          </div>
        )}
      </div>

      {error && (
        <div style={{ marginTop: 8, color: '#fca5a5', fontSize: 11 }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 10 }}>
          <div style={{ color: '#94a3b8', fontSize: 10, marginBottom: 6 }}>
            해석: {result.interpreted_intents.join(', ') || 'none'}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            {result.candidates.map(candidate => (
              <div
                key={candidate.id}
                style={{
                  border: '1px solid rgba(148,163,184,0.14)',
                  borderRadius: 7,
                  padding: 8,
                  background: 'rgba(2,6,23,0.42)',
                }}
              >
                <div style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 700 }}>
                  {candidate.title}
                </div>
                <div style={{ color: '#64748b', fontSize: 10, marginTop: 2 }}>
                  {candidate.intent} · {candidate.constraints.join(' / ')}
                </div>
                <ul style={{
                  margin: '6px 0 0',
                  paddingLeft: 16,
                  color: '#94a3b8',
                  fontSize: 10,
                  lineHeight: 1.45,
                }}>
                  {candidate.expected_effects.map(effect => (
                    <li key={effect}>{effect}</li>
                  ))}
                </ul>
                {candidate.risks.length > 0 && (
                  <div style={{ color: '#fbbf24', fontSize: 10, marginTop: 6 }}>
                    위험: {candidate.risks.join(', ')}
                  </div>
                )}
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={buildPreview}
            disabled={previewLoading || !sitePolygon || !siteArea}
            style={{
              width: '100%',
              marginTop: 8,
              padding: '8px 0',
              borderRadius: 7,
              border: '1px solid rgba(125,211,252,0.2)',
              cursor: previewLoading || !sitePolygon || !siteArea ? 'default' : 'pointer',
              fontSize: 11,
              fontWeight: 700,
              background: previewLoading || !sitePolygon || !siteArea
                ? 'rgba(255,255,255,0.03)'
                : 'rgba(20,184,166,0.12)',
              color: previewLoading || !sitePolygon || !siteArea ? '#64748b' : '#5eead4',
            }}
          >
            {previewLoading ? '미리보기 계산 중...' : '실제 매스 후보 계산'}
          </button>
          {result.notes.length > 0 && (
            <div style={{
              marginTop: 8,
              color: '#64748b',
              fontSize: 10,
              lineHeight: 1.45,
            }}>
              {result.notes.map(note => <div key={note}>· {note}</div>)}
            </div>
          )}
        </div>
      )}

      {preview && (
        <div style={{ marginTop: 10 }}>
          <div style={{ color: '#94a3b8', fontSize: 10, marginBottom: 6 }}>
            미리보기: {preview.algorithm} · {preview.building_type}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {preview.candidates.map(candidate => (
              <button
                key={candidate.id}
                type="button"
                onClick={() => selectPreview(candidate)}
                disabled={!candidate.mass_geojson}
                style={{
                  textAlign: 'left',
                  borderRadius: 7,
                  border: activePreviewId === candidate.id
                    ? '1px solid rgba(94,234,212,0.65)'
                    : '1px solid rgba(148,163,184,0.14)',
                  padding: 8,
                  background: activePreviewId === candidate.id
                    ? 'rgba(20,184,166,0.12)'
                    : 'rgba(2,6,23,0.42)',
                  cursor: candidate.mass_geojson ? 'pointer' : 'not-allowed',
                }}
              >
                <div style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 700 }}>
                  {candidate.title}
                </div>
                <div style={{ color: candidate.feasible ? '#5eead4' : '#fbbf24', fontSize: 10, marginTop: 3 }}>
                  {candidate.feasible ? 'PASS' : 'CHECK'} · penalty {candidate.penalty.toFixed(3)}
                </div>
                <div style={{ color: '#94a3b8', fontSize: 10, marginTop: 5, lineHeight: 1.45 }}>
                  FAR {formatMetric(candidate.metrics.far)} · BCR {formatMetric(candidate.metrics.bcr)} ·
                  높이 {formatMetric(candidate.metrics.height)}m
                </div>
	                {candidate.notes.length > 0 && (
	                  <div style={{ color: '#64748b', fontSize: 10, marginTop: 5, lineHeight: 1.45 }}>
	                    {candidate.notes[0]}
	                  </div>
	                )}
	                {candidate.notes.some(note => note.includes('agent')) && (
	                  <div style={{ color: '#60a5fa', fontSize: 10, marginTop: 5, lineHeight: 1.45 }}>
	                    {candidate.notes.filter(note => note.includes('agent')).slice(0, 2).join(' · ')}
	                  </div>
	                )}
	              </button>
	            ))}
          </div>
	          {preview.notes.length > 0 && (
            <div style={{ marginTop: 8, color: '#64748b', fontSize: 10, lineHeight: 1.45 }}>
              {preview.notes.map(note => <div key={note}>· {note}</div>)}
            </div>
	          )}
	          <A2UISurfaceRenderer messages={preview.a2ui_messages} />
	        </div>
	      )}
    </div>
  );
};

export default InteractiveDesignPanel;
