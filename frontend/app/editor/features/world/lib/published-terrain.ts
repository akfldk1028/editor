type Snapshot = { vrt_sha256: string; sampler: string; expiresAt: number }
type Catalog = Map<string, { version: string; snapshot?: Snapshot }>

export function createPublishedTerrainReader(get: (url: string) => Promise<Response> = url => fetch(url, { cache: url.endsWith('/catalog.json') ? 'no-store' : 'default', signal: AbortSignal.timeout(2000) }), now = Date.now, onSnapshot: (version: string) => void = () => {}) {
  let catalog: Promise<Catalog | null> | undefined
  let checkedAt = -Infinity
  const sources = new Map<string, Promise<{ vrt_sha256: string; sampler?: string } | null>>()
  const base = `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/map-data/world-terrain`
  return async (key: string, vrtSha256: string): Promise<Float32Array | undefined> => {
    if (!/^\d+\/\d+\/\d+$/.test(key)) return undefined
    if (!catalog || now() - checkedAt >= 60000) {
      checkedAt = now()
      sources.clear()
      catalog = get(`${base}/catalog.json`).then(async response => {
        const value = response.ok ? await response.json() : null
        if (!value || !/^[a-zA-Z0-9_-]+$/.test(value.version) || !Array.isArray(value.tiles)) return null
        const index: Catalog = new Map()
        for (const entry of [value.fallback, value]) {
          if (!entry || !/^[a-zA-Z0-9_-]+$/.test(entry.version) || !Array.isArray(entry.tiles)) continue
          const policy = entry.displaySnapshot
          const snapshot = policy && /^[a-f0-9]{64}$/.test(policy.vrt_sha256) && typeof policy.sampler === 'string'
            && policy.sampler.length > 0 && Number.isFinite(policy.expiresAt) ? policy as Snapshot : undefined
          for (const tile of entry.tiles) if (typeof tile === 'string' && /^\d+\/\d+\/\d+$/.test(tile)) index.set(tile, { version: entry.version, snapshot })
        }
        return index
      }).catch(() => null)
    }
    try {
      const index = await catalog
      const entry = index?.get(key)
      if (!entry) return undefined
      const { version, snapshot } = entry
      const pinned = snapshot && now() < snapshot.expiresAt ? snapshot : undefined
      if (!sources.has(version)) sources.set(version, get(`${base}/${version}/local-source.json`)
        .then(async response => {
          const value = response.ok ? await response.json() : null
          return typeof value?.vrt_sha256 === 'string' ? { vrt_sha256: value.vrt_sha256, sampler: value.sampler } : null
        }).catch(() => null))
      const source = await sources.get(version)
      const expected = pinned?.vrt_sha256 ?? vrtSha256
      if (source && source.vrt_sha256 !== expected) return undefined
      if (pinned && (!source || source.sampler !== pinned.sampler)) return undefined
      const response = await get(`${base}/${version}/${key.replaceAll('/', '-')}.json`)
      const value = response.ok ? await response.json() : null
      const valid = !!expected && value?.dataset?.vrt_sha256 === expected && (!pinned || value?.dataset?.sampler === pinned.sampler)
        && value?.size === 33 && Array.isArray(value.heights) && value.heights.length === 1089
        && value.heights.every((h: unknown) => typeof h === 'number' && Number.isFinite(h) && h !== -9999 && Math.abs(h) <= 12000)
      if (!valid) return undefined
      if (pinned) onSnapshot(version)
      return new Float32Array(value.heights)
    } catch { return undefined }
  }
}
