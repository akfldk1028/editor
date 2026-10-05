import { requiredValue } from '../lib/required-value';
import React, { useRef, useEffect } from 'react';
import type { DesignData } from '../lib/types';
import type { ScatterPoint } from '../hooks/use-optimization-stream';

interface Props {
  designs: DesignData[];
  scatterHistory: ScatterPoint[];
  maxGeneration: number;
  selectedId: number | null;
  onSelect: (design: DesignData) => void;
  xLabel?: string;
  yLabel?: string;
}

const MARGIN = { top: 20, right: 20, bottom: 48, left: 56 };
const CHART_HEIGHT = 380;

/**
 * AUA-style HSL rainbow gradient.
 * hue 240 (blue) → 0 (red), saturation 100%, lightness ~50%.
 */
function genColorHSL(gen: number, maxGen: number, feasible: boolean): string {
  if (!feasible) return 'hsla(220, 15%, 35%, 0.12)';
  const t = maxGen > 0 ? gen / maxGen : 0;
  const hue = Math.round(240 - t * 240); // 240→0: blue→cyan→green→yellow→red
  return `hsla(${hue}, 92%, 58%, ${0.5 + t * 0.3})`;
}

/** Pareto front point glow color */
function paretoGlow(idx: number, total: number): string {
  const t = total > 1 ? idx / (total - 1) : 0;
  const hue = Math.round(200 - t * 160); // 200→40: cyan→orange gradient along front
  return `hsl(${hue}, 90%, 62%)`;
}

/** Safe min/max for large arrays (avoids stack overflow from spread) */
function arrayMinMax(arr: number[]): [number, number] {
  let min = Infinity, max = -Infinity;
  for (let i = 0; i < arr.length; i++) {
    if (requiredValue(arr[i]) < min) min = requiredValue(arr[i]);
    if (requiredValue(arr[i]) > max) max = requiredValue(arr[i]);
  }
  return [min, max];
}

interface Bounds {
  xMin: number; xMax: number; yMin: number; yMax: number;
  plotW: number; plotH: number;
  scaleX: (v: number) => number;
  scaleY: (v: number) => number;
}

/** Compute plot bounds + scale functions from scatter + pareto data */
function computeBounds(
  scatterHistory: ScatterPoint[],
  designs: DesignData[],
  width: number,
): Bounds | null {
  const allX: number[] = [];
  const allY: number[] = [];
  for (const s of scatterHistory) { allX.push(s[0]); allY.push(s[1]); }
  for (const d of designs) { allX.push(d.objectives[0] || 0); allY.push(d.objectives[1] || 0); }
  if (allX.length === 0) return null;

  const [rawXMin, rawXMax] = arrayMinMax(allX);
  const [rawYMin, rawYMax] = arrayMinMax(allY);
  const xRange = rawXMax - rawXMin || 1;
  const yRange = rawYMax - rawYMin || 1;
  const xMin = rawXMin - xRange * 0.05;
  const xMax = rawXMax + xRange * 0.05;
  const yMin = rawYMin - yRange * 0.05;
  const yMax = rawYMax + yRange * 0.05;

  const plotW = width - MARGIN.left - MARGIN.right;
  const plotH = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;

  const scaleX = (v: number) => MARGIN.left + ((v - xMin) / (xMax - xMin || 1)) * plotW;
  const scaleY = (v: number) => MARGIN.top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;

  return { xMin, xMax, yMin, yMax, plotW, plotH, scaleX, scaleY };
}

const ParetoChart: React.FC<Props> = React.memo(({
  designs, scatterHistory, maxGeneration, selectedId, onSelect,
  xLabel = 'Floor Area (m\u00B2)', yLabel = 'Daylight Score',
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    if (designs.length === 0 && scatterHistory.length === 0) return;

    const rect = container.getBoundingClientRect();
    const width = rect.width;
    const dpr = window.devicePixelRatio || 1;

    canvas.width = width * dpr;
    canvas.height = CHART_HEIGHT * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${CHART_HEIGHT}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    // Background with subtle gradient
    const bgGrad = ctx.createLinearGradient(0, 0, 0, CHART_HEIGHT);
    bgGrad.addColorStop(0, '#080d18');
    bgGrad.addColorStop(1, '#0a1020');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, width, CHART_HEIGHT);

    const bounds = computeBounds(scatterHistory, designs, width);
    if (!bounds) return;
    const { xMin, xMax, yMin, yMax, plotW, plotH, scaleX, scaleY } = bounds;

    // Grid lines — subtle
    ctx.setLineDash([1, 5]);
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth = 1;
    const numTicks = 5;
    for (let i = 0; i <= numTicks; i++) {
      const x = MARGIN.left + (i / numTicks) * plotW;
      ctx.beginPath(); ctx.moveTo(x, MARGIN.top); ctx.lineTo(x, MARGIN.top + plotH); ctx.stroke();
      const y = MARGIN.top + (i / numTicks) * plotH;
      ctx.beginPath(); ctx.moveTo(MARGIN.left, y); ctx.lineTo(MARGIN.left + plotW, y); ctx.stroke();
    }
    ctx.setLineDash([]);

    // Axis tick values
    ctx.fillStyle = '#4a5568';
    ctx.font = '10px ui-monospace, monospace';
    ctx.textAlign = 'center';
    for (let i = 0; i <= numTicks; i++) {
      const val = xMin + (i / numTicks) * (xMax - xMin);
      const x = MARGIN.left + (i / numTicks) * plotW;
      ctx.fillText(val.toFixed(0), x, CHART_HEIGHT - MARGIN.bottom + 16);
    }
    ctx.textAlign = 'right';
    for (let i = 0; i <= numTicks; i++) {
      const val = yMin + (i / numTicks) * (yMax - yMin);
      const y = MARGIN.top + plotH - (i / numTicks) * plotH;
      ctx.fillText(val.toFixed(1), MARGIN.left - 8, y + 3);
    }

    // --- Layer 1: Scatter cloud (AUA rainbow HSL) ---
    for (const s of scatterHistory) {
      const x = scaleX(s[0]);
      const y = scaleY(s[1]);
      const feasible = s[2];
      const gen = s[3];

      if (!feasible) {
        // Infeasible: hollow square (AUA style)
        ctx.strokeStyle = 'rgba(100,116,139,0.12)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(x - 1.5, y - 1.5, 3, 3);
      } else {
        // Feasible: solid circle with HSL rainbow color
        ctx.beginPath();
        ctx.arc(x, y, 3.2, 0, Math.PI * 2);
        ctx.fillStyle = genColorHSL(gen, maxGeneration, true);
        ctx.fill();
      }
    }

    // Sort Pareto front once (shared by line + points)
    const sortedPareto = [...designs].sort((a, b) => (a.objectives[0] || 0) - (b.objectives[0] || 0));

    // --- Layer 2: Pareto front connecting line (glowing) ---
    if (sortedPareto.length > 1) {
      // Outer glow
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(96,200,255,0.12)';
      ctx.lineWidth = 8;
      ctx.lineJoin = 'round';
      sortedPareto.forEach((d, i) => {
        const x = scaleX(d.objectives[0] || 0);
        const y = scaleY(d.objectives[1] || 0);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // Main line
      ctx.beginPath();
      ctx.strokeStyle = 'rgba(96,200,255,0.5)';
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      sortedPareto.forEach((d, i) => {
        const x = scaleX(d.objectives[0] || 0);
        const y = scaleY(d.objectives[1] || 0);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    // --- Layer 3: Pareto front points (rainbow gradient along front) ---
    for (let i = 0; i < sortedPareto.length; i++) {
      const d = requiredValue(sortedPareto[i]);
      const x = scaleX(requiredValue(d.objectives[0]) || 0);
      const y = scaleY(requiredValue(d.objectives[1]) || 0);
      const isSelected = d.id === selectedId;
      const color = paretoGlow(i, sortedPareto.length);

      // Glow
      const glowSize = isSelected ? 22 : 14;
      const glow = ctx.createRadialGradient(x, y, 0, x, y, glowSize);
      if (isSelected) {
        glow.addColorStop(0, 'rgba(255,220,100,0.5)');
        glow.addColorStop(0.5, 'rgba(255,180,50,0.15)');
        glow.addColorStop(1, 'rgba(255,180,50,0)');
      } else {
        const t = sortedPareto.length > 1 ? i / (sortedPareto.length - 1) : 0;
        const hue = Math.round(200 - t * 160);
        glow.addColorStop(0, `hsla(${hue},90%,62%,0.25)`);
        glow.addColorStop(1, `hsla(${hue},90%,62%,0)`);
      }
      ctx.fillStyle = glow;
      ctx.fillRect(x - glowSize, y - glowSize, glowSize * 2, glowSize * 2);

      // Point
      const radius = isSelected ? 8 : 6;
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);

      if (isSelected) {
        const grad = ctx.createRadialGradient(x, y - 1, 0, x, y, radius);
        grad.addColorStop(0, '#fff');
        grad.addColorStop(0.3, '#fde68a');
        grad.addColorStop(1, '#f59e0b');
        ctx.fillStyle = grad;
      } else {
        const grad = ctx.createRadialGradient(x, y - 1, 0, x, y, radius);
        grad.addColorStop(0, '#fff');
        grad.addColorStop(0.4, color);
        grad.addColorStop(1, color);
        ctx.fillStyle = grad;
      }
      ctx.fill();

      // Ring
      ctx.strokeStyle = isSelected ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.25)';
      ctx.lineWidth = isSelected ? 2.5 : 1;
      ctx.stroke();
    }

    // Axis labels
    ctx.fillStyle = '#5a6577';
    ctx.font = '11px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(xLabel, MARGIN.left + plotW / 2, CHART_HEIGHT - 4);
    ctx.save();
    ctx.translate(13, MARGIN.top + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(yLabel, 0, 0);
    ctx.restore();

    // Plot border
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    ctx.strokeRect(MARGIN.left, MARGIN.top, plotW, plotH);

  }, [designs, scatterHistory, maxGeneration, selectedId, xLabel, yLabel]);

  const selectNearest = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || designs.length === 0) return;

    const rect = canvas.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;

    const bounds = computeBounds(scatterHistory, designs, rect.width);
    if (!bounds) return;
    const { scaleX, scaleY } = bounds;

    let closest: DesignData | null = null;
    let minDist = 64;
    for (const d of designs) {
      const dx = scaleX(d.objectives[0] || 0) - mx;
      const dy = scaleY(d.objectives[1] || 0) - my;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < minDist) { minDist = dist; closest = d; }
    }
    if (closest) onSelect(closest);
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    selectNearest(e.clientX, e.clientY);
  };

  const totalCount = scatterHistory.length;
  const paretoCount = designs.length;

  return (
    <div style={{
      background: 'linear-gradient(180deg, #0c1120 0%, #0e1525 100%)',
      borderRadius: 12,
      padding: '14px 16px 16px',
      border: '1px solid rgba(255,255,255,0.06)',
      boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 12,
      }}>
        <h3 style={{
          color: '#8b95a8', fontSize: 11, fontWeight: 700, margin: 0,
          letterSpacing: '0.1em',
        }}>
          PARETO FRONT
        </h3>
        <div style={{ display: 'flex', gap: 6 }}>
          <span style={{
            padding: '2px 8px', borderRadius: 10,
            background: 'rgba(255,255,255,0.04)', color: '#5a6577',
            fontSize: 10, fontFamily: 'ui-monospace, monospace',
          }}>
            {totalCount} evaluated
          </span>
          <span style={{
            padding: '2px 8px', borderRadius: 10,
            background: 'rgba(96,200,255,0.08)', color: '#60c8ff',
            fontSize: 10, fontFamily: 'ui-monospace, monospace',
            fontWeight: 600,
          }}>
            {paretoCount} pareto
          </span>
        </div>
      </div>

      {/* Generation color legend */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        marginBottom: 8, paddingLeft: MARGIN.left,
      }}>
        <span style={{ color: '#4a5568', fontSize: 9 }}>Gen</span>
        <div style={{
          flex: 1, maxWidth: 120, height: 4, borderRadius: 2,
          background: 'linear-gradient(90deg, hsl(240,92%,58%), hsl(180,92%,58%), hsl(120,92%,58%), hsl(60,92%,58%), hsl(0,92%,58%))',
        }} />
        <span style={{ color: '#4a5568', fontSize: 9 }}>0 → {maxGeneration}</span>
      </div>

      <div ref={containerRef} style={{ width: '100%' }}>
        <canvas
          ref={canvasRef}
          onPointerDown={handlePointerDown}
          style={{ cursor: 'crosshair', borderRadius: 8 }}
        />
      </div>
    </div>
  );
});

ParetoChart.displayName = 'ParetoChart';
export default ParetoChart;
