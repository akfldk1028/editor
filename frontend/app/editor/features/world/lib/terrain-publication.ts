import { defaultMapReleaseReader } from './map-release'
import { defaultTerrainArchiveReader } from './terrain-archive'
import { createTerrainHeightContract, TERRAIN_HEIGHT_CONTRACT } from './terrain-height-contract'
import { mapAssetUrl } from './map-asset-url'

/** Only an explicitly marked, pinned release changes the legacy terrain policy. */
export function createTerrainPublicationReader(
  releaseReader = defaultMapReleaseReader,
  archive = defaultTerrainArchiveReader,
) {
  let pending: Promise<ReturnType<typeof createTerrainHeightContract> | undefined> | undefined
  return () => pending ??= (async () => {
    const release = await releaseReader()
    if (release?.terrain.heightContract === undefined) return undefined
    if (release.terrain.heightContract !== TERRAIN_HEIGHT_CONTRACT) throw new Error('Invalid terrain height contract')
    const source = await archive.prepare(), pin = release.terrain
    const expectedUrl = /^https?:\/\//.test(pin.url) ? pin.url : mapAssetUrl('terrain', pin.url)
    if (!source || source.url !== expectedUrl || source.archiveSha256 !== pin.sha256 || source.metadata.vrt_sha256 !== pin.vrt_sha256
      || !/^[a-f0-9]{64}$/.test(pin.sha256)) throw new Error('Terrain publication identity mismatch')
    const m = source.metadata
    if (m.schema !== 'ngii-heightmap-v1' || m.grid !== 'Cesium.GeographicTilingScheme' || m.size !== 33
      || m.archiveZoomOffset !== 1) throw new Error('Invalid published terrain grid')
    return createTerrainHeightContract(async ({ level, x, y }) => {
      const tile = await archive.raw(`${level}/${x}/${y}`)
      if (tile === undefined) throw new Error('Published terrain raw source unavailable')
      if (tile && (tile.revision !== pin.vrt_sha256 || tile.sourceLevel !== level)) throw new Error('Raw terrain publication changed')
      return tile?.heights ?? null
    }, { archiveSha256: pin.sha256, minLevel: m.minLevel, maxLevel: m.maxLevel })
  })().catch(error => { pending = undefined; throw error })
}

export const defaultTerrainPublicationReader = createTerrainPublicationReader()
