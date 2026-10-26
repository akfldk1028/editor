import { decodeBuildings, type BuildingTile } from './building-geometry'
import Pbf from 'pbf'
import { VectorTile } from '@mapbox/vector-tile'
import { prepareBuildingMeshes } from './building-mesh'

const active = new Map<number, AbortController>()
self.onmessage = async (event: MessageEvent<{ id: number; data: ArrayBuffer; tile: BuildingTile } | { cancel: number }>) => {
  if ('cancel' in event.data) { active.get(event.data.cancel)?.abort(); return }
  const { id, data, tile } = event.data
  const controller = new AbortController()
  active.set(id, controller)
  try {
    controller.signal.throwIfAborted()
    const features = await decodeBuildings(new Uint8Array(data), tile, Pbf, VectorTile, controller.signal)
    const transfers = await prepareBuildingMeshes(features, controller.signal)
    self.postMessage({ id, features }, { transfer: transfers })
  } catch (error) {
    self.postMessage({ id, error: error instanceof Error ? error.message : String(error) })
  } finally {
    active.delete(id)
  }
}
