'use client'

/**
 * One 3D map, either engine: our clean world (useWorld3D) or the VWorld 3D SDK (useVworld3D). The page keeps its
 * own state and remounts only this component (key={engine}) when the user switches, so a chat or an analysis in
 * progress survives the switch. The engine's actions are handed up through onActions.
 */

import { type CSSProperties, useEffect, useRef } from 'react'
import { useVworld3D } from '../../land-map/hooks/use-vworld-3d'
import { useWorld3D } from '../hooks/use-world-3d'
import { WorldControls } from './WorldControls'

export type MapEngineKind = 'clean' | 'vworld'

export interface MapActions {
  ready: boolean
  loading: boolean
  error: string | null
  highlightParcel: (geometry: object) => void
  clearHighlight: () => void
  flyTo: (lng: number, lat: number, zoom?: number) => void
  /** Show or hide the surrounding buildings. */
  setBuildingsVisible: (visible: boolean) => void
  drawSetbackLines: (lines: Record<string, unknown>) => void
  clearSetbackLines: () => void
}

export function MapEngine({ engine, onClick, onActions, style, id }: {
  engine: MapEngineKind
  onClick: (lng: number, lat: number) => void
  onActions: (actions: MapActions) => void
  style?: CSSProperties
  id?: string
}) {
  const target = useRef<HTMLDivElement>(null)
  // engine is fixed for this component's life (the parent remounts it on change), so the hook order never changes.
  const use3D = engine === 'clean' ? useWorld3D : useVworld3D
  const map = use3D({ target, onClick })
  const world = engine === 'clean' ? (map as ReturnType<typeof useWorld3D>) : null
  const setShow = world?.setShow

  useEffect(() => {
    onActions({
      ready: map.ready, loading: map.loading, error: map.error,
      highlightParcel: map.highlightParcel, clearHighlight: map.clearHighlight, flyTo: map.flyTo,
      // "buildings off" here means all surrounding buildings, not only the ones on the site.
      setBuildingsVisible: setShow ? (v) => setShow((s) => ({ ...s, buildings: v })) : map.setBuildingsVisible,
      drawSetbackLines: map.drawSetbackLines, clearSetbackLines: map.clearSetbackLines,
    })
  }, [onActions, map.ready, map.loading, map.error, map.highlightParcel, map.clearHighlight, map.flyTo,
    map.setBuildingsVisible, map.drawSetbackLines, map.clearSetbackLines, setShow])

  return <>
    <div ref={target} id={id} style={{ width: '100%', height: '100%', ...style,
      background: engine === 'clean' ? '#f7f7f5' : style?.background }} />
    {world && <WorldControls world={world} title="주변 맥락" compact
      className="absolute bottom-3 right-3 z-10 flex flex-col gap-0.5 rounded-md bg-white/90 px-2 py-1 text-[11px] text-neutral-800 shadow" />}
  </>
}
