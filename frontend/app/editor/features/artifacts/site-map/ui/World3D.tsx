'use client'

import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'

import { WorldControls } from '../../../world/components/WorldControls'
import { useWorld3D } from '../../../world/hooks/use-world-3d'
import { prepareCesium } from '../../../world/lib/cesium-loader'
import { prepareWorldBuildingRenderer } from '../../../world/lib/world-building-renderer'
import { defaultMapReleaseReader } from '../../../world/lib/map-release'
import { placeSiteCamera } from '../../../world/lib/site-camera'
import { showVworldPhotoBuildings } from '../../../world/lib/vworld-photo-buildings'
import type { IntentView, LayoutView } from '../../../world/lib/layout-masses'
import type { LngLat, ParcelSet } from '../lib/engine'
import { boundsCenter, parcelBounds, parcelRings } from '../lib/layers/parcelOutline'
import { shouldFrameSite, sitePose } from '../lib/site-pose'
import { readSceneCamera, restoreSceneCamera, type SceneCamera } from '../lib/scene-camera'
import VworldSiteWorld from './VworldSiteWorld'

/**
 * The 3D view of the same site: the world feature's Cesium engine (read-only
 * import), showing the parcels the 2D map has drawn. Clicks pick through the
 * same picker; Shift is not available here, so adding uses the card toggle.
 *
 * The engine is created only once the site is known, and the camera is placed
 * on the site at once (no flight), so the world never starts loading cells
 * around its default opening view (Seoul) — they queue ahead of the site's.
 * The camera frames the initial site and a different searched or restored site.
 * Returning to this view or confirming the same site preserves the user's pose.
 */
export interface LayoutOverlay {
  layout: LayoutView
  intent: IntentView | null
  /** One line for the status corner: which run, how many storeys, on what basis. */
  caption: string
  runId?: string
}

export default function World3D({ active, drawn, onPick, overlay = null, photo = false }: { active: boolean; drawn: ParcelSet; onPick(at: LngLat): void; overlay?: LayoutOverlay | null; photo?: boolean }) {
  const [mode, setMode] = useState<'mass' | 'photo' | 'lod1' | 'textured'>('mass')
  const viewer = useRef<any>(null)
  const camera = useRef<SceneCamera | null>(null)
  const onViewer = useCallback((value: any) => { viewer.current = value }, [])
  const chooseMode = useCallback(async (next: typeof mode) => {
    // Finish the shared-global Cesium preload before mounting the SDK's own build.
    await prepareCesium().catch(() => {})
    camera.current = readSceneCamera(viewer.current)
    setMode(next)
  }, [])
  // The map's 실사 button switches between our masses and VWorld's textured buildings.
  useEffect(() => { setMode(current => photo ? 'photo' : current === 'photo' ? 'mass' : current) }, [photo])
  const controls = <label className="flex items-center gap-2">건물 표시
    <select aria-label="건물 표시 방식" value={mode} onChange={e => void chooseMode(e.target.value as typeof mode)}>
      <option value="mass">흰 매스</option>
      <option value="photo">실사 (내부 확인용)</option>
      <option value="lod1">브이월드 LoD1</option>
      <option value="textured">브이월드 텍스처 모델</option>
    </select>
  </label>
  useEffect(() => {
    if (!active || (mode !== 'mass' && mode !== 'photo')) return
    // Fetch the engine and archive while the parcel is located; the viewer still waits for its actual site.
    void prepareCesium().catch(() => {})
    void prepareWorldBuildingRenderer(defaultMapReleaseReader).catch(() => {})
  }, [active, mode])
  // The world draws one outline: the merged boundary of a bundle, else the single parcel.
  const shape = drawn.outline ?? drawn.geometries[0] ?? null
  const [known, setKnown] = useState(shape !== null)
  useEffect(() => {
    if (shape) setKnown(true)
  }, [shape])

  return (
    <div className="site-map-3d" data-active={active}>
      {known
        ? mode === 'mass' || mode === 'photo'
          ? <SiteWorld active={active} drawn={drawn} onPick={onPick} overlay={overlay} shape={shape} controls={controls} camera={camera.current} onViewer={onViewer} photo={mode === 'photo'} />
          : <VworldSiteWorld active={active} drawn={drawn} onPick={onPick} overlay={overlay} shape={shape} mode={mode} controls={controls} camera={camera.current} onViewer={onViewer} />
        : <span className="site-map-3d-status">대지 불러오는 중</span>}
    </div>
  )
}

function SiteWorld({ active, drawn, onPick, overlay, shape, controls, camera, onViewer, photo }: {
  active: boolean; drawn: ParcelSet; onPick(at: LngLat): void; overlay: LayoutOverlay | null; shape: object | null
  controls: ReactNode; camera: SceneCamera | null; onViewer(viewer: any): void; photo: boolean
}) {
  const target = useRef<HTMLDivElement>(null)
  const onClick = useCallback((lng: number, lat: number) => onPick([lng, lat]), [onPick])
  const openingBounds = parcelBounds(drawn.geometries.flatMap(parcelRings))
  const initialCamera = useRef(camera)
  const initialized = useRef<string | null>(null)
  const world = useWorld3D({ target, onClick, initialLocation: openingBounds ? boundsCenter(openingBounds) : undefined,
    initializeCamera: async (viewer, C, sample, live) => {
      if (initialCamera.current) {
        restoreSceneCamera(viewer, C, initialCamera.current)
        initialCamera.current = null
        initialized.current = openingBounds ? boundsCenter(openingBounds).map(v => v.toFixed(6)).join(',') : null
      } else if (openingBounds) {
        const [lon, lat] = boundsCenter(openingBounds)
        if (await placeSiteCamera(viewer, C, lon, lat, sitePose(openingBounds, viewer.camera.frustum), sample, live, () => undefined, true)) {
          initialized.current = [lon, lat].map(v => v.toFixed(6)).join(',')
        }
      }
    } })
  const { ready, error, viewerRef, highlightParcel, clearHighlight, frameSite, drawLayout } = world
  useEffect(() => { if (ready) onViewer(viewerRef.current) }, [ready, onViewer, viewerRef])

  // 실사: VWorld's textured buildings replace ours in this same viewer; site, terrain and planned masses stay.
  const { setStatus } = world
  useEffect(() => {
    const viewer = viewerRef.current, C = world.cesiumRef.current
    if (!ready || !photo || !viewer || !C) return
    return showVworldPhotoBuildings(viewer, C, setStatus)
  }, [ready, photo, viewerRef, world.cesiumRef, setStatus])

  // The planned building (the newest 배치 설계 of this site) stands on the parcel; it follows the ground setting.
  useEffect(() => {
    if (!ready) return
    drawLayout(overlay?.layout ?? null, overlay?.intent ?? null)
  }, [ready, overlay, drawLayout, world.terrain])
  /** The last framed site survives hiding the view so returning preserves a user's pose. */
  const placed = useRef<string | null>(null)

  const place = useCallback(([lng, lat]: LngLat, bounds: readonly [number, number, number, number]) => {
    const initializedSite = initialized.current
    initialized.current = null
    if (initializedSite === [lng, lat].map(v => v.toFixed(6)).join(',')) return
    if (initialCamera.current && world.cesiumRef.current) {
      restoreSceneCamera(viewerRef.current, world.cesiumRef.current, initialCamera.current)
      initialCamera.current = null
      return
    }
    const frustum = viewerRef.current?.camera.frustum
    return frameSite(lng, lat, sitePose(bounds, { aspectRatio: frustum?.aspectRatio, fovy: frustum?.fovy }))
  }, [frameSite, viewerRef, world.cesiumRef])

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
    const bounds = parcelBounds(drawn.geometries.flatMap(parcelRings))
    if (!active || !bounds) return
    const center = boundsCenter(bounds)
    const key = center.map((v) => v.toFixed(6)).join(',')
    // A delayed save acknowledgement must not undo zoom/pan on the same site.
    // Explicit searches or confirmations of a different site still frame it.
    if (!shouldFrameSite(placed.current, key, drawn.look)) return
    placed.current = key
    void place(center, bounds)
  }, [ready, active, shape, drawn.geometries, drawn.look, highlightParcel, clearHighlight, place])

  return (
    <>
      <div className="site-map-world" ref={target} />
      <WorldControls world={world} title="주변 맥락" compact className="site-map-world-controls">{controls}</WorldControls>
      {overlay && <span className="site-map-3d-layout">{overlay.caption}</span>}
      {!ready && <span className="site-map-3d-status">{error ?? '3D 불러오는 중'}</span>}
    </>
  )
}
