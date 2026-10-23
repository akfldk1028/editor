/* eslint-disable @typescript-eslint/no-explicit-any */
import { BUILDING_ZOOM, decodeBuildings, inside, overlaps, tileXY, tilesIn, type BuildingTile, type Footprint } from './building-geometry'
import { fetchContextBuildings, type Ground, type HeightCounts } from './context-masses'

type Entry = { tile: BuildingTile; features: Footprint[]; primitives: any[]; heights: number[]; bottoms?: number[]; applied?: number[]; visible: Footprint[] }
const KEEP = 58
const emptyCounts = (): HeightCounts => ({ measured: 0, estimated: 0, unknown: 0 })
let libraries: Promise<any[]> | null = null
function loadLibraries() {
  if (!libraries) libraries = Promise.all([
    'https://cdn.jsdelivr.net/npm/pmtiles@3.2.1/+esm',
    'https://cdn.jsdelivr.net/npm/pbf@4.0.1/+esm',
    'https://cdn.jsdelivr.net/npm/@mapbox/vector-tile@2.0.3/+esm',
  ].map(url => import(/* webpackIgnore: true */ /* turbopackIgnore: true */ url))).catch(e => { libraries = null; throw e })
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
  const [libs, response] = await Promise.all([loadLibraries(), fetch(`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/context-tiles`)])
  const manifest = await response.json()
  if (!response.ok) throw new Error(manifest.detail || `건물 타일 ${response.status}`)
  const archive = new libs[0].PMTiles(manifest.href)
  await archive.getHeader()
  return { archive, Pbf: libs[1].default, VectorTile: libs[2].VectorTile }
}

export class BuildingTiles {
  private archive: any = null
  private Pbf: any
  private VectorTile: any
  private opening: Promise<void> | null = null
  private disposed = false
  private entries = new Map<string, Entry>()
  private queue: BuildingTile[] = []
  private desired = new Set<string>()
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
  private supplement: Entry = { tile: { x: 0, y: 0, key: 'supplement' }, features: [], primitives: [], heights: [], visible: [] }
  private removeRender: () => void
  private lastRefresh = 0
  // Set when the globe finished loading terrain tiles: only then can the drawn ground under a building have moved.
  private groundChanged = true
  private tileError = ''
  private supplementError = ''
  private firstRendered = false
  backgroundReady = false
  private preview: Entry | null = null
  private retired: { primitives: any[]; replacement: Entry }[] = []
  readonly startedAt = performance.now()
  firstRenderedAt: number | null = null

  constructor(private viewer: any, private C: any, private changed: (counts: HeightCounts, pending: number, error: string) => void,
    private prepared?: ReturnType<typeof prepareBuildingTiles>, private firstFrame?: () => void) {
    const removeRendered = viewer.scene.postRender.addEventListener(() => {
      if (!this.firstRendered && [...this.entries.values()].some(e => e.primitives.some(p => p.ready))) {
        this.firstRendered = true
        this.firstRenderedAt = performance.now()
        performance.mark('world-buildings-first-render')
        for (const e of this.entries.values()) {
          if (e === this.preview) {
            this.retired.push({ primitives: e.primitives, replacement: e })
            e.primitives = []
          }
          this.build(e)
        }
        this.report()
        this.startBackground()
      }
      this.retired = this.retired.filter(old => {
        if (old.replacement.primitives.some(p => !p.ready)) return true
        for (const p of old.primitives) this.viewer.scene.primitives.remove(p)
        return false
      })
    })
    // Re-seating every building on the drawn ground reads globe.getHeight at each footprint vertex (~0.5 s on 684-1).
    // Run on every rendered frame it held the main thread ~70% of the time while DEM tiles streamed in (one every
    // 5-12 s, each rendering): it runs only after terrain tiles finished loading, and at most once a second.
    const removeProgress = viewer.scene.globe.tileLoadProgressEvent.addEventListener(() => { this.groundChanged = true })
    const removeUpdate = viewer.scene.postUpdate.addEventListener(() => {
      if (!this.groundChanged || performance.now() - this.lastRefresh < 1000) return
      this.lastRefresh = performance.now()
      this.groundChanged = false
      if (this.base === 'terrain') this.refreshHeights()
    })
    this.removeRender = () => { removeRendered(); removeUpdate(); removeProgress() }
    // Cesium's credit container keeps attribution on every surface sharing this viewer.
    viewer.scene.frameState.creditDisplay.addStaticCredit(new C.Credit('건물: 국토교통부 GIS건물통합정보 (공공누리 제1유형)', true))
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

  load(box: [number, number, number, number], focus: { lon: number; lat: number }) {
    if (this.disposed) return
    this.focus = tileXY(focus.lon, focus.lat)
    this.focusDegrees = focus
    this.requestedView = true
    const visible = tilesIn(box, focus)
    this.desired = new Set(visible.map(t => t.key))
    this.queue = visible.filter(t => !this.entries.has(t.key))
    this.setShow(this.shown)
    this.evict()
    this.selectPreview()
    if (!this.archive) void this.open()
    else this.pump()
  }

  private pump() {
    if (!this.archive || this.disposed) return
    while (this.running < 8 && this.queue.length) {
      const tile = this.queue.shift()!
      if (this.entries.has(tile.key)) continue
      const entry: Entry = { tile, features: [], primitives: [], heights: [], visible: [] }
      this.entries.set(tile.key, entry)
      this.running++
      this.archive.getZxy(BUILDING_ZOOM, tile.x, tile.y, this.controller.signal).then((result: any) => {
        if (this.disposed || this.entries.get(tile.key) !== entry) return
        entry.features = result ? decodeBuildings(result.data, tile, this.Pbf, this.VectorTile) : []
        if (this.firstRendered) this.build(entry)
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
    if (this.requestedView && !this.running && !this.queue.length && !this.preview) this.startBackground()
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
    if (nearest) { this.preview = nearest.e; this.build(nearest.e, [nearest.f]) }
  }

  private evict() {
    const distance = (e: Entry) => (e.tile.x - this.focus[0]) ** 2 + (e.tile.y - this.focus[1]) ** 2
    const far = [...this.entries.values()].sort((a, b) => distance(b) - distance(a)).slice(0, Math.max(0, this.entries.size - KEEP))
    for (const e of far) { this.remove(e); this.entries.delete(e.tile.key) }
    if (far.length) this.reconcileSupplement()
  }

  private height(f: Footprint): number {
    if (this.base !== 'terrain') return this.base
    // Follow the surface actually drawn while DEM tiles arrive or fall back flat. An offline DEM z alone would
    // leave buildings suspended above the temporary flat globe; getHeight is local and never issues a request.
    const p = f.ring[0]!
    const drawn = this.viewer.scene.globe.getHeight(this.C.Cartographic.fromDegrees(p[0], p[1]))
    if (!Number.isFinite(drawn)) return this.level
    return f.z != null && Math.abs(f.z - drawn) < 1 ? f.z : drawn
  }

  private distance(f: Footprint) {
    return (f.ring[0]![0]! - this.focusDegrees.lon) ** 2 + (f.ring[0]![1]! - this.focusDegrees.lat) ** 2
  }

  get supplementPending() { return Boolean(this.supplementController) }

  private build(e: Entry, features = e.features) {
    this.remove(e)
    e.visible = features.filter(f => !(this.hideOnSite && this.site && inside(f.ring[0]!, this.site)))
    e.heights = e.visible.map(f => this.height(f))
    e.bottoms = []
    e.applied = [...e.heights]
    for (const unknown of [false, true]) {
      const instances = e.visible.flatMap((f, i) => {
        if ((f.s === 'u') !== unknown) return []
        const z = e.heights[i]!
        // The skirt hides interpolation gaps on slopes without raising the roof.
        const bottom = this.base === 'terrain' ? Math.min(z, ...f.ring.map(p => {
          const h = this.viewer.scene.globe.getHeight(this.C.Cartographic.fromDegrees(p[0], p[1]))
          return Number.isFinite(h) ? h : z
        })) - 12 : z
        e.bottoms![i] = bottom
        return [new this.C.GeometryInstance({ id: `${f.key}/${i}`,
          geometry: this.C.PolygonGeometry.fromPositions({ positions: this.C.Cartesian3.fromDegreesArray(f.ring.flat()),
            height: bottom, extrudedHeight: z + f.h, vertexFormat: this.C.PerInstanceColorAppearance.VERTEX_FORMAT,
            offsetAttribute: this.C.GeometryOffsetAttribute.ALL }),
          attributes: { offset: new this.C.OffsetGeometryInstanceAttribute(0, 0, 0),
            color: this.C.ColorGeometryInstanceAttribute.fromColor(this.C.Color.fromCssColorString(unknown ? '#ffffff' : '#fbfbf9').withAlpha(unknown ? 0.55 : 1)) } })]
      })
      if (instances.length) e.primitives.push(this.viewer.scene.primitives.add(new this.C.Primitive({ geometryInstances: instances,
        asynchronous: true, show: this.shown && (e === this.supplement || this.desired.has(e.tile.key)), appearance: new this.C.PerInstanceColorAppearance({ closed: true, translucent: unknown }) })))
    }
    this.viewer.scene.requestRender()
  }

  private refreshHeights() {
    for (const e of [...this.entries.values(), this.supplement]) {
      if (e.primitives.some(p => !p.ready)) continue
      // A newly resolved terrace can fall farther than the original skirt. Rebuild only for that geometry change,
      // retaining the previous batch until ready; ordinary elevation changes only update the instance offsets.
      if (!this.retired.length && e.visible.some((f, i) => {
        const bottom = e.bottoms?.[i] ?? e.heights[i]!
        const movedBottom = bottom + this.height(f) - e.heights[i]!
        return f.ring.some(p => {
          const h = this.viewer.scene.globe.getHeight(this.C.Cartographic.fromDegrees(p[0], p[1]))
          return Number.isFinite(h) && movedBottom > h - 2
        })
      })) {
        this.retired.push({ primitives: e.primitives, replacement: e })
        e.primitives = []
        this.build(e, e === this.supplement ? e.visible : e.features)
        continue
      }
      for (const [i, f] of e.visible.entries()) {
        const z = this.height(f), point = f.ring[0]!
        if (Math.abs(z - (e.applied?.[i] ?? e.heights[i]!)) < 0.25) continue
        const delta = this.C.Cartesian3.subtract(this.C.Cartesian3.fromDegrees(point[0], point[1], z),
          this.C.Cartesian3.fromDegrees(point[0], point[1], e.heights[i]), new this.C.Cartesian3())
        for (const primitive of e.primitives) {
          const attributes = primitive.getGeometryInstanceAttributes(`${f.key}/${i}`)
          if (attributes) attributes.offset = this.C.OffsetGeometryInstanceAttribute.toValue(delta, attributes.offset)
        }
        e.applied![i] = z
        this.viewer.scene.requestRender()
      }
    }
  }

  setGround(base: Ground, level: number) {
    if (this.base === base && this.level === level) return
    this.base = base; this.level = level
    for (const e of this.entries.values()) this.build(e)
    this.reconcileSupplement()
  }

  setSite(site: number[][] | null, hide: boolean) {
    const old = this.site, wasHidden = this.hideOnSite
    this.site = site; this.hideOnSite = hide
    for (const e of this.entries.values()) {
      if (e.features.some(f => Boolean(wasHidden && old && inside(f.ring[0]!, old)) !== Boolean(hide && site && inside(f.ring[0]!, site)))) this.build(e)
    }
    this.reconcileSupplement()
    this.report()
  }

  setShow(show: boolean) {
    this.shown = show
    for (const e of [...this.entries.values(), this.supplement]) for (const p of e.primitives) p.show = show && (e === this.supplement || this.desired.has(e.tile.key))
    for (const old of this.retired) for (const p of old.primitives) p.show = show && this.desired.has(old.replacement.tile.key)
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
      const result = await fetchContextBuildings(lat, lon, 320, AbortSignal.any([controller.signal, AbortSignal.timeout(15_000)]))
      if (this.disposed || controller.signal.aborted) return
      if (result.status !== 'ok') throw new Error(result.reason || '실시간 건물 자료 없음')
      const features: Footprint[] = []
      for (const [i, f] of (result.features?.features ?? []).entries()) {
        const polys = f.geometry?.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry?.type === 'MultiPolygon' ? f.geometry.coordinates : []
        const p = f.properties ?? {}
        for (const poly of polys) {
          if (poly[0]?.length < 4 || !(Number(p.height_m) > 0)) continue
          features.push({ key: `live/${p.id ?? i}`, pnu: String(p.pnu ?? ''), ring: poly[0], h: Number(p.height_m),
            s: p.height_status === 'measured' ? 'm' : p.height_status === 'estimated' ? 'e' : 'u' })
        }
      }
      this.supplement.features = features
      this.reconcileSupplement()
    } catch (e) {
      if (!controller.signal.aborted && !this.disposed) {
        this.supplementError = `주변 신축 보강 실패: ${e instanceof Error ? e.message : String(e)}`
      }
    } finally {
      if (!this.disposed && this.supplementController === controller) { this.supplementController = null; this.report() }
    }
  }

  private reconcileSupplement() {
    const tiled = [...this.entries.values()].flatMap(e => e.features)
    const accepted: Footprint[] = []
    for (const f of this.supplement.features) {
      if (!tiled.some(t => overlaps(f, t)) && !accepted.some(t => overlaps(f, t))) accepted.push(f)
    }
    this.build(this.supplement, accepted)
  }

  private report() {
    const counts = emptyCounts(), seen = new Set<string>()
    for (const e of [...this.entries.values(), this.supplement]) for (const f of e === this.supplement || this.desired.has(e.tile.key) ? e.visible : []) {
      if (seen.has(f.key)) continue
      seen.add(f.key)
      counts[f.s === 'm' ? 'measured' : f.s === 'e' ? 'estimated' : 'unknown']++
    }
    this.changed(counts, this.running + this.queue.length + Number(Boolean(this.supplementController)), [this.tileError, this.supplementError].filter(Boolean).join(' · '))
  }

  private remove(e: Entry) {
    for (const p of e.primitives) this.viewer.scene.primitives.remove(p)
    e.primitives = []
  }

  dispose() {
    this.disposed = true
    this.controller.abort(); this.supplementController?.abort(); this.removeRender()
    for (const e of [...this.entries.values(), this.supplement]) this.remove(e)
    for (const old of this.retired) for (const p of old.primitives) this.viewer.scene.primitives.remove(p)
    this.retired = []
    this.entries.clear(); this.queue = []
  }
}
