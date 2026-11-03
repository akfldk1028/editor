'use client'

import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { useVworld3D } from '../../../land-map/hooks/use-vworld-3d'
import { getCesium } from '../../../land-map/lib/vworld-3d-loader'
import type { VworldBuildingMode } from '../../../land-map/lib/vworld-buildings'
import { clearLayout, drawLayout, excavate, showUnderground } from '../../../world/lib/layout-masses'
import type { LngLat, ParcelSet } from '../lib/engine'
import { boundsCenter, parcelBounds, parcelRings } from '../lib/layers/parcelOutline'
import { restoreSceneCamera, type SceneCamera } from '../lib/scene-camera'
import type { LayoutOverlay } from './World3D'

export default function VworldSiteWorld({ active, drawn, onPick, overlay, shape, mode, controls, camera, onViewer }: {
  active: boolean; drawn: ParcelSet; onPick(at: LngLat): void; overlay: LayoutOverlay | null; shape: object | null
  mode: VworldBuildingMode; controls: ReactNode; camera: SceneCamera | null; onViewer(viewer: any): void
}) {
  const target = useRef<HTMLDivElement>(null)
  const onClick = useCallback((lon: number, lat: number) => onPick([lon, lat]), [onPick])
  const bounds = parcelBounds(drawn.geometries.flatMap(parcelRings))
  const map = useVworld3D({ target, onClick, initialLocation: bounds ? boundsCenter(bounds) : undefined, imagery: 'satellite' })
  const { ready, error, viewerRef, highlightParcel, clearHighlight, flyTo, setBuildingMode, setBuildingsVisible } = map
  const [unavailable, setUnavailable] = useState(false)
  const [buildings, setBuildings] = useState(true)
  const [planned, setPlanned] = useState(true)
  const placed = useRef<string | null>(null)
  const initialCamera = useRef(camera)
  const lastLook = useRef<string | null>(null)

  useEffect(() => {
    if (!ready) return
    onViewer(viewerRef.current)
    ;(target.current as any).__vworldViewer = viewerRef.current
  }, [ready, onViewer, viewerRef])

  useEffect(() => {
    if (!ready) return
    const available = setBuildingMode(mode)
    setUnavailable(!available)
    if (!buildings || !available) setBuildingsVisible(false)
  }, [ready, mode, buildings, setBuildingMode, setBuildingsVisible])

  useEffect(() => {
    if (!ready) return
    const viewer = viewerRef.current
    viewer.useDefaultRenderLoop = active
    if (active) { viewer.resize(); viewer.scene.requestRender() }
    else placed.current = null
  }, [ready, active, viewerRef])

  useEffect(() => {
    if (!ready) return
    if (shape) highlightParcel(shape)
    else clearHighlight()
    const bounds = parcelBounds(drawn.geometries.flatMap(parcelRings))
    const previousLook = lastLook.current
    lastLook.current = drawn.look
    if (!active || !bounds) return
    const center = boundsCenter(bounds)
    const key = center.map(v => v.toFixed(6)).join(',')
    const confirmed = drawn.look === 'saved' && previousLook !== 'saved'
    if (placed.current !== null && (drawn.look === 'picked' || (placed.current === key && !confirmed))) return
    placed.current = key
    const pose = initialCamera.current
    initialCamera.current = null
    if (pose) restoreSceneCamera(viewerRef.current, getCesium(), pose)
    else flyTo(...center)
  }, [ready, active, shape, drawn.geometries, drawn.look, highlightParcel, clearHighlight, flyTo, viewerRef])

  useEffect(() => {
    if (!ready) return
    const viewer = viewerRef.current, C = getCesium()
    showUnderground(C, viewer.scene.globe, planned ? overlay?.layout ?? null : null)
    const layout = planned && overlay ? { ...overlay.layout, cutaway: true } : null
    excavate(C, viewer.scene.globe, layout)
    if (overlay && layout) drawLayout(viewer.entities, C, layout, overlay.intent, 'terrain')
    else clearLayout(viewer.entities)
    viewer.scene.requestRender()
    return () => { if (!viewer.isDestroyed()) clearLayout(viewer.entities) }
  }, [ready, overlay, planned, viewerRef])

  return <>
    <div className="site-map-world" ref={target} />
    <div className="site-map-world-controls">
      <div className="font-medium">주변 맥락</div>
      {controls}
      <div className="flex gap-3">
        <label><input type="checkbox" checked={buildings} onChange={e => setBuildings(e.target.checked)} /> 주변 건물</label>
        {overlay && <label><input type="checkbox" checked={planned} onChange={e => setPlanned(e.target.checked)} /> 계획 건물</label>}
      </div>
      <div className="text-xs text-neutral-500">브이월드 제공 지역에 표시됩니다. 정밀 모델은 지역별로 다릅니다.</div>
      {unavailable && <div role="status">이 지도에서는 선택한 건물 레이어를 사용할 수 없습니다.</div>}
    </div>
    {overlay && planned && <span className="site-map-3d-layout">{overlay.caption}</span>}
    {!ready && <span className="site-map-3d-status">{error ?? '브이월드 불러오는 중'}</span>}
  </>
}
