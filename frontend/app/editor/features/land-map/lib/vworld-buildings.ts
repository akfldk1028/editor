export type VworldBuildingMode = 'lod1' | 'textured'

type Layer = { show(): void; hide(): void }
type MapLayers = { getLayerElement?(id: string): Layer | undefined }

const BUILDINGS = ['facility_build', 'facility_build_lod1', 'facility_build_lod2', 'facility_build_lod3', 'facility_build_all', 'facility_build_gw']

export function selectBuildingLayer(map: MapLayers | null, mode: VworldBuildingMode) {
  const layerId = mode === 'lod1' ? 'facility_build_lod1' : 'facility_build'
  const selected = map?.getLayerElement?.(layerId)
  if (!selected) return { available: false, layerId }
  for (const id of BUILDINGS) {
    const layer = map?.getLayerElement?.(id)
    if (!layer) continue
    if (id === layerId) layer.show()
    else layer.hide()
  }
  return { available: true, layerId }
}

export function setBuildingLayersVisible(map: MapLayers | null, visible: boolean, mode: VworldBuildingMode) {
  if (visible) return selectBuildingLayer(map, mode)
  for (const id of BUILDINGS) map?.getLayerElement?.(id)?.hide()
  return { available: true, layerId: null }
}
