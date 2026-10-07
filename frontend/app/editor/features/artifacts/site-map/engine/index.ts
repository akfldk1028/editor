import type { MapEngine, MapEngineKind } from './types'

export type { LngLat, MapEngine, MapEngineKind, MapLayers, MapView } from './types'

/**
 * Naver when a key is configured, else the temporary OpenLayers engine; an
 * explicit `?engine=` wins (naver without a key falls back).
 */
export function chooseEngine(requested: string | undefined, naverKeyId: string | undefined): MapEngineKind {
  if (requested === 'openlayers') return 'openlayers'
  return naverKeyId ? 'naver' : 'openlayers'
}

/** Loads only the chosen engine's code. */
export async function createMapEngine(kind: MapEngineKind, naverKeyId: string | undefined): Promise<MapEngine> {
  if (kind === 'naver' && naverKeyId) {
    const { createNaverEngine } = await import('./naver')
    return createNaverEngine(naverKeyId)
  }
  const { createOpenLayersEngine } = await import('./openlayers')
  return createOpenLayersEngine()
}
