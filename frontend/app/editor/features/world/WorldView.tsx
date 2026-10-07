'use client'

/**
 * World view: our own Cesium globe with clean white context masses — anywhere in Korea, no VWorld SDK or key.
 * Open it at a parcel (/world?pnu=… or ?q=<주소> or ?lat=&lon=) or search; as the camera moves, the cells it sees
 * are filled in. Base map is a toggle: plain white, or the VWorld 2D map through the backend.
 * Plan (W0–W6, VWorld 3D toggle later): agents/SceneAgent/docs/editor-world-plan.md
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { useCallback, useEffect, useRef, useState } from 'react'
import { locateParcel } from '../land-map/lib/land-api-client'
import { loadCesium } from './lib/cesium-loader'
import { CELL_RADIUS_M, MAX_ALTITUDE_M, MAX_CELLS, cellsIn, visibleBox } from './lib/context-cells'
import { type HeightCounts, drawContextMasses, fetchContextBuildings } from './lib/context-masses'

const GOSAN = { lat: 37.73002, lon: 127.1085 } // only where the view opens when nothing is asked for
const PARALLEL = 3
type Base = 'white' | 'vworld2d'

function ringOf(geometry: any): number[][] | null {
  const g = geometry?.type === 'Feature' ? geometry.geometry : geometry
  if (g?.type === 'Polygon') return g.coordinates[0]
  if (g?.type === 'MultiPolygon') return g.coordinates[0][0]
  return null
}

export default function WorldView() {
  const host = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<any>(null)
  const cesiumRef = useRef<any>(null)
  const asked = useRef(new Set<string>())       // cells already loaded or loading
  const queue = useRef<{ key: string; lat: number; lon: number }[]>([])
  const running = useRef(0)
  const [base, setBase] = useState<Base>('white')
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('3D 엔진 불러오는 중…')
  const [buildings, setBuildings] = useState(0)
  const [counts, setCounts] = useState<HeightCounts>({ measured: 0, estimated: 0, unknown: 0 })
  const [pending, setPending] = useState(0)

  const pump = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    while (running.current < PARALLEL && queue.current.length) {
      const cell = queue.current.shift()!
      running.current++
      fetchContextBuildings(cell.lat, cell.lon, CELL_RADIUS_M)
        .then((reply) => {
          if (reply.status !== 'ok' || viewer.isDestroyed()) return
          const { counts: got } = drawContextMasses(viewer, Cesium, reply)
          setBuildings((n) => n + got.measured + got.estimated + got.unknown)
          setCounts((c) => ({ measured: c.measured + got.measured, estimated: c.estimated + got.estimated,
            unknown: c.unknown + got.unknown }))
        })
        .catch((error) => {
          asked.current.delete(cell.key) // try again on the next move
          setStatus(error instanceof Error ? error.message : String(error))
        })
        .finally(() => {
          running.current--
          setPending(queue.current.length + running.current)
          pump()
        })
    }
    setPending(queue.current.length + running.current)
  }, [])

  const loadVisible = useCallback(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    if (viewer.camera.positionCartographic.height > MAX_ALTITUDE_M) {
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

  const flyTo = useCallback((lat: number, lon: number) => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat - 0.0032, 520),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-42), roll: 0 },
      duration: 1.2,
    })
  }, [])

  const goTo = useCallback(async (input: string) => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium || !input.trim()) return
    setStatus('위치 찾는 중…')
    try {
      const parcel = await locateParcel(input)
      const ring = ringOf(parcel.geometry)
      viewer.entities.removeById('world-parcel')
      if (ring) {
        viewer.entities.add({ id: 'world-parcel', name: '대지', polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(ring.flatMap((c) => [c[0], c[1]])),
          width: 3, material: Cesium.Color.fromCssColorString('#e8590c'), clampToGround: false } })
      }
      const lat = parcel.coordinates?.y ?? (ring ? ring.reduce((s, c) => s + c[1]!, 0) / ring.length : NaN)
      const lon = parcel.coordinates?.x ?? (ring ? ring.reduce((s, c) => s + c[0]!, 0) / ring.length : NaN)
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error('위치를 찾지 못했습니다')
      flyTo(lat, lon)
      setStatus('')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    }
  }, [flyTo])

  useEffect(() => {
    let disposed = false
    loadCesium().then((Cesium) => {
      if (disposed || !host.current) return
      cesiumRef.current = Cesium
      const viewer = new Cesium.Viewer(host.current, {
        baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
        navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false,
        infoBox: true, selectionIndicator: true, terrainProvider: new Cesium.EllipsoidTerrainProvider(),
      })
      const scene = viewer.scene
      scene.globe.baseColor = Cesium.Color.fromCssColorString('#ecebe6')
      scene.backgroundColor = Cesium.Color.fromCssColorString('#f6f6f3')
      if (scene.skyBox) scene.skyBox.show = false
      if (scene.skyAtmosphere) scene.skyAtmosphere.show = false
      if (scene.sun) scene.sun.show = false
      scene.fog.enabled = false
      viewerRef.current = viewer
      viewer.camera.moveEnd.addEventListener(loadVisible)
      const q = new URLSearchParams(window.location.search)
      const lat = Number(q.get('lat')), lon = Number(q.get('lon'))
      const start = q.get('pnu') || q.get('q')
      if (start) {
        setQuery(start)
        viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(127.8, 36.3, 900000) })
        goTo(start)
      } else {
        const at = Number.isFinite(lat) && lat && Number.isFinite(lon) && lon ? { lat, lon } : GOSAN
        viewer.camera.setView({
          destination: Cesium.Cartesian3.fromDegrees(at.lon, at.lat - 0.0032, 520),
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-42), roll: 0 },
        })
        loadVisible()
      }
    }).catch((error) => setStatus(error.message))
    return () => {
      disposed = true
      queue.current = []
      viewerRef.current?.destroy()
      viewerRef.current = null
    }
  }, [goTo, loadVisible])

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
  }, [base, status])

  return <div className="relative h-[calc(100vh-3.5rem)] w-full">
    <div ref={host} className="absolute inset-0" />
    <div className="absolute left-3 top-3 z-10 flex w-80 flex-col gap-2 rounded-md bg-white/90 p-3 text-sm shadow">
      <div className="font-medium">주변 맥락 · 흰 매스</div>
      <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); goTo(query) }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="주소 또는 필지번호(PNU)"
          className="min-w-0 flex-1 border px-2 py-0.5" />
        <button type="submit" className="rounded border px-2 py-0.5">이동</button>
      </form>
      <div className="flex gap-3">
        <label><input type="radio" checked={base === 'white'} onChange={() => setBase('white')} /> 흰 바탕</label>
        <label><input type="radio" checked={base === 'vworld2d'} onChange={() => setBase('vworld2d')} /> 브이월드 2D 지도</label>
      </div>
      <div className="text-xs text-muted-foreground">
        건물 {buildings}동{pending ? ` · 불러오는 칸 ${pending}개` : ''} — 화면을 움직이면 보이는 곳이 채워집니다
      </div>
      <div className="text-xs text-muted-foreground">
        높이: 실측 {counts.measured} · 층수로 추정 {counts.estimated} · 모름 {counts.unknown}(옅게)
      </div>
      {status && <div className="text-xs text-muted-foreground">{status}</div>}
    </div>
  </div>
}
