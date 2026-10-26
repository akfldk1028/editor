import { join } from 'node:path'
import { preparedMapFile } from './prepared-map-files'

export function mapDataRoot(kind: string): string | undefined {
  const root = process.env.DATA_ROOT || 'C:/Data/25_ACE'
  if (kind === 'releases') return join(root, 'releases')
  if (kind === 'buildings') return process.env.SCENE_TILES_DIR || join(root, 'tiles/buildings')
  if (kind === 'world-buildings') return process.env.WORLD_BUILDINGS_ASSET_OUTPUT || join(root, kind)
  if (kind === 'world-terrain') return process.env.WORLD_TERRAIN_OUTPUT || join(root, kind)
  if (kind === 'world-ground') return process.env.WORLD_GROUND_OUTPUT || join(root, kind)
  return undefined
}

export async function preparedMapAsset(parts: string[], publicRoot: string, head = false, signal?: AbortSignal, range?: string) {
  const root = mapDataRoot(parts[0] ?? '')
  if (root) {
    const response = await preparedMapFile(parts, publicRoot, head, signal, range, root)
    if (response.status !== 404) return response
  }
  return preparedMapFile(parts, publicRoot, head, signal, range)
}
