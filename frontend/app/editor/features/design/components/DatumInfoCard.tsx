import React from 'react';
import type { SunlightEnvelope } from '../../land-map/lib/types';
import type { DatumResultDict } from '../lib/types';

const CASE_LABEL: Record<string, string> = {
  flat: '평탄지 (§119① 5호)',
  slope_le3m: '경사지 ≤3m (§119② 가중평균)',
  slope_gt3m: '경사지 >3m (§119② 단서)',
  road_flat: '도로접지 평지 (§119① 5호 가목)',
  road_sloped: '도로접지 경사 (§119① 5호 가목 단서)',
  site_above_road: '대지>도로 (§119① 5호 나목)',
  neighbor_avg_86: '정북인접 평균 (§86)',
};

const SOURCE_LABEL: Record<string, string> = {
  open_meteo: 'Open-Meteo (90m, ±~11m)',
  copernicus_glo30: 'Copernicus GLO-30 (30m, ±~2m)',
  ngii_lidar_1m: 'NGII LiDAR (1m, ±14cm)',
  ngii_5m: 'NGII 5m DEM (±~1m)',
  ngii_local_dem: 'NGII 수치지형도 SHP→DEM (5m)',
  failed: '⚠ fetch 실패',
};

const BASIS_LABEL: Record<string, string> = {
  ground_flat: '대지 평탄',
  ground_weighted_avg: '대지 둘레 가중평균',
  ground_split_3m: '대지 3m 분할',
  road_centerline: '도로 중심선',
  road_centerline_weighted_avg: '도로 가중평균',
  site_above_road_half_raise: '대지>도로 1/2 raise',
  neighbor_avg_86: '인접지 평균',
  elevation_fetch_failed: '⚠ fetch 실패 → 0.0 fallback',
};

interface Props {
  /** envelope 우선 (정북일조 적용 zone). 없으면 datumResult로 fallback. */
  envelope?: SunlightEnvelope | null;
  /** envelope 없는 zone(상업 등)에서 datum 단독 표시용. */
  datumResult?: DatumResultDict | null;
}

/**
 * 정북일조 envelope의 §119 datum 메타데이터를 시각 표시.
 *
 * Source 우선순위:
 *   1. envelope이 있으면 envelope의 datum_* 필드 사용 (정북일조 적용 zone)
 *   2. 없으면 datumResult 사용 (정북일조 미적용 zone, 상업/녹지 등)
 *   3. 둘 다 없으면 null 반환 (렌더 안 함)
 *
 * 3-state:
 *   elevation_source = null      → datum 미계산 (회색 안내, ENABLE_DATUM_ELEVATION=false)
 *   elevation_source = open_meteo → cyan accent, datum_m + case + basis + source
 *   elevation_source = failed    → amber accent, fetch 실패 표시
 *
 * Sibling: ConstraintSummary와 동일 surface(`#111827`/`#1e293b`).
 */
const DatumInfoCard: React.FC<Props> = React.memo(({ envelope, datumResult }) => {
  const sunlightApplies = Boolean(envelope);
  // envelope 우선, 없으면 datumResult를 envelope-호환 shape로 변환
  // elevation_source: Session 4부터 동적 (open_meteo / copernicus_glo30 / ngii_lidar_1m / ngii_local_dem / failed)
  const data: {
    elevation_source: 'open_meteo' | 'copernicus_glo30' | 'ngii_lidar_1m' | 'ngii_5m' | 'ngii_local_dem' | 'failed' | null | undefined;
    datum_elevation_m?: number | null;
    datum_case?: string | null;
    datum_basis?: string | null;
  } | null = envelope
    ? {
      elevation_source: envelope.elevation_source,
      datum_elevation_m: envelope.datum_elevation_m,
      datum_case: envelope.datum_case,
      datum_basis: envelope.datum_basis,
    }
    : datumResult
      ? {
        elevation_source: datumResult.elevation_source,
        datum_elevation_m: datumResult.elevation_m,
        datum_case: datumResult.case,
        datum_basis: datumResult.basis,
      }
      : null;

  const parcelDatumM = datumResult?.parcel_datum_m ?? datumResult?.elevation_m ?? null;
  const roadDatumM = datumResult?.road_datum_m ?? null;
  const neighborDatumM = datumResult?.neighbor_datum_m ?? null;
  const neighborAvgM = datumResult?.neighbor_avg_datum_m ?? null;
  const splitBandCount = datumResult?.split_bands?.length ?? datumResult?.split_polygons?.length ?? 0;

  if (!data && !datumResult) return null;

  // datum 미계산 (env flag false 또는 backend 미전달)
  if (data?.elevation_source == null) {
    return (
      <div style={{
        background: '#111827', borderRadius: 10, padding: 14, marginBottom: 10,
        border: '1px solid #1e293b',
      }}>
        <h3 style={{
          color: '#64748b', fontSize: 10, fontWeight: 600,
          marginBottom: 6, letterSpacing: '0.08em',
          textTransform: 'uppercase' as const, margin: 0,
        }}>지반 레벨 (§119 datum)</h3>
        <p style={{ margin: '6px 0 0 0', fontSize: 11, color: '#64748b', lineHeight: 1.5 }}>
          datum 미계산 (ENABLE_DATUM_ELEVATION=false). envelope은 Cesium terrain 사용.
        </p>
      </div>
    );
  }

  const datum_m = data?.datum_elevation_m ?? datumResult?.elevation_m ?? 0;
  const datumCase = data?.datum_case ?? null;
  const datumBasis = data?.datum_basis ?? null;
  const caseLabel = datumCase
    ? (CASE_LABEL[datumCase] ?? datumCase) : '-';
  const src = data?.elevation_source ?? datumResult?.elevation_source ?? null;
  const srcLabel = src ? (SOURCE_LABEL[src] ?? src) : '-';
  const basisLabel = datumBasis
    ? (BASIS_LABEL[datumBasis] ?? datumBasis) : null;
  const isFailed = src === 'failed';
  const accent = isFailed ? '#f59e0b' : '#22d3ee';   // amber / cyan (design 모듈은 hex 직접 사용 패턴)
  const rows: Array<[string, string, boolean]> = [
    [sunlightApplies ? '정북일조 기준 H=0' : '정북일조', sunlightApplies ? `${datum_m.toFixed(2)} m` : '미적용', false],
    ...(parcelDatumM != null ? [['대지 §119 기준면', `${parcelDatumM.toFixed(2)} m`, true] as [string, string, boolean]] : []),
    ...(roadDatumM != null ? [['전면도로 기준면', `${roadDatumM.toFixed(2)} m`, true] as [string, string, boolean]] : []),
    ...(neighborDatumM != null ? [['인접대지 기준면', `${neighborDatumM.toFixed(2)} m`, true] as [string, string, boolean]] : []),
    ...(sunlightApplies && neighborAvgM != null ? [['§86 평균수평면', `${neighborAvgM.toFixed(2)} m`, true] as [string, string, boolean]] : []),
    ...(splitBandCount > 0 ? [['3m 분할 band', `${splitBandCount}개`, false] as [string, string, boolean]] : []),
    [sunlightApplies ? '§119/§86 케이스' : '§119 케이스', caseLabel, false],
    ...(basisLabel ? [['산정 방법', basisLabel, false] as [string, string, boolean]] : []),
    ['데이터 소스', srcLabel, true],
  ];

  return (
    <div style={{
      background: '#111827', borderRadius: 10, padding: 14, marginBottom: 10,
      border: '1px solid #1e293b',
      borderLeft: `3px solid ${accent}`,
    }}>
      <h3 style={{
        color: '#64748b', fontSize: 10, fontWeight: 600,
        marginBottom: 10, letterSpacing: '0.08em',
        textTransform: 'uppercase' as const, margin: 0,
      }}>지반 레벨 (§119 datum)</h3>

      {/* H=0 표고 강조 */}
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 8,
        padding: '8px 0 6px 0',
        borderBottom: '1px solid #1e293b',
        marginBottom: 6, marginTop: 4,
      }}>
        <span style={{ color: '#94a3b8', fontSize: 12 }}>
          {sunlightApplies ? '정북일조 기준 H = 0' : '대지 §119 기준면'}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 22, fontWeight: 700, color: accent,
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          fontFeatureSettings: '"tnum"',
        }}>
          {datum_m.toFixed(2)}
          <span style={{ fontSize: 12, fontWeight: 500, color: '#64748b', marginLeft: 4 }}>m</span>
        </span>
      </div>

      {/* 케이스 + 산정방법 + 소스 */}
      {rows.map(([label, val, mono], i) => (
        <div key={label} style={{
          display: 'flex', justifyContent: 'space-between',
          padding: '4px 0', fontSize: 11,
          borderTop: i > 0 ? '1px solid #1e293b' : 'none',
        }}>
          <span style={{ color: '#94a3b8' }}>{label}</span>
          <span style={{
            color: '#e2e8f0', fontWeight: 500,
            fontFamily: mono ? 'ui-monospace, SFMono-Regular, Menlo, monospace' : 'inherit',
          }}>{val}</span>
        </div>
      ))}

      <p style={{
        margin: '8px 0 0 0', fontSize: 10, color: '#64748b', lineHeight: 1.5,
      }}>
        {sunlightApplies
          ? 'envelope walls/slanted_polygons 의 H는 이 datum 기준 상대값. Cesium 렌더 시 datum_m 위에 envelope 위치.'
          : '정북일조 미적용 용도지역에서는 §86 envelope를 렌더하지 않고, §119 대지/도로/인접대지 기준면만 표시합니다.'}
      </p>
    </div>
  );
});

DatumInfoCard.displayName = 'DatumInfoCard';

export default DatumInfoCard;
