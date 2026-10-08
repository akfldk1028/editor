import type { ParcelLook } from '../layers/parcelOutline'

/** [longitude, latitude] in WGS84. */
export type LngLat = readonly [number, number]

export interface MapView {
  center: LngLat
  zoom: number
}

export interface MapLayers {
  /** 지적편집도: parcel boundaries with zoning, in the provider's own colours. */
  cadastral: boolean
}

export type MapEngineKind = 'naver' | 'openlayers'

/** The parcels to draw: each with the look's fill and outline, plus the merged boundary when there are several. */
export interface ParcelSet {
  geometries: readonly object[]
  outline: object | null
  look: ParcelLook
}

/** A click on the map: where, at which pixel of the map element, and whether Shift was held. */
export interface MapPointer {
  at: LngLat
  pixel: readonly [number, number]
  shift: boolean
}

/**
 * A 2D site map. The provider draws its base map and cadastral layer in its
 * own colours; the engine only adds our overlays (parcels, hover preview,
 * lot chips, search marker) and the cursor.
 */
export interface MapEngine {
  readonly kind: MapEngineKind
  /** Resolves once the map is drawn; rejects when the provider refuses (e.g. authentication). */
  mount(element: HTMLElement, view: MapView, layers: MapLayers): Promise<void>
  setCenter(center: LngLat, zoom?: number): void
  /** Draws the parcels (GeoJSON in WGS84), replacing the last set, and fits the view to them unless `fit` is false. */
  showParcels(parcels: ParcelSet, fit?: boolean): void
  /** The faint hover preview outline; null clears it. */
  setHover(geojson: object | null): void
  /** Small 지번 chips over the selected parcels. */
  setLabels(labels: readonly { at: LngLat; text: string }[]): void
  setMarker(position: LngLat | null): void
  setLayers(layers: MapLayers): void
  zoomBy(delta: number): void
  /** Redraws at the element's current size, keeping the centre (also called by the engine's own size observer). */
  resize(): void
  getZoom(): number
  /** Cursor: pointer over the map, grabbing while dragging, progress while busy. */
  setBusy(busy: boolean): void
  /** A single click on the map (not a drag); null stops listening. */
  onClick(handler: ((event: MapPointer) => void) | null): void
  /** The pointer's position while it moves over the map (not dragging); null when it leaves. */
  onHover(handler: ((at: LngLat | null) => void) | null): void
  destroy(): void
}
