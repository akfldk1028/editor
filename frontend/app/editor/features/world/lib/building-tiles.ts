/* eslint-disable @typescript-eslint/no-explicit-any */
import { BUILDING_ZOOM, decodeBuildings, inside, insideFootprint, overlaps, tileXY, tilesIn, tilesOverlap, type BuildingTile, type Footprint } from './building-geometry'
import { fetchContextBuildings, type Ground, type HeightCounts } from './context-masses'
import { FootprintIndex } from './footprint-index'
import { BuildingDecoder } from './building-decode-client'
import { lodTiles, type BuildingView } from './building-lod'
import { PrebuiltBuildings } from './prebuilt-buildings'
import { preparedGeometry } from './building-mesh'
import { loadBuildingSource } from './building-source'
import { buildingColor } from './building-palette'

type Entry = { tile: BuildingTile; features: Footprint[]; primitives: any[]; heights: number[]; bottoms?: number[]; applied?: number[]; visible: Footprint[]; loading?: boolean; needsBuild?: boolean; request?: AbortController }
type DatumBatch = { missing: Footprint[]; next: number; active: number; needed: () => boolean; sample: (f: Footprint) => Promise<void>; finish: () => void; failure?: { reason: unknown } }
const KEEP = 96
const WORK_MS = 6
const PREVIEW_BUILDINGS = 16
const DATUM_IN_FLIGHT = 8
const emptyCounts = (): HeightCounts => ({ measured: 0, estimated: 0, unknown: 0 })
let libraries: Promise<any[]> | null = null
function loadLibraries() {
  if (!libraries) libraries = Promise.all([
    import('pmtiles'), import('pbf'), import('@mapbox/vector-tile'),
  ]).catch(e => { libraries = null; throw e })
  return libraries
}

let preparation: ReturnType<typeof prepare> | null = null
let preparedAt = 0
export function prepareBuildingTiles() {
  if (!preparation || Date.now() - preparedAt > 60_000) {
    preparedAt = Date.now()
    preparation = prepare().catch(e => { preparation = null; throw e })
  }
  return preparation
}
async function prepare() {
  const [libs, manifest] = await Promise.all([loadLibraries(), loadBuildingSource()])
  let archive = new libs[0].PMTiles(manifest.href)
  try { await archive.getHeader() } catch {
    // A retired published version must recover through the current manifest.
    const current = await loadBuildingSource(fetch, false)
    archive = new libs[0].PMTiles(current.href)
    await archive.getHeader()
  }
  return { archive, Pbf: libs[1].default, VectorTile: libs[2].VectorTile }
}

export class BuildingTiles {
  private decoder = typeof Worker === 'undefined' ? null : new BuildingDecoder()
  private archive: any = null
  private Pbf: any
  private VectorTile: any
  private opening: Promise<void> | null = null
  private disposed = false
  private entries = new Map<string, Entry>()
  private queue: BuildingTile[] = []
  private desired = new Set<string>()
  private previous = new Set<string>()
  private requestedView = false
  private running = 0
  private focus: [number, number] = [0, 0]
  private focusDegrees = { lon: 0, lat: 0 }
  private base: Ground = 'terrain'
  private level = 0
  private site: number[][] | null = null
  private hideOnSite = false
  private shown = true
  private controller = new AbortController()
  private supplementController: AbortController | null = null
  private supplementAt = ''
  private supplementSelection: Footprint[] = []
  private footprintIndexes = new WeakMap<Footprint[], FootprintIndex>()
  private supplementInputs: { source: Footprint[]; tiles: Footprint[][] } | null = null
  private supplement: Entry = { tile: { z: 16, x: 0, y: 0, key: 'supplement' }, features: [], primitives: [], heights: [], visible: [] }
  private removeRender: () => void
  private datums = new WeakMap<Footprint, number>()
  private datumJobs = new Map<Entry, Promise<void>>()
  private datumBatches = new Map<Entry, DatumBatch>()
  private datumRunning = 0
  private datumCompleted = 0
  private datumTimer: ReturnType<typeof setTimeout> | null = null
  private datumUpdates = new Map<Entry, ReturnType<typeof setTimeout>>()
  private datumRetryAt = new WeakMap<Entry, number>()
  private datumErrors = new Map<Entry, string>()
  private work = new Map<Entry, Generator<void>>()
  private datumRebuilds = new Map<Entry, { features: Footprint[]; immediate: boolean }>()
  private workTimer: ReturnType<typeof setTimeout> | null = null
  private tileError = ''
  private supplementError = ''
  private firstRendered = false
  private baked: PrebuiltBuildings | null = null
  private lastView: { box: [number, number, number, number]; focus: { lon: number; lat: number }; view?: BuildingView } | null = null
  backgroundReady = false
  private preview: Entry | null = null
  private backgroundTimer: ReturnType<typeof setTimeout>
  private retired: { primitives: any[]; replacement: Entry }[] = []
  private instanceFeatures = new WeakMap<object, { id: string; feature: Footprint }[]>()
  private maskedRevision = new WeakMap<object, number>()
  private ownershipRevision = 0
  private bakedSignature = ''
  private reportedGeometry: Footprint[][] = []
  private reportedCounts = emptyCounts()
  readonly startedAt = performance.now()
  firstRenderedAt: number | null = null

  constructor(private viewer: any, private C: any, private changed: (counts: HeightCounts, pending: number, error: string) => void,
    private prepared?: ReturnType<typeof prepareBuildingTiles>, private firstFrame?: () => void) {
    this.backgroundTimer = setTimeout(() => { if (!this.disposed) this.startBackground() }, 1000)
    const removeRendered = viewer.scene.postRender.addEventListener(() => {
      const masksReady = this.prepareOwnershipMasks()
      if (masksReady && this.baked?.hasOfferedCoverage) this.baked.commitReadyCoverage()
      let switched = false
      for (const key of masksReady ? this.previous : []) {
        const old = this.entries.get(key)
        const replacements = [...this.desired].filter(k => {
          const [z, x, y] = k.split('/').map(Number)
          return old && tilesOverlap(old.tile, { z: z!, x: x!, y: y!, key: k })
        })
        if (replacements.every(k => {
          const e = this.entries.get(k)
          return e && !e.loading && !e.needsBuild && !this.datumJobs.has(e)
            && !this.work.has(e) && e.primitives.every(p => p.ready)
        })) { this.previous.delete(key); switched = true }
      }
      if (switched) {
        this.setShow(this.shown)
        this.evict()
        this.reconcileSupplement()
        this.report()
      }
      if (!this.firstRendered && (this.baked?.rendered || [...this.entries.values()].some(e => e.primitives.some(p => p.ready && p.show)))) {
        this.firstRendered = true
        this.firstRenderedAt = performance.now()
        performance.mark('world-buildings-first-render')
        this.startBackground()
        for (const e of this.entries.values()) {
          this.build(e)
        }
        this.report()
      }
      if (masksReady && this.baked?.needsFallback) {
        const wanted = [...this.desired].map(key => {
          const [z, x, y] = key.split('/').map(Number)
          return { key, z: z!, x: x!, y: y! }
        })
        const drawable = [...this.entries.values()].filter(e => this.desired.has(e.tile.key)
          && this.inView(e) && !e.loading && !e.needsBuild && !this.work.has(e) && !this.datumJobs.has(e)
          && e.primitives.every(p => p.ready)).map(e => e.tile)
        if (this.baked.retireFailed(wanted, drawable)) {
          this.ownershipRevision++
          this.prepareOwnershipMasks()
        }
      }
      this.retired = this.retired.filter(old => {
        if (!masksReady || this.work.has(old.replacement) || old.replacement.primitives.some(p => !p.ready)) return true
        for (const p of old.primitives) this.viewer.scene.primitives.remove(p)
        return false
      })
      if (this.syncPrimitiveVisibility()) this.viewer.scene.requestRender()
    })
    // With requestRenderMode, async primitive stages otherwise wait for an unrelated
    // camera/network event. Keep frames alive only while visible replacements upload.
    const removeProgress = viewer.scene.postUpdate.addEventListener(() => {
      viewer.terrainProvider?.pruneRequests?.()
      if (!this.shown) return
      const pending = (e: Entry) => e.primitives.some(p => !p.ready)
      if (pending(this.supplement) || [...this.entries.values()].some(e =>
        (this.desired.has(e.tile.key) || this.previous.has(e.tile.key)) && pending(e))) viewer.scene.requestRender()
    })
    this.removeRender = () => { removeRendered(); removeProgress() }
    // Cesium's credit container keeps attribution on every surface sharing this viewer.
    viewer.scene.frameState.creditDisplay.addStaticCredit(new C.Credit('건물: 국토교통부 GIS건물통합정보 (공공누리 제1유형)', true))
    if (C.Cesium3DTileset && !(typeof location !== 'undefined' && new URLSearchParams(location.search).get('buildings') === 'vector')) {
      this.baked = new PrebuiltBuildings(viewer, C, coverage => {
        if (this.disposed) return
        if (coverage) {
          this.ownershipRevision++
          for (const e of this.entries.values()) if (!e.loading) this.build(e)
          if (this.lastView) this.load(this.lastView.box, this.lastView.focus, this.lastView.view)
        }
        this.supplementInputs = null
        this.reconcileSupplement(); this.report()
      })
    }
    void this.open()
  }

  private open(): Promise<void> {
    if (this.opening) return this.opening
    this.opening = (this.prepared ?? prepareBuildingTiles())
      .then(({ archive, Pbf, VectorTile }) => {
        if (this.disposed) return
        this.archive = archive
        this.Pbf = Pbf
        this.VectorTile = VectorTile
        this.tileError = ''
        this.pump()
      }).catch(e => {
        if (!this.disposed) { this.tileError = `건물 타일: ${e.message}`; this.opening = null; this.prepared = undefined; this.report(); this.startBackground() }
      })
    return this.opening
  }

  load(box: [number, number, number, number], focus: { lon: number; lat: number }, view?: BuildingView) {
    if (this.disposed) return
    this.lastView = { box, focus, view }
    this.baked?.setView(box, focus)
    const signature = this.baked?.ownershipSignature ?? ''
    if (signature !== this.bakedSignature) {
      this.bakedSignature = signature; this.ownershipRevision++
      // Cached prepared regions can change visibility without new network data.
      // Reconcile only committed ownership here; offers commit after the frame.
      this.prepareOwnershipMasks(false)
    }
    this.focus = tileXY(focus.lon, focus.lat)
    this.focusDegrees = focus
    this.requestedView = true
    const visible = view ? lodTiles(box, focus, view, [...this.desired].map(key => {
      const [z, x, y] = key.split('/').map(Number)
      return { z: z!, x: x!, y: y!, key }
    })) : tilesIn(box, focus)
    const archiveVisible = visible.filter(t => !this.baked?.owns(t))
    this.desired = new Set(archiveVisible.map(t => t.key))
    const fallbacks = new Map<string, BuildingTile>()
    if (this.firstRendered) for (const target of archiveVisible) {
      if (target.z <= 13 || this.entries.has(target.key)) continue
      const scale = 2 ** (target.z - 13), x = Math.floor(target.x / scale), y = Math.floor(target.y / scale)
      const key = `13/${x}/${y}`
      if (fallbacks.has(key) || [...this.entries.values()].some(e => e.tile.z <= target.z
        && tilesOverlap(e.tile, target) && e.primitives.some(p => p.ready && p.show))) continue
      fallbacks.set(key, { z: 13, x, y, key })
      this.previous.add(key)
    }
    for (const e of this.entries.values()) {
      const drawn = e.primitives.some(p => p.show && p.ready)
        || this.retired.some(old => old.replacement === e && old.primitives.some(p => p.show && p.ready))
      if (drawn && !this.desired.has(e.tile.key)) this.previous.add(e.tile.key)
    }
    for (const key of this.desired) this.previous.delete(key)
    for (const e of this.entries.values()) {
      if (e.loading && !this.desired.has(e.tile.key) && !this.previous.has(e.tile.key)) {
        this.remove(e)
        this.entries.delete(e.tile.key)
        continue
      }
      if (!this.desired.has(e.tile.key) && !this.previous.has(e.tile.key)) { this.work.delete(e); this.datumRebuilds.delete(e) }
      else if ((this.firstRendered || this.preview === e) && !e.loading && (e.needsBuild || !e.primitives.length)
        && !this.work.has(e) && !this.datumJobs.has(e) && Date.now() >= (this.datumRetryAt.get(e) ?? 0)) this.build(e)
    }
    // Fill newly exposed regions before spending request slots on central detail.
    const requests = [...fallbacks.values(), ...archiveVisible.filter(t => t.z === 13), ...archiveVisible.filter(t => t.z > 13)]
    this.queue = requests.filter(t => !this.entries.has(t.key))
    this.setShow(this.shown)
    this.evict()
    this.selectPreview()
    this.reconcileSupplement()
    this.resolveDatums(this.supplement, this.supplementSelection)
    if (!this.archive) void this.open()
    else this.pump()
  }

  private pump() {
    if (!this.archive || this.disposed) return
    while (this.running < 8 && this.queue.length) {
      const tile = this.queue.shift()!
      if (this.entries.has(tile.key)) continue
      const request = new AbortController()
      const signal = AbortSignal.any([this.controller.signal, request.signal])
      const entry: Entry = { tile, features: [], primitives: [], heights: [], visible: [], loading: true, request }
      this.entries.set(tile.key, entry)
      this.running++
      this.archive.getZxy(tile.z, tile.x, tile.y, signal).then(async (result: any) => {
        if (this.disposed || this.entries.get(tile.key) !== entry) return
        const features = result ? await (this.decoder
          ? this.decoder.decode(result.data, tile, signal)
          : decodeBuildings(result.data, tile, this.Pbf, this.VectorTile, signal)) : []
        if (this.disposed || this.entries.get(tile.key) !== entry) return
        entry.features = features
        entry.loading = false
        if (this.firstRendered && (this.desired.has(tile.key) || this.previous.has(tile.key))) this.build(entry)
        else this.selectPreview()
        this.tileError = ''
        this.reconcileSupplement()
      }).catch((e: Error) => {
        if (this.disposed || this.entries.get(tile.key) !== entry) return
        this.remove(entry)
        this.entries.delete(tile.key)
        this.tileError = `건물 타일: ${e.message}`
      }).finally(() => {
        this.running--
        if (!this.disposed) { this.evict(); this.report(); this.pump() }
      })
    }
    this.report()
    if (this.requestedView && !this.running && !this.queue.length && !this.preview && !this.baked) this.startBackground()
  }

  private startBackground() {
    if (this.backgroundReady) return
    this.backgroundReady = true
    this.firstFrame?.()
  }

  private selectPreview() {
    if (this.firstRendered) return
    if (this.preview && (!this.desired.has(this.preview.tile.key) || this.entries.get(this.preview.tile.key) !== this.preview)) {
      this.remove(this.preview)
      this.preview = null
    }
    if (this.preview) return
    const candidates = [...this.entries.values()].filter(e => this.desired.has(e.tile.key))
      .flatMap(e => e.features.filter(f => !(this.hideOnSite && this.site && inside(f.ring[0]!, this.site))).map(f => ({ e, f })))
      .sort((a, b) => this.distance(a.f) - this.distance(b.f))
    const nearest = candidates[0]
    if (nearest) {
      this.preview = nearest.e
      this.build(nearest.e, candidates.filter(c => c.e === nearest.e).slice(0, PREVIEW_BUILDINGS).map(c => c.f), true)
    }
  }

  private evict() {
    const distance = (e: Entry) => {
      const scale = 2 ** (BUILDING_ZOOM - e.tile.z)
      return (e.tile.x * scale - this.focus[0]) ** 2 + (e.tile.y * scale - this.focus[1]) ** 2
    }
    const inactive = [...this.entries.values()].filter(e => !this.desired.has(e.tile.key) && !this.previous.has(e.tile.key))
    // Visible overview tiles must not consume the return-view cache and evict all fine geometry.
    const far = inactive.sort((a, b) => distance(b) - distance(a)).slice(0, Math.max(0, inactive.length - KEEP))
    for (const e of far) { this.remove(e); this.entries.delete(e.tile.key) }
    if (far.length) this.reconcileSupplement()
  }

  private *ground(f: Footprint): Generator<void, { z: number; bottom: number } | undefined> {
    if (this.base !== 'terrain') return { z: this.base, bottom: this.base }
    const z = Number.isFinite(f.z) ? f.z! : this.datums.get(f)
    if (z === undefined) return undefined
    // The skirt stays below both the datum and the unloaded terrain fallback without camera-dependent ray tests.
    return { z, bottom: Math.min(z, 0, this.level) - 12 }
  }

  private resolveDatums(e: Entry, features: Footprint[]) {
    const demanded = () => e === this.supplement || this.desired.has(e.tile.key)
      || (this.previous.has(e.tile.key) && e.primitives.length === 0)
    if (!demanded() || this.base !== 'terrain' || this.datumJobs.has(e) || Date.now() < (this.datumRetryAt.get(e) ?? 0)) return
    const missing = features.filter(f => !Number.isFinite(f.z) && !this.datums.has(f)
      && !(e !== this.supplement && this.baked?.contains(f))
      && !(this.hideOnSite && this.site && inside(f.ring[0]!, this.site)))
    if (!missing.length) return
    const provider = this.viewer.terrainProvider
    const needed = () => !this.disposed && this.base === 'terrain'
      && (e === this.supplement || this.entries.get(e.tile.key) === e) && demanded()
    const sample = async (f: Footprint) => {
      if (!provider?.sampleHeight) throw new Error('DEM height sampler unavailable')
      const [lon, lat] = f.ring[0]!
      const z = await provider.sampleHeight(lon, lat, needed)
      if (!Number.isFinite(z)) throw new Error('DEM height unavailable')
      if (!this.disposed) {
        this.datums.set(f, z)
        if (!this.datumUpdates.has(e)) this.datumUpdates.set(e, setTimeout(() => {
          this.datumUpdates.delete(e)
          if (this.disposed || (e !== this.supplement && this.entries.get(e.tile.key) !== e) || !this.inView(e)) return
          const preview = !this.firstRendered && this.preview === e
          this.buildAfterDatums(e, preview ? features : e === this.supplement ? this.supplementSelection : e.features, preview)
        }, 32))
      }
    }
    let finish!: () => void
    const done = new Promise<void>(resolve => { finish = resolve })
    const batch: DatumBatch = { missing: missing.sort((a, b) => this.distance(a) - this.distance(b)), next: 0, active: 0, needed, sample, finish }
    const task = done.then(() => {
      this.datumJobs.delete(e)
      clearTimeout(this.datumUpdates.get(e)); this.datumUpdates.delete(e)
      if (this.disposed || (e !== this.supplement && this.entries.get(e.tile.key) !== e)) return
      if (!needed()) { this.report(); return }
      const failure = batch.failure
      if (failure) {
        this.datumRetryAt.set(e, Date.now() + 5000)
        this.datumErrors.set(e, `건물 지반 높이: ${failure.reason instanceof Error ? failure.reason.message : String(failure.reason)}`)
      } else {
        this.datumRetryAt.delete(e)
        this.datumErrors.delete(e)
      }
      const preview = !this.firstRendered && this.preview === e
      this.buildAfterDatums(e, preview ? features : e === this.supplement ? this.supplementSelection : e.features, preview)
      if (!this.firstRendered && !e.primitives.length && !this.datumJobs.size && !this.running && !this.queue.length) this.startBackground()
      this.report()
    })
    this.datumJobs.set(e, task)
    this.datumBatches.set(e, batch)
    this.pumpDatums()
    this.report()
  }

  private pumpDatums() {
    if (this.disposed || this.datumTimer !== null) return
    if (this.datumCompleted >= 64) {
      this.datumTimer = setTimeout(() => {
        this.datumTimer = null; this.datumCompleted = 0; this.pumpDatums()
      }, 0)
      return
    }
    // Only admitted samples reach terrain's request queue. Camera moves can
    // discard obsolete work before thousands of L20 requests are registered.
    while (this.datumRunning < DATUM_IN_FLIGHT) {
      let selected: DatumBatch | undefined, nearest = Infinity
      for (const [entry, batch] of this.datumBatches) {
        if (!batch.needed()) batch.next = batch.missing.length
        if (batch.next === batch.missing.length) {
          if (!batch.active) { this.datumBatches.delete(entry); batch.finish() }
          continue
        }
        const distance = this.distance(batch.missing[batch.next]!)
        if (distance < nearest) { nearest = distance; selected = batch }
      }
      if (!selected) break
      const batch = selected, feature = batch.missing[batch.next++]!
      this.datumRunning++; batch.active++
      void batch.sample(feature).catch(reason => { batch.failure ??= { reason } }).finally(() => {
        this.datumRunning--; batch.active--; this.datumCompleted++
        this.pumpDatums()
      })
    }
  }

  private distance(f: Footprint) {
    return (f.ring[0]![0]! - this.focusDegrees.lon) ** 2 + (f.ring[0]![1]! - this.focusDegrees.lat) ** 2
  }

  get supplementPending() { return Boolean(this.supplementController) }

  heightAt(lon: number, lat: number): number | undefined {
    if (!this.shown) return undefined
    let roof: number | undefined = this.baked?.heightAt(lon, lat)
    for (const e of [...this.entries.values(), this.supplement]) {
      if (!this.inView(e)) continue
      for (const f of e.visible) {
        if (!insideFootprint([lon, lat], f)) continue
        const z = this.base !== 'terrain' ? this.base : Number.isFinite(f.z) ? f.z! : this.datums.get(f)
        if (z !== undefined) roof = Math.max(roof ?? -Infinity, z + f.h)
      }
    }
    return roof
  }

  private scheduleWork() {
    if (this.disposed || this.workTimer !== null) return
    this.workTimer = setTimeout(() => {
      this.workTimer = null
      const deadline = performance.now() + WORK_MS
      // Re-rank every slice: response arrival order and the previous camera
      // position must not put distant geometry ahead of the current focus.
      const distance = (e: Entry) => {
        if (e === this.supplement) return 0
        const scale = 2 ** (BUILDING_ZOOM - e.tile.z)
        const dx = Math.max(e.tile.x * scale - this.focus[0], 0, this.focus[0] - (e.tile.x + 1) * scale)
        const dy = Math.max(e.tile.y * scale - this.focus[1], 0, this.focus[1] - (e.tile.y + 1) * scale)
        return dx * dx + dy * dy
      }
      const overview = (e: Entry) => e.tile.z === 13 && e !== this.supplement ? 0 : 1
      const ordered = [...this.work.keys()].sort((a, b) => overview(a) - overview(b) || distance(a) - distance(b))
      let index = 0
      let completed = false
      do {
        const entry = ordered[index]
        const job = entry ? this.work.get(entry) : undefined
        if (!job) break
        try {
          if (job.next().done) {
            if (entry) {
              this.work.delete(entry)
              const queued = this.datumRebuilds.get(entry)
              if (queued) this.build(entry, queued.features, queued.immediate)
            }
            index++
            completed = true
          }
        } catch (error) {
          if (entry) { this.work.delete(entry); this.datumRebuilds.delete(entry) }
          index++
          this.tileError = `건물 표시: ${error instanceof Error ? error.message : String(error)}`
          this.report()
        }
      } while (performance.now() < deadline)
      if (this.firstRendered && !this.work.size && !this.running && !this.queue.length) this.startBackground()
      if (completed) { this.report(); this.viewer.scene.requestRender() }
      if (this.work.size) this.scheduleWork()
    }, 0)
  }

  private buildAfterDatums(e: Entry, features: Footprint[], immediate: boolean) {
    // Let the visible prefix finish; later heights replace it once instead of discarding each slice.
    if (this.work.has(e)) { this.datumRebuilds.set(e, { features, immediate }); return }
    this.build(e, features, immediate)
  }

  private build(e: Entry, features = e.features, immediate = false) {
    this.datumRebuilds.delete(e)
    this.work.delete(e)
    // Finer replacements build while their coarse parent remains visible.
    // inView() is a drawing gate, not a work-admission gate.
    if (e !== this.supplement && !this.desired.has(e.tile.key) && !this.previous.has(e.tile.key)) {
      e.needsBuild = true; return
    }
    this.resolveDatums(e, features)
    e.needsBuild = true
    const job = this.buildGeometry(e, features, immediate)
    if (immediate) {
      for (const _ of job) { /* bounded first neighbourhood, before workers are loaded */ }
      this.report()
    }
    else { this.work.set(e, job); this.scheduleWork() }
  }

  private *buildGeometry(e: Entry, features: Footprint[], immediate: boolean): Generator<void> {
    const eligible = features.filter(f => !(e !== this.supplement && this.baked?.contains(f))
      && !(this.hideOnSite && this.site && inside(f.ring[0]!, this.site)))
    const visible = eligible.filter(f => this.base !== 'terrain' || Number.isFinite(f.z) || this.datums.has(f))
    const needsBuild = this.base === 'terrain' && eligible.some(f => !Number.isFinite(f.z) && !this.datums.has(f))
    if (e.primitives.length && visible.length === e.visible.length && visible.every((f, i) => {
      const z = this.base !== 'terrain' ? this.base : Number.isFinite(f.z) ? f.z! : this.datums.get(f)!
      const bottom = this.base !== 'terrain' ? this.base : Math.min(z, 0, this.level) - 12
      return f === e.visible[i] && e.heights[i] === z && e.bottoms?.[i] === bottom
    })) { e.needsBuild = needsBuild; return }
    const heights: number[] = [], bottoms: number[] = [], instances: any[] = []
    const instancesForMask: {id:string;feature:Footprint}[] = []
    for (const [i, f] of visible.entries()) {
      const ground = yield* this.ground(f)
      if (!ground) continue
      const { z, bottom } = ground
      heights[i] = z
      bottoms[i] = bottom
      instancesForMask.push({id:`${f.key}/${i}`,feature:f})
      instances.push(new this.C.GeometryInstance({ id: `${f.key}/${i}`,
          geometry: f.mesh && f.mesh.bottom === bottom && f.mesh.top === z + f.h ? preparedGeometry(this.C, f.mesh)
            : new this.C.PolygonGeometry({ polygonHierarchy: new this.C.PolygonHierarchy(
              this.C.Cartesian3.fromDegreesArray(f.ring.flat()),
              (f.holes ?? []).map(hole => new this.C.PolygonHierarchy(this.C.Cartesian3.fromDegreesArray(hole.flat())))),
            height: bottom, extrudedHeight: z + f.h, vertexFormat: this.C.PerInstanceColorAppearance.VERTEX_FORMAT,
            offsetAttribute: this.C.GeometryOffsetAttribute.ALL }),
          attributes: { show: this.C.ShowGeometryInstanceAttribute
              ? new this.C.ShowGeometryInstanceAttribute(true) : { value: new Uint8Array([1]) }, offset: new this.C.OffsetGeometryInstanceAttribute(0, 0, 0),
            color: this.C.ColorGeometryInstanceAttribute.fromColor(this.C.Color.fromCssColorString(buildingColor(f.s)).withAlpha(1)) } }))
      yield
    }
    if (e.primitives.length) this.retired.push({ primitives: e.primitives, replacement: e })
    e.primitives = []
    e.visible = visible; e.heights = heights; e.bottoms = bottoms; e.applied = [...heights]
    if (instances.length) {
      const primitive = this.viewer.scene.primitives.add(new this.C.Primitive({ geometryInstances: instances,
        asynchronous: !immediate, show: false, appearance: new this.C.PerInstanceColorAppearance({ closed: true, translucent: false }) }))
      e.primitives.push(primitive); this.instanceFeatures.set(primitive, instancesForMask)
    }
    e.needsBuild = needsBuild
    this.viewer.scene.requestRender()
  }

  setGround(base: Ground, level: number) {
    if (this.base === base && this.level === level) return
    this.base = base; this.level = level; this.ownershipRevision++
    this.baked?.setGround(base === 'terrain')
    for (const e of this.entries.values()) this.build(e)
    this.reconcileSupplement(true)
    if (this.lastView) this.load(this.lastView.box, this.lastView.focus, this.lastView.view)
  }

  setSite(site: number[][] | null, hide: boolean) {
    const old = this.site, wasHidden = this.hideOnSite
    this.site = site; this.hideOnSite = hide
    this.baked?.setSite(site, hide)
    for (const e of this.entries.values()) {
      if (e.features.some(f => Boolean(wasHidden && old && inside(f.ring[0]!, old)) !== Boolean(hide && site && inside(f.ring[0]!, site)))) this.build(e)
    }
    this.reconcileSupplement(true)
    this.report()
  }

  private inView(e: Entry): boolean {
    if (e === this.supplement || this.previous.has(e.tile.key)) return true
    if (!this.desired.has(e.tile.key)) return false
    // Replace independently by covered region, so one slow/failed tile cannot block the whole view.
    return ![...this.previous].some(key => {
      const old = this.entries.get(key)
      return old && tilesOverlap(old.tile, e.tile)
    })
  }

  /** Prepare every GPU mask before committing a source; no partially applied ownership. */
  private prepareOwnershipMasks(includeOffers = true): boolean {
    const maskRevision = this.ownershipRevision * 2 + Number(includeOffers)
    const primitives = [...this.entries.values(), this.supplement].flatMap(e => e.primitives)
      .concat(this.retired.flatMap(old => old.primitives))
    const writes: {attributes:any;visible:number}[] = [], prepared:any[] = []
    for (const primitive of primitives) {
      if (!primitive.ready || this.maskedRevision.get(primitive) === maskRevision) continue
      const features = this.instanceFeatures.get(primitive) ?? []
      if (features.length && this.baked && typeof primitive.getGeometryInstanceAttributes !== 'function') return false
      for (const {id,feature} of features) {
        if (!primitive.getGeometryInstanceAttributes) continue
        let attributes:any
        try { attributes = primitive.getGeometryInstanceAttributes(id) } catch { return false }
        if (!attributes?.show) return false
        const covered = this.baked?.contains(feature, true) || includeOffers && this.baked?.contains(feature)
        writes.push({attributes,visible:covered?0:1})
      }
      prepared.push(primitive)
    }
    for (const {attributes,visible} of writes) if (attributes.show[0] !== visible) attributes.show = new Uint8Array([visible])
    for (const primitive of prepared) this.maskedRevision.set(primitive, maskRevision)
    return true
  }

  private syncPrimitiveVisibility() {
    let changed = false
    const set = (p:any,visible:boolean) => { if (p.show !== visible) {p.show=visible;changed=true} }
    for (const e of [...this.entries.values(), this.supplement]) for (const p of e.primitives) {
      set(p,this.shown && this.inView(e) && p.ready !== false && this.maskedRevision.has(p))
    }
    for (const old of this.retired) for (const p of old.primitives) set(p,this.shown && this.inView(old.replacement))
    return changed
  }
  setShow(show: boolean) {
    this.shown = show
    this.baked?.setShow(show)
    this.syncPrimitiveVisibility()
    this.viewer.scene.requestRender()
  }

  async supplementNear(lon: number, lat: number) {
    const key = `${lon.toFixed(4)}/${lat.toFixed(4)}`
    if (key === this.supplementAt || this.disposed) return
    this.supplementAt = key
    this.supplementController?.abort()
    const controller = new AbortController()
    this.supplementController = controller
    this.supplement.features = []
    this.reconcileSupplement()
    this.supplementError = ''
    this.report()
    try {
      // Cold source assembly was measured at 13.6s before proxy/queue overhead.
      // Keep it cancellable and bounded without cutting off valid enrichment
      // just as it finishes; archive rendering continues independently.
      const result = await fetchContextBuildings(lat, lon, 320, AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]))
      if (this.disposed || controller.signal.aborted) return
      if (result.status !== 'ok') throw new Error(result.reason || '실시간 건물 자료 없음')
      const features: Footprint[] = []
      for (const [i, f] of (result.features?.features ?? []).entries()) {
        const polys = f.geometry?.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry?.type === 'MultiPolygon' ? f.geometry.coordinates : []
        const p = f.properties ?? {}
        for (const poly of polys) {
          if (poly[0]?.length < 4 || !(Number(p.height_m) > 0)) continue
          const datum = p.top_m != null ? Number(p.top_m) - Number(p.height_m) : undefined
          features.push({ key: `live/${p.id ?? i}`, pnu: String(p.pnu ?? ''), ring: poly[0], holes: poly.slice(1), h: Number(p.height_m),
            z: Number.isFinite(datum) ? datum : undefined,
            s: p.height_status === 'measured' ? 'm' : p.height_status === 'estimated' ? 'e' : 'u' })
        }
      }
      this.supplement.features = features
      this.reconcileSupplement()
    } catch (e) {
      if (!controller.signal.aborted && !this.disposed) {
        if (this.supplementController === controller) this.supplementAt = ''
        this.supplementError = `주변 신축 보강 실패: ${e instanceof Error ? e.message : String(e)}`
      }
    } finally {
      if (!this.disposed && this.supplementController === controller) { this.supplementController = null; this.report() }
    }
  }

  private reconcileSupplement(force = false) {
    const source = this.supplement.features
    const tiles = source.length ? [...this.entries.values()].filter(e => this.inView(e)).map(e => e.features) : []
    const last = this.supplementInputs
    if (!force && last?.source === source && last.tiles.length === tiles.length && tiles.every((features, i) => features === last.tiles[i])) return
    this.supplementInputs = { source, tiles }
    const indexes = tiles.map(features => {
      let index = this.footprintIndexes.get(features)
      if (!index) { index = new FootprintIndex(features); this.footprintIndexes.set(features, index) }
      return index
    })
    const accepted: Footprint[] = []
    for (const f of this.supplement.features) {
      if (!this.baked?.overlaps(f) && !indexes.some(index => index.overlaps(f)) && !accepted.some(t => overlaps(f, t))) accepted.push(f)
    }
    if (!force && accepted.length === this.supplementSelection.length && accepted.every((f, i) => f === this.supplementSelection[i])) return
    this.supplementSelection = accepted
    this.build(this.supplement, accepted)
  }

  private report() {
    // Geometry publishes a new visible array atomically. Progress-only updates
    // must not scan every city footprint again; visibility changes invalidate it.
    const geometry = [...this.entries.values(), this.supplement].filter(e => this.inView(e)).map(e => e.visible)
    if (geometry.length !== this.reportedGeometry.length || geometry.some((items, i) => items !== this.reportedGeometry[i])) {
      const counts = emptyCounts(), seen = new Set<string>()
      for (const items of geometry) for (const f of items) {
        if (seen.has(f.key)) continue
        seen.add(f.key)
        counts[f.s === 'm' ? 'measured' : f.s === 'e' ? 'estimated' : 'unknown']++
      }
      this.reportedGeometry = geometry; this.reportedCounts = counts
    }
    const counts = { ...this.reportedCounts }
    if (this.baked && this.shown && this.base === 'terrain') {
      counts.measured += this.baked.counts.measured
      counts.estimated += this.baked.counts.estimated
      counts.unknown += this.baked.counts.unknown
    }
    this.changed(counts, this.running + this.queue.length + this.work.size + this.datumJobs.size + Number(Boolean(this.supplementController)), [this.tileError, this.baked?.error, this.supplementError, ...this.datumErrors.values()].filter(Boolean).join(' · '))
  }

  private remove(e: Entry) {
    e.request?.abort()
    clearTimeout(this.datumUpdates.get(e)); this.datumUpdates.delete(e)
    this.work.delete(e)
    this.datumRebuilds.delete(e)
    this.datumErrors.delete(e)
    for (const p of e.primitives) this.viewer.scene.primitives.remove(p)
    e.primitives = []
    this.retired = this.retired.filter(old => {
      if (old.replacement !== e) return true
      for (const p of old.primitives) this.viewer.scene.primitives.remove(p)
      return false
    })
  }

  dispose() {
    this.disposed = true
    clearTimeout(this.backgroundTimer)
    this.baked?.dispose()
    this.decoder?.dispose()
    if (this.workTimer !== null) clearTimeout(this.workTimer)
    if (this.datumTimer !== null) clearTimeout(this.datumTimer)
    this.workTimer = null; this.work.clear(); this.datumRebuilds.clear(); this.datumJobs.clear(); this.datumErrors.clear()
    for (const batch of this.datumBatches.values()) batch.finish()
    this.datumBatches.clear()
    for (const timer of this.datumUpdates.values()) clearTimeout(timer)
    this.datumUpdates.clear()
    this.controller.abort(); this.supplementController?.abort(); this.removeRender()
    for (const e of [...this.entries.values(), this.supplement]) this.remove(e)
    for (const old of this.retired) for (const p of old.primitives) this.viewer.scene.primitives.remove(p)
    this.retired = []
    this.entries.clear(); this.queue = []
  }
}
