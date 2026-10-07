'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { MapEngine as WorldEngine, type MapActions } from '../../world/components/MapEngine'
import type { LngLat, ParcelSet } from './engine'
import { boundsCenter, parcelBounds, parcelRings } from './layers/parcelOutline'

/**
 * The 3D view of the same site: the world feature's Cesium engine (read-only
 * import), showing the parcels the 2D map has drawn. Clicks pick through the
 * same picker; Shift is not available here, so adding uses the card toggle.
 * The camera moves to the site only when this view is switched to.
 */
export default function World3D({ active, drawn, onPick }: { active: boolean; drawn: ParcelSet; onPick(at: LngLat): void }) {
  const [actions, setActions] = useState<MapActions | null>(null)
  const flown = useRef(false)
  const onClick = useCallback((lng: number, lat: number) => onPick([lng, lat]), [onPick])

  // The world draws one outline: the merged boundary of a bundle, else the single parcel.
  const shape = drawn.outline ?? drawn.geometries[0] ?? null
  useEffect(() => {
    if (!actions?.ready) return
    if (shape) actions.highlightParcel(shape)
    else actions.clearHighlight()
  }, [actions, shape])

  useEffect(() => {
    if (!active) {
      flown.current = false
      return
    }
    if (!actions?.ready || flown.current) return
    const bounds = parcelBounds(drawn.geometries.flatMap(parcelRings))
    if (!bounds) return
    flown.current = true
    actions.flyTo(...boundsCenter(bounds))
  }, [active, actions, drawn.geometries])

  return (
    <div className="site-map-3d" data-active={active}>
      <WorldEngine engine="clean" onActions={setActions} onClick={onClick} />
      {actions && !actions.ready && <span className="site-map-3d-status">{actions.error ?? '3D 불러오는 중'}</span>}
    </div>
  )
}
