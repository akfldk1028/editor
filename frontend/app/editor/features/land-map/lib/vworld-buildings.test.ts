import { describe, expect, test } from 'bun:test'
import { selectBuildingLayer, setBuildingLayersVisible } from './vworld-buildings'

function mockMap(ids: string[]) {
  const layers = new Map(ids.map(id => [id, { visible: false, show() { this.visible = true }, hide() { this.visible = false } }]))
  return { layers, getLayerElement: (id: string) => layers.get(id) }
}

describe('VWorld building representations', () => {
  test('selects only the requested building layer, preserving unrelated layers', () => {
    const map = mockMap(['facility_build', 'facility_build_lod1', 'facility_build_lod2', 'facility_build_all', 'poi_base'])
    map.layers.get('poi_base')!.visible = true
    expect(selectBuildingLayer(map, 'lod1').available).toBe(true)
    expect(map.layers.get('facility_build_lod1')!.visible).toBe(true)
    expect(map.layers.get('facility_build')!.visible).toBe(false)
    expect(selectBuildingLayer(map, 'textured').available).toBe(true)
    expect(map.layers.get('facility_build')!.visible).toBe(true)
    expect(map.layers.get('facility_build_lod1')!.visible).toBe(false)
    expect(map.layers.get('poi_base')!.visible).toBe(true)
  })

  test('a missing representation reports unavailable without lying or hiding the current model', () => {
    const map = mockMap(['facility_build'])
    map.layers.get('facility_build')!.visible = true
    expect(selectBuildingLayer(map, 'lod1').available).toBe(false)
    expect(map.layers.get('facility_build')!.visible).toBe(true)
  })

  test('visibility uses building layer ownership, never every Cesium tileset', () => {
    const map = mockMap(['facility_build', 'facility_build_lod1', 'poi_base'])
    for (const layer of map.layers.values()) layer.visible = true
    setBuildingLayersVisible(map, false, 'textured')
    expect(map.layers.get('facility_build')!.visible).toBe(false)
    expect(map.layers.get('facility_build_lod1')!.visible).toBe(false)
    expect(map.layers.get('poi_base')!.visible).toBe(true)
    setBuildingLayersVisible(map, true, 'lod1')
    expect(map.layers.get('facility_build_lod1')!.visible).toBe(true)
    expect(map.layers.get('facility_build')!.visible).toBe(false)
  })
})
