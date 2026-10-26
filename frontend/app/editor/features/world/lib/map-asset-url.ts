import { pinnedMapRelease } from './map-release'
export type MapAssetKind = 'buildings' | 'world-buildings' | 'terrain'

export function configuredMapBase(kind: MapAssetKind): string | undefined {
  const override = kind === 'buildings' ? process.env.NEXT_PUBLIC_BUILDINGS_BASE_URL
    : kind === 'world-buildings' ? process.env.NEXT_PUBLIC_WORLD_BUILDINGS_BASE_URL : process.env.NEXT_PUBLIC_TERRAIN_BASE_URL
  const value = override || pinnedMapRelease()?.assetBases?.[kind]
  if (!value?.trim()) return undefined
  const url = new URL(value)
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Invalid public map asset base URL')
  return value.trim().replace(/\/+$/, '')
}

export function mapAssetUrl(kind: MapAssetKind, path: string): string {
  if (/^https?:\/\//.test(path)) return path
  const root = kind === 'terrain' ? 'world-terrain' : kind
  const relative = path.replace(new RegExp(`^(?:/api/map-data)?/${root}/`), '').replace(/^\/+/, '')
  if (!relative || relative.split('/').some(part => part === '..' || part === '.')) throw new Error('Invalid map asset path')
  const remote = configuredMapBase(kind)
  return remote ? `${remote}/${relative}` : `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/map-data/${root}/${relative}`
}
