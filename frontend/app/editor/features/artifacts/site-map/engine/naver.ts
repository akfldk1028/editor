import { hoverOutline, mergedOutline, parcelBounds, parcelOutline, parcelRings, parcelStyle, selectionFill } from '../layers/parcelOutline'
import { lotChipHtml } from '../layers/lotChip'
import { searchMarker, searchMarkerHtml } from '../layers/searchMarker'
import { mapCursor } from './cursor'
import { observeSize, whenSized } from './size'
import type { LngLat, MapEngine, MapLayers, MapPointer, MapView, ParcelSet } from './types'

/* Just the parts of Naver Maps JS v3 used here. */
interface NaverLatLng { lat(): number; lng(): number }
interface NaverOverlay { setMap(map: NaverMap | null): void }
interface NaverMarker extends NaverOverlay { setPosition(position: NaverLatLng): void; setIcon(icon: unknown): void }
interface NaverPolygon extends NaverOverlay { setPaths(paths: NaverLatLng[][]): void; setOptions(options: Record<string, unknown>): void }
interface NaverPointerEvent { coord: NaverLatLng; offset?: { x: number; y: number }; pointerEvent?: MouseEvent; originalEvent?: MouseEvent }
interface NaverMap {
  setCenter(center: NaverLatLng): void
  setZoom(zoom: number, effect?: boolean): void
  getZoom(): number
  getCenter(): NaverLatLng
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
  Polygon: new (options: Record<string, unknown>) => NaverPolygon
  Marker: new (options: Record<string, unknown>) => NaverMarker
  Event: {
    once(target: unknown, name: string, listener: () => void): unknown
    addListener(target: unknown, name: string, listener: (event: NaverPointerEvent) => void): unknown
    removeListener(listener: unknown): void
  }
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
  let container: HTMLElement | null = null
  // Overlays are pooled: a redraw updates existing polygons/markers and only adds or hides the difference.
  const parcels: NaverPolygon[] = []
  const merged: NaverPolygon[] = []
  const hover: NaverPolygon[] = []
  const labels: NaverMarker[] = []
  let marker: NaverMarker | null = null
  let onAuthFailure: (() => void) | null = null
  let stopObserving: (() => void) | null = null
  let clickListener: unknown = null
  let cursor: ReturnType<typeof mapCursor> | null = null
  let dragListeners: unknown[] = []
  let hoverListeners: unknown[] = []
  const latLng = ([lng, lat]: LngLat) => new maps!.LatLng(lat, lng)
  const clear = (overlays: NaverOverlay[]) => { for (const overlay of overlays) overlay.setMap(null) }
  function syncPolygons(pool: NaverPolygon[], geometries: readonly object[], options: Record<string, unknown>) {
    const rings = geometries.flatMap((geometry) => parcelRings(geometry))
    rings.forEach((ring, index) => {
      const paths = [ring.map(latLng)]
      const existing = pool[index]
      if (existing) {
        existing.setOptions(options)
        existing.setPaths(paths)
        existing.setMap(map)
      } else {
        pool.push(new maps!.Polygon({ map, paths, clickable: false, ...options }))
      }
    })
    for (const unused of pool.slice(rings.length)) unused.setMap(null)
  }

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
        // A click picks a parcel at once, so double-click zoom is off (wheel and the +/- buttons zoom).
        disableDoubleClickZoom: true,
        scaleControl: true,
        // Status chips sit top-left and the zoom controls top-right.
        scaleControlOptions: { position: maps.Position.BOTTOM_LEFT },
        logoControlOptions: { position: maps.Position.BOTTOM_RIGHT },
      })
      map = instance
      // Parcels are picked by clicking: a pointer over the map, grabbing while dragging.
      cursor = mapCursor(element)
      dragListeners = [maps.Event.addListener(instance, 'dragstart', () => cursor?.dragging(true)),
        maps.Event.addListener(instance, 'dragend', () => cursor?.dragging(false))]
      container = element
      stopObserving = observeSize(element, () => this.resize())
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

    showParcels({ geometries, outline, look }: ParcelSet, fit = true) {
      if (!maps || !map) return
      const style = parcelStyle(look)
      syncPolygons(parcels, geometries, {
        strokeColor: parcelOutline.color,
        strokeWeight: style.width,
        strokeStyle: style.dashed ? 'shortdash' : 'solid',
        fillColor: selectionFill.color,
        fillOpacity: style.fillOpacity,
      })
      syncPolygons(merged, outline ? [outline] : [], {
        strokeColor: parcelOutline.color, strokeWeight: mergedOutline.width, strokeStyle: 'solid', fillOpacity: 0,
      })
      const bounds = parcelBounds(geometries.flatMap(parcelRings))
      if (!bounds || !fit) return
      const [west, south, east, north] = bounds
      map.fitBounds(new maps.LatLngBounds(latLng([west, south]), latLng([east, north])), { top: 96, right: 64, bottom: 64, left: 64 })
      if (map.getZoom() > 18) map.setZoom(18)
    },

    setHover(geojson: object | null) {
      if (!maps || !map) return
      syncPolygons(hover, geojson ? [geojson] : [], {
        strokeColor: hoverOutline.color, strokeWeight: hoverOutline.width, strokeOpacity: hoverOutline.opacity, fillOpacity: 0,
      })
    },

    setLabels(next) {
      if (!maps || !map) return
      next.forEach(({ at, text }, index) => {
        const icon = { content: lotChipHtml(text), anchor: new maps!.Point(0, 0) }
        const existing = labels[index]
        if (existing) {
          existing.setIcon(icon)
          existing.setPosition(latLng(at))
          existing.setMap(map)
        } else {
          labels.push(new maps!.Marker({ map, position: latLng(at), clickable: false, icon }))
        }
      })
      clear(labels.slice(next.length))
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

    resize() {
      if (!maps || !map || !container) return
      const { width, height } = container.getBoundingClientRect()
      if (!width || !height) return
      // setSize anchors the top-left corner; put the centre back so the view stays where it was.
      const center = map.getCenter()
      map.setSize(new maps.Size(width, height))
      map.setCenter(center)
    },

    getZoom() {
      return map?.getZoom() ?? 0
    },

    setBusy(busy: boolean) {
      cursor?.busy(busy)
    },

    onClick(handler: ((event: MapPointer) => void) | null) {
      if (!maps || !map) return
      if (clickListener) maps.Event.removeListener(clickListener)
      clickListener = handler ? maps.Event.addListener(map, 'click', (event) => handler({
        at: [event.coord.lng(), event.coord.lat()],
        pixel: [event.offset?.x ?? 0, event.offset?.y ?? 0],
        shift: Boolean((event.pointerEvent ?? event.originalEvent)?.shiftKey),
      })) : null
    },

    onHover(handler: ((at: LngLat | null) => void) | null) {
      if (!maps || !map) return
      for (const listener of hoverListeners) maps.Event.removeListener(listener)
      hoverListeners = handler ? [
        maps.Event.addListener(map, 'mousemove', (event) => handler([event.coord.lng(), event.coord.lat()])),
        maps.Event.addListener(map, 'mouseout', () => handler(null)),
        maps.Event.addListener(map, 'dragstart', () => handler(null)),
      ] : []
    },

    destroy() {
      if (onAuthFailure) authListeners.delete(onAuthFailure)
      if (clickListener) maps?.Event.removeListener(clickListener)
      for (const listener of [...hoverListeners, ...dragListeners]) maps?.Event.removeListener(listener)
      clickListener = null
      dragListeners = []
      hoverListeners = []
      stopObserving?.()
      clear([...parcels, ...merged, ...hover, ...labels])
      marker?.setMap(null)
      cadastral?.setMap(null)
      map?.destroy()
      map = null
    },
  }
}
