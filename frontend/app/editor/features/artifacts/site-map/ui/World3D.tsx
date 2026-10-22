'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { WorldControls } from '../../../world/components/WorldControls'
import { useWorld3D } from '../../../world/hooks/use-world-3d'
import { prepareCesium } from '../../../world/lib/cesium-loader'
import { prepareBuildingTiles } from '../../../world/lib/building-tiles'
import type { IntentView, LayoutView } from '../../../world/lib/layout-masses'
import type { LngLat, ParcelSet } from '../lib/engine'
import { boundsCenter, parcelBounds, parcelRings } from '../lib/layers/parcelOutline'
import { sitePose } from '../lib/site-pose'

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
export interface LayoutOverlay {
  layout: LayoutView
  intent: IntentView | null
  /** One line for the status corner: which run, how many storeys, on what basis. */
  caption: string
  runId?: string
}

export default function World3D({ active, drawn, onPick, overlay = null }: { active: boolean; drawn: ParcelSet; onPick(at: LngLat): void; overlay?: LayoutOverlay | null }) {
  useEffect(() => {
    if (!active) return
    // Fetch the engine and archive while the parcel is located; the viewer still waits for its actual site.
    void prepareCesium().catch(() => {})
    void prepareBuildingTiles().catch(() => {})
  }, [active])
  // The world draws one outline: the merged boundary of a bundle, else the single parcel.
  const shape = drawn.outline ?? drawn.geometries[0] ?? null
  const [known, setKnown] = useState(shape !== null)
  useEffect(() => {
    if (shape) setKnown(true)
  }, [shape])

  return (
    <div className="site-map-3d" data-active={active}>
      {known
        ? <SiteWorld active={active} drawn={drawn} onPick={onPick} overlay={overlay} shape={shape} />
        : <span className="site-map-3d-status">대지 불러오는 중</span>}
    </div>
  )
}

/** Metres between two lon/lat points (flat, good enough within a city). */
function metres([lng1, lat1]: LngLat, [lng2, lat2]: LngLat): number {
  return Math.hypot((lat1 - lat2) * 111_000, (lng1 - lng2) * 88_000)
}

function SiteWorld({ active, drawn, onPick, overlay, shape }: { active: boolean; drawn: ParcelSet; onPick(at: LngLat): void; overlay: LayoutOverlay | null; shape: object | null }) {
  const target = useRef<HTMLDivElement>(null)
  const onClick = useCallback((lng: number, lat: number) => onPick([lng, lat]), [onPick])
  const world = useWorld3D({ target, onClick })
  const { ready, error, viewerRef, cesiumRef, highlightParcel, clearHighlight, flyTo, frameSite, drawLayout } = world

  // The planned building (the newest 배치 설계 of this site) stands on the parcel; it follows the ground setting.
  useEffect(() => {
    if (!ready) return
    drawLayout(overlay?.layout ?? null, overlay?.intent ?? null)
  }, [ready, overlay, drawLayout, world.terrain])
  /** The site the camera was last placed on in this activation; null = not yet. */
  const placed = useRef<string | null>(null)
  /** The parcels' look on the previous pass (every pass, placed or not): a site confirmed again turns 'saved' from
   *  'site' or 'picked', and that turn moves the camera even onto the same parcel. */
  const lastLook = useRef<string | null>(null)

  /** The camera's ground point under the screen centre's pose: where flyTo leaves it, as [lng, lat]. */
  const cameraAt = useCallback((): LngLat | null => {
    const viewer = viewerRef.current, Cesium = cesiumRef.current
    if (!viewer || !Cesium || viewer.isDestroyed()) return null
    const p = viewer.camera.positionCartographic
    return [Cesium.Math.toDegrees(p.longitude), Cesium.Math.toDegrees(p.latitude)]
  }, [viewerRef, cesiumRef])

  /** The engine's own site pose (flyTo), completed at once; true when the camera is there. */
  const place = useCallback(([lng, lat]: LngLat, bounds?: readonly [number, number, number, number]): boolean => {
    // The camera frames the parcel itself (its size sets the distance), not a fixed wide pose over its centre.
    if (bounds) frameSite(lng, lat, sitePose(bounds))
    else flyTo(lng, lat)
    viewerRef.current?.camera.completeFlight()
    const at = cameraAt()
    return at !== null && metres(at, [lng, lat]) < 1500
  }, [flyTo, frameSite, viewerRef, cameraAt])

  useEffect(() => {
    if (!active) placed.current = null
  }, [active])

  // Hidden, the 3D view must not keep rendering frames: its render loop stops and restarts on return.
  useEffect(() => {
    const viewer = viewerRef.current
    if (!ready || !viewer || viewer.isDestroyed()) return
    viewer.useDefaultRenderLoop = active
    if (active) viewer.scene.requestRender()
  }, [ready, active, viewerRef])

  useEffect(() => {
    if (!ready) return
    if (!shape) {
      clearHighlight()
      return
    }
    highlightParcel(shape)
    const previousLook = lastLook.current
    lastLook.current = drawn.look
    const bounds = parcelBounds(drawn.geometries.flatMap(parcelRings))
    if (!active || !bounds) return
    const center = boundsCenter(bounds)
    const key = center.map((v) => v.toFixed(6)).join(',')
    // Once per activation; afterwards a searched, restored or newly confirmed site moves the camera (confirming the
    // same parcel again from the conversation included), never a click preview.
    const confirmed = drawn.look === 'saved' && previousLook !== 'saved'
    if (placed.current !== null && (drawn.look === 'picked' || (placed.current === key && !confirmed))) return
    placed.current = key
    if (place(center, bounds)) return
    // Not there (the viewer was not ready to move): try once more on the next frame.
    const frame = requestAnimationFrame(() => {
      if (!place(center, bounds)) console.warn('[site-map] 3D camera did not reach the site', center, cameraAt())
    })
    return () => cancelAnimationFrame(frame)
  }, [ready, active, shape, drawn.geometries, drawn.look, highlightParcel, clearHighlight, place, cameraAt])

  return (
    <>
      <div className="site-map-world" ref={target} />
      <WorldControls world={world} title="주변 맥락" compact className="site-map-world-controls" />
      {overlay && <span className="site-map-3d-layout">{overlay.caption}</span>}
      {!ready && <span className="site-map-3d-status">{error ?? '3D 불러오는 중'}</span>}
    </>
  )
}
