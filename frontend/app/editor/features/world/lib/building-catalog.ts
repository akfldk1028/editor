import { mapAssetUrl, configuredMapBase } from './map-asset-url'
import { defaultMapReleaseReader, requireLegacyMapRelease } from './map-release'

export type BuildingRegion = { id: string; z: number; x: number; y: number; bounds: number[]; url: string; footprints: string; coverage?: string[]; partialCoverage?: string[] }
export type CatalogView = { box: number[]; focus: { lon: number; lat: number } }
type Shard = { key: string; bounds: number[]; href: string }
type Index = { revision: string; shards: Shard[] }
type Get = (url: string, options?: RequestInit) => Promise<Response>

export class BuildingCatalog {
  private index?: Index
  private legacy?: BuildingRegion[]
  private checkedAt = -Infinity
  private opening?: Promise<void>
  private cached = new Map<string, BuildingRegion[]>()
  private retryAt = new Map<string, number>()
  private active?: { key: string; controller: AbortController }
  private selectedKey?: string

  constructor(private get: Get = (url, options) => fetch(url, options), private now = Date.now, private readRelease = defaultMapReleaseReader) {}

  private wanted(view: CatalogView): Shard[] {
    const [w,s,e,n] = view.box, { lon, lat } = view.focus
    const distance = (a: Shard) => (Math.max(a.bounds[0]!-lon, 0, lon-a.bounds[2]!) * Math.cos(lat*Math.PI/180)) ** 2
      + Math.max(a.bounds[1]!-lat, 0, lat-a.bounds[3]!) ** 2
    return (this.index?.shards ?? []).filter(a => a.bounds[0]! <= e! && a.bounds[2]! >= w! && a.bounds[1]! <= n! && a.bounds[3]! >= s!)
      .sort((a,b) => distance(a)-distance(b)).slice(0,8)
  }

  private viewKey(view: CatalogView) { return this.wanted(view).map(s => s.key).join('|') }

  retarget(view: CatalogView) {
    if (this.active && this.active.key !== this.viewKey(view)) this.active.controller.abort()
  }

  needsView(view: CatalogView) {
    if (this.now() - this.checkedAt >= 60_000) return true
    if (this.legacy) return false
    if (this.index && this.selectedKey !== this.viewKey(view)) return true
    return this.wanted(view).some(s => !this.cached.has(s.key) && this.now() >= (this.retryAt.get(s.key) ?? 0))
  }

  private async open(signal: AbortSignal) {
    if (this.opening) return this.opening
    if (this.now() - this.checkedAt < 60_000) return
    this.checkedAt = this.now()
    this.opening = (async () => {
      const publication = await this.readRelease()
      const release = publication ? requireLegacyMapRelease(publication) : undefined
      const latest = release ? Response.json(release.buildingCatalog) : await this.get(mapAssetUrl('world-buildings','latest.json'), { signal, cache:'no-cache' })
      if (latest.status === 404 && !configuredMapBase('world-buildings')) {
        const old = await this.get(mapAssetUrl('world-buildings','catalog.json'), { signal })
        if (!old.ok) throw new Error(`Building catalog ${old.status}`)
        const value = await old.json()
        if (!Array.isArray(value.regions)) throw new Error('Invalid building catalog')
        this.legacy = value.regions; return
      }
      if (!latest.ok) throw new Error(`Building catalog pointer ${latest.status}`)
      const pointer = await latest.json()
      if (!/^[a-f0-9]{64}$/.test(pointer.revision ?? '') || typeof pointer.index !== 'string') throw new Error('Invalid building catalog pointer')
      const response = await this.get(mapAssetUrl('world-buildings',pointer.index), { signal })
      if (!response.ok) throw new Error(`Building catalog index ${response.status}`)
      const value = await response.json()
      if (value.schema !== 'world-buildings/catalog-index-v1' || value.revision !== pointer.revision || !Array.isArray(value.shards)) throw new Error('Invalid building catalog index')
      if (value.revision !== this.index?.revision) { this.cached.clear(); this.retryAt.clear() }
      this.index = value; this.legacy = undefined
    })().catch(error => { this.checkedAt = this.now()-55_000; throw error }).finally(() => { this.opening = undefined })
    return this.opening
  }

  async read(getView: () => CatalogView | null, changed: (regions: BuildingRegion[]) => void, parentSignal: AbortSignal) {
    await this.open(parentSignal)
    if (this.legacy) { changed(this.legacy); return }
    const view = getView(), index = this.index
    if (!view || !index) return
    const wanted = this.wanted(view), controller = new AbortController()
    this.selectedKey = this.viewKey(view)
    this.active = { key:this.viewKey(view), controller }
    const signal = AbortSignal.any([parentSignal,controller.signal])
    const collected: BuildingRegion[] = []
    try {
      // Prefetch only two adjacent priorities. Publish in distance order even if
      // the farther response arrives first, preserving near-first geometry.
      for (let start=0;start<wanted.length;start+=2) {
        const jobs = wanted.slice(start,start+2).map(async shard => {
          if (this.cached.has(shard.key)) return this.cached.get(shard.key)!
          if (this.now() < (this.retryAt.get(shard.key) ?? 0)) return []
          try {
            const response = await this.get(mapAssetUrl('world-buildings',shard.href), { signal:AbortSignal.any([signal,AbortSignal.timeout(5000)]) })
            if (!response.ok) throw new Error(`Building catalog shard ${response.status}`)
            const body = await response.json()
            if (body.schema !== 'world-buildings/shard-v1' || body.revision !== index.revision || !Array.isArray(body.regions)) throw new Error('Invalid building catalog shard')
            if (signal.aborted || this.index?.revision !== index.revision) return []
            this.cached.set(shard.key,body.regions); this.retryAt.delete(shard.key)
            if (this.cached.size > 32) this.cached.delete(this.cached.keys().next().value!)
            return body.regions as BuildingRegion[]
          } catch {
            if (!signal.aborted) this.retryAt.set(shard.key,this.now()+5000)
            return []
          }
        })
        for (const job of jobs) {
          const regions = await job
          if (signal.aborted || this.index?.revision !== index.revision) return
          collected.push(...regions); changed([...collected])
        }
      }
    } finally { if (this.active?.controller === controller) this.active = undefined }
  }
}
