'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { WorldControls } from '../../world/components/WorldControls'
import { useWorld3D } from '../../world/hooks/use-world-3d'
import type { LngLat, ParcelSet } from './engine'
import { boundsCenter, parcelBounds, parcelRings } from './layers/parcelOutline'

/**
 * The 3D view of the same site: the world feature's Cesium engine (read-only
 * import), showing the parcels the 2D map has drawn. Clicks pick through the
 * same picker; Shift is not available here, so adding uses the card toggle.
 *
 * The engine is created only once the site is known, and the camera is placed
 * on the site at once (no flight), so the world never starts loading cells
 * around its default opening view (Seoul) — they queue ahead of the site's.
 * The camera moves when this view is switched to, and when a different site
 * is searched or restored while it is shown; never on a click preview.
 */
export default function World3D({ active, drawn, onPick }: { active: boolean; drawn: ParcelSet; onPick(at: LngLat): void }) {
  // The world draws one outline: the merged boundary of a bundle, else the single parcel.
  const shape = drawn.outline ?? drawn.geometries[0] ?? null
  const [known, setKnown] = useState(shape !== null)
  useEffect(() => {
    if (shape) setKnown(true)
  }, [shape])

  return (
    <div className="site-map-3d" data-active={active}>
      {known
        ? <SiteWorld active={active} drawn={drawn} onPick={onPick} shape={shape} />
        : <span className="site-map-3d-status">대지 불러오는 중</span>}
    </div>
  )
}

/** Metres between two lon/lat points (flat, good enough within a city). */
function metres([lng1, lat1]: LngLat, [lng2, lat2]: LngLat): number {
  return Math.hypot((lat1 - lat2) * 111_000, (lng1 - lng2) * 88_000)
}

function SiteWorld({ active, drawn, onPick, shape }: { active: boolean; drawn: ParcelSet; onPick(at: LngLat): void; shape: object | null }) {
  const target = useRef<HTMLDivElement>(null)
  const onClick = useCallback((lng: number, lat: number) => onPick([lng, lat]), [onPick])
  const world = useWorld3D({ target, onClick })
  const { ready, error, viewerRef, cesiumRef, highlightParcel, clearHighlight, flyTo } = world
  /** The site the camera was last placed on in this activation; null = not yet. */
  const placed = useRef<string | null>(null)

  /** The camera's ground point under the screen centre's pose: where flyTo leaves it, as [lng, lat]. */
  const cameraAt = useCallback((): LngLat | null => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium || viewer.isDestroyed()) return null
    const p = viewer.camera.positionCartographic
    return [Cesium.Math.toDegrees(p.longitude), Cesium.Math.toDegrees(p.latitude)]
  }, [viewerRef, cesiumRef])

  /** The engine's own site pose (flyTo), completed at once; true when the camera is there. */
  const place = useCallback(([lng, lat]: LngLat): boolean => {
    flyTo(lng, lat)
    viewerRef.current?.camera.completeFlight()
    const at = cameraAt()
    return at !== null && metres(at, [lng, lat]) < 1500
  }, [flyTo, viewerRef, cameraAt])

  useEffect(() => {
    if (!active) placed.current = null
  }, [active])

  useEffect(() => {
    if (!ready) return
    if (!shape) {
      clearHighlight()
      return
    }
    highlightParcel(shape)
    const bounds = parcelBounds(drawn.geometries.flatMap(parcelRings))
    if (!active || !bounds) return
    const center = boundsCenter(bounds)
    const key = center.map((v) => v.toFixed(6)).join(',')
    // Once per activation; afterwards only a searched or restored site moves the camera, never a click preview.
    if (placed.current !== null && (drawn.look === 'picked' || placed.current === key)) return
    placed.current = key
    if (place(center)) return
    // Not there (the viewer was not ready to move): try once more on the next frame.
    const frame = requestAnimationFrame(() => {
      if (!place(center)) console.warn('[site-map] 3D camera did not reach the site', center, cameraAt())
    })
    return () => cancelAnimationFrame(frame)
  }, [ready, active, shape, drawn.geometries, drawn.look, highlightParcel, clearHighlight, place, cameraAt])

  return (
    <>
      <div ref={target} style={{ width: '100%', height: '100%', background: '#f7f7f5' }} />
      <WorldControls world={world} title="주변 맥락" compact
        className="absolute bottom-3 right-3 z-10 flex flex-col gap-0.5 rounded-md bg-white/90 px-2 py-1 text-[11px] text-neutral-800 shadow" />
      {!ready && <span className="site-map-3d-status">{error ?? '3D 불러오는 중'}</span>}
    </>
  )
}
