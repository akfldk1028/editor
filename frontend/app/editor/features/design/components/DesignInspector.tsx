import React from 'react';
import type { DesignData, GeoJSONFeature } from '../lib/types';

interface Props {
  design: DesignData | null;
  objectiveNames?: string[];
  feature?: GeoJSONFeature | null;
}

const OBJECTIVE_META: Record<string, { label: string; unit: string; color: string }> = {
  floor_area:      { label: '연면적',   unit: 'm\u00B2', color: '#60c8ff' },
  daylight_score:  { label: '일조점수', unit: '점',      color: '#fbbf24' },
  landscaping_pct: { label: '외부공간', unit: '%',       color: '#34d399' },
  setback:         { label: '이격거리', unit: 'm',       color: '#a78bfa' },
};

const STRATEGY_LABELS: Record<string, string> = {
  none: '없음',
  ground_surface: '외부 지상주차',
  piloti_ground: '필로티 주차',
  basement: '지하주차',
  semi_basement: '반지하 주차',
  mechanical: '기계식 주차',
  mixed: '혼합 주차',
};

function parkingSummary(feature?: GeoJSONFeature | null) {
  const props = feature?.properties as any;
  const precheck = props?.parking_precheck;
  const strategy = precheck?.selected_strategy || precheck?.strategy || props?.parking_strategy;
  const requiredCount = precheck?.required_count || props?.parking_required_count;
  const layout = precheck?.layout_candidate;
  const massStageParking = layout?.mass_stage_parking;
  const required = typeof requiredCount?.required_spaces === 'number' ? requiredCount.required_spaces : null;
  const provided = typeof layout?.provided_spaces === 'number' ? layout.provided_spaces : null;
  const unmet = typeof layout?.unmet_spaces === 'number' ? layout.unmet_spaces : null;
  const status = layout?.status || precheck?.status || requiredCount?.status || 'needs_review';
  const displayStatus = status === 'pass'
    ? status
    : massStageParking?.status === 'pass'
      ? 'mass_stage_pass'
      : status;
  const metricValue = typeof requiredCount?.metric_value === 'number' ? requiredCount.metric_value : null;
  const rawSpaces = typeof requiredCount?.raw_spaces === 'number' ? requiredCount.raw_spaces : null;
  const spacesPer = metricValue != null && rawSpaces != null && rawSpaces > 0 ? metricValue / rawSpaces : null;
  const metricLabel = requiredCount?.metric === 'facility_area_m2' ? '시설면적' : requiredCount?.metric || '산정면적';
  const ruleLabel = requiredCount?.selected_rule_id || requiredCount?.base_rule_id || '';
  const unitSchedule = requiredCount?.unit_schedule;
  const layoutFormula = layout?.layout_formula;
  const adjacency = layout?.adjacency;
  const aisleStatus = layout?.drive_aisle_clearance?.status;
  const turningStatus = layout?.turning_clearance?.status;
  const authorityReview = layout?.authority_review_check || layout?.turning_clearance?.authority_review_check;
  const connector = layout?.grid_solver;
  const evidenceNeeded = Array.isArray(authorityReview?.external_evidence_needed)
    ? authorityReview.external_evidence_needed.length
    : 0;
  const blockers = Array.isArray(authorityReview?.blockers)
    ? authorityReview.blockers.length
    : 0;
  return {
    strategy,
    strategyLabel: strategy ? (STRATEGY_LABELS[strategy] || String(strategy)) : '주차 전략 산정 필요',
    required,
    provided,
    unmet,
    status,
    displayStatus,
    reason: requiredCount?.reason || precheck?.reason || '',
    formula: unitSchedule?.source
      ? `공동주택 추정 ${unitSchedule.units?.length ?? '-'}세대 / 면적비 ${Number(unitSchedule.area_ratio_raw_spaces ?? 0).toFixed(2)}대 / 세대최소 ${Number(unitSchedule.household_min_raw_spaces ?? 0).toFixed(2)}대 → ${required ?? '-'}대`
      : metricValue != null && spacesPer != null && rawSpaces != null && required != null
      ? `${metricLabel} ${metricValue.toFixed(2)}㎡ ÷ ${spacesPer.toFixed(0)}㎡/대 = ${rawSpaces.toFixed(2)} → ${required}대`
      : '',
    ruleLabel,
    layoutMode: layoutFormula?.mode || layout?.placement_mode || '',
    moduleFormula: layoutFormula?.module
      ? `단면 ${layoutFormula.module.single_loaded_90_depth_m}m / 양면 ${layoutFormula.module.double_loaded_90_depth_m}m`
      : '',
    adjacencyLabel: adjacency?.contiguous_ok
      ? `연접 OK (${adjacency.touching_pairs ?? 0}쌍 접촉)`
      : adjacency
        ? `연접 검토 (${adjacency.max_gap_m ?? '-'}m gap)`
        : '',
    aisleLabel: aisleStatus === 'pass'
      ? `차로 OK (${layout?.drive_aisle_clearance?.provided_width_m ?? '-'}m)`
      : aisleStatus
        ? '차로 검토'
        : '',
    turningLabel: turningStatus === 'v1_pass'
      ? '회전 예비 OK'
      : turningStatus
        ? '회전 검토'
        : '',
    authorityReviewLabel: authorityReview?.status
      ? blockers > 0
        ? `보완필요 ${blockers}건`
        : evidenceNeeded > 0
          ? `증빙필요 ${evidenceNeeded}건`
          : '예비검토 OK'
      : '',
    massStageLabel: massStageParking?.status === 'pass'
      ? '매스단계 OK'
      : massStageParking?.reason || '',
    connectorLabel: connector?.entrance_verified
      ? `진입 OK (${connector.entrance_connector_width_m ?? '-'}m x ${connector.entrance_connector_length_m ?? '-'}m)`
      : connector?.entrance_connection_type
        ? '진입 검토'
        : '',
  };
}

function parkingStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pass: '배치 가능',
    mass_stage_pass: '매스단계 가능',
    fail: '배치 부족',
    has_layout_candidate: '배치 후보',
    needs_aisle_review: '차로 검토 필요',
    needs_swept_path_review: '회전/동선 검토 필요',
    needs_parking_requirements: '법정대수 산정 필요',
    computed_estimate: '추정 산정',
    needs_graph_requirement: 'Graph 규정 필요',
    graph_unavailable: 'Graph 연결 필요',
    needs_metric: '면적/세대수 필요',
    needs_review: '검토 필요',
  };
  return labels[status] || status;
}

const DesignInspector: React.FC<Props> = React.memo(({ design, objectiveNames, feature }) => {
  if (!design) {
    return (
      <div style={{
        background: 'linear-gradient(180deg, #0c1120 0%, #0e1525 100%)',
        borderRadius: 12,
        padding: 28,
        color: '#2d3548',
        fontSize: 12,
        textAlign: 'center' as const,
        border: '1px dashed rgba(255,255,255,0.06)',
      }}>
        <div style={{ fontSize: 24, marginBottom: 8, opacity: 0.3 }}>&#x25CE;</div>
        파레토 포인트를 클릭하세요
      </div>
    );
  }

  // Build objective cards from design data
  const objNames = objectiveNames || [];
  const objectives = design.objectives || [];
  const parking = parkingSummary(feature);

  return (
    <div style={{
      background: 'linear-gradient(180deg, #0c1120 0%, #0e1525 100%)',
      borderRadius: 12,
      padding: 16,
      border: '1px solid rgba(255,255,255,0.06)',
      boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 14,
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ color: '#5a6577', fontSize: 10, fontWeight: 700, letterSpacing: '0.1em' }}>
            DESIGN
          </span>
          <span style={{ color: '#e2e8f0', fontSize: 22, fontWeight: 800, fontFamily: 'ui-monospace, monospace' }}>
            #{design.id}
          </span>
        </div>
        <span style={{
          padding: '3px 10px', borderRadius: 8,
          fontSize: 10, fontWeight: 700, letterSpacing: '0.05em',
          background: design.feasible
            ? 'rgba(52,211,153,0.1)' : 'rgba(239,68,68,0.08)',
          color: design.feasible ? '#34d399' : '#f87171',
          border: `1px solid ${design.feasible ? 'rgba(52,211,153,0.2)' : 'rgba(239,68,68,0.15)'}`,
        }}>
          {design.feasible ? 'FEASIBLE' : 'INFEASIBLE'}
        </span>
      </div>

      {/* Objective metric cards — dynamic based on building type */}
      {objectives.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
          {objectives.slice(0, 2).map((val, i) => {
            const name = objNames[i] || (i === 0 ? 'floor_area' : 'daylight_score');
            const meta = OBJECTIVE_META[name] || { label: name, unit: '', color: '#60c8ff' };
            return (
              <div key={i} style={{
                flex: 1,
                padding: '14px 12px',
                background: `linear-gradient(135deg, ${meta.color}08, ${meta.color}04)`,
                borderRadius: 10,
                textAlign: 'center' as const,
                border: `1px solid ${meta.color}18`,
                position: 'relative' as const,
                overflow: 'hidden',
              }}>
                {/* Subtle glow at top */}
                <div style={{
                  position: 'absolute', top: 0, left: '20%', right: '20%', height: 1,
                  background: `linear-gradient(90deg, transparent, ${meta.color}40, transparent)`,
                }} />
                <div style={{ color: '#5a6577', fontSize: 9, fontWeight: 600, letterSpacing: '0.08em', marginBottom: 6 }}>
                  {meta.label}
                </div>
                <div style={{
                  color: meta.color, fontSize: 22, fontWeight: 800,
                  fontFamily: 'ui-monospace, monospace',
                  textShadow: `0 0 20px ${meta.color}30`,
                }}>
                  {val >= 1000 ? val.toLocaleString('en-US', { maximumFractionDigits: 0 }) : val.toFixed(1)}
                </div>
                <div style={{ color: '#3d4556', fontSize: 9, marginTop: 2 }}>{meta.unit}</div>
              </div>
            );
          })}
        </div>
      )}

      {/* Parking requirements and strategy */}
      <div style={{
        marginBottom: 14,
        padding: 12,
        borderRadius: 10,
        background: 'rgba(15,23,42,0.72)',
        border: '1px solid rgba(250,204,21,0.16)',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 9,
        }}>
          <span style={{ color: '#facc15', fontSize: 10, fontWeight: 800, letterSpacing: '0.08em' }}>
            PARKING
          </span>
          <span style={{
            padding: '2px 7px',
            borderRadius: 6,
            background: parking.strategy === 'piloti_ground' ? 'rgba(250,204,21,0.14)' : 'rgba(96,200,255,0.10)',
            color: parking.strategy === 'piloti_ground' ? '#facc15' : '#60c8ff',
            fontSize: 10,
            fontWeight: 700,
          }}>
            {parking.strategyLabel}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div>
            <div style={{ color: '#5a6577', fontSize: 9, marginBottom: 3 }}>법정 주차대수</div>
            <div style={{ color: parking.required == null ? '#f59e0b' : '#e2e8f0', fontSize: 16, fontWeight: 800, fontFamily: 'ui-monospace, monospace' }}>
              {parking.required == null ? '산정필요' : `${parking.required}대`}
            </div>
          </div>
          <div>
            <div style={{ color: '#5a6577', fontSize: 9, marginBottom: 3 }}>계획 제공대수</div>
            <div style={{ color: parking.provided == null ? '#94a3b8' : '#34d399', fontSize: 16, fontWeight: 800, fontFamily: 'ui-monospace, monospace' }}>
              {parking.provided == null ? '-' : `${parking.provided}대`}
            </div>
          </div>
        </div>
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: 10 }}>
          <span style={{ color: '#64748b' }}>상태</span>
          <span style={{ color: parking.status === 'fail' ? '#f87171' : parking.required == null ? '#f59e0b' : '#34d399', textAlign: 'right' as const }}>
            {parkingStatusLabel(String(parking.displayStatus))}
            {parking.unmet && parking.unmet > 0 ? ` / 부족 ${parking.unmet}대` : ''}
          </span>
        </div>
        {parking.formula && (
          <div style={{
            marginTop: 8,
            paddingTop: 7,
            borderTop: '1px solid rgba(148,163,184,0.12)',
            color: '#cbd5e1',
            fontSize: 10,
            lineHeight: 1.35,
            fontFamily: 'ui-monospace, monospace',
          }}>
            {parking.formula}
            {parking.ruleLabel ? (
              <div style={{ marginTop: 3, color: '#64748b', fontFamily: 'inherit' }}>
                rule: {parking.ruleLabel}
              </div>
            ) : null}
          </div>
        )}
        {(parking.layoutMode || parking.moduleFormula || parking.adjacencyLabel || parking.aisleLabel || parking.connectorLabel || parking.turningLabel || parking.authorityReviewLabel) && (
          <div style={{
            marginTop: 7,
            color: '#cbd5e1',
            fontSize: 10,
            lineHeight: 1.38,
          }}>
            {parking.layoutMode ? (
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: '#64748b' }}>배치공식</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', color: '#f9a8d4', textAlign: 'right' as const }}>
                  {parking.layoutMode}
                </span>
              </div>
            ) : null}
            {parking.moduleFormula ? (
              <div style={{ marginTop: 3, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: '#64748b' }}>모듈</span>
                <span style={{ fontFamily: 'ui-monospace, monospace', textAlign: 'right' as const }}>
                  {parking.moduleFormula}
                </span>
              </div>
            ) : null}
            {parking.adjacencyLabel ? (
              <div style={{ marginTop: 3, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: '#64748b' }}>연접</span>
                <span style={{ color: parking.adjacencyLabel.includes('OK') ? '#34d399' : '#f59e0b', textAlign: 'right' as const }}>
                  {parking.adjacencyLabel}
                </span>
              </div>
            ) : null}
            {parking.aisleLabel ? (
              <div style={{ marginTop: 3, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: '#64748b' }}>차로</span>
                <span style={{ color: parking.aisleLabel.includes('OK') ? '#34d399' : '#f59e0b', textAlign: 'right' as const }}>
                  {parking.aisleLabel}
                </span>
              </div>
            ) : null}
            {parking.connectorLabel ? (
              <div style={{ marginTop: 3, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: '#64748b' }}>진입</span>
                <span style={{ color: parking.connectorLabel.includes('OK') ? '#34d399' : '#f59e0b', textAlign: 'right' as const }}>
                  {parking.connectorLabel}
                </span>
              </div>
            ) : null}
            {parking.turningLabel ? (
              <div style={{ marginTop: 3, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: '#64748b' }}>회전</span>
                <span style={{ color: parking.turningLabel.includes('OK') ? '#34d399' : '#f59e0b', textAlign: 'right' as const }}>
                  {parking.turningLabel}
                </span>
              </div>
            ) : null}
            {parking.authorityReviewLabel ? (
              <div style={{ marginTop: 3, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: '#64748b' }}>관청검토</span>
                <span style={{ color: parking.authorityReviewLabel.includes('OK') ? '#34d399' : '#f59e0b', textAlign: 'right' as const }}>
                  {parking.authorityReviewLabel}
                </span>
              </div>
            ) : null}
            {parking.massStageLabel ? (
              <div style={{ marginTop: 3, display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                <span style={{ color: '#64748b' }}>매스단계</span>
                <span style={{ color: parking.massStageLabel.includes('OK') ? '#34d399' : '#f59e0b', textAlign: 'right' as const }}>
                  {parking.massStageLabel}
                </span>
              </div>
            ) : null}
          </div>
        )}
        {parking.reason && (
          <div style={{ marginTop: 6, color: '#64748b', fontSize: 9, lineHeight: 1.35 }}>
            {parking.reason}
          </div>
        )}
      </div>

      {/* Performance bars */}
      {objectives.length >= 2 && (
        <div style={{ marginBottom: 14 }}>
          {objectives.slice(0, 2).map((val, i) => {
            const name = objNames[i] || (i === 0 ? 'floor_area' : 'daylight_score');
            const meta = OBJECTIVE_META[name] || { label: name, unit: '', color: '#60c8ff' };
            // Normalize to 0-100 range for display
            const displayPct = name === 'floor_area'
              ? Math.min(100, val / 300)         // 30000m²→100%
              : name === 'daylight_score'
                ? val                            // already 0-100
                : Math.min(100, val);
            return (
              <div key={i} style={{ marginBottom: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ color: '#5a6577', fontSize: 10 }}>{meta.label}</span>
                  <span style={{
                    color: meta.color, fontSize: 12, fontWeight: 700,
                    fontFamily: 'ui-monospace, monospace',
                  }}>
                    {val >= 1000 ? (val / 1000).toFixed(1) + 'k' : val.toFixed(1)}
                  </span>
                </div>
                <div style={{
                  height: 3, background: 'rgba(255,255,255,0.03)', borderRadius: 2,
                  overflow: 'hidden',
                }}>
                  <div style={{
                    height: '100%', borderRadius: 2,
                    width: `${Math.min(100, displayPct)}%`,
                    background: `linear-gradient(90deg, ${meta.color}60, ${meta.color})`,
                    boxShadow: `0 0 8px ${meta.color}40`,
                    transition: 'width 0.4s ease',
                  }} />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Gene parameters — compact scrollable grid */}
      <details style={{ marginBottom: 0 }}>
        <summary style={{
          color: '#3d4556', fontSize: 10, fontWeight: 600, letterSpacing: '0.08em',
          cursor: 'pointer', marginBottom: 6, userSelect: 'none' as const,
          listStyle: 'none',
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          <span style={{ fontSize: 8, transition: 'transform 0.2s' }}>&#x25B6;</span>
          PARAMETERS ({design.inputs.length} genes)
        </summary>
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2,
          maxHeight: 160, overflowY: 'auto' as const,
        }}>
          {design.inputs.map((inp, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between',
              padding: '3px 8px',
              background: 'rgba(255,255,255,0.02)',
              borderRadius: 4, fontSize: 10,
            }}>
              <span style={{ color: '#3d4556' }}>G{i}</span>
              <span style={{ color: '#8b95a8', fontFamily: 'ui-monospace, monospace' }}>
                {typeof inp[0] === 'number' ? inp[0].toFixed(2) : inp[0]}
              </span>
            </div>
          ))}
        </div>
      </details>

      {/* Meta info */}
      <div style={{
        marginTop: 10, paddingTop: 10,
        borderTop: '1px solid rgba(255,255,255,0.04)',
        display: 'flex', gap: 12, fontSize: 10, color: '#3d4556',
        fontFamily: 'ui-monospace, monospace',
      }}>
        <span>Gen {design.generation}</span>
        <span>Rank {design.rank}</span>
        <span>Pen {design.penalty.toFixed(2)}</span>
      </div>
    </div>
  );
});

DesignInspector.displayName = 'DesignInspector';
export default DesignInspector;
