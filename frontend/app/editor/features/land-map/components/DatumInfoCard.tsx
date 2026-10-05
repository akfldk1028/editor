import React from 'react';
import { COLOR, STYLE } from '../lib/constants';
import type { SunlightEnvelope, DatumResultDict } from '../lib/types';

interface DatumInfoCardProps {
  /** envelope 우선 (정북일조 적용 zone). 없으면 datumResult로 fallback. */
  envelope?: SunlightEnvelope | null;
  /** envelope 없는 zone(상업/녹지)에서 datum 단독 표시용 (Phase 2D-2). */
  datumResult?: DatumResultDict | null;
}

const CASE_LABEL: Record<string, string> = {
  flat: '평탄지 (§119① 5호)',
  slope_le3m: '경사지 ≤8m (§119② 가중평균)',
  slope_gt3m: '경사지 >8m (§119② 단서)',
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
  elevation_fetch_failed: '표고 조회 실패 — 기준 표고 미확정',
};

export const DatumInfoCard = React.memo(function DatumInfoCard({ envelope, datumResult }: DatumInfoCardProps) {
  // envelope 우선, 없으면 datumResult를 envelope-호환 shape로 변환 (design 카드와 동일 패턴)
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

  if (!data) return null;

  // datum 미계산 (ENABLE_DATUM_ELEVATION=false 또는 source=null)
  if (data.elevation_source == null) {
    return (
      <div style={{
        borderRadius: 12,
        background: 'rgba(255,255,255,0.015)',
        border: '1px solid rgba(255,255,255,0.04)',
        padding: '14px 16px',
      }}>
        <p style={{
          margin: 0, fontSize: 10, fontWeight: 700, color: COLOR.textMuted, marginBottom: 6,
          letterSpacing: '0.1em', textTransform: 'uppercase' as const,
        }}>
          지반 레벨 (§119 datum)
        </p>
        <p style={{ margin: 0, fontSize: 12, color: COLOR.textMuted }}>
          지반 기준 표고가 계산되지 않았습니다.
        </p>
      </div>
    );
  }

  const datum_m = data.datum_elevation_m;
  const caseLabel = data.datum_case ? (CASE_LABEL[data.datum_case] ?? data.datum_case) : '-';
  const srcLabel = SOURCE_LABEL[data.elevation_source] ?? data.elevation_source;
  const basisLabel = data.datum_basis
    ? (BASIS_LABEL[data.datum_basis] ?? data.datum_basis)
    : null;
  const isFailed = data.elevation_source === 'failed';
  const accent = isFailed ? COLOR.amber : COLOR.cyan;

  // sibling LandInfoSummary 와 동일한 surface (시각 일관성)
  return (
    <div style={{
      borderRadius: 12,
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid rgba(255,255,255,0.04)',
      padding: '14px 16px',
      // 좌측 accent로 datum 카드 구분 (hardcoded 색상 회피, COLOR token 사용)
      borderLeft: `3px solid ${accent}`,
    }}>
      <p style={{
        margin: 0, fontSize: 10, fontWeight: 700, color: COLOR.textMuted, marginBottom: 10,
        letterSpacing: '0.1em', textTransform: 'uppercase' as const,
      }}>
        지반 레벨 (§119 datum)
      </p>

      {/* 지반 표고 강조 */}
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 8,
        padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.04)', marginBottom: 8,
      }}>
        <span style={{ color: COLOR.textMuted, fontSize: 13 }}>H = 0 절대 표고</span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 22, fontWeight: 700, color: accent,
          fontFamily: STYLE.monoFont, fontFeatureSettings: '"tnum"',
        }}>
          {isFailed || datum_m == null ? '미확정' : datum_m.toFixed(2)}
          {!isFailed && datum_m != null && <span style={{ fontSize: 13, fontWeight: 500, color: COLOR.textMuted, marginLeft: 4 }}>m</span>}
        </span>
      </div>

      {/* 케이스 + 산정방법 + 소스 */}
      {([
        ['§119/§86 케이스', caseLabel, false],
        ...(basisLabel ? [['산정 방법', basisLabel, false]] : []),
        ['데이터 소스', srcLabel, true],
      ] as Array<[string, string, boolean]>).map(([label, val, mono], i) => (
        <div key={label} style={{
          display: 'flex', justifyContent: 'space-between',
          padding: '5px 0', fontSize: 12,
          borderTop: i > 0 ? '1px solid rgba(255,255,255,0.04)' : 'none',
        }}>
          <span style={{ color: COLOR.textMuted }}>{label}</span>
          <span style={{
            color: COLOR.text, fontWeight: 500,
            fontFamily: mono ? STYLE.monoFont : 'inherit',
          }}>{val}</span>
        </div>
      ))}

      {/* envelope 추가 정보 */}
      <p style={{
        margin: '10px 0 0 0', fontSize: 11, color: COLOR.textMuted, lineHeight: 1.5,
      }}>
        표시된 데이터 소스와 산정 방법을 기준으로 확인하세요. 높이 형상은 기준 표고에 대한 상대값입니다.
      </p>
    </div>
  );
});
