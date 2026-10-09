/**
 * Cadastral lines from the same source as the parcel polygons (Vworld 연속지적도 through the backend WMS
 * proxy, EPSG:3857), so the lines under a selected lot and the lot's outline agree by construction. Naver's
 * own 지적편집도 draws re-platted districts (고산 공공주택지구, 2026-10-09) differently from the registry,
 * which made a Vworld outline look rotated against it. The Naver engine lays one image per view (GroundOverlay).
 */
import { MAP_CONFIG } from '../../../../land-map/lib/constants'

const ORIGIN = 20037508.342789244
/** The backend proxy refuses images above 2048 px a side. */
const MAX_PX = 2048

/** WGS84 lon/lat → EPSG:3857 metres. */
export function toMercator(lng: number, lat: number): [number, number] {
  const x = (lng * ORIGIN) / 180
  const y = (Math.log(Math.tan(((90 + lat) * Math.PI) / 360)) * ORIGIN) / Math.PI
  return [x, y]
}

/** The proxy URL for the cadastral image of a lon/lat box at a pixel size (clamped to the proxy's limit). */
export function cadastralImageUrl(west: number, south: number, east: number, north: number, width: number, height: number,
  base: string = MAP_CONFIG.wmsUrl, layers: string = MAP_CONFIG.wmsLayers): string {
  const [minX, minY] = toMercator(west, south)
  const [maxX, maxY] = toMercator(east, north)
  const scale = Math.min(1, MAX_PX / Math.max(width, height))
  const query = new URLSearchParams({
    SERVICE: 'WMS', REQUEST: 'GetMap', VERSION: '1.3.0', CRS: 'EPSG:3857', LAYERS: layers, FORMAT: 'image/png', TRANSPARENT: 'true',
    WIDTH: String(Math.max(1, Math.round(width * scale))), HEIGHT: String(Math.max(1, Math.round(height * scale))),
    BBOX: [minX, minY, maxX, maxY].map((value) => value.toFixed(3)).join(','),
  })
  return `${base}?${query}`
}
