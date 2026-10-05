import React from 'react';
import { COLOR, STYLE } from '../lib/constants';

interface RegulationCardProps {
  name: string;
  value: string | number | null | undefined;
  unit?: string;
  article?: string;
  description?: string;
  accent?: string;
}

export const RegulationCard = React.memo(function RegulationCard({
  name, value, unit, article, description, accent = COLOR.textDim,
}: RegulationCardProps) {
  return (
    <div
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)';
        e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.3)';
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'rgba(255,255,255,0.015)';
        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.04)';
        e.currentTarget.style.boxShadow = '0 1px 4px rgba(0,0,0,0.15)';
        e.currentTarget.style.transform = 'translateY(0)';
      }}
      style={{
        position: 'relative',
        borderRadius: 10,
        background: 'rgba(255,255,255,0.015)',
        border: '1px solid rgba(255,255,255,0.04)',
        padding: '11px 14px 11px 18px',
        boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
        transform: 'translateY(0)',
        transition: 'all 0.2s ease',
        overflow: 'hidden',
      }}
    >
      {/* Left accent bar */}
      <div style={{
        position: 'absolute', left: 0, top: 8, bottom: 8,
        width: 3, borderRadius: '0 2px 2px 0',
        background: accent,
        opacity: value != null ? 0.6 : 0.15,
      }} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: COLOR.textSecondary }}>{name}</span>
        {value != null && (
          <span style={{
            fontSize: 15, fontWeight: 700, color: COLOR.text,
            fontFeatureSettings: '"tnum"',
            fontFamily: STYLE.monoFont,
          }}>
            {value}{unit && <span style={{ fontSize: 11, fontWeight: 400, marginLeft: 2, color: COLOR.textMuted }}>{unit}</span>}
          </span>
        )}
      </div>
      {description && (
        <p style={{ margin: 0, marginTop: 4, fontSize: 12, color: COLOR.textMuted, lineHeight: 1.6 }}>{description}</p>
      )}
      {article && (
        <p style={{ margin: 0, marginTop: 3, fontSize: 11, color: COLOR.textDim, fontFamily: STYLE.monoFont }}>{article}</p>
      )}
    </div>
  );
});
