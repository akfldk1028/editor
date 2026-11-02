/* eslint-disable @typescript-eslint/no-explicit-any */
import { inside, overlaps } from './building-geometry'
import type { HeightCounts } from './context-masses'
import { mapAssetUrl } from './map-asset-url'
import type { NationalBuildingSource } from './national-building-source'

const empty = (): HeightCounts => ({ measured: 0, estimated: 0, unknown: 0 })
const STAND_IN_MAX_ERROR = 2000
export const AMBIENT = 0.35

/** One hierarchical tileset: Cesium retains coarse parents while refining children. */
export class NationalBuildings {
  private tileset: any
  private disposed = false
  private shown = true
  private site: number[][] | null = null
  private hide = false
  private revision = 0
  private styled = new WeakMap<object, { revision: number; counts: HeightCounts }>()
  private visible = new Map<object, HeightCounts>()
  private removes: (() => void)[] = []
  private lastReport = ''
  private error = ''
  private white: any
  private detailSeen = false
  backgroundReady = false
  firstRenderedAt: number | null = null

  constructor(private viewer: any, private C: any, source: NationalBuildingSource,
    private changed: (counts: HeightCounts, pending: number, error: string) => void,
    private firstFrame?: () => void) {
    this.removes.push(viewer.scene.preRender.addEventListener(() => this.visible.clear()))
    this.removes.push(viewer.scene.postRender.addEventListener(() => {
      this.report()
      // requestRenderMode: Cesium asks for a render only after the *next* frame when a tile request or decode
      // completes, so an idle scene advances one tile level per unrelated render (~1 s). Keep frames coming
      // while tiles are pending or processing; the scene goes idle again once the tileset has loaded.
      if (this.tileset && this.shown && !this.tileset.tilesLoaded) viewer.scene.requestRender()
    }))
    void this.open(source)
  }

  private async open(source: NationalBuildingSource) {
    try {
      const url = mapAssetUrl('world-buildings', source.url), origin = new URL(url, globalThis.location?.href ?? 'http://localhost/')
      // Plain-http (HTTP/1.1) hosts run 6 connections; letting Cesium queue 18 hands priority to the browser's FIFO,
      // so near tiles and tileset JSON wait behind far b3dm. Cesium orders and cancels when it owns the queue.
      if (origin.protocol === 'http:' && this.C.RequestScheduler?.requestsByServer)
        this.C.RequestScheduler.requestsByServer[`${origin.hostname}:${origin.port || '80'}`] = 6
      const tileset = await this.C.Cesium3DTileset.fromUrl(url, {
        // 32 px: generalized region roots (v4: ~20-30 m error) must hand over to leaves before ~400 m near views
        // (64 kept merged blocks at Busan near). Measured on v4: near = leaves, mid zoom 2.0 s / 2.7 MB.
        maximumScreenSpaceError: 32, dynamicScreenSpaceError: true, foveatedScreenSpaceError: true,
        progressiveResolutionHeightFraction: 0.3, preloadFlightDestinations: false, preloadWhenHidden: false,
        // Local tiles answer in ~15 ms: request during zoom/pan inertia and at the screen edges at once instead of
        // waiting for the camera to stop (+0.2 s foveated delay). Cesium cancels requests for tiles no longer visited.
        cullRequestsWhileMoving: false, foveatedTimeDelay: 0,
        // Load only the tiles that meet the error budget: region roots and z15 repeat every leaf building (~4 MB each),
        // and REPLACE base traversal also waits for every off-screen sibling. Busan near: 79.5 MB / 11.4 s -> 3.1 MB / 1.3 s.
        skipLevelOfDetail: true, immediatelyLoadDesiredLevelOfDetail: true,
        cacheBytes: 512 * 1024 * 1024, maximumCacheOverflowBytes: 128 * 1024 * 1024,
      })
      if (this.disposed) { tileset.destroy(); return }
      this.tileset = tileset
      this.white = this.C.Color.fromCssColorString('#fbfbf9').withAlpha(1)
      tileset.show = this.shown
      tileset.colorBlendMode = this.C.Cesium3DTileColorBlendMode.REPLACE
      if (tileset.imageBasedLighting) {
        tileset.imageBasedLighting.imageBasedLightingFactor = new this.C.Cartesian2(1, 0)
        // Low uniform ambient so the scene's key light shades walls apart from roofs (1 washed every face white).
        tileset.imageBasedLighting.sphericalHarmonicCoefficients = Array.from({ length: 9 }, (_, i) =>
          new this.C.Cartesian3(i === 0 ? AMBIENT : 0, i === 0 ? AMBIENT : 0, i === 0 ? AMBIENT : 0))
      }
      this.removes.push(tileset.tileVisible.addEventListener((tile: any) => this.style(tile.content, this.standIn(tile), tile.geometricError === 0)))
      this.removes.push(tileset.tileFailed.addEventListener((failure: { message: string }) => {
        this.error = `전국 건물 타일: ${failure.message}`; this.report()
      }))
      this.viewer.scene.primitives.add(tileset)
      this.viewer.scene.requestRender()
    } catch (error) {
      if (!this.disposed) { this.error = String(error); this.report() }
    }
  }

  // Cesium refines against memoryAdjustedScreenSpaceError; a REPLACE parent past it is drawn only while its
  // children load. Under cache pressure the parent is final, and hiding it would leave a hole.
  private standIn(tile: any) {
    // Legacy fine aggregates (z12-z13 class, error <= ~2 km) read as a simplified city: let them stand in while detail loads.
    if (tile.geometricError <= STAND_IN_MAX_ERROR) return false
    if (!(tile._screenSpaceError > (this.tileset.memoryAdjustedScreenSpaceError ?? this.tileset.maximumScreenSpaceError))) return false
    // A failed child (or failed root of a child's external tileset) never loads, so the parent stays final there.
    return !(tile.children ?? []).some((c: any) => c.contentFailed || c.children?.[0]?.contentFailed)
  }

  private style(content: any, standIn = false, leaf = false) {
    if (this.disposed) return
    if (content.innerContents?.length) { for (const child of content.innerContents) this.style(child, standIn, leaf); return }
    // Legacy global HLOD (occupied-quadtree-v1: componentCount, no lodBlock) is one ground-to-tallest-roof box per
    // cell; up close it reads as a white slab, so it is shown only at its own level of detail. The generalized HLOD
    // (v2) carries lodBlock and bbox columns: its city blocks are the believable placeholder while children load.
    const first = content.featuresLength ? content.getFeature(0) : undefined
    if (standIn && first?.hasProperty?.('componentCount') && !first.hasProperty('lodBlock')) {
      for (let i = 0; i < content.featuresLength; i++) content.getFeature(i).show = false
      // Restyle from scratch when it becomes final again, so site hiding is re-applied.
      this.styled.delete(content)
      return
    }
    let cached = this.styled.get(content)
    if (!cached || cached.revision !== this.revision) {
      const counts = empty()
      for (let i = 0; i < content.featuresLength; i++) {
        const feature = content.getFeature(i)
        feature.show = !(this.hide && this.site && this.onSite(feature, this.site))
        feature.color = this.white
        // A merged block stands for many buildings it does not list; count buildings only where they are individual.
        if (feature.show && feature.getProperty('lodBlock') !== 1) counts[feature.getProperty('status') === 'm' ? 'measured' : feature.getProperty('status') === 'e' ? 'estimated' : 'unknown']++
      }
      cached = { revision: this.revision, counts }; this.styled.set(content, cached)
    }
    this.visible.set(content, cached.counts)
    // Leaf detail only (zero geometric error): carried bake roots have neither componentCount nor lodBlock.
    if (!this.detailSeen && leaf && content.featuresLength) {
      this.detailSeen = true; performance.mark('world-buildings-first-detail')
    }
    if (!this.backgroundReady) {
      this.backgroundReady = true
      this.firstRenderedAt = performance.now()
      performance.mark('world-buildings-first-render')
      queueMicrotask(() => { if (!this.disposed) this.firstFrame?.() })
    }
  }

  // A generalized region root carries each feature's bbox. A merged block can span a kilometre around the site, so
  // it is never hidden (leaves take over near the site); a landmark is one building and hides when its bbox touches
  // the site. Leaf buildings keep the point test.
  private onSite(feature: any, site: number[][]) {
    if (feature.getProperty('lodBlock') === 1) return false
    if (!feature.hasProperty?.('west')) return inside([feature.getProperty('lon'), feature.getProperty('lat')], site)
    const [w, s, e, n] = ['west', 'south', 'east', 'north'].map(k => feature.getProperty(k) as number) as [number, number, number, number]
    return overlaps({ key: '', pnu: '', h: 0, s: 'u', ring: [[w, s], [e, s], [e, n], [w, n], [w, s]] }, { key: '', pnu: '', h: 0, s: 'u', ring: site })
  }

  private report() {
    if (this.disposed) return
    const counts = empty()
    if (this.shown) for (const row of this.visible.values()) {
      counts.measured += row.measured; counts.estimated += row.estimated; counts.unknown += row.unknown
    }
    const pending = this.tileset?.tilesLoaded ? 0 : Number(!this.error)
    const key = JSON.stringify([counts, pending, this.error])
    if (key !== this.lastReport) { this.lastReport = key; this.changed(counts, pending, this.error) }
  }

  load(..._view: unknown[]) { this.viewer.scene.requestRender() }
  setSite(site: number[][] | null, hide: boolean) { this.site = site; this.hide = hide; this.revision++; this.viewer.scene.requestRender() }
  setShow(show: boolean) { this.shown = show; if (this.tileset) this.tileset.show = show; this.viewer.scene.requestRender() }
  // Geometry has publication-pinned ground heights; switching a UI plane cannot move it.
  setGround(..._ground: unknown[]) {}
  // No runtime-vector supplements in this renderer.
  async supplementNear(..._position: unknown[]) {}
  heightAt(_lon: number, _lat: number): number | undefined { return undefined }
  dispose() {
    this.disposed = true
    for (const remove of this.removes) remove()
    this.removes = []; this.visible.clear()
    if (this.tileset) this.viewer.scene.primitives.remove(this.tileset)
  }
}
