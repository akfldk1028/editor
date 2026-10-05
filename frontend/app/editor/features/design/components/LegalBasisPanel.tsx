import React from 'react';
import type { DatumBoundarySegment, DatumPointSample, RoadFrontageDict, SetbackGeometriesMap } from '../lib/types';

interface Props {
  setbackGeometries?: SetbackGeometriesMap | null;
}

const cardStyle: React.CSSProperties = {
  background: '#111827',
  borderRadius: 10,
  padding: 14,
  marginBottom: 10,
  border: '1px solid #1e293b',
};

const labelStyle: React.CSSProperties = {
  color: '#94a3b8',
  fontSize: 11,
};

const valueStyle: React.CSSProperties = {
  color: '#e2e8f0',
  fontSize: 11,
  fontWeight: 600,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  fontFeatureSettings: '"tnum"',
};

function numberOrNull(value: unknown): number | null {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatM(value: unknown, digits = 2): string {
  const n = numberOrNull(value);
  return n == null ? '-' : `${n.toFixed(digits)}m`;
}

function segmentElev(segment: DatumBoundarySegment): number | null {
  return numberOrNull(segment.midpoint_elev_m ?? segment.elevation_m);
}

function sampleElev(sample: DatumPointSample): number | null {
  return numberOrNull(sample.elev_m ?? sample.elevation_m);
}

function rangeText(values: Array<number | null>): string {
  const nums = values.filter((v): v is number => v != null);
  if (!nums.length) return '-';
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  return `${min.toFixed(2)}-${max.toFixed(2)}m`;
}

function roadWidth(road: RoadFrontageDict): number | null {
  return numberOrNull(road.roadWidthM ?? road.road_width_m);
}

const Row: React.FC<{ label: string; value: string; tone?: string }> = ({ label, value, tone }) => (
  <div style={{
    display: 'flex',
    justifyContent: 'space-between',
    gap: 12,
    padding: '5px 0',
    borderTop: '1px solid #1e293b',
  }}>
    <span style={labelStyle}>{label}</span>
    <span style={{ ...valueStyle, color: tone || valueStyle.color }}>{value}</span>
  </div>
);

const LegalBasisPanel: React.FC<Props> = React.memo(({ setbackGeometries }) => {
  const datum = setbackGeometries?.datum_result;
  if (!datum) return null;

  const roads = setbackGeometries?.road_frontages ?? [];
  const roadWidths = roads
    .map(roadWidth)
    .filter((v): v is number => v != null && v > 0)
    .sort((a, b) => b - a);
  const uniqueRoadWidths = Array.from(new Set(roadWidths.map((v) => v.toFixed(1))));
  const roadSamples = datum.road_samples ?? [];
  const parcelSegments = datum.parcel_segments ?? [];
  const neighborSegments = datum.neighbor_segments ?? [];
  const neighborCount = setbackGeometries?.neighbor_parcels?.length ?? 0;
  const sunlight = setbackGeometries?.sunlight_envelope;
  const daylight = setbackGeometries?.daylight_diagonal_envelope;
  const sourceOk = datum.elevation_source === 'ngii_local_dem';

  return (
    <div style={cardStyle}>
      <h3 style={{
        color: '#64748b',
        fontSize: 10,
        fontWeight: 700,
        margin: 0,
        marginBottom: 10,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
      }}>
        법규 산정 근거
      </h3>

      <Row
        label="수치지형도 소스"
        value={datum.elevation_source || '-'}
        tone={sourceOk ? '#22c55e' : '#f59e0b'}
      />
      <Row label="대지 샘플" value={`${parcelSegments.length}개 / ${rangeText(parcelSegments.map(segmentElev))}`} />
      <Row label="도로 샘플" value={`${roadSamples.length}개 / ${rangeText(roadSamples.map(sampleElev))}`} />
      <Row label="인접대지 샘플" value={`${neighborSegments.length}개 / ${rangeText(neighborSegments.map(segmentElev))}`} />
      <Row label="검출 도로폭" value={uniqueRoadWidths.length ? uniqueRoadWidths.map((v) => `${v}m`).join(', ') : '-'} />
      <Row label="전면도로 후보" value={`${roads.length}개`} />
      <Row label="인접대지 후보" value={`${neighborCount}개`} />
      <Row
        label="정북일조"
        value={sunlight ? `적용 / 기준면 ${formatM(sunlight.datum_elevation_m)}` : '미적용'}
        tone={sunlight ? valueStyle.color : '#f59e0b'}
      />
      <Row
        label="채광사선 참고면"
        value={daylight ? `${formatM(datum.parcel_datum_m ?? datum.elevation_m)} / 매스 창면 검토 필요` : '미표시'}
        tone={daylight ? '#a855f7' : '#64748b'}
      />
      <Row
        label="화면 기본 레이어"
        value={[
          sunlight ? '정북면' : null,
          daylight ? '채광옵션' : null,
          roads.length ? '도로' : null,
          neighborCount ? '인접' : null,
        ].filter(Boolean).join(' / ') || '-'}
      />

      <p style={{
        margin: '9px 0 0',
        color: '#64748b',
        fontSize: 10,
        lineHeight: 1.5,
      }}>
        VWorld 기본 화면은 검토용 요약 레이어입니다. 전체 디버그는 URL에
        {' '}?layers=all, 도로 라벨 전체는 ?roadLabels=all 을 붙여 확인합니다.
      </p>
    </div>
  );
});

LegalBasisPanel.displayName = 'LegalBasisPanel';

export default LegalBasisPanel;
