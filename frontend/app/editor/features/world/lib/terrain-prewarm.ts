import { defaultTerrainArchiveReader } from './terrain-archive'

type Reader = ((key: string) => Promise<unknown>) & { prepare(): Promise<unknown> }

/** Warm only the selected site's sample; share the archive/pinned release with the actual provider. */
export async function prewarmTerrainAt(location: readonly [number, number] | undefined,
  live: () => boolean, read: Reader = defaultTerrainArchiveReader): Promise<void> {
  if (!location || !location.every(Number.isFinite) || !live()) return
  const [lon, lat] = location
  if (lon < 124 || lon > 132 || lat < 33 || lat > 39) return
  try {
    await read.prepare()
    if (!live()) return
    // Identical to Cesium.GeographicTilingScheme.positionToTileXY at the provider's sample level.
    const width = 180 / 2 ** 20
    await read(`20/${Math.floor((lon + 180) / width)}/${Math.floor((90 - lat) / width)}`)
  } catch {
    // Best effort only: normal provider sampling owns error reporting and retries.
  }
}
