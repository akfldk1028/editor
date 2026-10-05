import { requiredValue } from '../lib/required-value';
import React, { useRef, useEffect, useCallback } from 'react';
import type { FloorPlanResult, FloorPlanDesign } from '../lib/types';

interface Props {
  result: FloorPlanResult | null;
  selectedIndex: number;
  onSelectIndex: (i: number) => void;
  loading: boolean;
}

const METRIC_LABELS: Record<string, { label: string; color: string; format: (v: number) => string }> = {
  adjacency_score: { label: '인접성', color: '#4ade80', format: v => (v * 100).toFixed(0) + '%' },
  area_error:      { label: '면적오차', color: '#fb923c', format: v => (v * 100).toFixed(0) + '%' },
  compactness:     { label: '밀집도', color: '#60a5fa', format: v => (v * 100).toFixed(0) + '%' },
};

/** Compute centroid of a polygon ring */
function centroid(coords: number[][]): [number, number] {
  let cx = 0, cy = 0;
  for (const [x, y] of coords) { cx += requiredValue(x); cy += requiredValue(y); }
  return [cx / coords.length, cy / coords.length];
}

function ringArea(ring: number[][] | null | undefined): number {
  if (!ring || ring.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = requiredValue(ring[i]);
    const b = requiredValue(ring[(i + 1) % ring.length]);
    sum += requiredValue(a[0]) * requiredValue(b[1]) - requiredValue(b[0]) * requiredValue(a[1]);
  }
  return Math.abs(sum) / 2;
}

function largestPolygonCoordinates(polygons: number[][][][] | null | undefined): number[][][] | null {
  if (!Array.isArray(polygons) || polygons.length === 0) return null;
  return polygons.reduce<number[][][] | null>((best, polygon) => {
    if (!Array.isArray(polygon) || !polygon[0]) return best;
    if (!best) return polygon;
    return ringArea(polygon[0]) > ringArea(best[0]) ? polygon : best;
  }, null);
}

function drawFloorPlan(
  canvas: HTMLCanvasElement,
  design: FloorPlanDesign,
  gridInfo: { rows: number; cols: number; cell_size: number },
) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);

  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, w, h);

  const features = design.floor_plan.features;
  if (!features.length) return;

  // Compute bounds from grid info
  const gw = gridInfo.cols * gridInfo.cell_size;
  const gh = gridInfo.rows * gridInfo.cell_size;

  const pad = 24;
  const scale = Math.min((w - pad * 2) / gw, (h - pad * 2) / gh);
  const ox = (w - gw * scale) / 2;
  const oy = (h - gh * scale) / 2;

  const tx = (x: number) => ox + x * scale;
  const ty = (y: number) => oy + (gh - y) * scale; // flip Y

  // Draw grid lines (subtle)
  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.lineWidth = 0.5;
  for (let c = 0; c <= gridInfo.cols; c++) {
    const x = tx(c * gridInfo.cell_size);
    ctx.beginPath(); ctx.moveTo(x, ty(0)); ctx.lineTo(x, ty(gh)); ctx.stroke();
  }
  for (let r = 0; r <= gridInfo.rows; r++) {
    const y = ty(r * gridInfo.cell_size);
    ctx.beginPath(); ctx.moveTo(tx(0), y); ctx.lineTo(tx(gw), y); ctx.stroke();
  }

  // Draw room polygons
  for (const feat of features) {
    const coords = feat.geometry.type === 'Polygon'
      ? feat.geometry.coordinates[0]
      : feat.geometry.type === 'MultiPolygon'
        ? largestPolygonCoordinates(feat.geometry.coordinates as unknown as number[][][][])?.[0] || null
        : null;
    if (!coords || coords.length < 3) continue;

    const color = feat.properties.color;

    // Fill
    ctx.beginPath();
    ctx.moveTo(tx(requiredValue(requiredValue(coords[0])[0])), ty(requiredValue(requiredValue(coords[0])[1])));
    for (let i = 1; i < coords.length; i++) {
      ctx.lineTo(tx(requiredValue(requiredValue(coords[i])[0])), ty(requiredValue(requiredValue(coords[i])[1])));
    }
    ctx.closePath();
    ctx.fillStyle = color + '40';
    ctx.fill();

    // Stroke
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Label
    const [cx, cy] = centroid(coords);
    ctx.fillStyle = '#e2e8f0';
    ctx.font = `${Math.max(10, Math.min(13, scale * 1.2))}px -apple-system, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(feat.properties.room_name, tx(cx), ty(cy));

    // Area sub-label
    ctx.fillStyle = '#64748b';
    ctx.font = `${Math.max(8, Math.min(10, scale * 0.8))}px ui-monospace, monospace`;
    ctx.fillText(`${feat.properties.area_m2.toFixed(0)}m²`, tx(cx), ty(cy) + 14);
  }
}

const FloorPlanViewer: React.FC<Props> = React.memo(({ result, selectedIndex, onSelectIndex, loading }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const currentDesign = result?.results[selectedIndex] ?? null;

  useEffect(() => {
    if (!canvasRef.current || !currentDesign || !result) return;
    drawFloorPlan(canvasRef.current, currentDesign, result.grid_info);
  }, [currentDesign, result]);

  const handleResize = useCallback(() => {
    if (!canvasRef.current || !currentDesign || !result) return;
    drawFloorPlan(canvasRef.current, currentDesign, result.grid_info);
  }, [currentDesign, result]);

  useEffect(() => {
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [handleResize]);

  if (loading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: '#60a5fa', fontSize: 13,
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 24, marginBottom: 8, animation: 'spin 1.5s linear infinite' }}>⟳</div>
          평면 생성 중...
        </div>
      </div>
    );
  }

  if (!result || !result.results.length) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: '#334155', fontSize: 12, textAlign: 'center',
        padding: 20,
      }}>
        <div>
          <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.3 }}>⊞</div>
          매스를 선택하고<br />"평면 생성" 버튼을 누르세요
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Canvas */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        <canvas
          ref={canvasRef}
          style={{ width: '100%', height: '100%', display: 'block' }}
        />
      </div>

      {/* Metrics */}
      {currentDesign && (
        <div style={{
          display: 'flex', gap: 6, padding: '8px 10px',
          borderTop: '1px solid rgba(255,255,255,0.04)',
        }}>
          {Object.entries(currentDesign.metrics).map(([key, val]) => {
            const meta = METRIC_LABELS[key];
            if (!meta) return null;
            return (
              <div key={key} style={{
                flex: 1, padding: '6px 8px',
                background: `${meta.color}08`, borderRadius: 6,
                border: `1px solid ${meta.color}18`,
                textAlign: 'center',
              }}>
                <div style={{ color: '#5a6577', fontSize: 9, fontWeight: 600 }}>{meta.label}</div>
                <div style={{
                  color: meta.color, fontSize: 16, fontWeight: 700,
                  fontFamily: 'ui-monospace, monospace',
                }}>
                  {meta.format(val)}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Result selector */}
      {result.results.length > 1 && (
        <div style={{
          display: 'flex', gap: 4, padding: '6px 10px',
          borderTop: '1px solid rgba(255,255,255,0.04)',
          overflowX: 'auto',
        }}>
          {result.results.map((_, i) => (
            <button
              key={i}
              onClick={() => onSelectIndex(i)}
              style={{
                padding: '3px 10px', borderRadius: 6,
                fontSize: 10, fontWeight: 600, cursor: 'pointer',
                border: 'none',
                background: i === selectedIndex ? 'rgba(96,200,255,0.15)' : 'rgba(255,255,255,0.03)',
                color: i === selectedIndex ? '#60c8ff' : '#5a6577',
              }}
            >
              #{i + 1}
            </button>
          ))}
        </div>
      )}
    </div>
  );
});

FloorPlanViewer.displayName = 'FloorPlanViewer';
export default FloorPlanViewer;
