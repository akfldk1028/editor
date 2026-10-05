import React from 'react';
import { COLOR, STYLE } from '../lib/constants';

interface BigStatProps {
  label: string;
  value: number | null | undefined;
  unit: string;
  color: string;
}

export const BigStat = React.memo(function BigStat({ label, value, unit, color }: BigStatProps) {
  // accent color only for glow/border, numbers stay white
  const glowRgba = color === COLOR.cyan
    ? 'rgba(34,211,238,0.08)'
    : 'rgba(52,211,153,0.08)';
  const borderGlow = color === COLOR.cyan
    ? 'rgba(34,211,238,0.2)'
    : 'rgba(52,211,153,0.2)';
  const topGrad = color === COLOR.cyan
    ? 'linear-gradient(90deg, transparent, rgba(34,211,238,0.5), transparent)'
    : 'linear-gradient(90deg, transparent, rgba(52,211,153,0.5), transparent)';

  return (
    <div style={{
      flex: 1,
      textAlign: 'center',
      padding: '22px 16px 20px',
      position: 'relative',
      overflow: 'hidden',
      borderRadius: 16,
      background: `linear-gradient(180deg, ${glowRgba} 0%, rgba(255,255,255,0.01) 100%)`,
      border: `1px solid ${borderGlow}`,
      boxShadow: `0 0 40px ${glowRgba}, 0 4px 20px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.05)`,
    }}>
      {/* Top gradient accent line */}
      <div style={{
        position: 'absolute', top: 0, left: '10%', right: '10%', height: 1,
        background: topGrad,
      }} />

      {/* Ambient radial glow behind number */}
      <div style={{
        position: 'absolute',
        top: '55%', left: '50%',
        transform: 'translate(-50%, -50%)',
        width: 140, height: 100,
        borderRadius: '50%',
        background: `radial-gradient(ellipse, ${glowRgba}, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      <p style={{
        margin: 0,
        fontSize: 10,
        fontWeight: 600,
        color: COLOR.textMuted,
        marginBottom: 10,
        letterSpacing: '0.12em',
        textTransform: 'uppercase' as const,
        position: 'relative',
      }}>
        {label}
      </p>
      <p style={{
        margin: 0,
        fontSize: 48,
        fontWeight: 800,
        color: COLOR.text,
        lineHeight: 1,
        fontFeatureSettings: '"tnum"',
        fontFamily: STYLE.monoFont,
        position: 'relative',
        letterSpacing: '-0.03em',
      }}>
        {value != null ? value : '--'}
        <span style={{
          fontSize: 18, fontWeight: 400, marginLeft: 3,
          color: COLOR.textMuted,
        }}>{unit}</span>
      </p>
    </div>
  );
});
