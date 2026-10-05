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

// ---------------------------------------------------------------------------
// Dynamically-loaded globals accessor
// ---------------------------------------------------------------------------

/* eslint-disable @typescript-eslint/no-explicit-any */
const getVw = (): any => (window as any).vw;
const getWs3d = (): any => (window as any).ws3d;
const getCesium = (): any => (window as any).Cesium;

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
// Script loader (idempotent — 한 번만 로드)
//
// 핵심 문제: webglMapInit.js.do 부트스트랩이 document.write()로 3개
// 하위 스크립트(Cesium 등)를 주입하는데, 동적 <script>에서
// document.write()는 브라우저가 무시함.
//
// 해결: document.write를 오버라이드 → <script> 태그로 부트스트랩 로드
//       → 인터셉트한 URL들을 순차 <script> 태그로 로드 → poll vw.Map
//
// <script> 태그 로딩은 CORS 면제 (fetch와 다름).
// ---------------------------------------------------------------------------

let scriptPromise: Promise<void> | null = null;
let retainedMap: any = null;
let retainedContainer: HTMLDivElement | null = null;
const sdkStyles = new Set<HTMLLinkElement>();

function canCreateWebGLContext(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(
      canvas.getContext('webgl2')
      || canvas.getContext('webgl')
      || canvas.getContext('experimental-webgl'),
    );
  } catch {
    return false;
  }
}

function appendScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('VWorld 지도 스크립트를 불러오지 못했습니다.'));
    document.head.appendChild(s);
  });
}

function waitForVwMap(timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;
    const check = () => {
      if (getVw()?.Map) { resolve(); return; }
      if (Date.now() > deadline) { reject(new Error('vw.Map 가용 타임아웃')); return; }
      setTimeout(check, 100);
    };
    check();
  });
}

async function loadVworldScript(apiKey: string): Promise<void> {
  if (getVw()?.Map) return;
  if (scriptPromise) return scriptPromise;

  scriptPromise = (async () => {
    const subScripts: string[] = [];
    const subStyles: string[] = [];
    const origWrite = document.write.bind(document);
    document.write = ((html: string) => {
      const scriptMatch = html.match(/src=['"]([^'"]+)['"]/);
      if (scriptMatch?.[1]) {
        subScripts.push(scriptMatch[1].replace(/^http:\/\//, 'https://'));
      }
      const styleMatch = html.match(/href=['"]([^'"]+\.css[^'"]*)['"]/);
      if (styleMatch?.[1]) {
        subStyles.push(styleMatch[1].replace(/^http:\/\//, 'https://'));
      }
    }) as typeof document.write;

    try {
      // 1) jQuery 로드 — VWViewerStartup이 $ 의존
      if (!(window as any).jQuery) {
        await appendScript('https://code.jquery.com/jquery-3.7.1.min.js');
      }

      // 2) 부트스트랩 <script> 로드 (CORS 면제)
      await appendScript(
        `https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=${apiKey}`,
      );

      // 3) 전역변수 http→https 강제 (Cesium 워커 등이 이 변수 참조)
      const w = window as any;
      for (const k of ['vworldUrl', 'vworld2DCache', 'vworldBaseMapUrl', 'vworldStyledMapUrl']) {
        if (w[k]) w[k] = w[k].replace('http://', 'https://');
      }

      // 4) 수집한 CSS/하위 스크립트 로드 (Cesium → VW → OL, 순서 중요)
      for (const href of subStyles) {
        if (document.querySelector(`link[href="${href}"]`)) continue;
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        sdkStyles.add(link);
        document.head.appendChild(link);
      }
      for (const src of subScripts) {
        await appendScript(src);
      }

      // 5) vw.Map 가용 대기
      await waitForVwMap(15_000);
    } catch (e) {
      scriptPromise = null;
      throw e;
    } finally {
      document.write = origWrite;
    }
  })();

  return scriptPromise;
}

function applyDiagramImageryStyle(layer: any) {
  if (!layer) return;
  try {
    layer.saturation = 0.0;
    layer.brightness = 1.18;
    layer.contrast = 0.72;
    layer.gamma = 1.08;
    layer.alpha = 0.42;
  } catch {
    // Cesium imagery layer styling is best-effort; VWorld still works without it.
  }
}

function ringArea(ring: number[][] | null | undefined): number {
  if (!ring || ring.length < 3) return 0;
  let total = 0;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    if (!a || !b || a[0] == null || a[1] == null || b[0] == null || b[1] == null) return 0;
    total += a[0] * b[1] - b[0] * a[1];
  }
  return Math.abs(total) / 2;
}

function largestPolygonCoordinates(polygons: number[][][][] | null | undefined): number[][][] | null {
  if (!Array.isArray(polygons) || polygons.length === 0) return null;
  return polygons.reduce<number[][][] | null>((best, polygon) => {
    if (!Array.isArray(polygon) || !polygon[0]) return best;
    if (!best) return polygon;
    return ringArea(polygon[0]) > ringArea(best[0]) ? polygon : best;
  }, null);
}

function extractGeoJsonRing(geojson: any): number[][] | undefined {
  const geo = geojson?.type === 'Feature' ? geojson.geometry : geojson;
  if (geo?.type === 'Polygon') return geo.coordinates?.[0];
  if (geo?.type === 'MultiPolygon') return largestPolygonCoordinates(geo.coordinates)?.[0] || undefined;
  return undefined;
}

// ---------------------------------------------------------------------------
// Zoom → altitude 변환 (3D 틸트 카메라용)
// ---------------------------------------------------------------------------

function zoomToAltitude(zoom: number): number {
  // zoom 15→6000m, 16→3000m, 17→1500m, 18→750m, 19→375m
  const clamped = Math.min(19, Math.max(10, zoom));
  return Math.max(150, 6000 / Math.pow(2, clamped - 15));
}

// ---------------------------------------------------------------------------
// Parcel highlight ID (map.removeObjectById 용)
// ---------------------------------------------------------------------------

const PARCEL_HIGHLIGHT_ID = 'selected-parcel';
const PARCEL_HOVER_ID = 'hovered-parcel';

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

    // 이벤트 핸들러 바인딩 — viewer + Cesium 확보 후 호출
    function bindEventHandlers(viewer: any, Cesium: any) {
      // LEFT_CLICK → onClick
      viewer.screenSpaceEventHandler.setInputAction(
        function (movement: any) {
          const ray = viewer.camera.getPickRay(movement.position);
          if (!ray) return;
          const cartesian = viewer.scene.globe.pick(ray, viewer.scene);
          if (!cartesian) return;
          const carto = Cesium.Cartographic.fromCartesian(cartesian);
          onClickRef.current?.(
            Cesium.Math.toDegrees(carto.longitude),
            Cesium.Math.toDegrees(carto.latitude),
          );
        },
        Cesium.ScreenSpaceEventType.LEFT_CLICK,
      );

      // MOUSE_MOVE → onHover (좌표 추출만, 디바운스는 소비자 책임)
      viewer.screenSpaceEventHandler.setInputAction(
        function (movement: any) {
          if (!onHoverRef.current) return;
          const ray = viewer.camera.getPickRay(movement.endPosition);
          if (!ray) return;
          const cartesian = viewer.scene.globe.pick(ray, viewer.scene);
          if (!cartesian) return;
          const carto = Cesium.Cartographic.fromCartesian(cartesian);
          onHoverRef.current(
            Cesium.Math.toDegrees(carto.longitude),
            Cesium.Math.toDegrees(carto.latitude),
          );
        },
        Cesium.ScreenSpaceEventType.MOUSE_MOVE,
      );
    }

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
          bindEventHandlers(existingViewer, Cesium);

          // 2026-05-11 — HMR 시 imagery layer가 사라지는 케이스 fix.
          try {
            if (existingViewer.imageryLayers.length === 0) {
              const layer = existingViewer.imageryLayers.addImageryProvider(
                new Cesium.UrlTemplateImageryProvider({
                  url: `https://api.vworld.kr/req/wmts/1.0.0/${apiKeyRef.current}/Base/{z}/{y}/{x}.png`,
                  maximumLevel: 19,
                  credit: new Cesium.Credit('Vworld'),
                }),
              );
              applyDiagramImageryStyle(layer);
            }
          } catch (e) {
            console.warn('HMR imagery 재추가 실패:', e);
          }

          // 2026-05-11 v2 — HMR 후 카메라가 우주(1700km)에 머물러 검정 화면.
          // 카메라 height > 100km면 한국 default 위치로 강제 reset.
          try {
            const camH = existingViewer.camera.positionCartographic?.height;
            if (!isFinite(camH) || camH > 100000) {
              existingViewer.camera.setView({
                destination: Cesium.Cartesian3.fromDegrees(
                  MAP_CONFIG_3D.center[0],
                  MAP_CONFIG_3D.center[1],
                  MAP_CONFIG_3D.defaultAltitude,
                ),
                orientation: {
                  heading: 0,
                  pitch: Cesium.Math.toRadians(MAP_CONFIG_3D.defaultPitch),
                  roll: 0,
                },
              });
            }
          } catch (e) {
            console.warn('HMR 카메라 reset 실패:', e);
          }

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
          bindEventHandlers(viewer, Cesium);
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
              bindEventHandlers(v, C);
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

          // 지적도 WMS (공식 패턴: vw.source.TileWMS)
          try {
            const wmsLayer = new vw.Layers();
            const wmsSource = new vw.source.TileWMS();
            wmsSource.setParams('tilesize=256');
            wmsSource.setLayers('lp_pa_cbnd_bubun,lp_pa_cbnd_bonbun');
            wmsSource.setStyles('lp_pa_cbnd_bubun_line,lp_pa_cbnd_bonbun_line');
            wmsSource.setFormat('image/png');
            wmsSource.setUrl(
              `https://api.vworld.kr/req/wms?Key=${apiKeyRef.current}&`,
            );
            const wmsTile = new vw.layer.Tile(wmsSource);
            wmsLayer.add(wmsTile);
          } catch (e) {
            console.warn('WMS 지적도 레이어 추가 실패:', e);
          }

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

  const SETBACK_DS_NAME = 'setback-lines';

  const SETBACK_COLORS: Record<string, { stroke: string; fill: string; width: number }> = {
    buildable_area:           { stroke: '#22c55e', fill: 'rgba(34,197,94,0.12)', width: 4 },
    north_setback:            { stroke: '#ef4444', fill: 'rgba(239,68,68,0.08)', width: 3 },
    adjacent_setback:         { stroke: '#f97316', fill: 'rgba(249,115,22,0.08)', width: 3 },
    road_setback:             { stroke: '#3b82f6', fill: 'rgba(59,130,246,0.08)', width: 3 },
    building_designation_line:{ stroke: '#a855f7', fill: 'rgba(168,85,247,0.08)', width: 3 },
    corner_cutoff:            { stroke: '#eab308', fill: 'rgba(234,179,8,0.08)', width: 2 },
  };

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
