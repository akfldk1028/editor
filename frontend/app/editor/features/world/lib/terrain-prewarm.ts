import { defaultTerrainArchiveReader } from './terrain-archive'

type Reader = ((key: string) => Promise<unknown>) & { prepare(): Promise<unknown>; raw?(key: string): Promise<unknown> }

/** Warm only the selected site's sample; share the archive/pinned release with the actual provider. */
export async function prewarmTerrainAt(location: readonly [number, number] | undefined,
  live: () => boolean, read: Reader = defaultTerrainArchiveReader): Promise<void> {
  if (!location || !location.every(Number.isFinite) || !live()) return
  const [lon, lat] = location
  if (lon < 124 || lon > 132 || lat < 33 || lat > 39) return
  try {
    const prepared = await read.prepare() as { metadata?: { minLevel?: number } } | undefined
    if (!live()) return
    // Identical to Cesium.GeographicTilingScheme.positionToTileXY at the provider's sample level.
    const width = 180 / 2 ** 20, x = Math.floor((lon + 180) / width), y = Math.floor((90 - lat) / width)
    // A pinned height contract samples raw tiles down the whole ancestor chain (its own cache): warm that chain, at once.
    const minLevel = prepared?.metadata?.minLevel
    if (read.raw && Number.isInteger(minLevel))
      await Promise.all(Array.from({ length: 21 - minLevel! }, (_, i) => read.raw!(`${20 - i}/${Math.floor(x / 2 ** i)}/${Math.floor(y / 2 ** i)}`).catch(() => {})))
    else await read(`20/${x}/${y}`)
  } catch {
    // Best effort only: normal provider sampling owns error reporting and retries.
  }
}
