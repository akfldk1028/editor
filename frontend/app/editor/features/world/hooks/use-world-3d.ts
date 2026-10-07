/**
 * Our own Cesium world: white context masses and the diagram ground (parcels, roads, land cover), loaded cell by
 * cell as the camera moves — no VWorld SDK or key. It returns the same actions as useVworld3D (highlightParcel,
 * clearHighlight, flyTo, setBuildingsVisible, viewerRef), so the design view's mass and setback renderers work on
 * either world.
 *
 * Until real terrain arrives the globe is flat at one ground level (setGroundLevel, e.g. the site's §119 datum), so
 * a mass placed at its datum stands on the ground instead of floating above sea level.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { type RefObject, useCallback, useEffect, useRef, useState } from 'react'
import { MAP_CONFIG_3D } from '../../land-map/lib/constants'
import { SETBACK_COLORS, SETBACK_DS_NAME } from '../../land-map/lib/vworld-3d-scene'
import { loadCesium } from '../lib/cesium-loader'
import { CELL_RADIUS_M, MAX_ALTITUDE_M, MAX_CELLS, cellsIn, visibleBox } from '../lib/context-cells'
import { type HeightCounts, drawContextGround, drawContextMasses, fetchContextBuildings, fetchContextGround } from '../lib/context-masses'

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
  const site = useRef<number[][] | null>(null)
  const hideOnSite = useRef(false)
  const clickRef = useRef(onClick)
  clickRef.current = onClick
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState('3D 엔진 불러오는 중…')
  const [base, setBase] = useState<WorldBase>('white')
  const [show, setShow] = useState<WorldLayers>({ buildings: true, ground: true, cover: false })
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
      const z = level.current
      running.current++
      const ground = fetchContextGround(cell.lat, cell.lon, CELL_RADIUS_M).then((reply) => {
        if (reply.status === 'ok' && !viewer.isDestroyed() && z === level.current)
          drawContextGround({ blocks: layers.current!.ground, cover: layers.current!.cover }, Cesium, reply, z)
      })
      fetchContextBuildings(cell.lat, cell.lon, CELL_RADIUS_M)
        .then((reply) => {
          if (reply.status !== 'ok' || viewer.isDestroyed() || z !== level.current) return
          const { counts: got } = drawContextMasses(layers.current!.buildings.entities, Cesium, reply, z)
          setBuildings((n) => n + got.measured + got.estimated + got.unknown)
          setCounts((c) => ({ measured: c.measured + got.measured, estimated: c.estimated + got.estimated, unknown: c.unknown + got.unknown }))
          if (hideOnSite.current) applyOnSite()
        })
        .then(() => ground)
        .catch((e) => {
          asked.current.delete(cell.key) // try again on the next move
          setStatus(e instanceof Error ? e.message : String(e))
        })
        .finally(() => {
          running.current--
          setPending(queue.current.length + running.current)
          pump()
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

  /** Put the flat ground at z metres (the site datum) and redraw the context on it. */
  const setGroundLevel = useCallback((z: number) => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium || !Number.isFinite(z) || z === level.current) return
    if (!Cesium.CustomHeightmapTerrainProvider) return // an old Cesium (from the VWorld SDK in this tab): stays at 0
    level.current = z
    viewer.terrainProvider = new Cesium.CustomHeightmapTerrainProvider({
      width: 2, height: 2, callback: () => new Float32Array([z, z, z, z]),
    })
    for (const l of Object.values(layers.current ?? {})) l.entities.removeAll()
    asked.current.clear()
    queue.current = []
    setBuildings(0)
    setCounts({ measured: 0, estimated: 0, unknown: 0 })
    loadVisible()
  }, [loadVisible])

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
    viewer.entities.removeById('world-parcel')
    viewer.entities.add({ id: 'world-parcel', name: '대지', polyline: {
      positions: Cesium.Cartesian3.fromDegreesArrayHeights(ring.flatMap((c) => [c[0]!, c[1]!, level.current + 1.0])),
      width: 2, material: new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString('#d6336c'), dashLength: 10 }) } })
    applyOnSite()
    // A parcel far from what the camera looks at (a search by PNU gives no coordinates): go there.
    const lon = ring.reduce((t, c) => t + c[0]!, 0) / ring.length, lat = ring.reduce((t, c) => t + c[1]!, 0) / ring.length
    const seen = visibleBox(viewer, Cesium)
    const far = !seen || Math.hypot((seen.focus.lat - lat) * 111_000, (seen.focus.lon - lon) * 88_000) > 1500
    if (far) flyTo(lon, lat)
  }, [applyOnSite, flyTo])

  const clearHighlight = useCallback(() => {
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
    loadCesium().then((Cesium) => {
      if (disposed || !target.current) return
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
      viewerRef.current?.destroy()
      viewerRef.current = null
      setReady(false)
    }
  }, [target, loadVisible])

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
    highlightParcel, clearHighlight, flyTo, setBuildingsVisible, setGroundLevel, loadVisible, drawSetbackLines, clearSetbackLines,
    base, setBase, show, setShow, status, setStatus, stats: { buildings, counts, pending },
  }
}
