/* eslint-disable @typescript-eslint/no-explicit-any */
import { inside } from './building-geometry'
import type { HeightCounts } from './context-masses'
import { mapAssetUrl } from './map-asset-url'
import type { NationalBuildingSource } from './national-building-source'

const empty = (): HeightCounts => ({ measured: 0, estimated: 0, unknown: 0 })

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
  backgroundReady = false
  firstRenderedAt: number | null = null

  constructor(private viewer: any, private C: any, source: NationalBuildingSource,
    private changed: (counts: HeightCounts, pending: number, error: string) => void,
    private firstFrame?: () => void) {
    this.removes.push(viewer.scene.preRender.addEventListener(() => this.visible.clear()))
    this.removes.push(viewer.scene.postRender.addEventListener(() => this.report()))
    void this.open(source)
  }

  private async open(source: NationalBuildingSource) {
    try {
      const tileset = await this.C.Cesium3DTileset.fromUrl(mapAssetUrl('world-buildings', source.url), {
        maximumScreenSpaceError: 16, dynamicScreenSpaceError: true, foveatedScreenSpaceError: true,
        progressiveResolutionHeightFraction: 0.3, preloadFlightDestinations: false, preloadWhenHidden: false,
        cacheBytes: 192 * 1024 * 1024, maximumCacheOverflowBytes: 32 * 1024 * 1024,
      })
      if (this.disposed) { tileset.destroy(); return }
      this.tileset = tileset
      tileset.show = this.shown
      tileset.colorBlendMode = this.C.Cesium3DTileColorBlendMode.REPLACE
      if (tileset.imageBasedLighting) {
        tileset.imageBasedLighting.imageBasedLightingFactor = new this.C.Cartesian2(1, 0)
        tileset.imageBasedLighting.sphericalHarmonicCoefficients = Array.from({ length: 9 }, (_, i) =>
          new this.C.Cartesian3(i === 0 ? 1 : 0, i === 0 ? 1 : 0, i === 0 ? 1 : 0))
      }
      this.removes.push(tileset.tileVisible.addEventListener((tile: any) => this.style(tile.content)))
      this.removes.push(tileset.tileFailed.addEventListener((failure: { message: string }) => {
        this.error = `전국 건물 타일: ${failure.message}`; this.report()
      }))
      this.viewer.scene.primitives.add(tileset)
      this.viewer.scene.requestRender()
    } catch (error) {
      if (!this.disposed) { this.error = String(error); this.report() }
    }
  }

  private style(content: any) {
    if (this.disposed) return
    if (content.innerContents?.length) { for (const child of content.innerContents) this.style(child); return }
    let cached = this.styled.get(content)
    if (!cached || cached.revision !== this.revision) {
      const counts = empty()
      for (let i = 0; i < content.featuresLength; i++) {
        const feature = content.getFeature(i)
        feature.show = !(this.hide && this.site && inside([feature.getProperty('lon'), feature.getProperty('lat')], this.site))
        feature.color = this.C.Color.fromCssColorString('#fbfbf9').withAlpha(1)
        if (feature.show) counts[feature.getProperty('status') === 'm' ? 'measured' : feature.getProperty('status') === 'e' ? 'estimated' : 'unknown']++
      }
      cached = { revision: this.revision, counts }; this.styled.set(content, cached)
    }
    this.visible.set(content, cached.counts)
    if (!this.backgroundReady) {
      this.backgroundReady = true
      this.firstRenderedAt = performance.now()
      performance.mark('world-buildings-first-render')
      queueMicrotask(() => { if (!this.disposed) this.firstFrame?.() })
    }
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
