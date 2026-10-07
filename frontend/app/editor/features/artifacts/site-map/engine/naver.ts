import { parcelBounds, parcelOutline, parcelRings } from '../layers/parcelOutline'
import { searchMarker, searchMarkerHtml } from '../layers/searchMarker'
import { observeSize, whenSized } from './size'
import type { LngLat, MapEngine, MapLayers, MapView } from './types'

/* Just the parts of Naver Maps JS v3 used here. */
interface NaverLatLng { lat(): number; lng(): number }
interface NaverOverlay { setMap(map: NaverMap | null): void }
interface NaverMap {
  setCenter(center: NaverLatLng): void
  setZoom(zoom: number, effect?: boolean): void
  getZoom(): number
  morph(center: NaverLatLng, zoom?: number): void
  fitBounds(bounds: unknown, margin?: { top: number; right: number; bottom: number; left: number }): void
  setSize(size: unknown): void
  destroy(): void
}
interface NaverMaps {
  Map: new (element: HTMLElement, options: Record<string, unknown>) => NaverMap
  LatLng: new (lat: number, lng: number) => NaverLatLng
  LatLngBounds: new (southWest: NaverLatLng, northEast: NaverLatLng) => unknown
  Point: new (x: number, y: number) => unknown
  Size: new (width: number, height: number) => unknown
  Position: { BOTTOM_LEFT: number; BOTTOM_RIGHT: number }
  CadastralLayer: new () => NaverOverlay
  Polygon: new (options: Record<string, unknown>) => NaverOverlay
  Marker: new (options: Record<string, unknown>) => NaverOverlay & { setPosition(position: NaverLatLng): void }
  Event: { once(target: unknown, name: string, listener: () => void): unknown }
}
declare global {
  interface Window {
    naver?: { maps?: NaverMaps }
    /** Called by the Naver script when the key is refused for this origin. */
    navermap_authFailure?: () => void
  }
}

const SCRIPT = 'https://oapi.map.naver.com/openapi/v3/maps.js'
let scriptLoad: Promise<NaverMaps> | null = null
const authListeners = new Set<() => void>()

/** Loads Naver Maps JS v3 once per page. */
function loadNaverMaps(keyId: string): Promise<NaverMaps> {
  window.navermap_authFailure = () => authListeners.forEach((listener) => listener())
  if (window.naver?.maps) return Promise.resolve(window.naver.maps)
  scriptLoad ??= new Promise<NaverMaps>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = `${SCRIPT}?ncpKeyId=${encodeURIComponent(keyId)}`
    script.async = true
    script.onload = () => (window.naver?.maps ? resolve(window.naver.maps) : reject(new Error('네이버 지도 스크립트가 비어 있습니다.')))
    script.onerror = () => {
      scriptLoad = null
      script.remove()
      reject(new Error('네이버 지도 스크립트를 불러오지 못했습니다.'))
    }
    document.head.appendChild(script)
  })
  return scriptLoad
}

/** Naver Maps v3 with its 지적편집도 (CadastralLayer), drawn in Naver's own colours. */
export function createNaverEngine(keyId: string): MapEngine {
  let maps: NaverMaps | null = null
  let map: NaverMap | null = null
  let cadastral: NaverOverlay | null = null
  let outline: NaverOverlay[] = []
  let marker: (NaverOverlay & { setPosition(position: NaverLatLng): void }) | null = null
  let onAuthFailure: (() => void) | null = null
  let stopObserving: (() => void) | null = null
  const latLng = ([lng, lat]: LngLat) => new maps!.LatLng(lat, lng)

  return {
    kind: 'naver',

    async mount(element: HTMLElement, view: MapView, layers: MapLayers) {
      maps = await loadNaverMaps(keyId)
      await whenSized(element)
      const instance = new maps.Map(element, {
        center: latLng(view.center),
        zoom: view.zoom,
        zoomControl: false,
        mapDataControl: false,
        scaleControl: true,
        // Status chips sit top-left and the zoom controls top-right.
        scaleControlOptions: { position: maps.Position.BOTTOM_LEFT },
        logoControlOptions: { position: maps.Position.BOTTOM_RIGHT },
      })
      map = instance
      stopObserving = observeSize(element, (width, height) => instance.setSize(new maps!.Size(width, height)))
      cadastral = new maps.CadastralLayer()
      if (layers.cadastral) cadastral.setMap(instance)
      // Authentication failures are reported asynchronously through a global callback.
      await new Promise<void>((resolve, reject) => {
        onAuthFailure = () => reject(new Error('네이버 지도 인증에 실패했습니다 (키 또는 등록 URL).'))
        authListeners.add(onAuthFailure)
        maps!.Event.once(instance, 'init', () => resolve())
        window.setTimeout(resolve, 4000)
      })
    },

    setCenter(center: LngLat, zoom?: number) {
      if (map) map.morph(latLng(center), zoom)
    },

    fitParcel(geojson: object) {
      if (!maps || !map) return
      for (const overlay of outline) overlay.setMap(null)
      const rings = parcelRings(geojson)
      outline = rings.map((ring) => new maps!.Polygon({
        map,
        paths: [ring.map(latLng)],
        strokeColor: parcelOutline.color,
        strokeWeight: parcelOutline.width,
        strokeStyle: 'shortdash',
        fillOpacity: 0,
        clickable: false,
      }))
      const bounds = parcelBounds(rings)
      if (!bounds) return
      const [west, south, east, north] = bounds
      map.fitBounds(new maps.LatLngBounds(latLng([west, south]), latLng([east, north])), { top: 96, right: 64, bottom: 64, left: 64 })
      if (map.getZoom() > 18) map.setZoom(18)
    },

    setMarker(position: LngLat | null) {
      if (!maps || !map) return
      if (!position) {
        marker?.setMap(null)
        marker = null
        return
      }
      const size = (searchMarker.radius + searchMarker.ringWidth) * 2
      marker ??= new maps.Marker({
        map,
        position: latLng(position),
        clickable: false,
        icon: { content: searchMarkerHtml(), anchor: new maps.Point(size / 2, size / 2) },
      })
      marker.setMap(map)
      marker.setPosition(latLng(position))
    },

    setLayers(layers: MapLayers) {
      cadastral?.setMap(layers.cadastral ? map : null)
    },

    zoomBy(delta: number) {
      if (map) map.setZoom(map.getZoom() + delta, true)
    },

    destroy() {
      if (onAuthFailure) authListeners.delete(onAuthFailure)
      stopObserving?.()
      for (const overlay of outline) overlay.setMap(null)
      marker?.setMap(null)
      cadastral?.setMap(null)
      map?.destroy()
      map = null
    },
  }
}
