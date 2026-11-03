/**
 * Our own Cesium world: white context masses and the diagram ground (parcels, roads, land cover), loaded cell by
 * cell as the camera moves — no VWorld SDK or key. It returns the same actions as useVworld3D (highlightParcel,
 * clearHighlight, flyTo, setBuildingsVisible, viewerRef), so the design view's mass and setback renderers work on
 * either world.
 *
 * The ground is the NGII DEM terrain (via SiteContext, toggle `terrain`); with it off, or where the DEM has no answer,
 * the ground is flat at one level (setGroundLevel, e.g. the site's §119 datum), so a mass placed at its datum stands on it.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { type RefObject, useCallback, useEffect, useRef, useState } from 'react'
import { MAP_CONFIG_3D } from '../../land-map/lib/constants'
import { SETBACK_COLORS, SETBACK_DS_NAME } from '../../land-map/lib/vworld-3d-scene'
import { acquireCesium } from '../lib/cesium-loader'
import { CELL_RADIUS_M, MAX_ALTITUDE_M, MAX_CELLS, cellsIn, visibleBox } from '../lib/context-cells'
import { type Ground, type HeightCounts, createGroundStages, drawGroundIncrementally } from '../lib/context-masses'
import { cachedGround, refreshGroundBoundaries, type GroundDetail } from '../lib/ground-cache'
import { type GroundStages, nextGroundRequest } from '../lib/ground-stages'
import { clearLayout as clearLayoutEntities, drawLayout as drawLayoutEntities, showUnderground, type IntentView, type LayoutView } from '../lib/layout-masses'
import { demTerrain } from '../lib/terrain'
import { prepareWorldBuildingRenderer, type WorldBuildingRenderer } from '../lib/world-building-renderer'
import { defaultMapReleaseReader } from '../lib/map-release'
import { placeSiteCamera } from '../lib/site-camera'
import { GroundLayer } from '../lib/ground-layer'
import { GroundResidency } from '../lib/ground-residency'
import { CameraMotion } from '../lib/camera-motion'
import { addCurrentSetback } from '../lib/setback-load'
import { prewarmTerrainAt } from '../lib/terrain-prewarm'
import { prepareGroundImagery } from '../lib/ground-imagery'

const PARALLEL = 3
export type WorldBase = 'white' | 'vworld2d'
export type WorldLayers = { buildings: boolean; ground: boolean; cover: boolean }

function ringOf(geometry: any): number[][] | null {
  const g = geometry?.type === 'Feature' ? geometry.geometry : geometry
  if (g?.type === 'Polygon') return g.coordinates[0]
  if (g?.type === 'MultiPolygon') return g.coordinates[0][0]
  return null
}

function inside(lon: number, lat: number, ring: number[][]): boolean {
  let hit = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!, [xj, yj] = ring[j]!
    if ((yi! > lat) !== (yj! > lat) && lon < ((xj! - xi!) * (lat - yi!)) / (yj! - yi!) + xi!) hit = !hit
  }
  return hit
}

export function useWorld3D({ target, onClick, initialLocation, initializeCamera }: { target: RefObject<HTMLDivElement | null>; onClick?: (lng: number, lat: number) => void; initialLocation?: readonly [number, number]; initializeCamera?: (viewer: any, C: any, sample: (lon: number, lat: number) => Promise<number>, live: () => boolean) => Promise<unknown> | void }) {
  const openingLocation = useRef(initialLocation)
  const openingCamera = useRef(initializeCamera)
  const viewerRef = useRef<any>(null)
  const cesiumRef = useRef<any>(null)
  const layers = useRef<{ buildings: any; ground: any; cover: any; layout: any } | null>(null)
  const asked = useRef(new Set<string>())
  const queue = useRef<{ key: string; cellKey: string; lat: number; lon: number; detail: GroundDetail }[]>([])
  const running = useRef(0)
  const cameraMoving = useRef(false)
  const groundRequests = useRef(new Map<AbortController, { cellKey: string; key: string; detail: GroundDetail }>())
  const roadsReady = useRef(new Set<string>())
  const groundGaps = useRef(new Set<string>())
  const groundStages = useRef<GroundStages | null>(null)
  const groundResidency = useRef(new GroundResidency(MAX_CELLS))
  const placement = useRef(0)
  const setbackGeneration = useRef(0)
  const pumpRef = useRef<() => void>(() => {})
  const level = useRef(0)
  const tileBuildings = useRef<WorldBuildingRenderer | null>(null)
  const supplementStarted = useRef(false)
  const terrainOn = useRef(true)
  const generation = useRef(0)   // bumped whenever the drawn context is thrown away
  const site = useRef<number[][] | null>(null)
  const outline = useRef<number[][] | null>(null)   // the highlighted parcel's outline (may differ from site after clearHighlight)
  const terrainProvider = useRef<any>(null)
  const hideOnSite = useRef(false)
  const clickRef = useRef(onClick)
  clickRef.current = onClick
  const [ready, setReady] = useState(false)
  // Ground imagery descriptor/headers start with the viewer, not after the opening camera settles.
  const groundPrefetch = useRef<{ promise: ReturnType<typeof prepareGroundImagery>; controller: AbortController } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState('3D 엔진 불러오는 중…')
  const [base, setBase] = useState<WorldBase>('white')
  const [show, setShow] = useState<WorldLayers>({ buildings: true, ground: true, cover: true })
  const shown = useRef(show)
  shown.current = show
  const coarseGround = useRef<{ kind: 'roads' | 'landcover'; layer: any }[]>([])
  const [terrain, setTerrain] = useState(true)
  const [buildings, setBuildings] = useState(0)
  const [counts, setCounts] = useState<HeightCounts>({ measured: 0, estimated: 0, unknown: 0 })
  const [pending, setPending] = useState(0)
  const [tilePending, setTilePending] = useState(0)
  const [buildingStatus, setBuildingStatus] = useState('')
  const [terrainStatus, setTerrainStatus] = useState('')
  const [terrainSnapshotStatus, setTerrainSnapshotStatus] = useState('')
  const [groundStatus, setGroundStatus] = useState('')

  /** Hide (or show again) the context buildings standing on the highlighted parcel — the project makes way for them. */
  const applyOnSite = useCallback(() => {
    const Cesium = cesiumRef.current, ring = site.current
    if (!Cesium || !layers.current) return
    tileBuildings.current?.setSite(ring, hideOnSite.current)
    if (ring?.length && tileBuildings.current?.backgroundReady) {
      supplementStarted.current = true
      void tileBuildings.current?.supplementNear(ring.reduce((s, p) => s + p[0]!, 0) / ring.length, ring.reduce((s, p) => s + p[1]!, 0) / ring.length).finally(() => pumpRef.current())
    }
    for (const e of layers.current.buildings.entities.values) {
      if (!hideOnSite.current || !ring) { e.show = true; continue }
      const first = e.polygon?.hierarchy?.getValue?.()?.positions?.[0]
      if (!first) continue
      const c = Cesium.Cartographic.fromCartesian(first)
      e.show = !inside(Cesium.Math.toDegrees(c.longitude), Cesium.Math.toDegrees(c.latitude), ring)
    }
  }, [])

  const pump = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium || !layers.current) return
    while (running.current < PARALLEL && queue.current.length) {
      const next = nextGroundRequest(queue.current, groundRequests.current.values(), roadsReady.current,
        !cameraMoving.current, !cameraMoving.current)
      if (next < 0) break
      const cell = queue.current.splice(next, 1)[0]!
      const gen = generation.current
      const z: Ground = terrainOn.current ? 'terrain' : level.current
      running.current++
      const live = () => !viewer.isDestroyed() && gen === generation.current && Boolean(layers.current)
      const controller = new AbortController()
      groundRequests.current.set(controller, cell)
      const ground = cachedGround(cell.lat, cell.lon, CELL_RADIUS_M, cell.detail,
        AbortSignal.any([controller.signal, AbortSignal.timeout(45_000)])).then(async (reply) => {
        if (live() && !controller.signal.aborted && groundStages.current) {
          if (cell.detail === 'full') {
            if (reply.gaps?.length) groundGaps.current.add(cell.cellKey)
            else groundGaps.current.delete(cell.cellKey)
            setGroundStatus(groundGaps.current.size ? '일부 지표면·도로 자료 부족' : '')
          }
          if (cell.detail === 'roads') roadsReady.current.add(cell.cellKey)
          await drawGroundIncrementally({ blocks: layers.current!.ground.forCell(cell.cellKey), cover: layers.current!.cover.forCell(cell.cellKey) }, Cesium, reply, z,
            () => live() && !controller.signal.aborted, () => viewer.scene.requestRender(),
            { state: groundStages.current, cellKey: cell.cellKey, detail: cell.detail })
          if (!live() || controller.signal.aborted) return
          // Keep the cached fill visible while upgrading old boundary metadata.
          // This stays in the same PARALLEL slot and cannot revive a retired cell.
          try {
            const fresh = await refreshGroundBoundaries(cell.lat, cell.lon, CELL_RADIUS_M, cell.detail, reply,
              AbortSignal.any([controller.signal, AbortSignal.timeout(45_000)]))
            if (fresh && live() && !controller.signal.aborted && groundStages.current) {
              await drawGroundIncrementally({ blocks: layers.current!.ground.forCell(cell.cellKey), cover: layers.current!.cover.forCell(cell.cellKey) }, Cesium, fresh, z,
                () => live() && !controller.signal.aborted, () => viewer.scene.requestRender(),
                undefined, true)
            }
          } catch { /* A boundary-only refresh must not discard the installed fill or retry forever. */ }
        }
      })
      Promise.allSettled([ground]).then((results) => {
        groundRequests.current.delete(controller)
        const failed = results.find((r): r is PromiseRejectedResult => r.status === 'rejected')
        if (failed && live() && !controller.signal.aborted) {
          asked.current.delete(cell.key)
          if (cell.detail === 'roads') roadsReady.current.add(cell.cellKey)
          if (!viewer.isDestroyed()) setStatus(failed.reason instanceof Error ? failed.reason.message : String(failed.reason))
        }
        running.current--
        setPending(queue.current.length + running.current)
        if (!viewer.isDestroyed()) pump()
      })
    }
    setPending(queue.current.length + running.current)
  }, [applyOnSite])

  pumpRef.current = pump

  /** True when the nationwide imagery owns both roads and cover at the focus: no live detail cells are drawn there. */
  const updateGroundImageOwnership = useCallback((focus: { lon: number; lat: number }) => {
    const current = layers.current
    if (!current) return false
    const owns = (kind: 'roads' | 'landcover') => coarseGround.current.some(item => {
      const provider = item.layer.imageryProvider
      // Ownership follows the provider, not visibility: hiding a layer must not bring the live island back.
      return item.kind === kind && provider.maximumLevel > 12
        && provider.coversPosition(focus.lon, focus.lat)
    })
    const surface = owns('landcover'), roads = owns('roads')
    current.ground.surfaceImagery = surface
    current.cover.surfaceImagery = surface
    current.ground.roadImagery = roads
    return surface && roads
  }, [])

  /** Drop every live parcel/road/cover cell: around the focus they would form a sharp-edged island over the uniform imagery. */
  const dropLiveGround = useCallback(() => {
    if (!layers.current || (!groundResidency.current.size && !queue.current.length && !groundRequests.current.size)) return
    generation.current++
    for (const controller of groundRequests.current.keys()) controller.abort()
    queue.current = []
    layers.current.ground.entities.removeAll()
    layers.current.cover.entities.removeAll()
    asked.current.clear()
    roadsReady.current.clear()
    groundGaps.current.clear()
    setGroundStatus('')
    groundStages.current?.clear()
    groundResidency.current.clear()
    setPending(running.current)
    viewerRef.current?.scene.requestRender()
  }, [])

  const loadVisible = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    const retireGround = () => {
      groundGaps.current.clear()
      setGroundStatus('')
      for (const cell of queue.current) asked.current.delete(cell.key)
      queue.current = []
      for (const [controller, cell] of groundRequests.current) {
        asked.current.delete(cell.key)
        controller.abort()
      }
      setPending(running.current)
    }
    const seen = visibleBox(viewer, Cesium)
    if (!seen) { retireGround(); return }
    const imageryOwned = updateGroundImageOwnership(seen.focus)
    const camera = viewer.camera.positionCartographic
    tileBuildings.current?.load(seen.box, seen.focus, { lon: Cesium.Math.toDegrees(camera.longitude),
      lat: Cesium.Math.toDegrees(camera.latitude), height: Math.max(1, camera.height - level.current),
      pixels: viewer.canvas.clientHeight, fov: viewer.camera.frustum.fovy ?? Math.PI / 3 })
    setStatus('')
    // Reserve the first HTTP connections for geometry; slow context APIs otherwise
    // queue static tiles/worker scripts behind them on HTTP/1.1 development hosts.
    if (!tileBuildings.current?.backgroundReady) return
    // Detailed parcel/road requests stay local; the building archive streams at every altitude.
    if (viewer.camera.positionCartographic.height - level.current > MAX_ALTITUDE_M) { retireGround(); return }
    if (!supplementStarted.current) {
      supplementStarted.current = true
      void tileBuildings.current?.supplementNear(seen.focus.lon, seen.focus.lat).finally(pump)
    }
    // The pinned nationwide road/cover imagery is the ground everywhere; the site outline is drawn separately.
    if (imageryOwned) { dropLiveGround(); return }
    const { lon, lat } = seen.focus
    const local: [number, number, number, number] = [Math.max(seen.box[0], lon - 0.012), Math.max(seen.box[1], lat - 0.012),
      Math.min(seen.box[2], lon + 0.012), Math.min(seen.box[3], lat + 0.012)]
    const nearby = cellsIn(local, seen.focus).slice(0, MAX_CELLS)
    const wanted = new Set(nearby.map(c => c.key))
    for (const key of groundGaps.current) if (!wanted.has(key)) groundGaps.current.delete(key)
    setGroundStatus(groundGaps.current.size ? '일부 지표면·도로 자료 부족' : '')
    for (const [controller, cell] of groundRequests.current) if (!wanted.has(cell.cellKey)) {
      asked.current.delete(cell.key)
      controller.abort()
    }
    for (const c of queue.current) if (!wanted.has(c.cellKey)) asked.current.delete(c.key)
    queue.current = queue.current.filter(c => wanted.has(c.cellKey))
    // Current cells are protected; recent views remain ready for zoom-out/in.
    // Abort obsolete work above before removing its ownership below.
    for (const key of groundResidency.current.visit(wanted)) {
      groundStages.current?.retire(key)
      layers.current?.ground.retireCell(key)
      layers.current?.cover.retireCell(key)
      asked.current.delete(`roads/${key}`)
      asked.current.delete(`full/${key}`)
      roadsReady.current.delete(key)
    }
    const candidates = nearby.slice(0, MAX_CELLS).flatMap(c => ([
      { ...c, cellKey: c.key, key: `roads/${c.key}`, detail: 'roads' as const },
      { ...c, cellKey: c.key, key: `full/${c.key}`, detail: 'full' as const },
    ]))
    const fresh = candidates.filter(c => !asked.current.has(c.key))
    for (const c of fresh) asked.current.add(c.key)
    const rank = new Map(nearby.map((cell, index) => [cell.key, index]))
    queue.current = [...fresh, ...queue.current].sort((a, b) => Number(a.detail === 'full') - Number(b.detail === 'full')
      || rank.get(a.cellKey)! - rank.get(b.cellKey)!)
    setStatus('')
    pump()
  }, [pump, updateGroundImageOwnership, dropLiveGround])

  /** The site's red dashed outline, draped on the terrain or just above the flat ground. */
  const drawOutline = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current, ring = outline.current
    if (!viewer || !Cesium) return
    viewer.entities.removeById('world-parcel')
    if (!ring) return
    viewer.entities.add({ id: 'world-parcel', name: '대지', polyline: {
      ...(terrainOn.current
        ? { positions: Cesium.Cartesian3.fromDegreesArray(ring.flatMap((c) => [c[0]!, c[1]!])), clampToGround: true, classificationType: Cesium.ClassificationType.TERRAIN }
        : { positions: Cesium.Cartesian3.fromDegreesArrayHeights(ring.flatMap((c) => [c[0]!, c[1]!, level.current + 1.0])) }),
      width: 2, material: new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString('#d6336c'), dashLength: 10 }) } })
  }, [])

  /** Record the site (whose context buildings make way for the project) without drawing its outline. */
  const setSite = useCallback((geometry: object | null) => {
    site.current = geometry ? ringOf(geometry) : null
    applyOnSite()
  }, [applyOnSite])

  /** The planned building last drawn, so a redraw of the context (the ground moved) puts it back at the new ground. */
  const lastLayout = useRef<{ layout: LayoutView; intent: IntentView | null | undefined } | null>(null)

  /** Throw the drawn context away and load what the camera sees again (the ground under it changed). */
  const redraw = useCallback(() => {
    generation.current++
    for (const controller of groundRequests.current.keys()) controller.abort()
    for (const l of Object.values(layers.current ?? {})) l.entities.removeAll()
    asked.current.clear()
    roadsReady.current.clear()
    groundGaps.current.clear()
    setGroundStatus('')
    groundStages.current?.clear()
    groundResidency.current.clear()
    queue.current = []
    tileBuildings.current?.setGround(terrainOn.current ? 'terrain' : level.current, level.current)
    drawOutline()
    loadVisible()
    const Cesium = cesiumRef.current
    if (Cesium && layers.current && lastLayout.current) {
      drawLayoutEntities(layers.current.layout.entities, Cesium, lastLayout.current.layout, lastLayout.current.intent, terrainOn.current ? 'terrain' : level.current)
    }
  }, [loadVisible, drawOutline])

  /** The ground: the DEM terrain, or flat at level.current. An old Cesium (from the VWorld SDK in this tab) stays flat at 0. */
  const applyGround = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    terrainProvider.current?.dispose?.()
    terrainProvider.current = null
    setTerrainStatus('')
    setTerrainSnapshotStatus('')
    if (!Cesium.CustomHeightmapTerrainProvider) {   // cannot happen with our own 1.122; never draw on a ground we cannot make
      terrainOn.current = false
      level.current = 0
      return
    }
    const z = level.current
    // On terrain the masses' feet go into the ground: the globe must hide what is below it.
    // National buildings keep their pinned ground heights in flat mode too: the globe must still hide their footings.
    viewer.scene.globe.depthTestAgainstTerrain = true
    if (terrainOn.current) {
      terrainProvider.current = demTerrain(Cesium, () => level.current,
        () => (viewer.isDestroyed() ? null : visibleBox(viewer, Cesium)?.focus ?? null), setTerrainStatus,
        undefined, undefined, () => setTerrainSnapshotStatus('준비된 지형 스냅샷 표시'))
      viewer.terrainProvider = terrainProvider.current
    } else {
      viewer.terrainProvider = new Cesium.CustomHeightmapTerrainProvider({ width: 2, height: 2, callback: () => new Float32Array([z, z, z, z]) })
    }
  }, [])

  /** The site's datum: the flat ground stands there (terrain off), and far tiles the DEM does not cover stand there. */
  const setGroundLevel = useCallback((z: number) => {
    if (!Number.isFinite(z) || z === level.current) return
    level.current = z
    tileBuildings.current?.setGround(terrainOn.current ? 'terrain' : z, z)
    if (terrainOn.current) return
    applyGround()
    redraw()
  }, [applyGround, redraw])

  const flyTo = useCallback((lng: number, lat: number) => {
    placement.current++
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    if (tileBuildings.current?.backgroundReady) {
      void tileBuildings.current.supplementNear(lng, lat).finally(() => pumpRef.current())
      supplementStarted.current = true
    }
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lng, lat - 0.0032, level.current + 520),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-42), roll: 0 },
      duration: 1.2,
    })
  }, [])

  /** Frames a site: the camera stands where the site map's fit of the parcel says (its size sets the distance). */
  const frameSite = useCallback(async (lng: number, lat: number, pose: { lng: number; lat: number; height: number; pitchDeg: number; range: number }) => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return false
    const request = ++placement.current
    if (tileBuildings.current?.backgroundReady) {
      void tileBuildings.current.supplementNear(lng, lat).finally(() => pumpRef.current())
      supplementStarted.current = true
    }
    try {
      const provider = terrainProvider.current
      const sample = terrainOn.current ? (lon: number, latitude: number) => provider.sampleHeight(lon, latitude) : async () => level.current
      return await placeSiteCamera(viewer, Cesium, lng, lat, pose, sample,
        () => request === placement.current, (lon, latitude) => tileBuildings.current?.heightAt(lon, latitude))
    } catch (error) {
      if (request === placement.current && !viewer.isDestroyed()) setStatus(`대지 카메라: ${error instanceof Error ? error.message : String(error)}`)
      return false
    }
  }, [])

  const highlightParcel = useCallback((geometry: object) => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    const ring = ringOf(geometry)
    if (!viewer || !Cesium || !ring) return
    site.current = ring
    outline.current = ring
    drawOutline()
    applyOnSite()
    // A parcel far from what the camera looks at (a search by PNU gives no coordinates): go there.
    const lon = ring.reduce((t, c) => t + c[0]!, 0) / ring.length, lat = ring.reduce((t, c) => t + c[1]!, 0) / ring.length
    const seen = visibleBox(viewer, Cesium)
    const far = !seen || Math.hypot((seen.focus.lat - lat) * 111_000, (seen.focus.lon - lon) * 88_000) > 1500
    if (far) flyTo(lon, lat)
  }, [applyOnSite, flyTo, drawOutline])

  const clearHighlight = useCallback(() => {
    placement.current++
    outline.current = null
    viewerRef.current?.entities.removeById('world-parcel')
  }, [])

  /** Our building from the MasterPlan layout (the `masterplan` run's result), over the parcel; null clears it. */
  const drawLayout = useCallback((layout: LayoutView | null, intent?: IntentView | null): number => {
    const Cesium = cesiumRef.current
    if (!Cesium || !layers.current) return 0
    lastLayout.current = layout ? { layout, intent } : null
    // The ground over a basement turns see-through, else the terrain hides the basement drawn below it.
    // seeThrough was never passed, so a basement car park (684-1: 30 stalls, aisle and ramp at -3 m) stayed under
    // opaque ground and the chosen layout showed only its boundary line (2026-11-03).
    showUnderground(Cesium, viewerRef.current?.scene?.globe, layout, true)
    if (!layout) {
      clearLayoutEntities(layers.current.layout.entities)
      return 0
    }
    const z: Ground = terrainOn.current ? 'terrain' : level.current
    return drawLayoutEntities(layers.current.layout.entities, Cesium, layout, intent, z)
  }, [])

  /** VWorld semantics: false = "existing buildings make way for the project" — here, the ones on the site hide. */
  const setBuildingsVisible = useCallback((visible: boolean) => {
    hideOnSite.current = !visible
    applyOnSite()
  }, [applyOnSite])

  /** Regulation lines from a land analysis (same colours and layer name as the VWorld view), on the ground. */
  const clearSetbackLines = useCallback(() => {
    setbackGeneration.current++
    const viewer = viewerRef.current
    if (!viewer) return
    for (let i = viewer.dataSources.length - 1; i >= 0; i--) {
      const ds = viewer.dataSources.get(i)
      if (ds.name === SETBACK_DS_NAME) viewer.dataSources.remove(ds, true)
    }
  }, [])

  const drawSetbackLines = useCallback((lines: Record<string, unknown>) => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium || !lines) return
    clearSetbackLines()
    const request = setbackGeneration.current
    for (const [key, geojson] of Object.entries(lines)) {
      if (!geojson || key === 'sunlight_envelope' || key === 'daylight_diagonal_envelope') continue
      const colors = SETBACK_COLORS[key] || SETBACK_COLORS.adjacent_setback!
      void addCurrentSetback(Cesium.GeoJsonDataSource.load(geojson, {
        stroke: Cesium.Color.fromCssColorString(colors.stroke), fill: Cesium.Color.fromCssColorString(colors.fill),
        strokeWidth: colors.width, clampToGround: true,
      }).then((source: any) => {
        // Clamped geometry classifies 3D Tiles too by default: keep setback colours on the ground, off building walls.
        for (const entity of source.entities.values) for (const g of [entity.polygon, entity.polyline]) if (g) g.classificationType = Cesium.ClassificationType.TERRAIN
        return source
      }), viewer, () => request === setbackGeneration.current, SETBACK_DS_NAME)
        .catch((e: unknown) => console.warn(`Setback ${key} 렌더 실패:`, e))
    }
  }, [clearSetbackLines])

  useEffect(() => {
    let disposed = false
    let release = () => {}
    let removeCamera = () => {}
    const rendererReady = prepareWorldBuildingRenderer(defaultMapReleaseReader)
    void rendererReady.catch(() => {})
    const warmPlacement = placement.current, warmGeneration = generation.current
    void prewarmTerrainAt(openingLocation.current,
      () => !disposed && warmPlacement === placement.current && warmGeneration === generation.current)
    acquireCesium().then(async ({ Cesium, release: give }) => {
      release = give
      if (disposed || !target.current) return give()
      cesiumRef.current = Cesium
      const viewer = new Cesium.Viewer(target.current, {
        baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
        navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false,
        infoBox: true, selectionIndicator: true, terrainProvider: new Cesium.EllipsoidTerrainProvider(),
        requestRenderMode: true, maximumRenderTimeChange: Infinity, targetFrameRate: 60,
        useDefaultRenderLoop: false,
      })
      const scene = viewer.scene
      // Navigation targets the terrain, like parcel selection. GPU depth picking
      // synchronously reads pixels on every wheel/inertia update and stalls input.
      scene.useDepthPicking = false
      scene.globe.baseColor = Cesium.Color.fromCssColorString('#f2f2f0')
      // Screen-space refinement is for display; fixed-resolution building and
      // camera height sampling still uses the level-17 source grids.
      scene.globe.maximumScreenSpaceError = 4
      scene.backgroundColor = Cesium.Color.fromCssColorString('#f7f7f5')
      if (scene.skyBox) scene.skyBox.show = false
      if (scene.skyAtmosphere) scene.skyAtmosphere.show = false
      if (scene.sun) scene.sun.show = false
      scene.fog.enabled = false
      // Fixed key light from the south-east, 45° up, like a massing diagram. The clock's sun lights nothing at night,
      // and under the buildings' uniform ambient term its faces read the same white. The globe is unlit either way.
      const keyLight = new Cesium.DirectionalLight({ direction: new Cesium.Cartesian3(0, 0, -1), intensity: 3 })
      const lightFrame = new Cesium.Matrix4(), lightLocal = new Cesium.Cartesian3(-0.5, 0.5, -Math.SQRT1_2)
      scene.light = keyLight
      scene.preRender.addEventListener(() => {
        Cesium.Transforms.eastNorthUpToFixedFrame(viewer.camera.positionWC, undefined, lightFrame)
        Cesium.Matrix4.multiplyByPointAsVector(lightFrame, lightLocal, keyLight.direction)
        Cesium.Cartesian3.normalize(keyLight.direction, keyLight.direction)
      })
      layers.current = { ground: new GroundLayer(viewer, Cesium, 'ground'), cover: new GroundLayer(viewer, Cesium, 'cover'),
        buildings: new Cesium.CustomDataSource('buildings'), layout: new Cesium.CustomDataSource('layout') }
      groundStages.current = createGroundStages({ blocks: layers.current.ground, cover: layers.current.cover }, Cesium,
        () => terrainOn.current ? 'terrain' : level.current)
      viewer.dataSources.add(layers.current.buildings)
      viewer.dataSources.add(layers.current.layout)
      // Same opening view as the VWorld engine; pages that know their site move the camera themselves.
      const [lon0, lat0] = openingLocation.current ?? MAP_CONFIG_3D.center
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(lon0, lat0 - 0.008, MAP_CONFIG_3D.defaultAltitude),
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(MAP_CONFIG_3D.defaultPitch), roll: 0 },
      })
      viewerRef.current = viewer
      const prefetch = new AbortController()
      groundPrefetch.current = { controller: prefetch, promise: prepareGroundImagery(Cesium, { signal: prefetch.signal }) }
      groundPrefetch.current.promise.catch(() => {})
      applyGround()
      // Resolve the actual site's camera before the globe starts requesting the
      // broad default view. Its terrain samples then have uncontended connections.
      try {
        await openingCamera.current?.(viewer, Cesium, (lon, lat) => terrainProvider.current.sampleHeight(lon, lat), () => !disposed)
      } catch (e) {
        if (!disposed) setStatus(`대지 카메라: ${e instanceof Error ? e.message : String(e)}`)
      }
      if (disposed) return
      viewer.useDefaultRenderLoop = true
      const renderer = await rendererReady
      if (disposed || viewerRef.current !== viewer || viewer.isDestroyed()) return
      tileBuildings.current = renderer.create({ viewer, C: Cesium, changed: (got, waiting, reason) => {
        if (disposed) return
        setCounts(got)
        setBuildings(got.measured + got.estimated + got.unknown)
        setTilePending(waiting)
        setBuildingStatus(reason)
      }, firstFrame: loadVisible })
      ;(viewer as any).buildingTiles = tileBuildings.current
      ;(target.current as any).__worldViewer = viewer
      let lastView = 0
      const motion = new CameraMotion()
      const updateMotion = () => {
        const c = viewer.camera, p = c.positionWC, d = c.directionWC, u = c.upWC
        const wasMoving = cameraMoving.current
        cameraMoving.current = motion.update(performance.now(), [p.x, p.y, p.z, d.x, d.y, d.z, u.x, u.y, u.z])
        if (wasMoving && !cameraMoving.current) loadVisible()
      }
      const moving = () => {
        updateMotion()
        if (performance.now() - lastView < 50) return
        lastView = performance.now()
        loadVisible()
      }
      viewer.camera.percentageChanged = 0.01
      const removeMotion = scene.preUpdate.addEventListener(updateMotion)
      const removeChanged = viewer.camera.changed.addEventListener(moving)
      removeCamera = () => { removeMotion(); removeChanged(); cameraMoving.current = false }
      loadVisible()
      viewer.screenSpaceEventHandler.setInputAction((click: any) => {
        const ray = viewer.camera.getPickRay(click.position)
        const at = ray && scene.globe.pick(ray, scene)
        if (!at) return
        const c = Cesium.Cartographic.fromCartesian(at)
        clickRef.current?.(Cesium.Math.toDegrees(c.longitude), Cesium.Math.toDegrees(c.latitude))
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK)
      setReady(true)
      setStatus('')
    }).catch((e) => { if (!disposed) setError(e instanceof Error ? e.message : String(e)) })
    return () => {
      disposed = true
      placement.current++
      removeCamera()
      queue.current = []
      generation.current++
      for (const request of groundRequests.current.keys()) request.abort()
      groundRequests.current.clear()
      groundStages.current?.clear()
      groundStages.current = null
      groundResidency.current.clear()
      asked.current.clear()
      roadsReady.current.clear()
      groundGaps.current.clear()
      tileBuildings.current?.dispose()
      tileBuildings.current = null
      groundPrefetch.current?.promise.then(result => result.dispose(), () => {})
      groundPrefetch.current?.controller.abort()
      groundPrefetch.current = null
      supplementStarted.current = false
      terrainProvider.current?.dispose?.()
      terrainProvider.current = null
      viewerRef.current?.destroy()
      viewerRef.current = null
      release()   // the VWorld engine may mount next: its own Cesium goes back on the globals
      setReady(false)
    }
  }, [target, loadVisible, applyGround])

  useEffect(() => {
    if (!ready || terrainOn.current === terrain) return
    terrainOn.current = terrain
    applyGround()
    if (terrain && !terrainOn.current) setTerrain(false)
    redraw()
  }, [terrain, ready, applyGround, redraw])

  useEffect(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    viewer.imageryLayers.removeAll()
    const controller = new AbortController()
    const groundLayers = layers.current
    let prepared: Awaited<ReturnType<typeof prepareGroundImagery>> | undefined
    const added: { kind: 'roads' | 'landcover'; layer: any }[] = []
    const early = groundPrefetch.current
    groundPrefetch.current = null
    if (base === 'vworld2d' && early) {
      early.promise.then(result => result.dispose(), () => {})
      early.controller.abort()
    }
    if (base === 'vworld2d') {
      viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
        url: `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/tiles/{z}/{y}/{x}.png`,
        maximumLevel: 19, credit: 'VWorld',
      }))
      // Live ground cells dropped under the national layer must come back without waiting for a camera move.
      loadVisible()
    } else {
      if (early) controller.signal.addEventListener('abort', () => early.controller.abort(), { once: true })
      void (early?.promise ?? prepareGroundImagery(Cesium, { signal: controller.signal })).then(result => {
        if (controller.signal.aborted || viewerRef.current !== viewer || viewer.isDestroyed()) {
          result.dispose()
          return
        }
        prepared = result
        for (const item of result.layers) {
          const layer = viewer.imageryLayers.addImageryProvider(item.provider)
          layer.show = item.kind === 'roads' ? shown.current.ground : shown.current.cover
          added.push({ kind: item.kind, layer })
        }
        coarseGround.current = added
        loadVisible()
        viewer.scene.requestRender()
      }).catch(error => {
        if (!controller.signal.aborted) console.warn('Ground imagery unavailable', error)
      })
    }
    return () => {
      controller.abort()
      prepared?.dispose()
      if (!viewer.isDestroyed()) for (const item of added) viewer.imageryLayers.remove(item.layer, true)
      if (layers.current === groundLayers && groundLayers && !viewer.isDestroyed()) {
        groundLayers.ground.surfaceImagery = false
        groundLayers.cover.surfaceImagery = false
        groundLayers.ground.roadImagery = false
      }
      if (coarseGround.current === added) coarseGround.current = []
    }
  }, [base, ready, loadVisible])

  useEffect(() => {
    if (!layers.current) return
    tileBuildings.current?.setShow(show.buildings)
    layers.current.buildings.show = show.buildings
    layers.current.ground.show = show.ground
    layers.current.cover.show = show.cover
    for (const item of coarseGround.current) item.layer.show = item.kind === 'roads' ? show.ground : show.cover
    loadVisible()
  }, [show, ready, loadVisible])

  return {
    ready, loading: !ready && !error, error, viewerRef, cesiumRef,
    highlightParcel, clearHighlight, setSite, flyTo, frameSite, setBuildingsVisible, setGroundLevel, loadVisible, drawSetbackLines, clearSetbackLines, drawLayout,
    base, setBase, show, setShow, terrain, setTerrain, status: [status, buildingStatus, terrainStatus, terrainSnapshotStatus, groundStatus].filter(Boolean).join(' · '), setStatus, stats: { buildings, counts, pending: pending + tilePending },
  }
}
