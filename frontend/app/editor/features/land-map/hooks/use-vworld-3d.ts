/**
 * Vworld 3D WebGL map hook — 3D 건물/지형 + 지적도 WMS + 필지 하이라이트
 *
 * Vworld WebGL API 3.0 (Cesium-based).
 * API key: /land/map-config/ → 외부 스크립트 동적 로드.
 *
 * 공식 샘플 기반 (github.com/V-world/V-world_API_sample):
 *
 *   초기화 순서 (모든 공식 샘플 동일):
 *     map = new vw.Map(); map.setOption(opts); map.start();
 *     const viewer = ws3d.viewer;               // start() 직후 사용 가능
 *     viewer.screenSpaceEventHandler.setInputAction(...);  // 직접 바인딩
 *     vw.ws3dInitCallBack = function() { ... }; // 비동기 콜백 (WMS 등)
 *
 *   WMS:  vw.source.TileWMS + vw.layer.Tile + vw.Layers
 *   필지: vw.geom.Polygon + vw.Coord + vw.Collection + setFillColor + create()
 *   이동: map.moveTo(CameraPosition) / viewer.camera.flyTo(...)
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { MAP_CONFIG_3D } from '../lib/constants';
import { canCreateWebGLContext, getCesium, getVw, getWs3d, loadVworldScript, sdkStyles } from './vworld-3d-loader';
import {
  addCadastralWmsLayer,
  applyDiagramImageryStyle,
  bindEventHandlers,
  extractGeoJsonRing,
  PARCEL_HIGHLIGHT_ID,
  PARCEL_HOVER_ID,
  SETBACK_COLORS,
  SETBACK_DS_NAME,
  recoverHmrViewer,
  zoomToAltitude,
} from './vworld-3d-scene';

/* eslint-disable @typescript-eslint/no-explicit-any */

// ---------------------------------------------------------------------------
// Interface
// ---------------------------------------------------------------------------

interface UseVworld3DOptions {
  target: React.RefObject<HTMLDivElement | null>;
  onClick?: (lng: number, lat: number) => void;
  /** 마우스 이동 시 좌표 콜백 (호출 빈도 높음 — 소비자가 디바운스 필요) */
  onHover?: (lng: number, lat: number) => void;
}

interface UseVworld3DReturn {
  ready: boolean;
  loading: boolean;
  error: string | null;
  /** 클릭 필지 하이라이트 (진한 파랑, 유지됨) */
  highlightParcel: (geojson: object) => void;
  /** 호버 필지 하이라이트 (연한 파랑, 마우스 이동 시 교체) */
  highlightHover: (geojson: object) => void;
  clearHighlight: () => void;
  clearHoverHighlight: () => void;
  flyTo: (lng: number, lat: number, zoom?: number) => void;
  /** Vworld 3D 건물 레이어 표시/숨김 (커스텀 매스 렌더링 시 기존 건물 가림 방지) */
  setBuildingsVisible: (visible: boolean) => void;
  /** 규제선 GeoJSON 3D 렌더링 (ground clamped) */
  drawSetbackLines: (lines: Record<string, unknown>) => void;
  clearSetbackLines: () => void;
  /** Cesium viewer ref for direct 3D entity manipulation */
  viewerRef: React.RefObject<any>;
}

// ---------------------------------------------------------------------------
// SDK 싱글턴 viewer 재사용용 모듈 상태 (HMR / Next 네비게이션)
// ---------------------------------------------------------------------------

let retainedMap: any = null;
let retainedContainer: HTMLDivElement | null = null;

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useVworld3D({
  target,
  onClick,
  onHover,
}: UseVworld3DOptions): UseVworld3DReturn {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mapInstanceRef = useRef<any>(null);  // vw.Map
  const viewerRef = useRef<any>(null);       // ws3d.viewer (Cesium.Viewer)
  const onClickRef = useRef(onClick);
  onClickRef.current = onClick;
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  const initRef = useRef(false);
  const apiKeyRef = useRef('');

  useEffect(() => {
    if (!target.current || initRef.current) return;
    initRef.current = true;

    let destroyed = false;

    async function init() {
      try {
        setLoading(true);
        setError(null);

        if (!canCreateWebGLContext()) {
          setError('WebGL을 사용할 수 없어 3D 지도를 비활성화했습니다.');
          setLoading(false);
          return;
        }

        // ── 1. Fetch API key ──────────────────────────────────────
        const configRes = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/map-config`);
        if (!configRes.ok) {
          const message = await configRes.json()
            .then((body) => body?.detail || body?.error)
            .catch(() => null);
          throw new Error(message || 'API 키 조회 실패');
        }
        const cfg = await configRes.json();
        if (!cfg?.api_key || typeof cfg.api_key !== 'string') {
          throw new Error('VWORLD_API_KEY가 설정되지 않았습니다.');
        }
        if (destroyed) return;
        apiKeyRef.current = cfg.api_key;

        // ── 2. Load Vworld 3D script ──────────────────────────────
        await loadVworldScript(cfg.api_key);
        if (destroyed) return;
        for (const style of sdkStyles) style.disabled = false;

        const vw = getVw();
        if (!vw?.Map) throw new Error('Vworld 3D API 로드 실패');

        // ── HMR guard: reuse existing viewer if ws3d.viewer is already defined
        //    Vworld SDK uses Object.defineProperties (non-configurable) on ws3d.viewer,
        //    so calling map.start() again after HMR throws "Cannot redefine property: viewer".
        const existingViewer = getWs3d()?.viewer;
        const Cesium = getCesium();
        if (existingViewer && Cesium) {
          viewerRef.current = existingViewer;
          // The SDK's singleton viewer survives Next navigation; its DOM must move with it.
          if (retainedContainer && target.current && retainedContainer !== target.current) {
            target.current.removeAttribute('id');
            target.current.appendChild(retainedContainer);
          }
          existingViewer.useDefaultRenderLoop = true;
          existingViewer.resize();
          existingViewer.scene.requestRender();
          // Recover mapInstanceRef from ws3d if available (HMR path)
          const ws3d = getWs3d();
          mapInstanceRef.current = retainedMap || ws3d?.map;
          bindEventHandlers(existingViewer, Cesium, onClickRef, onHoverRef);

          recoverHmrViewer(existingViewer, Cesium, apiKeyRef.current);

          setReady(true);
          setLoading(false);
          return;
        }

        // ── 3. Container ID (vw.Map 필수) + 커서 스타일 ──────────
        const container = target.current!;
        if (!container.id) container.id = 'vworld-3d-map';
        container.style.cursor = 'crosshair';

        // ── 4. Initialize & start map ─────────────────────────────
        //    공식 패턴: new vw.Map() → setOption() → start()
        const map = new vw.Map();
        map.setOption({
          mapId: container.id,
          initPosition: new vw.CameraPosition(
            new vw.CoordZ(
              MAP_CONFIG_3D.center[0],
              MAP_CONFIG_3D.center[1],
              MAP_CONFIG_3D.defaultAltitude,
            ),
            new vw.Direction(0, MAP_CONFIG_3D.defaultPitch, 0),
          ),
          logo: true,
          navigation: true,
        });
        map.start();
        mapInstanceRef.current = map;
        retainedMap = map;
        retainedContainer = container;

        // ── 5. viewer — start() 직후 사용 가능 (공식 패턴) ────────
        const viewer = getWs3d()?.viewer;

        if (viewer && Cesium) {
          viewerRef.current = viewer;
          bindEventHandlers(viewer, Cesium, onClickRef, onHoverRef);
        }

        // ── 7. ws3dInitCallBack — start() 후 설정 (공식 패턴) ─────
        vw.ws3dInitCallBack = function () {
          if (destroyed) return;

          // viewer 재확인 — 동적 로딩 시 start() 직후 미가용 케이스 대비
          if (!viewerRef.current) {
            const v = getWs3d()?.viewer;
            const C = getCesium();
            if (v && C) {
              viewerRef.current = v;
              bindEventHandlers(v, C, onClickRef, onHoverRef);
            }
          }

          // ── 위성 → 다이어그램 basemap 교체 (Cesium imagery) ──
          try {
            const v = viewerRef.current;
            const C = getCesium();
            if (v && C) {
              v.imageryLayers.removeAll();
              const layer = v.imageryLayers.addImageryProvider(
                new C.UrlTemplateImageryProvider({
                  url: `https://api.vworld.kr/req/wmts/1.0.0/${apiKeyRef.current}/Base/{z}/{y}/{x}.png`,
                  maximumLevel: 19,
                  credit: new C.Credit('Vworld'),
                }),
              );
              applyDiagramImageryStyle(layer);
            }
          } catch (e) {
            console.warn('다이어그램 basemap 교체 실패:', e);
          }

          addCadastralWmsLayer(vw, apiKeyRef.current);

          setReady(true);
          setLoading(false);
        };
      } catch (e: unknown) {
        if (destroyed) return;
        const msg = e instanceof Error ? e.message : '3D 지도 로드 실패';
        console.error('Vworld 3D init error:', e);
        setError(msg);
        setLoading(false);
      }
    }

    init();

    return () => {
      destroyed = true;
      const vw = getVw();
      if (vw) vw.ws3dInitCallBack = null;
      try { mapInstanceRef.current?.removeObjectById(PARCEL_HIGHLIGHT_ID); } catch { /* no-op */ }
      try { mapInstanceRef.current?.removeObjectById(PARCEL_HOVER_ID); } catch { /* no-op */ }
      // Cesium viewer 엔티티 정리 (메모리 누수 방지) — viewer 자체는 유지 (HMR 재사용)
      try {
        viewerRef.current?.entities?.removeAll();
        if (viewerRef.current) {
          viewerRef.current.useDefaultRenderLoop = false;
          const Cesium = getCesium();
          if (Cesium) {
            viewerRef.current.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.LEFT_CLICK);
            viewerRef.current.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.MOUSE_MOVE);
          }
        }
      } catch { /* no-op */ }
      for (const style of sdkStyles) style.disabled = true;
      // Do NOT destroy viewer or innerHTML — Vworld SDK viewer is non-recreatable (HMR)
      viewerRef.current = null;
      mapInstanceRef.current = null;
      initRef.current = false;
    };
  }, [target]);

  // ---------------------------------------------------------------------------
  // 필지 하이라이트
  //
  // 공식 패턴 ([검색, DATA] 주소 검색 후 필지 표출.html):
  //   pnuPoly.push(new vw.Coord(i[0], i[1]));
  //   var coordCol2 = new vw.Collection(pnuPoly);
  //   searchPolygon = new vw.geom.Polygon(coordCol2);
  //   searchPolygon.setFillColor(new vw.Color(255, 0, 0, 70));
  //   searchPolygon.setWidth(1);
  //   searchPolygon.setId("pnuPolygon");
  //   searchPolygon.create();
  // ---------------------------------------------------------------------------

  const highlightParcel = useCallback((geojson: object) => {
    const vw = getVw();
    const map = mapInstanceRef.current;
    if (!vw || !map) return;

    // 기존 하이라이트 제거
    try { map.removeObjectById(PARCEL_HIGHLIGHT_ID); } catch { /* no-op */ }

    try {
      const ring = extractGeoJsonRing(geojson);

      if (!ring || ring.length < 3) {
        console.warn('하이라이트 실패: 유효하지 않은 지오메트리');
        return;
      }

      // vw.geom.Polygon (공식 패턴 그대로)
      const vwCoords = ring.map(
        (c: number[]) => new vw.Coord(c[0], c[1]),
      );
      const collection = new vw.Collection(vwCoords);
      const polygon = new vw.geom.Polygon(collection);
      polygon.setFillColor(new vw.Color(34, 197, 94, 12));
      polygon.setWidth(3);
      polygon.setId(PARCEL_HIGHLIGHT_ID);
      polygon.create();
    } catch (e) {
      console.warn('필지 하이라이트 실패:', e);

      // Fallback: Cesium GeoJsonDataSource ([WebGL3] GeoJson 지면 위로.html)
      const viewer = viewerRef.current;
      const Cesium = getCesium();
      if (viewer && Cesium) {
        viewer.dataSources.removeAll();
        Cesium.GeoJsonDataSource.load(geojson, {
          stroke: Cesium.Color.fromCssColorString('#3b82f6'),
          fill: Cesium.Color.fromCssColorString('#22c55e').withAlpha(0.04),
          strokeWidth: 3,
          clampToGround: true,
        })
          .then((ds: any) => viewer.dataSources.add(ds))
          .catch((err: any) => console.warn('GeoJSON fallback 실패:', err));
      }
    }
  }, []);

  // ---------------------------------------------------------------------------
  // 호버 하이라이트 (연한 파랑 — 마우스 이동 시 교체)
  //
  // highlightParcel과 동일 로직, 다른 ID/색상.
  // 클릭 하이라이트(PARCEL_HIGHLIGHT_ID)와 독립적으로 공존.
  // ---------------------------------------------------------------------------

  const highlightHover = useCallback((geojson: object) => {
    const vw = getVw();
    const map = mapInstanceRef.current;
    if (!vw || !map) return;

    try { map.removeObjectById(PARCEL_HOVER_ID); } catch { /* no-op */ }

    try {
      const ring = extractGeoJsonRing(geojson);

      if (!ring || ring.length < 3) return;

      const vwCoords = ring.map((c: number[]) => new vw.Coord(c[0], c[1]));
      const collection = new vw.Collection(vwCoords);
      const polygon = new vw.geom.Polygon(collection);
      polygon.setFillColor(new vw.Color(236, 72, 153, 120)); // 진한 핑크
      polygon.setWidth(1);
      polygon.setId(PARCEL_HOVER_ID);
      polygon.create();
    } catch { /* silent */ }
  }, []);

  // ---------------------------------------------------------------------------
  // 하이라이트 제거
  // ---------------------------------------------------------------------------

  const clearHighlight = useCallback(() => {
    try { mapInstanceRef.current?.removeObjectById(PARCEL_HIGHLIGHT_ID); } catch { /* no-op */ }
    try { viewerRef.current?.dataSources?.removeAll(); } catch { /* no-op */ }
  }, []);

  const clearHoverHighlight = useCallback(() => {
    try { mapInstanceRef.current?.removeObjectById(PARCEL_HOVER_ID); } catch { /* no-op */ }
  }, []);

  // ---------------------------------------------------------------------------
  // 카메라 이동
  //
  // 공식 패턴 (즉시): map.moveTo(new vw.CameraPosition(CoordZ, Direction))
  // Cesium (애니메이션): viewer.camera.flyTo({ destination, orientation, duration })
  // ---------------------------------------------------------------------------

  const flyTo = useCallback((lng: number, lat: number, zoom = 18) => {
    const viewer = viewerRef.current;
    const Cesium = getCesium();

    if (viewer && Cesium) {
      const altitude = zoomToAltitude(zoom);
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(lng, lat, altitude),
        orientation: {
          heading: Cesium.Math.toRadians(0),
          pitch: Cesium.Math.toRadians(-60),
          roll: 0,
        },
        duration: MAP_CONFIG_3D.flyDuration,
      });
    } else {
      // Fallback: vw.Map.moveTo (즉시 이동)
      const vw = getVw();
      const map = mapInstanceRef.current;
      if (vw && map) {
        const altitude = zoomToAltitude(zoom);
        const pos = new vw.CameraPosition(
          new vw.CoordZ(lng, lat, altitude),
          new vw.Direction(0, -60, 0),
        );
        map.moveTo(pos);
      }
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Vworld 3D 건물 레이어 표시/숨김
  //
  // 커스텀 매스 렌더링 시 기존 Vworld 건물이 가려서 안 보이는 문제 해결.
  // 1차: SDK facility_build 레이어 hide/show
  // 2차: Cesium Cesium3DTileset.show toggle (fallback)
  // ---------------------------------------------------------------------------

  const setBuildingsVisible = useCallback((visible: boolean) => {
    // Approach 1: Vworld SDK layer API
    const map = mapInstanceRef.current;
    try {
      const layer = map?.getLayerElement?.('facility_build');
      if (layer) {
        if (visible) layer.show();
        else layer.hide();
      }
    } catch { /* fallback to Cesium */ }

    // Approach 2: Cesium 3D Tileset iteration
    const viewer = viewerRef.current;
    const Cesium = getCesium();
    if (!viewer || !Cesium) return;
    const primitives = viewer.scene.primitives;
    for (let i = 0; i < primitives.length; i++) {
      const p = primitives.get(i);
      if (p instanceof Cesium.Cesium3DTileset) {
        p.show = visible;
      }
    }
  }, []);

  // ---------------------------------------------------------------------------
  // 규제선 렌더링 (Cesium GeoJsonDataSource, ground clamped)
  // ---------------------------------------------------------------------------

  const drawSetbackLines = useCallback((lines: Record<string, unknown>) => {
    const viewer = viewerRef.current;
    const Cesium = getCesium();
    if (!viewer || !Cesium) return;

    // 기존 규제선 제거
    const existing = viewer.dataSources._dataSources?.filter(
      (ds: any) => ds.name === SETBACK_DS_NAME,
    );
    if (existing) {
      for (const ds of existing) viewer.dataSources.remove(ds, true);
    }

    const entries = Object.entries(lines);
    for (const [key, geojson] of entries) {
      if (!geojson || key === 'sunlight_envelope' || key === 'daylight_diagonal_envelope') continue;
      const colors = SETBACK_COLORS[key] || SETBACK_COLORS.adjacent_setback!;

      try {
        Cesium.GeoJsonDataSource.load(geojson, {
          stroke: Cesium.Color.fromCssColorString(colors.stroke),
          fill: Cesium.Color.fromCssColorString(colors.fill),
          strokeWidth: colors.width,
          clampToGround: true,
        }).then((ds: any) => {
          ds.name = SETBACK_DS_NAME;
          viewer.dataSources.add(ds);
        }).catch((err: any) => console.warn(`Setback ${key} 렌더 실패:`, err));
      } catch (e) {
        console.warn(`Setback ${key} 로드 실패:`, e);
      }
    }
  }, []);

  const clearSetbackLines = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const toRemove = viewer.dataSources._dataSources?.filter(
      (ds: any) => ds.name === SETBACK_DS_NAME,
    ) || [];
    for (const ds of toRemove) viewer.dataSources.remove(ds, true);
  }, []);

  return { ready, loading, error, highlightParcel, highlightHover, clearHighlight, clearHoverHighlight, flyTo, setBuildingsVisible, drawSetbackLines, clearSetbackLines, viewerRef };
}
