'use client'

/**
 * World view: our own Cesium globe with clean white context masses — anywhere in Korea, no VWorld SDK or key.
 * Open it at a parcel (/world?pnu=… or ?q=<주소> or ?lat=&lon=) or search; as the camera moves, the cells it sees
 * are filled in. Base map is a toggle: plain white, or the VWorld 2D map through the backend.
 * Plan (W0–W6, VWorld 3D toggle later): agents/SceneAgent/docs/editor-world-plan.md
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { locateParcel } from '../land-map/lib/land-api-client'
import { WorldControls } from './components/WorldControls'
import { useWorld3D } from './hooks/use-world-3d'

const GOSAN = { lat: 37.73002, lon: 127.1085 } // only where the view opens when nothing is asked for

function centre(geometry: any): { lat: number; lon: number } | null {
  const g = geometry?.type === 'Feature' ? geometry.geometry : geometry
  const ring: number[][] | undefined = g?.type === 'Polygon' ? g.coordinates[0] : g?.type === 'MultiPolygon' ? g.coordinates[0][0] : undefined
  if (!ring?.length) return null
  return { lat: ring.reduce((s, c) => s + c[1]!, 0) / ring.length, lon: ring.reduce((s, c) => s + c[0]!, 0) / ring.length }
}

export default function WorldView() {
  const host = useRef<HTMLDivElement>(null)
  const world = useWorld3D({ target: host })
  const { ready, viewerRef, cesiumRef, highlightParcel, flyTo, loadVisible, setStatus } = world
  const [query, setQuery] = useState('')

  const goTo = useCallback(async (input: string) => {
    if (!input.trim()) return
    setStatus('위치 찾는 중…')
    try {
      const parcel = await locateParcel(input)
      highlightParcel(parcel.geometry)
      const at = parcel.coordinates ? { lat: parcel.coordinates.y, lon: parcel.coordinates.x } : centre(parcel.geometry)
      if (!at) throw new Error('위치를 찾지 못했습니다')
      flyTo(at.lon, at.lat)
      setStatus('')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error))
    }
  }, [highlightParcel, flyTo, setStatus])

  useEffect(() => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!ready || !viewer || !Cesium) return
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
  }, [ready, viewerRef, cesiumRef, goTo, loadVisible])

  return <div className="relative h-[calc(100vh-3.5rem)] w-full">
    <div ref={host} className="absolute inset-0" />
    <WorldControls world={world} title="주변 맥락 · 흰 매스">
      <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); goTo(query) }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="주소 또는 필지번호(PNU)"
          className="min-w-0 flex-1 border px-2 py-0.5" />
        <button type="submit" className="rounded border px-2 py-0.5">이동</button>
      </form>
    </WorldControls>
  </div>
}
