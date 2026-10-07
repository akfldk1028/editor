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
import { type Ground, type HeightCounts, drawContextGround, drawContextMasses, fetchContextBuildings, fetchContextGround } from '../lib/context-masses'
import { demTerrain } from '../lib/terrain'

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

export function useWorld3D({ target, onClick }: { target: RefObject<HTMLDivElement | null>; onClick?: (lng: number, lat: number) => void }) {
  const viewerRef = useRef<any>(null)
  const cesiumRef = useRef<any>(null)
  const layers = useRef<{ buildings: any; ground: any; cover: any } | null>(null)
  const asked = useRef(new Set<string>())
  const queue = useRef<{ key: string; lat: number; lon: number }[]>([])
  const running = useRef(0)
  const level = useRef(0)
  const terrainOn = useRef(true)
  const generation = useRef(0)   // bumped whenever the drawn context is thrown away
  const site = useRef<number[][] | null>(null)
  const outline = useRef<number[][] | null>(null)   // the highlighted parcel's outline (may differ from site after clearHighlight)
  const terrainProvider = useRef<any>(null)
  const hideOnSite = useRef(false)
  const clickRef = useRef(onClick)
  clickRef.current = onClick
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState('3D 엔진 불러오는 중…')
  const [base, setBase] = useState<WorldBase>('white')
  const [show, setShow] = useState<WorldLayers>({ buildings: true, ground: true, cover: false })
  const [terrain, setTerrain] = useState(true)
  const [buildings, setBuildings] = useState(0)
  const [counts, setCounts] = useState<HeightCounts>({ measured: 0, estimated: 0, unknown: 0 })
  const [pending, setPending] = useState(0)

  /** Hide (or show again) the context buildings standing on the highlighted parcel — the project makes way for them. */
  const applyOnSite = useCallback(() => {
    const Cesium = cesiumRef.current, ring = site.current
    if (!Cesium || !layers.current) return
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
      const cell = queue.current.shift()!
      const gen = generation.current
      const z: Ground = terrainOn.current ? 'terrain' : level.current
      running.current++
      const live = () => !viewer.isDestroyed() && gen === generation.current && layers.current
      const ground = fetchContextGround(cell.lat, cell.lon, CELL_RADIUS_M).then((reply) => {
        if (reply.status === 'ok' && live())
          drawContextGround({ blocks: layers.current!.ground, cover: layers.current!.cover }, Cesium, reply, z)
      })
      const masses = fetchContextBuildings(cell.lat, cell.lon, CELL_RADIUS_M).then((reply) => {
        if (reply.status !== 'ok' || !live()) return
        const { counts: got } = drawContextMasses(layers.current!.buildings.entities, Cesium, reply, z)
        setBuildings((n) => n + got.measured + got.estimated + got.unknown)
        setCounts((c) => ({ measured: c.measured + got.measured, estimated: c.estimated + got.estimated, unknown: c.unknown + got.unknown }))
        if (hideOnSite.current) applyOnSite()
      })
      // the cell is done when both have settled; a failure of either is retried on the next camera move
      Promise.allSettled([ground, masses]).then((results) => {
        const failed = results.find((r): r is PromiseRejectedResult => r.status === 'rejected')
        if (failed) {
          asked.current.delete(cell.key)
          if (!viewer.isDestroyed()) setStatus(failed.reason instanceof Error ? failed.reason.message : String(failed.reason))
        }
        running.current--
        setPending(queue.current.length + running.current)
        if (!viewer.isDestroyed()) pump()
      })
    }
    setPending(queue.current.length + running.current)
  }, [applyOnSite])

  const loadVisible = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    if (viewer.camera.positionCartographic.height - level.current > MAX_ALTITUDE_M) {
      setStatus('더 가까이 오면 주변 건물을 불러옵니다')
      return
    }
    const seen = visibleBox(viewer, Cesium)
    if (!seen) return
    const fresh = cellsIn(seen.box, seen.focus).filter((c) => !asked.current.has(c.key)).slice(0, MAX_CELLS)
    for (const c of fresh) asked.current.add(c.key)
    queue.current = [...fresh, ...queue.current] // what the camera sees now goes first
    setStatus('')
    pump()
  }, [pump])

  /** The site's red dashed outline, draped on the terrain or just above the flat ground. */
  const drawOutline = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current, ring = outline.current
    if (!viewer || !Cesium) return
    viewer.entities.removeById('world-parcel')
    if (!ring) return
    viewer.entities.add({ id: 'world-parcel', name: '대지', polyline: {
      ...(terrainOn.current
        ? { positions: Cesium.Cartesian3.fromDegreesArray(ring.flatMap((c) => [c[0]!, c[1]!])), clampToGround: true }
        : { positions: Cesium.Cartesian3.fromDegreesArrayHeights(ring.flatMap((c) => [c[0]!, c[1]!, level.current + 1.0])) }),
      width: 2, material: new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString('#d6336c'), dashLength: 10 }) } })
  }, [])

  /** Record the site (whose context buildings make way for the project) without drawing its outline. */
  const setSite = useCallback((geometry: object | null) => {
    site.current = geometry ? ringOf(geometry) : null
    applyOnSite()
  }, [applyOnSite])

  /** Throw the drawn context away and load what the camera sees again (the ground under it changed). */
  const redraw = useCallback(() => {
    generation.current++
    for (const l of Object.values(layers.current ?? {})) l.entities.removeAll()
    asked.current.clear()
    queue.current = []
    setBuildings(0)
    setCounts({ measured: 0, estimated: 0, unknown: 0 })
    drawOutline()
    loadVisible()
  }, [loadVisible, drawOutline])

  /** The ground: the DEM terrain, or flat at level.current. An old Cesium (from the VWorld SDK in this tab) stays flat at 0. */
  const applyGround = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    terrainProvider.current?.dispose?.()
    terrainProvider.current = null
    if (!Cesium.CustomHeightmapTerrainProvider) {   // cannot happen with our own 1.122; never draw on a ground we cannot make
      terrainOn.current = false
      level.current = 0
      return
    }
    const z = level.current
    // On terrain the masses' feet go into the ground: the globe must hide what is below it.
    viewer.scene.globe.depthTestAgainstTerrain = terrainOn.current
    if (terrainOn.current) {
      terrainProvider.current = demTerrain(Cesium, () => level.current, () => visibleBox(viewer, Cesium)?.focus ?? null)
      viewer.terrainProvider = terrainProvider.current
    } else {
      viewer.terrainProvider = new Cesium.CustomHeightmapTerrainProvider({ width: 2, height: 2, callback: () => new Float32Array([z, z, z, z]) })
    }
  }, [])

  /** The site's datum: the flat ground stands there (terrain off), and far tiles the DEM does not cover stand there. */
  const setGroundLevel = useCallback((z: number) => {
    if (!Number.isFinite(z) || z === level.current) return
    level.current = z
    if (terrainOn.current) return
    applyGround()
    redraw()
  }, [applyGround, redraw])

  const flyTo = useCallback((lng: number, lat: number) => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lng, lat - 0.0032, level.current + 520),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-42), roll: 0 },
      duration: 1.2,
    })
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
    outline.current = null
    viewerRef.current?.entities.removeById('world-parcel')
  }, [])

  /** VWorld semantics: false = "existing buildings make way for the project" — here, the ones on the site hide. */
  const setBuildingsVisible = useCallback((visible: boolean) => {
    hideOnSite.current = !visible
    applyOnSite()
  }, [applyOnSite])

  /** Regulation lines from a land analysis (same colours and layer name as the VWorld view), on the ground. */
  const clearSetbackLines = useCallback(() => {
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
    for (const [key, geojson] of Object.entries(lines)) {
      if (!geojson || key === 'sunlight_envelope' || key === 'daylight_diagonal_envelope') continue
      const colors = SETBACK_COLORS[key] || SETBACK_COLORS.adjacent_setback!
      Cesium.GeoJsonDataSource.load(geojson, {
        stroke: Cesium.Color.fromCssColorString(colors.stroke), fill: Cesium.Color.fromCssColorString(colors.fill),
        strokeWidth: colors.width, clampToGround: true,
      }).then((ds: any) => {
        ds.name = SETBACK_DS_NAME
        if (!viewer.isDestroyed()) viewer.dataSources.add(ds)
      }).catch((e: unknown) => console.warn(`Setback ${key} 렌더 실패:`, e))
    }
  }, [clearSetbackLines])

  useEffect(() => {
    let disposed = false
    let release = () => {}
    acquireCesium().then(({ Cesium, release: give }) => {
      release = give
      if (disposed || !target.current) return give()
      cesiumRef.current = Cesium
      const viewer = new Cesium.Viewer(target.current, {
        baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
        navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false,
        infoBox: true, selectionIndicator: true, terrainProvider: new Cesium.EllipsoidTerrainProvider(),
      })
      const scene = viewer.scene
      scene.globe.baseColor = Cesium.Color.fromCssColorString('#f2f2f0')
      scene.backgroundColor = Cesium.Color.fromCssColorString('#f7f7f5')
      if (scene.skyBox) scene.skyBox.show = false
      if (scene.skyAtmosphere) scene.skyAtmosphere.show = false
      if (scene.sun) scene.sun.show = false
      scene.fog.enabled = false
      layers.current = { ground: new Cesium.CustomDataSource('ground'), cover: new Cesium.CustomDataSource('cover'),
        buildings: new Cesium.CustomDataSource('buildings') }
      for (const l of Object.values(layers.current)) viewer.dataSources.add(l)
      // Same opening view as the VWorld engine; pages that know their site move the camera themselves.
      const [lon0, lat0] = MAP_CONFIG_3D.center
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(lon0, lat0 - 0.008, MAP_CONFIG_3D.defaultAltitude),
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(MAP_CONFIG_3D.defaultPitch), roll: 0 },
      })
      viewerRef.current = viewer
      applyGround()
      viewer.camera.moveEnd.addEventListener(loadVisible)
      viewer.screenSpaceEventHandler.setInputAction((click: any) => {
        const ray = viewer.camera.getPickRay(click.position)
        const at = ray && scene.globe.pick(ray, scene)
        if (!at) return
        const c = Cesium.Cartographic.fromCartesian(at)
        clickRef.current?.(Cesium.Math.toDegrees(c.longitude), Cesium.Math.toDegrees(c.latitude))
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK)
      setReady(true)
      setStatus('')
    }).catch((e) => setError(e instanceof Error ? e.message : String(e)))
    return () => {
      disposed = true
      queue.current = []
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
    if (base === 'vworld2d') {
      viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
        url: `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/land/tiles/{z}/{y}/{x}.png`,
        maximumLevel: 19, credit: 'VWorld',
      }))
    }
  }, [base, ready])

  useEffect(() => {
    if (!layers.current) return
    layers.current.buildings.show = show.buildings
    layers.current.ground.show = show.ground
    layers.current.cover.show = show.cover
  }, [show, ready])

  return {
    ready, loading: !ready && !error, error, viewerRef, cesiumRef,
    highlightParcel, clearHighlight, setSite, flyTo, setBuildingsVisible, setGroundLevel, loadVisible, drawSetbackLines, clearSetbackLines,
    base, setBase, show, setShow, terrain, setTerrain, status, setStatus, stats: { buildings, counts, pending },
  }
}
