import { expect, test } from 'bun:test';
import { buildDatumMarkers, extractRing, flattenRing } from './site-map-geometry';
import { renderDaylightDiagonalEnvelope } from './envelopes/daylight';
import type { SetbackGeometriesMap } from './types';

const small = [[0, 0], [1, 0], [1, 1], [0, 0]];
const large = [[10, 10], [14, 10], [14, 14], [10, 10]];

test('map and fallback select the largest multipolygon parcel without rewriting coordinates', () => {
  const ring = extractRing({ type: 'MultiPolygon', coordinates: [[small], [large]] });
  expect(ring).toBe(large);
  expect(flattenRing(ring!)).toEqual([10, 10, 14, 10, 14, 14, 10, 10]);
  expect(extractRing({ type: 'LineString', coordinates: small })).toBeNull();
});

test('datum markers retain weighted parcel level and separate road, neighbor and sunlight levels', () => {
  const setbacks = {
    datum_result: {
      parcel_datum_m: 12,
      road_datum_m: 9,
      neighbor_datum_m: 14,
      neighbor_avg_datum_m: 13,
      parcel_segments: [
        { midpoint_lng: 0, midpoint_lat: 0, length_m: 1 },
        { midpoint_lng: 4, midpoint_lat: 4, length_m: 3 },
      ],
      road_samples: [{ lng: 1, lat: 2, weight: 2 }],
      neighbor_segments: [{ midpoint_lng: 5, midpoint_lat: 7, length_m: 2 }],
    },
    sunlight_envelope: {},
  } as SetbackGeometriesMap;
  const markers = buildDatumMarkers(setbacks, small);
  expect(markers.map(({ id, lng, lat, elevationM }) => ({ id, lng, lat, elevationM }))).toEqual([
    { id: 'parcel-119', lng: 3, lat: 3, elevationM: 12 },
    { id: 'road', lng: 1, lat: 2, elevationM: 9 },
    { id: 'neighbor', lng: 5, lat: 7, elevationM: 14 },
    { id: 'neighbor-avg-86', lng: 4, lat: 5, elevationM: 13 },
  ]);
  expect(buildDatumMarkers({ ...setbacks, sunlight_envelope: undefined }, small)).toHaveLength(3);
  expect(buildDatumMarkers({}, small)).toEqual([]);
});

test('daylight surfaces remain per-vertex polygons at datum-adjusted elevations', () => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { location: { search: '?daylight=1' } } });
  try {
    const entities: Array<Record<string, any>> = [];
    const color = { withAlpha: (alpha: number) => ({ alpha }) };
    const cesium = {
      Color: { fromCssColorString: () => color },
      Cartesian3: { fromDegreesArrayHeights: (values: number[]) => values, fromDegrees: (...values: number[]) => values },
    };
    renderDaylightDiagonalEnvelope({ entities: { add: (entity: Record<string, any>) => entities.push(entity) } }, cesium, {
      surface_polygons: [{ positions: [[1, 2], [2, 2], [2, 3]], max_heights: [0, 5, 10] }],
    }, { wall: '#a855f7' }, 20);
    expect(entities).toHaveLength(2);
    expect(entities[0]?.polygon.hierarchy).toEqual([1, 2, 20, 2, 2, 25, 2, 3, 30]);
    expect(entities[0]?.polygon.perPositionHeight).toBe(true);
    expect(entities[0]?.wall).toBeUndefined();
    expect(entities[1]?.polyline.positions).toEqual([[1, 2, 20], [2, 2, 25], [2, 3, 30], [1, 2, 20]]);
  } finally {
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow);
    else Reflect.deleteProperty(globalThis, 'window');
  }
});
