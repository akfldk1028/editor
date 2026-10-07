'use client'

import { Layers, Minus, Plus, Search } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import { locateParcel } from '../../land-map/lib/land-api-client'
import type { ArtifactProps } from '../../shell/artifact-types'
import { chooseEngine, createMapEngine, type LngLat, type MapEngine, type MapEngineKind } from './engine'
import { boundsCenter, parcelBounds, parcelRings } from './layers/parcelOutline'
import { siteFromParams, type Site } from './site'
import './site-map.css'

const naverKeyId = process.env.NEXT_PUBLIC_NAVER_MAP_KEY_ID
/** Near 고산 so the first frame is already in the right city while the parcel loads. */
const initialView = { center: [127.1084, 37.7301] as LngLat, zoom: 17 }
const engineLabels: Record<MapEngineKind, string> = { naver: 'NAVER 지도', openlayers: 'VWorld (임시)' }

type Status = { kind: 'idle' } | { kind: 'busy'; text: string } | { kind: 'error'; text: string }

/** The default artifact: the site's parcel on a 2D cadastral map. */
export default function SiteMapArtifact({ params, shell }: ArtifactProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<MapEngine | null>(null)
  const searchAbort = useRef<AbortController | null>(null)
  const [initialSite] = useState(() => siteFromParams(params))
  const [engineKind, setEngineKind] = useState<MapEngineKind | null>(null)
  const [cadastral, setCadastral] = useState(true)
  const cadastralRef = useRef(cadastral)
  const [query, setQuery] = useState('')
  const [site, setSite] = useState<Site>(initialSite)
  const [status, setStatus] = useState<Status>({ kind: 'busy', text: '지도를 불러오는 중' })
  const { setTitle } = shell

  useEffect(() => {
    setTitle('대지 지도', site.label)
  }, [setTitle, site.label])

  const locate = useCallback(async (target: Site, withMarker: boolean) => {
    const engine = engineRef.current
    if (!engine) return
    searchAbort.current?.abort()
    const controller = new AbortController()
    searchAbort.current = controller
    setStatus({ kind: 'busy', text: '필지를 찾는 중' })
    try {
      const parcel = await locateParcel(target.query, controller.signal)
      if (controller.signal.aborted || engineRef.current !== engine) return
      engine.fitParcel(parcel.geometry)
      const bounds = parcelBounds(parcelRings(parcel.geometry))
      const position: LngLat | null = parcel.coordinates
        ? [parcel.coordinates.x, parcel.coordinates.y]
        : bounds ? boundsCenter(bounds) : null
      engine.setMarker(withMarker ? position : null)
      setSite(target)
      setStatus({ kind: 'idle' })
    } catch (error) {
      if (controller.signal.aborted) return
      setStatus({ kind: 'error', text: error instanceof Error ? error.message : '필지를 찾지 못했습니다.' })
    }
  }, [])

  // One engine per mount; a refused Naver key falls back to the temporary engine.
  useEffect(() => {
    const element = mapRef.current
    if (!element) return
    let disposed = false
    let engine: MapEngine | null = null

    async function start(kind: MapEngineKind) {
      engine = await createMapEngine(kind, naverKeyId)
      if (disposed) return engine.destroy()
      try {
        await engine.mount(element!, initialView, { cadastral: cadastralRef.current })
      } catch (error) {
        engine.destroy()
        engine = null
        element!.replaceChildren()
        if (disposed) return
        if (kind !== 'naver') throw error
        console.error('[site-map] Naver engine failed; using the temporary engine.', error)
        setStatus({ kind: 'error', text: `${error instanceof Error ? error.message : '네이버 지도 오류'} 임시 지도로 표시합니다.` })
        return start('openlayers')
      }
      if (disposed) return engine.destroy()
      engineRef.current = engine
      setEngineKind(kind)
      await locate(initialSite, false)
    }

    start(chooseEngine(params.engine, naverKeyId)).catch((error: unknown) => {
      if (!disposed) setStatus({ kind: 'error', text: error instanceof Error ? error.message : '지도를 불러오지 못했습니다.' })
    })
    return () => {
      disposed = true
      searchAbort.current?.abort()
      engine?.destroy()
      engineRef.current = null
    }
  }, [initialSite, locate, params.engine])

  function toggleCadastral() {
    const next = !cadastral
    cadastralRef.current = next
    setCadastral(next)
    engineRef.current?.setLayers({ cadastral: next })
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    const value = query.trim()
    if (value) void locate({ query: value, label: value }, true)
  }

  return (
    <div className="site-map" data-engine={engineKind ?? undefined}>
      {/* Providers restyle their target (Naver makes it position: relative), so they get an inner element. */}
      <div aria-label={`${site.label} 지도`} className="site-map-canvas" role="img"><div ref={mapRef} /></div>

      <form className="site-map-search" onSubmit={submit} role="search">
        <Search aria-hidden="true" size={14} />
        <input
          aria-label="주소 또는 PNU 검색"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="주소 또는 PNU"
          type="search"
          value={query}
        />
      </form>

      <div aria-label="지도 조작" className="site-map-controls" role="group">
        <button aria-label="확대" className="site-map-button" onClick={() => engineRef.current?.zoomBy(1)} title="확대" type="button"><Plus size={16} /></button>
        <button aria-label="축소" className="site-map-button" onClick={() => engineRef.current?.zoomBy(-1)} title="축소" type="button"><Minus size={16} /></button>
        <button aria-label="지적편집도" aria-pressed={cadastral} className="site-map-button" onClick={toggleCadastral} title="지적편집도" type="button"><Layers size={16} /></button>
      </div>

      <div className="site-map-status" role="status">
        {status.kind !== 'idle' && <span data-kind={status.kind}>{status.text}</span>}
        {engineKind && <small>{engineLabels[engineKind]}</small>}
      </div>
    </div>
  )
}
