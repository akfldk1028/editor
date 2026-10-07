import 'ol/ol.css'

import { defaults as defaultControls } from 'ol/control/defaults'
import { defaults as defaultInteractions } from 'ol/interaction/defaults'
import Feature from 'ol/Feature'
import GeoJSON from 'ol/format/GeoJSON'
import Point from 'ol/geom/Point'
import TileLayer from 'ol/layer/Tile'
import VectorLayer from 'ol/layer/Vector'
import OlMap from 'ol/Map'
import type MapBrowserEvent from 'ol/MapBrowserEvent'
import Overlay from 'ol/Overlay'
import { fromLonLat, toLonLat } from 'ol/proj'
import TileWMS from 'ol/source/TileWMS'
import VectorSource from 'ol/source/Vector'
import XYZ from 'ol/source/XYZ'
import { Circle, Fill, Stroke, Style } from 'ol/style'
import View from 'ol/View'

import { MAP_CONFIG } from '../../../land-map/lib/constants'
import { lotChipElement } from '../layers/lotChip'
import { hoverOutline, mergedOutline, parcelOutline, parcelStyle, rgba, selectionFill, type ParcelLook } from '../layers/parcelOutline'
import { searchMarker } from '../layers/searchMarker'
import { mapCursor } from './cursor'
import { observeSize, whenSized } from './size'
import type { LngLat, MapEngine, MapLayers, MapPointer, MapView, ParcelSet } from './types'

const VWORLD_WMS = 'https://api.vworld.kr/req/wms'
/** 용도지역 (zoning) — only reachable with the browser key; the backend WMS proxy serves cadastral layers only. */
const ZONING_LAYER = 'lt_c_uq111'
const geojson = new GeoJSON()
const read = (value: object) => geojson.readFeatures(value, { dataProjection: 'EPSG:4326', featureProjection: 'EPSG:3857' })

/** The browser Vworld key, or null when the backend has none configured. */
async function browserKey(): Promise<string | null> {
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/map-config`)
    if (!response.ok) return null
    const body = (await response.json()) as { api_key?: string }
    return body.api_key || null
  } catch {
    return null
  }
}

function lookStyle(look: ParcelLook) {
  const style = parcelStyle(look)
  return new Style({
    stroke: new Stroke({ color: parcelOutline.color, width: style.width, lineDash: style.dashed ? [...parcelOutline.dash] : undefined }),
    fill: style.fillOpacity ? new Fill({ color: rgba(selectionFill.color, style.fillOpacity) }) : undefined,
  })
}

/**
 * Temporary engine until Naver keys are everywhere: Vworld base map (through
 * the backend tile proxy), cadastral boundaries (backend WMS proxy) and zoning
 * (Vworld WMS), all drawn exactly as Vworld renders them.
 */
export function createOpenLayersEngine(): MapEngine {
  let map: OlMap | null = null
  const parcelSource = new VectorSource()
  const mergedSource = new VectorSource()
  const hoverSource = new VectorSource()
  const markerSource = new VectorSource()
  const parcelLayer = new VectorLayer({ source: parcelSource, style: lookStyle('site'), zIndex: 10 })
  const cadastralLayers: TileLayer[] = []
  let labels: Overlay[] = []
  let cursor: ReturnType<typeof mapCursor> | null = null
  let stopObserving: (() => void) | null = null
  let clickListener: ((event: MapBrowserEvent) => void) | null = null
  let moveListener: ((event: MapBrowserEvent) => void) | null = null
  let leaveListener: (() => void) | null = null

  return {
    kind: 'openlayers',

    async mount(element: HTMLElement, view: MapView, layers: MapLayers) {
      const base = new TileLayer({
        source: new XYZ({ url: MAP_CONFIG.tileUrl, maxZoom: MAP_CONFIG.maxZoom, attributions: '© Vworld' }),
      })
      const cadastral = new TileLayer({
        source: new TileWMS({
          url: MAP_CONFIG.wmsUrl,
          params: { LAYERS: MAP_CONFIG.wmsLayers, FORMAT: 'image/png', TRANSPARENT: 'true', VERSION: '1.3.0', CRS: 'EPSG:3857' },
          serverType: 'mapserver',
        }),
        minZoom: MAP_CONFIG.cadastralMinZoom,
      })
      cadastralLayers.push(cadastral)
      const key = await browserKey()
      if (key) {
        cadastralLayers.unshift(new TileLayer({
          source: new TileWMS({
            url: VWORLD_WMS,
            params: { LAYERS: ZONING_LAYER, STYLES: ZONING_LAYER, FORMAT: 'image/png', TRANSPARENT: 'true', VERSION: '1.3.0', KEY: key },
          }),
          minZoom: MAP_CONFIG.cadastralMinZoom,
        }))
      }
      for (const layer of cadastralLayers) layer.setVisible(layers.cadastral)

      const merged = new VectorLayer({
        source: mergedSource,
        style: new Style({ stroke: new Stroke({ color: parcelOutline.color, width: mergedOutline.width }) }),
        zIndex: 11,
      })
      const hover = new VectorLayer({
        source: hoverSource,
        style: new Style({ stroke: new Stroke({ color: rgba(hoverOutline.color, hoverOutline.opacity), width: hoverOutline.width }) }),
        zIndex: 9,
      })
      const marker = new VectorLayer({
        source: markerSource,
        style: new Style({
          image: new Circle({
            radius: searchMarker.radius,
            fill: new Fill({ color: searchMarker.color }),
            stroke: new Stroke({ color: searchMarker.ring, width: searchMarker.ringWidth }),
          }),
        }),
        zIndex: 12,
      })

      await whenSized(element)
      map = new OlMap({
        target: element,
        layers: [base, ...cadastralLayers, hover, parcelLayer, merged, marker],
        controls: defaultControls({ zoom: false, rotate: false, attributionOptions: { collapsible: false } }),
        // A click picks a parcel at once, so double-click zoom is off (wheel and the +/- buttons zoom).
        interactions: defaultInteractions({ doubleClickZoom: false }),
        view: new View({
          center: fromLonLat([...view.center]),
          zoom: view.zoom,
          maxZoom: MAP_CONFIG.maxZoom,
          minZoom: MAP_CONFIG.minZoom,
        }),
      })
      const instance = map
      cursor = mapCursor(element)
      instance.on('pointerdrag', () => cursor?.dragging(true))
      instance.on('moveend', () => cursor?.dragging(false))
      stopObserving = observeSize(element, () => instance.updateSize())
    },

    setCenter(center: LngLat, zoom?: number) {
      map?.getView().animate({ center: fromLonLat([...center]), zoom, duration: MAP_CONFIG.flyDuration })
    },

    showParcels({ geometries, outline, look }: ParcelSet, fit = true) {
      parcelSource.clear()
      mergedSource.clear()
      parcelLayer.setStyle(lookStyle(look))
      for (const geometry of geometries) parcelSource.addFeatures(read(geometry))
      if (outline) mergedSource.addFeatures(read(outline))
      const extent = parcelSource.getExtent()
      if (fit && map && extent?.every(Number.isFinite)) {
        map.getView().fit(extent, { padding: [96, 64, 64, 64], maxZoom: 18, duration: MAP_CONFIG.flyDuration })
      }
    },

    setHover(value: object | null) {
      hoverSource.clear()
      if (value) hoverSource.addFeatures(read(value))
    },

    setLabels(next) {
      for (const overlay of labels) map?.removeOverlay(overlay)
      labels = next.map(({ at, text }) => new Overlay({
        element: lotChipElement(text), position: fromLonLat([...at]), positioning: 'top-left', stopEvent: false,
      }))
      for (const overlay of labels) map?.addOverlay(overlay)
    },

    setMarker(position: LngLat | null) {
      markerSource.clear()
      if (position) markerSource.addFeature(new Feature(new Point(fromLonLat([...position]))))
    },

    setLayers(layers: MapLayers) {
      for (const layer of cadastralLayers) layer.setVisible(layers.cadastral)
    },

    zoomBy(delta: number) {
      const view = map?.getView()
      const zoom = view?.getZoom()
      if (view && zoom !== undefined) view.animate({ zoom: zoom + delta, duration: 200 })
    },

    resize() {
      map?.updateSize()
    },

    getZoom() {
      return map?.getView().getZoom() ?? 0
    },

    setBusy(busy: boolean) {
      cursor?.busy(busy)
    },

    onClick(handler: ((event: MapPointer) => void) | null) {
      if (!map) return
      if (clickListener) map.un('click', clickListener)
      clickListener = handler ? (event) => {
        const [lng, lat] = toLonLat(event.coordinate)
        const original = event.originalEvent as MouseEvent
        handler({ at: [lng!, lat!], pixel: [event.pixel[0]!, event.pixel[1]!], shift: Boolean(original.shiftKey) })
      } : null
      if (clickListener) map.on('click', clickListener)
    },

    onHover(handler: ((at: LngLat | null) => void) | null) {
      if (!map) return
      if (moveListener) map.un('pointermove', moveListener)
      if (leaveListener) map.getViewport().removeEventListener('pointerleave', leaveListener)
      // The cursor follows every move; the handler hears only moves that are not drags.
      moveListener = (event) => {
        if (!handler) return
        if (event.dragging) return handler(null)
        const [lng, lat] = toLonLat(event.coordinate)
        handler([lng!, lat!])
      }
      leaveListener = handler ? () => handler(null) : null
      map.on('pointermove', moveListener)
      if (leaveListener) map.getViewport().addEventListener('pointerleave', leaveListener)
    },

    destroy() {
      stopObserving?.()
      if (clickListener) map?.un('click', clickListener)
      if (moveListener) map?.un('pointermove', moveListener)
      if (leaveListener) map?.getViewport().removeEventListener('pointerleave', leaveListener)
      clickListener = moveListener = null
      leaveListener = null
      map?.setTarget(undefined)
      map = null
    },
  }
}
