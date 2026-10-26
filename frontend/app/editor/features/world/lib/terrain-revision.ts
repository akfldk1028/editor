export type TerrainRevision = { revision: string; vrt_sha256: string | null }

export async function readTerrainRevision(): Promise<TerrainRevision | null> {
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/terrain-revision`,
      { cache: 'no-store', signal: AbortSignal.timeout(2000) })
    const value = response.ok ? await response.json() : null
    return typeof value?.revision === 'string' && value.revision.length > 0
      ? { revision: value.revision, vrt_sha256: typeof value.vrt_sha256 === 'string' ? value.vrt_sha256 : null } : null
  } catch { return null }
}
