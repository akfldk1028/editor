import React from 'react';
import { COLOR, STYLE } from '../lib/constants';
import type { LandInfo } from '../lib/types';

interface LandInfoSummaryProps {
  landInfo: LandInfo | null;
}

const fmt = (n: number | undefined) =>
  n != null ? n.toLocaleString('ko-KR') : '-';

export const LandInfoSummary = React.memo(function LandInfoSummary({ landInfo }: LandInfoSummaryProps) {
  if (!landInfo) return null;

  const rows: [string, string][] = [];
  if (landInfo.land_area_m2) rows.push(['면적', `${fmt(landInfo.land_area_m2)} m²`]);
  if (landInfo.official_land_price) rows.push(['공시지가', `${fmt(landInfo.official_land_price)} 원/m²`]);
  if (landInfo.land_use_situation) rows.push(['지목', landInfo.land_use_situation]);
  if (landInfo.zones?.length) rows.push(['용도지역', landInfo.zones.join(', ')]);

  if (rows.length === 0) return null;

  return (
    <div style={{
      borderRadius: 12,
      background: 'rgba(255,255,255,0.015)',
      border: '1px solid rgba(255,255,255,0.04)',
      padding: '14px 16px',
    }}>
      <p style={{
        margin: 0, fontSize: 10, fontWeight: 700, color: COLOR.textMuted, marginBottom: 10,
        letterSpacing: '0.1em', textTransform: 'uppercase' as const,
      }}>
        토지 정보
      </p>
      {rows.map(([label, val], i) => (
        <div key={label} style={{
          display: 'flex', justifyContent: 'space-between',
          padding: '6px 0', fontSize: 13,
          borderTop: i > 0 ? '1px solid rgba(255,255,255,0.04)' : 'none',
        }}>
          <span style={{ color: COLOR.textMuted }}>{label}</span>
          <span style={{ color: COLOR.text, fontWeight: 500, fontFeatureSettings: '"tnum"', fontFamily: STYLE.monoFont }}>{val}</span>
        </div>
      ))}
    </div>
  );
});
