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

/**
 * A 2D site map. The provider draws its base map and cadastral layer in its
 * own colours; the engine only adds the parcel outline and the search marker.
 */
export interface MapEngine {
  readonly kind: MapEngineKind
  /** Resolves once the map is drawn; rejects when the provider refuses (e.g. authentication). */
  mount(element: HTMLElement, view: MapView, layers: MapLayers): Promise<void>
  setCenter(center: LngLat, zoom?: number): void
  /** Draws the parcel outline (GeoJSON in WGS84) and fits the view to it. */
  fitParcel(geojson: object): void
  setMarker(position: LngLat | null): void
  setLayers(layers: MapLayers): void
  zoomBy(delta: number): void
  destroy(): void
}
