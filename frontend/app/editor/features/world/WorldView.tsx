'use client'

/**
 * World view: our own Cesium globe with clean white context masses — works with no VWorld SDK or key.
 * Base map is a toggle: plain white, or the VWorld 2D map through the backend when its server key is set.
 * Plan (W0–W6, VWorld 3D toggle later): agents/SceneAgent/docs/editor-world-plan.md
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
import { useCallback, useEffect, useRef, useState } from 'react'
import { loadCesium } from './lib/cesium-loader'
import { type ContextReply, drawContextMasses, fetchContextBuildings } from './lib/context-masses'

const GOSAN = { lat: 37.73002, lon: 127.1085 } // 의정부 고산 공공1 — the project the agents are tested on
type Base = 'white' | 'vworld2d'

function startPoint() {
  const q = new URLSearchParams(window.location.search)
  const lat = Number(q.get('lat')), lon = Number(q.get('lon')), r = Number(q.get('r'))
  return { lat: Number.isFinite(lat) && lat ? lat : GOSAN.lat, lon: Number.isFinite(lon) && lon ? lon : GOSAN.lon,
    radius: Number.isFinite(r) && r >= 10 && r <= 1000 ? r : 300 }
}

export default function WorldView() {
  const host = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<any>(null)
  const cesiumRef = useRef<any>(null)
  const [base, setBase] = useState<Base>('white')
  const [radius, setRadius] = useState(300)
  const [status, setStatus] = useState('3D 엔진 불러오는 중…')
  const [counts, setCounts] = useState<ContextReply['counts']>()

  const load = useCallback(async (lat: number, lon: number, r: number) => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    setStatus(`주변 건물 불러오는 중… (반경 ${r} m)`)
    try {
      const reply = await fetchContextBuildings(lat, lon, r)
      if (reply.status !== 'ok') {
        setStatus(`주변 건물 없음: ${reply.reason ?? '근거 부족'}`)
        return
      }
      const n = drawContextMasses(viewer, Cesium, reply)
      setCounts(reply.counts)
      setStatus(`건물 ${n}동`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    }
  }, [])

  useEffect(() => {
    let disposed = false
    const start = startPoint()
    setRadius(start.radius)
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
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(start.lon, start.lat - 0.0032, 520),
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(-42), roll: 0 },
      })
      load(start.lat, start.lon, start.radius)
    }).catch((error) => setStatus(error.message))
    return () => {
      disposed = true
      viewerRef.current?.destroy()
      viewerRef.current = null
    }
  }, [load])

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

  const reloadHere = () => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium) return
    const centre = viewer.camera.pickEllipsoid(new Cesium.Cartesian2(viewer.canvas.clientWidth / 2, viewer.canvas.clientHeight / 2))
    if (!centre) return setStatus('화면 가운데가 땅을 가리키지 않습니다')
    const c = Cesium.Cartographic.fromCartesian(centre)
    load(Cesium.Math.toDegrees(c.latitude), Cesium.Math.toDegrees(c.longitude), radius)
  }

  return <div className="relative h-[calc(100vh-3.5rem)] w-full">
    <div ref={host} className="absolute inset-0" />
    <div className="absolute left-3 top-3 z-10 flex max-w-sm flex-col gap-2 rounded-md bg-white/90 p-3 text-sm shadow">
      <div className="font-medium">주변 맥락 · 흰 매스</div>
      <div className="flex gap-3">
        <label><input type="radio" checked={base === 'white'} onChange={() => setBase('white')} /> 흰 바탕</label>
        <label><input type="radio" checked={base === 'vworld2d'} onChange={() => setBase('vworld2d')} /> 브이월드 2D 지도</label>
      </div>
      <div className="flex items-center gap-2">
        <span>반경</span>
        <select value={radius} onChange={(e) => setRadius(Number(e.target.value))} className="border px-1">
          {[200, 300, 500, 800].map((r) => <option key={r} value={r}>{r} m</option>)}
        </select>
        <button type="button" onClick={reloadHere} className="rounded border px-2 py-0.5">화면 가운데 다시 불러오기</button>
      </div>
      <div className="text-muted-foreground">{status}</div>
      {counts && <div className="text-xs text-muted-foreground">
        높이: 실측 {counts.measured} · 층수로 추정 {counts.estimated} · 모름 {counts.unknown}(옅게)
      </div>}
    </div>
  </div>
}
