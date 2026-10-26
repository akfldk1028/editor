/* eslint-disable @typescript-eslint/no-explicit-any */
import { inside, insideFootprint, tileXY, tilesOverlap, type BuildingTile, type Footprint } from './building-geometry'
import { FootprintIndex } from './footprint-index'
import type { HeightCounts } from './context-masses'
import { BuildingCatalog, type BuildingRegion } from './building-catalog'
import { mapAssetUrl } from './map-asset-url'
import { buildingColor } from './building-palette'

type Region = BuildingRegion
type Loaded = { region: Region; tileset: any; ready: boolean; committed?: boolean; settled?: boolean; failed: boolean; fallbackReady?: boolean; features: Footprint[]; drawnKeys?: Set<string>; committedKeys?: Set<string>; index?: FootprintIndex; controller: AbortController; metadataTimer?: ReturnType<typeof setTimeout>; metadataController?: AbortController; metadataRequested?: boolean }
const KEEP_REGIONS = 16
const GPU_BUDGET = 256 * 1024 * 1024

export function coversTile(region: Pick<Region, 'z' | 'x' | 'y' | 'coverage'>, tile: BuildingTile) {
  const scale = 2 ** (tile.z - region.z)
  if (!(tile.z >= region.z && Math.floor(tile.x / scale) === region.x && Math.floor(tile.y / scale) === region.y)) return false
  if (!region.coverage) return true
  if (tile.z >= 16) {
    const divisor = 2 ** (tile.z - 16)
    return region.coverage.includes(`16/${Math.floor(tile.x / divisor)}/${Math.floor(tile.y / divisor)}`)
  }
  const n = 2 ** (16 - tile.z)
  for (let dx = 0; dx < n; dx++) for (let dy = 0; dy < n; dy++) {
    if (!region.coverage.includes(`16/${tile.x * n + dx}/${tile.y * n + dy}`)) return false
  }
  return true
}

/** Precomputed geometry streams directly to GPU; the archive remains the source outside baked coverage. */
export class PrebuiltBuildings {
  private loaded: Loaded[] = []
  private regions: Region[] = []
  private requested = new Set<string>()
  private retryAfter = new Map<string, number>()
  private opening = 0
  private selected: Region[] = []
  private selectedUrls = new Set<string>()
  private regionLimit = KEEP_REGIONS
  private catalogLoading = false
  private catalog = new BuildingCatalog()
  private view: { box: number[]; focus: { lon: number; lat: number } } | null = null
  private openRegion: ((region: Region) => Promise<void>) | null = null
  private disposed = false
  private controller = new AbortController()
  private enabled = true
  private shown = true
  private site: number[][] | null = null
  private hide = false
  private revision = 0
  private styled = new WeakMap<object, number>()
  private visible = new Map<any, HeightCounts>()
  private coverageChanged = false
  private metadataTimers = new Set<ReturnType<typeof setTimeout>>()
  private metadataQueue: Promise<void> = Promise.resolve()
  private removePre: () => void
  private removePost: () => void
  counts: HeightCounts = { measured: 0, estimated: 0, unknown: 0 }
  rendered = false
  error = ''

  constructor(private viewer: any, private C: any, private changed: (coverage?: boolean) => void) {
    this.removePre = viewer.scene.preRender.addEventListener(() => this.visible.clear())
    this.removePost = viewer.scene.postRender.addEventListener(() => {
      let settled = false
      for (const loaded of this.loaded) if (!loaded.settled && loaded.tileset.tilesLoaded === true) {
        loaded.settled = true; settled = true
      }
      if (settled) queueMicrotask(() => this.pump())
      const counts = { measured: 0, estimated: 0, unknown: 0 }
      for (const c of this.visible.values()) { counts.measured += c.measured; counts.estimated += c.estimated; counts.unknown += c.unknown }
      const different = Object.keys(counts).some(k => counts[k as keyof HeightCounts] !== this.counts[k as keyof HeightCounts])
      this.counts = counts
      const coverage = this.coverageChanged
      this.coverageChanged = false
      if (different || coverage) queueMicrotask(() => { if (!this.disposed) this.changed(coverage) })
    })
    void this.open()
  }

  private async open() {
    try {
      if (this.disposed) return
      this.openRegion = async (region: Region) => {
        const tileset = await this.C.Cesium3DTileset.fromUrl(mapAssetUrl('world-buildings',region.url), {
          maximumScreenSpaceError: this.screenError(region), dynamicScreenSpaceError: true, foveatedScreenSpaceError: true,
          foveatedTimeDelay: 0.1, progressiveResolutionHeightFraction: 0.3,
          preloadFlightDestinations: false, preloadWhenHidden: false, cacheBytes: 12 * 1024 * 1024,
          maximumCacheOverflowBytes: 4 * 1024 * 1024,
        })
        if (this.disposed || !this.selectedUrls.has(region.url)) { tileset.destroy(); this.requested.delete(region.url); return }
        if (this.C.Cesium3DTileColorBlendMode) tileset.colorBlendMode = this.C.Cesium3DTileColorBlendMode.REPLACE
        // The diagram uses neutral ambient light, not Cesium's blue atmosphere irradiance.
        if (tileset.imageBasedLighting) {
          tileset.imageBasedLighting.imageBasedLightingFactor = new this.C.Cartesian2(1, 0)
          tileset.imageBasedLighting.sphericalHarmonicCoefficients = Array.from({ length: 9 }, (_, i) =>
            new this.C.Cartesian3(i === 0 ? 1 : 0, i === 0 ? 1 : 0, i === 0 ? 1 : 0))
        }
        const loaded: Loaded = { region, tileset, ready: false, committed: false, failed: false, features: [], controller: new AbortController() }
        if (region.partialCoverage?.length) loaded.drawnKeys = new Set()
        this.loaded.push(loaded)
        tileset.show = this.enabled && this.shown
        // A downloaded manifest is not drawable coverage. Keep the archive's
        // buildings until the visible replacement content has actually arrived.
        tileset.allTilesLoaded.addEventListener(() => {
          if (loaded.ready || loaded.failed || this.disposed || loaded.controller.signal.aborted) return
          loaded.ready = true
          loaded.settled = true
          queueMicrotask(() => { if (!this.disposed && !loaded.controller.signal.aborted) { this.trim(); this.changed(true); this.pump() } })
        })
        tileset.tileFailed.addEventListener((failure: { message: string }) => {
          if (loaded.failed) return
          loaded.failed = true
          this.error = `사전 생성 건물 타일: ${failure.message}`
          queueMicrotask(() => { if (!this.disposed) this.changed(true) })
        })
        tileset.tileVisible.addEventListener((tile: any) => {
          if (!loaded.metadataRequested && this.metadataEligible(loaded.region)) {
            loaded.metadataRequested = true
            const timer = setTimeout(() => {
              this.metadataTimers.delete(timer)
              this.metadataQueue = this.metadataQueue.then(() => {
                // An overview can enqueue many optional indexes. Once zoomed in,
                // those must not compete with the new target's geometry requests.
                if (!this.metadataEligible(loaded.region)) { loaded.metadataRequested = false; return }
                if (!this.disposed && !loaded.controller.signal.aborted) return this.loadMetadata(loaded)
              })
            }, 1000)
            this.metadataTimers.add(timer)
            loaded.metadataTimer = timer
          }
          const content = tile.content
          const counts = { measured: 0, estimated: 0, unknown: 0 }
          if (this.styled.get(content) !== this.revision) {
            for (let i = 0; i < content.featuresLength; i++) {
              const f = content.getFeature(i)
              if (loaded.drawnKeys) {
                const key = f.getProperty('key')
                if (typeof key === 'string' && !loaded.drawnKeys.has(key)) {
                  loaded.drawnKeys.add(key)
                  this.coverageChanged = true
                }
              }
              f.show = Boolean(loaded.committed) && (!loaded.drawnKeys || Boolean(loaded.committedKeys?.has(f.getProperty('key')))) && !(this.hide && this.site && inside([f.getProperty('lon'), f.getProperty('lat')], this.site))
              f.color = this.C.Color.fromCssColorString(buildingColor(f.getProperty('status'))).withAlpha(1)
              if (f.show) counts[f.getProperty('status') === 'm' ? 'measured' : f.getProperty('status') === 'e' ? 'estimated' : 'unknown']++
            }
            content.__worldCounts = counts
            this.styled.set(content, this.revision)
          }
          this.visible.set(content, content.__worldCounts)
          if (counts.measured + counts.estimated + counts.unknown > 0) this.rendered = true
        })
        this.viewer.scene.primitives.add(tileset)
        this.trim()
        this.viewer.scene.requestRender()
      }
      await this.refreshCatalog()
      this.pump()
    } catch (error) {
      if (!this.disposed) { this.error = String(error); this.changed() }
    }
  }

  private async refreshCatalog() {
    this.catalogLoading = true
    try {
      await this.catalog.read(() => this.view, incoming => {
        if (this.disposed) return
        const key = (r: Region) => `${r.z}/${r.x}/${r.y}`
        const regions = new Map<string, Region>(incoming.map(r => [key(r), r]))
        // Keep the version already loading/on screen until its normal eviction.
        for (const region of this.regions) if (this.requested.has(region.url)) regions.set(key(region), region)
        this.regions = [...regions.values()]
        this.selectRegions()
        this.trim()
        this.updateShow()
        this.pump()
      }, this.controller.signal)
    } finally {
      this.catalogLoading = false
      if (!this.disposed && this.view && this.catalog.needsView(this.view)) {
        queueMicrotask(() => { if (!this.disposed && !this.catalogLoading) void this.refreshCatalog().catch(() => {}) })
      }
    }
  }

  setView(box: number[], focus: { lon: number; lat: number }) {
    if (!this.view || Math.abs(this.view.focus.lon-focus.lon) + Math.abs(this.view.focus.lat-focus.lat) > 0.01) this.regionLimit = KEEP_REGIONS
    this.view = { box, focus }
    this.selectRegions()
    this.catalog.retarget(this.view)
    if (!this.catalogLoading && this.catalog.needsView(this.view)) {
      if (!this.openRegion) void this.open()
      else void this.refreshCatalog().catch(() => { /* Keep usable coverage during a catalog outage. */ })
    }
    if (this.trim()) this.changed(true)
    this.updateShow()
    for (const loaded of this.loaded) {
      loaded.tileset.maximumScreenSpaceError = this.screenError(loaded.region)
      if (!this.metadataEligible(loaded.region)) {
        if (loaded.metadataTimer) { clearTimeout(loaded.metadataTimer); this.metadataTimers.delete(loaded.metadataTimer); loaded.metadataTimer = undefined }
        loaded.metadataController?.abort(); loaded.metadataController = undefined
        loaded.features = []; loaded.index = undefined; loaded.metadataRequested = false
      }
    }
    this.pump()
  }

  private inView(region: Region) {
    if (!this.view) return false
    const [w, s, e, n] = this.view.box
    return region.bounds[0]! <= e! && region.bounds[2]! >= w! && region.bounds[1]! <= n! && region.bounds[3]! >= s!
  }

  private trim(): boolean {
    if (!this.view) return false
    const { lon, lat } = this.view.focus
    const distance = (l: Loaded) => (((l.region.bounds[0]! + l.region.bounds[2]!) / 2 - lon) * Math.cos(lat * Math.PI / 180)) ** 2
      + ((l.region.bounds[1]! + l.region.bounds[3]!) / 2 - lat) ** 2
    const missing = this.selected.filter(r => !this.loaded.some(l => l.region.url === r.url)).length
    const evicted = this.loaded.filter(l => !this.selectedUrls.has(l.region.url)).sort((a, b) => distance(b) - distance(a))
      .slice(0, Math.max(0, this.loaded.length - (KEEP_REGIONS - missing)))
    let bytes = this.loaded.reduce((sum,l) => sum + (l.tileset.totalMemoryUsageInBytes || 0), 0)
      - evicted.reduce((sum,l) => sum + (l.tileset.totalMemoryUsageInBytes || 0), 0)
    for (const l of [...this.loaded].sort((a,b) => distance(b)-distance(a))) {
      if (bytes <= GPU_BUDGET || this.loaded.length-evicted.length <= 1) break
      if (evicted.includes(l)) continue
      evicted.push(l); bytes -= l.tileset.totalMemoryUsageInBytes || 0
      this.regionLimit = Math.min(this.regionLimit, this.loaded.length-evicted.length)
    }
    for (const l of evicted) {
      l.controller.abort()
      l.metadataController?.abort()
      if (l.metadataTimer) { clearTimeout(l.metadataTimer); this.metadataTimers.delete(l.metadataTimer) }
      this.requested.delete(l.region.url)
      this.viewer.scene.primitives.remove(l.tileset)
      l.features = []; l.index = undefined
    }
    if (evicted.length) { this.loaded = this.loaded.filter(l => !evicted.includes(l)); this.selectRegions() }
    return evicted.length > 0
  }

  private pump() {
    if (this.disposed || !this.view || !this.openRegion) return
    const wanted = this.selected.filter(r => !this.requested.has(r.url) && Date.now() >= (this.retryAfter.get(r.url) ?? 0))
    const unfinished = () => this.loaded.filter(l => this.selectedUrls.has(l.region.url) && !l.settled && !l.ready && !l.failed).length
    while (this.opening + unfinished() < 2 && this.loaded.length + this.opening < KEEP_REGIONS && wanted.length) {
      const region = wanted.shift()!
      this.requested.add(region.url)
      this.opening++
      void this.openRegion(region).then(() => this.retryAfter.delete(region.url)).catch(error => {
        this.requested.delete(region.url)
        if (!this.disposed) {
          this.retryAfter.set(region.url, Date.now() + 5000)
          this.error = String(error); this.changed()
        }
      }).finally(() => { this.opening--; this.pump() })
    }
  }

  private async loadMetadata(loaded: Loaded) {
    try {
      const controller = new AbortController(); loaded.metadataController = controller
      const response = await fetch(mapAssetUrl('world-buildings',loaded.region.footprints), { signal: AbortSignal.any([this.controller.signal, loaded.controller.signal, controller.signal]), priority: 'low' })
      if (!response.ok) return
      const features = await response.json()
      if (this.disposed || loaded.controller.signal.aborted || controller.signal.aborted || !this.metadataEligible(loaded.region)) return
      loaded.features = features; loaded.index = new FootprintIndex(features); this.changed()
    } catch { /* Rendering can continue without optional overlap/roof metadata. */ }
  }

  get needsFallback() { return this.loaded.some(l => l.failed && !l.fallbackReady) }

  retireFailed(wanted: BuildingTile[], drawable: BuildingTile[]) {
    let retired = false
    const ready = new Set(drawable.map(tile => `${tile.z}/${tile.x}/${tile.y}`))
    for (const loaded of this.loaded) {
      if (!loaded.failed || loaded.fallbackReady) continue
      const targets = wanted.filter(tile => tilesOverlap({ ...loaded.region, key: loaded.region.id }, tile))
      if (!targets.length || !targets.every(tile => ready.has(`${tile.z}/${tile.x}/${tile.y}`))) continue
      loaded.fallbackReady = true; retired = true
      loaded.tileset.show = false
      this.viewer.scene.requestRender()
    }
    return retired
  }

  owns(tile: BuildingTile) { return this.enabled && this.loaded.some(l => l.tileset.show && l.ready && !l.failed && coversTile(l.region, tile)) }
  get ownershipSignature() { return this.loaded.map(l => `${l.region.url}/${l.tileset.show}/${l.ready}/${l.committed}/${l.failed}/${l.fallbackReady}/${l.drawnKeys?.size ?? 0}/${l.committedKeys?.size ?? 0}`).join('|') }
  get hasOfferedCoverage() { return this.loaded.some(l => l.ready && !l.failed && (!l.committed || (l.drawnKeys?.size ?? 0) > (l.committedKeys?.size ?? 0)) && l.tileset.show) }
  commitReadyCoverage() {
    let changed = false
    for (const loaded of this.loaded) if (loaded.ready && !loaded.failed && (!loaded.committed || (loaded.drawnKeys?.size ?? 0) > (loaded.committedKeys?.size ?? 0)) && loaded.tileset.show) {
      loaded.committed = true; if (loaded.drawnKeys) loaded.committedKeys = new Set(loaded.drawnKeys); changed = true
    }
    if (changed) { this.revision++; this.viewer.scene.requestRender() }
    return changed
  }
  contains(f: Footprint, displayed = false) {
    const [x, y] = tileXY(f.ring[0]![0]!, f.ring[0]![1]!, 16)
    const zoom = Number(f.key.split('/')[0]), overview = zoom >= 13 && zoom < 16
    return this.enabled && this.loaded.some(l => l.tileset.show
      && (displayed ? l.committed && !l.fallbackReady : l.ready && !l.failed)
      && (coversTile(l.region, { z: 16, x, y, key: '' }) || (displayed ? l.committedKeys : l.drawnKeys)?.has(f.key)
        // Archive feature indexes differ across zoom levels; use prepared detail instead of overlapping overview masses.
        || overview && l.region.partialCoverage?.includes(`16/${x}/${y}`)))
  }
  overlaps(f: Footprint) { return this.enabled && this.loaded.some(l => !l.failed && l.index?.overlaps(f)) }
  heightAt(lon: number, lat: number) {
    if (!this.enabled || !this.shown) return undefined
    let height: number | undefined
    for (const l of this.loaded) if (!l.fallbackReady) for (const f of l.features) {
      if (this.hide && this.site && inside(f.ring[0]!, this.site)) continue
      if (insideFootprint([lon, lat], f)) height = Math.max(height ?? -Infinity, f.z! + f.h)
    }
    return height
  }
  setGround(terrain: boolean) { this.enabled = terrain; this.updateShow() }
  setShow(show: boolean) { this.shown = show; this.updateShow() }
  setSite(site: number[][] | null, hide: boolean) { this.site = site; this.hide = hide; this.revision++; this.viewer.scene.requestRender() }
  private updateShow() {
    for (const l of this.loaded) l.tileset.show = this.enabled && this.shown && this.selectedUrls.has(l.region.url) && !l.fallbackReady
    this.viewer.scene.requestRender()
  }

  private selectRegions() {
    if (!this.view) return
    const {lon,lat}=this.view.focus
    const distance=(r:Region)=>(Math.max(r.bounds[0]!-lon,0,lon-r.bounds[2]!)*Math.cos(lat*Math.PI/180))**2
      + Math.max(r.bounds[1]!-lat,0,lat-r.bounds[3]!)**2
    this.selected=this.regions.filter(r=>this.inView(r)).sort((a,b)=>distance(a)-distance(b)).slice(0,this.regionLimit)
    this.selectedUrls=new Set(this.selected.map(r=>r.url))
  }

  private screenError(region: Region) {
    const rank=this.selected.findIndex(r=>r.url===region.url)
    const height=this.viewer.camera?.positionCartographic?.height ?? 0
    return height > 12_000 ? 128 : rank < 4 ? 12 : rank < 8 ? 64 : 128
  }

  private metadataEligible(region: Region) {
    return (this.viewer.camera?.positionCartographic?.height ?? 0) < 3000
      && this.selected.slice(0,4).some(r=>r.url===region.url)
  }
  dispose() {
    this.disposed = true; this.controller.abort(); this.removePre(); this.removePost()
    for (const timer of this.metadataTimers) clearTimeout(timer)
    this.metadataTimers.clear()
    for (const l of this.loaded) this.viewer.scene.primitives.remove(l.tileset)
    this.loaded = []
  }
}
