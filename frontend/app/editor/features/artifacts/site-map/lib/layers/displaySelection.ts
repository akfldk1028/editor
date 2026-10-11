import type { LngLat } from '../engine/types'
import { captureCadastralRaster } from './naverRaster'
import { traceSelection, type Pixel } from './rasterSelection'

export interface SelectionProjection {
  toPixel(point: LngLat): Pixel
  toCoordinate(point: Pixel): LngLat
}

export function createDisplaySelection(read = captureCadastralRaster) {
  const cache = new Map<string, { zoom: number; revision: number; ring: LngLat[] }>()
  let raster: ImageData | null = null
  let sourceId: string | null = null
  let revision = 0
  return {
    invalidate() { raster = null },
    capture(element: HTMLElement, zoom: number) {
      const captured = read(element, zoom)
      raster = captured?.raster ?? null
      if (!captured || captured.sourceId !== sourceId) cache.clear()
      sourceId = captured?.sourceId ?? null
      revision++
    },
    ring(source: LngLat[], zoom: number, projection: SelectionProjection): LngLat[] {
      const key = JSON.stringify(source)
      const previous = cache.get(key)
      if (previous && (previous.zoom > zoom || previous.revision === revision)) return previous.ring
      if (!raster) return previous?.ring ?? source
      const contour = traceSelection(raster, source.map(point => projection.toPixel(point)))
      if (!contour) { cache.delete(key); return source }
      const ring = contour.map(point => projection.toCoordinate(point))
      cache.delete(key)
      cache.set(key, { zoom, revision, ring })
      if (cache.size > 100) cache.delete(cache.keys().next().value!)
      return ring
    },
    clear() { raster = null; sourceId = null; cache.clear() },
  }
}
