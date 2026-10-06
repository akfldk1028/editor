/**
 * Vworld 3D 장면 헬퍼 — 지오메트리/카메라/하이라이트 상수/이벤트 바인딩
 * (use-vworld-3d.ts 에서 분리)
 */

import { MAP_CONFIG_3D } from './constants'

/* eslint-disable @typescript-eslint/no-explicit-any */

type PointRef = { current: ((lng: number, lat: number) => void) | undefined }

export function applyDiagramImageryStyle(layer: any) {
  if (!layer) return
  try {
    layer.saturation = 0.0
    layer.brightness = 1.18
    layer.contrast = 0.72
    layer.gamma = 1.08
    layer.alpha = 0.42
  } catch {
    // Cesium imagery layer styling is best-effort; VWorld still works without it.
  }
}

function ringArea(ring: number[][] | null | undefined): number {
  if (!ring || ring.length < 3) return 0
  let total = 0
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]
    const b = ring[(i + 1) % ring.length]
    if (!a || !b || a[0] == null || a[1] == null || b[0] == null || b[1] == null) return 0
    total += a[0] * b[1] - b[0] * a[1]
  }
  return Math.abs(total) / 2
}

function largestPolygonCoordinates(
  polygons: number[][][][] | null | undefined,
): number[][][] | null {
  if (!Array.isArray(polygons) || polygons.length === 0) return null
  return polygons.reduce<number[][][] | null>((best, polygon) => {
    if (!Array.isArray(polygon) || !polygon[0]) return best
    if (!best) return polygon
    return ringArea(polygon[0]) > ringArea(best[0]) ? polygon : best
  }, null)
}

export function extractGeoJsonRing(geojson: any): number[][] | undefined {
  const geo = geojson?.type === 'Feature' ? geojson.geometry : geojson
  if (geo?.type === 'Polygon') return geo.coordinates?.[0]
  if (geo?.type === 'MultiPolygon')
    return largestPolygonCoordinates(geo.coordinates)?.[0] || undefined
  return undefined
}

// ---------------------------------------------------------------------------
// Zoom → altitude 변환 (3D 틸트 카메라용)
// ---------------------------------------------------------------------------

export function zoomToAltitude(zoom: number): number {
  // zoom 15→6000m, 16→3000m, 17→1500m, 18→750m, 19→375m
  const clamped = Math.min(19, Math.max(10, zoom))
  return Math.max(150, 6000 / Math.pow(2, clamped - 15))
}

// ---------------------------------------------------------------------------
// Parcel highlight ID (map.removeObjectById 용)
// ---------------------------------------------------------------------------

export const PARCEL_HIGHLIGHT_ID = 'selected-parcel'
export const PARCEL_HOVER_ID = 'hovered-parcel'

// ---------------------------------------------------------------------------
// 규제선 렌더링 (Cesium GeoJsonDataSource, ground clamped)
// ---------------------------------------------------------------------------

export const SETBACK_DS_NAME = 'setback-lines'

export const SETBACK_COLORS: Record<string, { stroke: string; fill: string; width: number }> = {
  buildable_area: { stroke: '#22c55e', fill: 'rgba(34,197,94,0.12)', width: 4 },
  north_setback: { stroke: '#ef4444', fill: 'rgba(239,68,68,0.08)', width: 3 },
  adjacent_setback: { stroke: '#f97316', fill: 'rgba(249,115,22,0.08)', width: 3 },
  road_setback: { stroke: '#3b82f6', fill: 'rgba(59,130,246,0.08)', width: 3 },
  building_designation_line: { stroke: '#a855f7', fill: 'rgba(168,85,247,0.08)', width: 3 },
  corner_cutoff: { stroke: '#eab308', fill: 'rgba(234,179,8,0.08)', width: 2 },
}

// 이벤트 핸들러 바인딩 — viewer + Cesium 확보 후 호출
export function bindEventHandlers(
  viewer: any,
  Cesium: any,
  onClickRef: PointRef,
  onHoverRef: PointRef,
) {
  // LEFT_CLICK → onClick
  viewer.screenSpaceEventHandler.setInputAction(function (movement: any) {
    const ray = viewer.camera.getPickRay(movement.position)
    if (!ray) return
    const cartesian = viewer.scene.globe.pick(ray, viewer.scene)
    if (!cartesian) return
    const carto = Cesium.Cartographic.fromCartesian(cartesian)
    onClickRef.current?.(
      Cesium.Math.toDegrees(carto.longitude),
      Cesium.Math.toDegrees(carto.latitude),
    )
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK)

  // MOUSE_MOVE → onHover (좌표 추출만, 디바운스는 소비자 책임)
  viewer.screenSpaceEventHandler.setInputAction(function (movement: any) {
    if (!onHoverRef.current) return
    const ray = viewer.camera.getPickRay(movement.endPosition)
    if (!ray) return
    const cartesian = viewer.scene.globe.pick(ray, viewer.scene)
    if (!cartesian) return
    const carto = Cesium.Cartographic.fromCartesian(cartesian)
    onHoverRef.current(
      Cesium.Math.toDegrees(carto.longitude),
      Cesium.Math.toDegrees(carto.latitude),
    )
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE)
}

// HMR 경로 — SDK 싱글턴 viewer 재사용 시 imagery/카메라 복구
export function recoverHmrViewer(existingViewer: any, Cesium: any, apiKey: string) {
  // 2026-05-11 — HMR 시 imagery layer가 사라지는 케이스 fix.
  try {
    if (existingViewer.imageryLayers.length === 0) {
      const layer = existingViewer.imageryLayers.addImageryProvider(
        new Cesium.UrlTemplateImageryProvider({
          url: `https://api.vworld.kr/req/wmts/1.0.0/${apiKey}/Base/{z}/{y}/{x}.png`,
          maximumLevel: 19,
          credit: new Cesium.Credit('Vworld'),
        }),
      )
      applyDiagramImageryStyle(layer)
    }
  } catch (e) {
    console.warn('HMR imagery 재추가 실패:', e)
  }

  // 2026-05-11 v2 — HMR 후 카메라가 우주(1700km)에 머물러 검정 화면.
  // 카메라 height > 100km면 한국 default 위치로 강제 reset.
  try {
    const camH = existingViewer.camera.positionCartographic?.height
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
      })
    }
  } catch (e) {
    console.warn('HMR 카메라 reset 실패:', e)
  }
}

export function addCadastralWmsLayer(vw: any, apiKey: string) {
  // 지적도 WMS (공식 패턴: vw.source.TileWMS)
  try {
    const wmsLayer = new vw.Layers()
    const wmsSource = new vw.source.TileWMS()
    wmsSource.setParams('tilesize=256')
    wmsSource.setLayers('lp_pa_cbnd_bubun,lp_pa_cbnd_bonbun')
    wmsSource.setStyles('lp_pa_cbnd_bubun_line,lp_pa_cbnd_bonbun_line')
    wmsSource.setFormat('image/png')
    wmsSource.setUrl(`https://api.vworld.kr/req/wms?Key=${apiKey}&`)
    const wmsTile = new vw.layer.Tile(wmsSource)
    wmsLayer.add(wmsTile)
  } catch (e) {
    console.warn('WMS 지적도 레이어 추가 실패:', e)
  }
}
