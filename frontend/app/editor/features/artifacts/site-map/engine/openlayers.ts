import 'ol/ol.css'

import { defaults as defaultControls } from 'ol/control/defaults'
import Feature from 'ol/Feature'
import GeoJSON from 'ol/format/GeoJSON'
import Point from 'ol/geom/Point'
import TileLayer from 'ol/layer/Tile'
import VectorLayer from 'ol/layer/Vector'
import OlMap from 'ol/Map'
import { fromLonLat } from 'ol/proj'
import TileWMS from 'ol/source/TileWMS'
import VectorSource from 'ol/source/Vector'
import XYZ from 'ol/source/XYZ'
import { Circle, Fill, Stroke, Style } from 'ol/style'
import View from 'ol/View'

import { MAP_CONFIG } from '../../../land-map/lib/constants'
import { parcelOutline } from '../layers/parcelOutline'
import { searchMarker } from '../layers/searchMarker'
import { observeSize, whenSized } from './size'
import type { LngLat, MapEngine, MapLayers, MapView } from './types'

const VWORLD_WMS = 'https://api.vworld.kr/req/wms'
/** 용도지역 (zoning) — only reachable with the browser key; the backend WMS proxy serves cadastral layers only. */
const ZONING_LAYER = 'lt_c_uq111'

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

/**
 * Temporary engine until Naver keys are everywhere: Vworld base map (through
 * the backend tile proxy), cadastral boundaries (backend WMS proxy) and zoning
 * (Vworld WMS), all drawn exactly as Vworld renders them.
 */
export function createOpenLayersEngine(): MapEngine {
  let map: OlMap | null = null
  const outlineSource = new VectorSource()
  const markerSource = new VectorSource()
  const cadastralLayers: TileLayer[] = []
  let stopObserving: (() => void) | null = null

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

      const outline = new VectorLayer({
        source: outlineSource,
        style: new Style({
          stroke: new Stroke({ color: parcelOutline.color, width: parcelOutline.width, lineDash: [...parcelOutline.dash] }),
        }),
        zIndex: 10,
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
        zIndex: 11,
      })

      await whenSized(element)
      map = new OlMap({
        target: element,
        layers: [base, ...cadastralLayers, outline, marker],
        controls: defaultControls({ zoom: false, rotate: false, attributionOptions: { collapsible: false } }),
        view: new View({
          center: fromLonLat([...view.center]),
          zoom: view.zoom,
          maxZoom: MAP_CONFIG.maxZoom,
          minZoom: MAP_CONFIG.minZoom,
        }),
      })
      const instance = map
      stopObserving = observeSize(element, () => instance.updateSize())
    },

    setCenter(center: LngLat, zoom?: number) {
      map?.getView().animate({ center: fromLonLat([...center]), zoom, duration: MAP_CONFIG.flyDuration })
    },

    fitParcel(geojson: object) {
      outlineSource.clear()
      outlineSource.addFeatures(new GeoJSON().readFeatures(geojson, { dataProjection: 'EPSG:4326', featureProjection: 'EPSG:3857' }))
      const extent = outlineSource.getExtent()
      if (map && extent?.every(Number.isFinite)) {
        map.getView().fit(extent, { padding: [96, 64, 64, 64], maxZoom: 18, duration: MAP_CONFIG.flyDuration })
      }
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

    destroy() {
      stopObserving?.()
      map?.setTarget(undefined)
      map = null
    },
  }
}
