/**
 * OpenLayers map hook — Vworld 배경지도 + 지적도 WMS 오버레이
 *
 * 설정값은 constants.ts MAP_CONFIG 에서 관리.
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import Map from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import TileWMS from 'ol/source/TileWMS';
import GeoJSON from 'ol/format/GeoJSON';
import { fromLonLat, toLonLat } from 'ol/proj';
import { Style, Fill, Stroke, Text as OlText } from 'ol/style';
import Feature from 'ol/Feature';
import Point from 'ol/geom/Point';
import type Polygon from 'ol/geom/Polygon';
import type MultiPolygon from 'ol/geom/MultiPolygon';
import { MAP_CONFIG } from '../lib/constants';
import type { SetbackLines } from '../lib/types';

interface UseVworldMapOptions {
  target: React.RefObject<HTMLDivElement | null>;
  onClick?: (lng: number, lat: number) => void;
  center?: [number, number];
  zoom?: number;
}

interface UseVworldMapReturn {
  mapError: string | null;
  mapRef: React.MutableRefObject<Map | null>;
  highlightParcel: (geojson: object, fit?: boolean) => void;
  clearHighlight: () => void;
  flyTo: (lng: number, lat: number, zoom?: number) => void;
  drawSetbackLines: (lines: SetbackLines) => void;
  clearSetbackLines: () => void;
}

const HIGHLIGHT_STYLE = new Style({
  fill: new Fill({ color: MAP_CONFIG.highlightColor }),
  stroke: new Stroke({ color: MAP_CONFIG.highlightStroke, width: 2.5 }),
});

// 정북일조 높이별 스타일: 가까울수록 진하고 두껍게, 멀수록 연하게
const SUNLIGHT_HEIGHT_STYLES: Record<number, Style> = {
  10: new Style({
    stroke: new Stroke({ color: '#ef4444', width: 5 }),
    text: new OlText({
      text: 'H=10m (1.5m)',
      font: '12px sans-serif',
      fill: new Fill({ color: '#ef4444' }),
      stroke: new Stroke({ color: '#fff', width: 3 }),
      placement: 'line',
      overflow: true,
    }),
  }),
  20: new Style({
    stroke: new Stroke({ color: '#f97316', width: 4, lineDash: [12, 6] }),
    text: new OlText({
      text: 'H=20m (10m)',
      font: '11px sans-serif',
      fill: new Fill({ color: '#f97316' }),
      stroke: new Stroke({ color: '#fff', width: 3 }),
      placement: 'line',
      overflow: true,
    }),
  }),
  30: new Style({
    stroke: new Stroke({ color: '#fb923c', width: 3, lineDash: [10, 8] }),
    text: new OlText({
      text: 'H=30m (15m)',
      font: '10px sans-serif',
      fill: new Fill({ color: '#fb923c' }),
      stroke: new Stroke({ color: '#fff', width: 3 }),
      placement: 'line',
      overflow: true,
    }),
  }),
  40: new Style({
    stroke: new Stroke({ color: '#fdba74', width: 2, lineDash: [8, 10] }),
    text: new OlText({
      text: 'H=40m (20m)',
      font: '10px sans-serif',
      fill: new Fill({ color: '#fdba74' }),
      stroke: new Stroke({ color: '#fff', width: 3 }),
      placement: 'line',
      overflow: true,
    }),
  }),
};

const SETBACK_STYLES: Record<string, Style> = {
  buildable_area: new Style({
    fill: new Fill({ color: 'rgba(34, 197, 94, 0.12)' }),
    stroke: new Stroke({ color: '#22c55e', width: 4, lineDash: [10, 6] }),
  }),
  north_setback: new Style({
    stroke: new Stroke({ color: '#ef4444', width: 5 }),
  }),
  adjacent_setback: new Style({
    stroke: new Stroke({ color: '#ef4444', width: 5 }),
  }),
  road_setback: new Style({
    stroke: new Stroke({ color: '#ef4444', width: 5 }),
  }),
  building_designation_line: new Style({
    stroke: new Stroke({ color: '#ef4444', width: 5 }),
  }),
};

export function useVworldMap({
  target,
  onClick,
  center = MAP_CONFIG.defaultCenter,
  zoom = MAP_CONFIG.defaultZoom,
}: UseVworldMapOptions): UseVworldMapReturn {
  const [mapError, setMapError] = useState<string | null>(null);
  const mapRef = useRef<Map | null>(null);
  const highlightSourceRef = useRef<VectorSource>(new VectorSource());
  const setbackSourceRef = useRef<VectorSource>(new VectorSource());
  const onClickRef = useRef(onClick);
  onClickRef.current = onClick;

  useEffect(() => {
    if (!target.current || mapRef.current) return;

    const baseTile = new TileLayer({
      source: new XYZ({
        url: MAP_CONFIG.tileUrl,
        maxZoom: MAP_CONFIG.maxZoom,
        attributions: '\u00a9 Vworld',
      }),
    });

    const cadastralWms = new TileLayer({
      source: new TileWMS({
        url: MAP_CONFIG.wmsUrl,
        params: {
          LAYERS: MAP_CONFIG.wmsLayers,
          FORMAT: 'image/png',
          TRANSPARENT: 'true',
          VERSION: '1.3.0',
          CRS: 'EPSG:3857',
        },
        serverType: 'mapserver',
      }),
      opacity: 0.7,
      minZoom: MAP_CONFIG.cadastralMinZoom,
    });

    const highlightLayer = new VectorLayer({
      source: highlightSourceRef.current,
      style: HIGHLIGHT_STYLE,
      zIndex: 10,
    });

    const tileError = () => setMapError('지도 또는 지적도를 불러오지 못했습니다. 지도 공급자 연결을 확인하세요.');
    baseTile.getSource()?.on('tileloaderror', tileError);
    cadastralWms.getSource()?.on('tileloaderror', tileError);

    const setbackLayer = new VectorLayer({
      source: setbackSourceRef.current,
      style: (feature) => {
        const key = feature.get('setbackType') as string;
        if (key === 'north_setback') {
          const h = feature.get('height_m') as number;
          if (h && SUNLIGHT_HEIGHT_STYLES[h]) return SUNLIGHT_HEIGHT_STYLES[h];
        }
        // §119 datum 라벨 — "지도에도 대지 레벨이 떠야 한다" 의도 반영.
        if (key === 'datum') {
          const datum_m = feature.get('datum_m') as number;
          return new Style({
            text: new OlText({
              text: `H₀ = ${datum_m.toFixed(2)}m`,
              font: '700 13px ui-monospace, SFMono-Regular, Menlo, monospace',
              fill: new Fill({ color: '#facc15' }),
              stroke: new Stroke({ color: '#000', width: 3 }),
              overflow: true,
            }),
          });
        }
        return SETBACK_STYLES[key] || SETBACK_STYLES.adjacent_setback;
      },
      zIndex: 11,
    });

    const map = new Map({
      target: target.current,
      layers: [baseTile, cadastralWms, highlightLayer, setbackLayer],
      view: new View({
        center: fromLonLat(center),
        zoom,
        maxZoom: MAP_CONFIG.maxZoom,
        minZoom: MAP_CONFIG.minZoom,
      }),
    });

    map.on('singleclick', (evt) => {
      const [lng, lat] = toLonLat(evt.coordinate);
      if (lng !== undefined && lat !== undefined) onClickRef.current?.(lng, lat);
    });

    mapRef.current = map;

    return () => {
      baseTile.getSource()?.un('tileloaderror', tileError);
      cadastralWms.getSource()?.un('tileloaderror', tileError);
      map.setTarget(undefined);
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  const highlightParcel = useCallback((geojson: object, fit = false) => {
    const src = highlightSourceRef.current;
    src.clear();
    try {
      const features = new GeoJSON().readFeatures(geojson, {
        dataProjection: 'EPSG:4326',
        featureProjection: 'EPSG:3857',
      });
      src.addFeatures(features);
      const extent = src.getExtent();
      if (fit && extent && extent.every(Number.isFinite)) {
        mapRef.current?.getView().fit(extent, { padding: [80, 40, 40, 40], maxZoom: 18, duration: MAP_CONFIG.flyDuration });
      }
    } catch (e) {
      console.warn('Failed to parse parcel geometry:', e);
    }
  }, []);

  const clearHighlight = useCallback(() => {
    highlightSourceRef.current.clear();
  }, []);

  const flyTo = useCallback((lng: number, lat: number, targetZoom = 18) => {
    const map = mapRef.current;
    if (!map) return;
    map.getView().animate({
      center: fromLonLat([lng, lat]),
      zoom: targetZoom,
      duration: MAP_CONFIG.flyDuration,
    });
  }, []);

  const drawSetbackLines = useCallback((lines: SetbackLines) => {
    const src = setbackSourceRef.current;
    src.clear();
    const format = new GeoJSON();

    // §119 datum 라벨 — buildable_area centroid 위에 "H₀ = X m" 텍스트 추가.
    // envelope 우선 (정북일조 적용 zone), 없으면 datum_result fallback (상업/녹지 등).
    const datum_m = lines.sunlight_envelope?.datum_elevation_m
      ?? lines.datum_result?.elevation_m
      ?? null;
    if (datum_m != null && lines.sunlight_envelope?.elevation_source !== 'failed' && lines.datum_result?.elevation_source !== 'failed' && lines.buildable_area) {
      try {
        const baFeat = format.readFeature(lines.buildable_area, {
          dataProjection: 'EPSG:4326',
          featureProjection: 'EPSG:3857',
        }) as Feature;
        const geom = baFeat.getGeometry() as Polygon | MultiPolygon | undefined;
        let coord: number[] | undefined;
        if (geom && 'getInteriorPoint' in geom) {
          coord = (geom as Polygon).getInteriorPoint().getCoordinates();
        } else if (geom && 'getInteriorPoints' in geom) {
          coord = (geom as MultiPolygon).getInteriorPoints().getFirstCoordinate();
        }
        if (coord) {
          const datumFeat = new Feature({ geometry: new Point(coord) });
          datumFeat.set('setbackType', 'datum');
          datumFeat.set('datum_m', datum_m);
          src.addFeature(datumFeat);
        }
      } catch (e) {
        console.warn('Failed to add datum label:', e);
      }
    }
    const entries: [string, unknown][] = [
      ['buildable_area', lines.buildable_area],
      ['north_setback', lines.north_setback],
      ['adjacent_setback', lines.adjacent_setback],
      ['road_setback', lines.road_setback],
      ['building_designation_line', lines.building_designation_line],
      // sunlight_envelope is 3D only (Cesium) — skip in 2D OpenLayers
    ];
    for (const [key, geojson] of entries) {
      if (!geojson) continue;
      try {
        const geo = geojson as Record<string, unknown>;

        // north_setback: FeatureCollection with height_m per feature
        if (key === 'north_setback' && geo.type === 'FeatureCollection') {
          const fc = geo as { features: Array<{ properties?: Record<string, unknown>; geometry: object }> };
          for (const feat of fc.features) {
            const featureObj = { type: 'Feature', properties: feat.properties || {}, geometry: feat.geometry };
            const olFeatures = format.readFeatures(featureObj, {
              dataProjection: 'EPSG:4326',
              featureProjection: 'EPSG:3857',
            });
            for (const f of olFeatures) {
              (f as Feature).set('setbackType', key);
              if (feat.properties?.height_m) (f as Feature).set('height_m', feat.properties.height_m);
            }
            src.addFeatures(olFeatures);
          }
          continue;
        }

        const features = format.readFeatures(geo, {
          dataProjection: 'EPSG:4326',
          featureProjection: 'EPSG:3857',
        });
        for (const f of features) {
          (f as Feature).set('setbackType', key);
        }
        src.addFeatures(features);
      } catch (e) {
        console.warn(`Failed to parse setback ${key}:`, e);
      }
    }
  }, []);

  const clearSetbackLines = useCallback(() => {
    setbackSourceRef.current.clear();
  }, []);

  return { mapError, mapRef, highlightParcel, clearHighlight, flyTo, drawSetbackLines, clearSetbackLines };
}
