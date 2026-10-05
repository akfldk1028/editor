import { expect, test } from 'bun:test';
import { drawFloorPlan } from './FloorPlanViewer';
import type { FloorPlanDesign } from '../lib/types';

const collection = (x: number, y: number): FloorPlanDesign['floor_plan'] => ({
  type: 'FeatureCollection', features: [{ type: 'Feature',
    properties: { room_code: 1, room_name: 'Living', color: '#123456', area_m2: 36 },
    geometry: { type: 'Polygon', coordinates: [[[x, y], [x + 6, y], [x + 6, y + 6], [x, y + 6], [x, y]]] },
  }],
});

for (const withLocal of [true, false]) {
  test(`canvas uses meters inside its viewport (${withLocal ? 'geographic response' : 'legacy local response'})`, () => {
    const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
    Object.defineProperty(globalThis, 'window', { configurable: true, value: { devicePixelRatio: 1 } });
    try {
      const labels: Array<[string, number, number]> = [];
      const points: number[][] = [];
      const ctx = { scale() {}, fillRect() {}, beginPath() {}, closePath() {}, fill() {}, stroke() {},
        moveTo(x: number, y: number) { points.push([x, y]); },
        lineTo(x: number, y: number) { points.push([x, y]); },
        fillText(text: string, x: number, y: number) { labels.push([text, x, y]); },
      };
      const canvas = { clientWidth: 400, clientHeight: 300, getContext: () => ctx } as unknown as HTMLCanvasElement;
      const design = { design_id: 1, metrics: {}, floor_plan: collection(withLocal ? 127 : 0, withLocal ? 37 : 0),
        ...(withLocal ? { floor_plan_local: collection(0, 0) } : {}),
      } as FloorPlanDesign;
      drawFloorPlan(canvas, design, { rows: 4, cols: 4, cell_size: 3 });
      expect(labels.map(([text]) => text)).toEqual(['Living', '36m\u00b2']);
      expect(points.length).toBeGreaterThan(20);
      for (const [x, y] of points) {
        expect(x).toBeGreaterThanOrEqual(24);
        expect(x).toBeLessThanOrEqual(376);
        expect(y).toBeGreaterThanOrEqual(24);
        expect(y).toBeLessThanOrEqual(276);
      }
      expect(labels[0]?.[1]).toBeCloseTo(124.4);
      expect(labels[0]?.[2]).toBeCloseTo(225.6);
    } finally {
      if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow);
      else Reflect.deleteProperty(globalThis, 'window');
    }
  });
}
