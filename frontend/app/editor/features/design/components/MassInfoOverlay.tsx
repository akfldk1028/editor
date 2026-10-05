import React from 'react';
import type { GeoJSONFeature } from '../lib/types';
import { SHAPE_COLORS, SHAPE_LABELS } from '../lib/cesium/mass-styles';

const PARKING_STRATEGY_LABELS: Record<string, string> = {
  none: '없음',
  ground_surface: '외부 지상',
  piloti_ground: '필로티',
  basement: '지하',
  semi_basement: '반지하',
  mechanical: '기계식',
  mixed: '혼합',
};

function parkingInfo(feature: GeoJSONFeature) {
  const p = feature.properties as any;
  const precheck = p.parking_precheck;
  const strategy = precheck?.selected_strategy || precheck?.strategy || p.parking_strategy;
  const requiredCount = precheck?.required_count || p.parking_required_count;
  const layout = precheck?.layout_candidate;
  const authorityReview = layout?.authority_review_check || layout?.turning_clearance?.authority_review_check;
  const evidenceNeeded = Array.isArray(authorityReview?.external_evidence_needed)
    ? authorityReview.external_evidence_needed.length
    : 0;
  const blockers = Array.isArray(authorityReview?.blockers)
    ? authorityReview.blockers.length
    : 0;
  return {
    strategy,
    strategyLabel: strategy ? (PARKING_STRATEGY_LABELS[strategy] || String(strategy)) : '검토',
    required: typeof requiredCount?.required_spaces === 'number' ? requiredCount.required_spaces : null,
    provided: typeof layout?.provided_spaces === 'number' ? layout.provided_spaces : null,
    status: layout?.status || precheck?.status || requiredCount?.status || 'needs_review',
    authorityLabel: authorityReview?.status
      ? blockers > 0
        ? `보완필요 ${blockers}`
        : evidenceNeeded > 0
          ? `증빙필요 ${evidenceNeeded}`
          : '예비OK'
      : '',
  };
}

export function MassInfoOverlay({ massFeatures }: { massFeatures?: GeoJSONFeature[] }) {
  return <>
      {massFeatures && massFeatures.length > 0 && (
        <div style={{
          position: 'absolute', top: 12, right: 12,
          padding: '10px 14px',
          background: 'rgba(15,23,42,0.88)', borderRadius: 8,
          border: '1px solid rgba(96,165,250,0.2)',
          backdropFilter: 'blur(8px)',
          fontSize: 12, color: '#e2e8f0',
          zIndex: 10, minWidth: 140,
        }}>
          <div style={{ color: '#60a5fa', fontWeight: 600, marginBottom: 6, fontSize: 11, letterSpacing: '0.05em' }}>
            BUILDING MASS
          </div>
          {massFeatures.map((f, i) => {
            const p = f.properties;
            const algoKey = p.mass_shape || p.algorithm || 'rectangle';
            const algoColor = SHAPE_COLORS[algoKey] || '#60a5fa';
            const parking = parkingInfo(f);
            return (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <span style={{ color: '#94a3b8' }}>형태</span>
                  <span style={{ fontFamily: 'monospace', color: algoColor, fontWeight: 600 }}>
            {SHAPE_LABELS[algoKey] || algoKey}
                  </span>
                </div>
                {(() => {
                  const groups = Array.isArray(p.maas_model?.floor_groups)
                    ? p.maas_model.floor_groups
                    : Array.isArray(p.floor_groups) ? p.floor_groups : [];
                  if (!groups.length) return null;
                  return (
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                      <span style={{ color: '#94a3b8' }}>층그룹</span>
                      <span style={{ fontFamily: 'monospace', color: '#a7f3d0' }}>
                        {groups.length}G / +{groups[0]?.far_contribution?.toFixed?.(1) ?? '-'}%
                      </span>
                    </div>
                  );
                })()}
                {(() => {
                  const groups = Array.isArray(p.maas_model?.floor_groups)
                    ? p.maas_model.floor_groups
                    : Array.isArray(p.floor_groups) ? p.floor_groups : [];
                  const packed = groups.filter((g) => g.program_packing?.status === 'ok');
                  const firstPacked = packed[0]?.program_packing?.preview_summary;
                  if (!groups.length) return null;
                  return (
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                      <span style={{ color: '#94a3b8' }}>패킹</span>
                      <span style={{ fontFamily: 'monospace', color: packed.length === groups.length ? '#22c55e' : '#f59e0b' }}>
                        {packed.length}/{groups.length}G
                        {firstPacked ? ` / ${firstPacked.room_count}실` : ''}
                      </span>
                    </div>
                  );
                })()}
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>높이</span>
                  <span style={{ fontFamily: 'monospace' }}>{p.height?.toFixed(1)}m</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>층수</span>
                  <span style={{ fontFamily: 'monospace' }}>
                    {p.num_floors}F
                    {p.step_floor ? ` (${p.step_floor}F+${p.num_floors - p.step_floor}F)` : ''}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span style={{ color: '#94a3b8' }}>건폐율</span>
                  <span style={{ fontFamily: 'monospace', color: '#22c55e' }}>{p.bcr?.toFixed(1)}%</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <span style={{ color: '#94a3b8' }}>용적률</span>
                  <span style={{ fontFamily: 'monospace', color: '#f59e0b' }}>{p.far?.toFixed(1)}%</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <span style={{ color: '#94a3b8' }}>연면적</span>
                  <span style={{ fontFamily: 'monospace', color: '#60c8ff' }}>
                    {p.floor_area >= 1000 ? (p.floor_area / 1000).toFixed(1) + 'k' : p.floor_area?.toFixed(0)}m²
                  </span>
                </div>
                <div style={{
                  marginTop: 4,
                  paddingTop: 5,
                  borderTop: '1px solid rgba(148,163,184,0.16)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: 12,
                }}>
                  <span style={{ color: '#94a3b8' }}>주차</span>
                  <span style={{
                    fontFamily: 'monospace',
                    color: parking.strategy === 'piloti_ground' ? '#facc15' : '#a7f3d0',
                    fontWeight: 700,
                  }}>
                    {parking.strategyLabel}
                  </span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <span style={{ color: '#94a3b8' }}>법정/계획</span>
                  <span style={{ fontFamily: 'monospace', color: parking.required == null ? '#f59e0b' : '#e2e8f0' }}>
                    {parking.required == null ? '산정필요' : `${parking.required}`}
                    {' / '}
                    {parking.provided == null ? '-' : parking.provided}
                  </span>
                </div>
                {parking.authorityLabel ? (
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <span style={{ color: '#94a3b8' }}>관청검토</span>
                    <span style={{
                      fontFamily: 'monospace',
                      color: parking.authorityLabel.includes('OK') ? '#22c55e' : '#f59e0b',
                    }}>
                      {parking.authorityLabel}
                    </span>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

  </>;
}
