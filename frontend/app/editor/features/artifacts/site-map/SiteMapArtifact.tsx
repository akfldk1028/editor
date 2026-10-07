'use client'

import { Layers, Minus, Plus, Search } from 'lucide-react'
import dynamic from 'next/dynamic'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'

import { locateParcel } from '../../land-map/lib/land-api-client'
import type { ArtifactProps } from '../../shell/artifact-types'
import { chooseEngine, createMapEngine, type LngLat, type MapEngine, type MapEngineKind } from './engine'
import { boundsCenter, parcelBounds, parcelRings } from './layers/parcelOutline'
import { latestSite, type SavedSite } from './selection'
import { defaultSite, siteFromSelection, siteParam, type Site } from './site'
import { SiteCard } from './SiteCard'
import { usePicker } from './usePicker'
import './site-map.css'

/** Loaded the first time 3D is chosen; it stays mounted (hidden) after that. */
const World3D = dynamic(() => import('./World3D'), { ssr: false })
type View = '2d' | '3d'
const VIEW_KEY = 'site-map.view'

/** `?view=` wins, then the viewer's last choice. */
function initialView3d(params: Readonly<Record<string, string>>): View {
  if (params.view === '3d' || params.view === '2d') return params.view
  try {
    return window.localStorage.getItem(VIEW_KEY) === '3d' ? '3d' : '2d'
  } catch {
    return '2d'
  }
}

const naverKeyId = process.env.NEXT_PUBLIC_NAVER_MAP_KEY_ID
/** Near 고산 so the first frame is already in the right city while the parcel loads. */
const initialView = { center: [127.1084, 37.7301] as LngLat, zoom: 17 }
const engineLabels: Record<MapEngineKind, string> = { naver: 'NAVER 지도', openlayers: 'VWorld (임시)' }

type Status = { kind: 'idle' } | { kind: 'busy'; text: string } | { kind: 'error'; text: string }

/** The default artifact: the site's parcels on a 2D cadastral map; click to pick, Shift+click to add. */
export default function SiteMapArtifact({ params, shell }: ArtifactProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  const engineRef = useRef<MapEngine | null>(null)
  const searchAbort = useRef<AbortController | null>(null)
  // `?pnu=` / `?address=` wins; otherwise the last saved site, else the default.
  const [requestedSite] = useState(() => siteParam(params))
  const [engineKind, setEngineKind] = useState<MapEngineKind | null>(null)
  const [cadastral, setCadastral] = useState(true)
  const cadastralRef = useRef(cadastral)
  const [query, setQuery] = useState('')
  const [site, setSite] = useState<Site>(() => requestedSite ?? { query: '', label: '' })
  const [status, setStatus] = useState<Status>({ kind: 'busy', text: '지도를 불러오는 중' })
  const [view, setView] = useState<View>(() => initialView3d(params))
  const [opened3d, setOpened3d] = useState(view === '3d')
  const { setTitle } = shell
  const onSaved = useCallback((saved: SavedSite) => setSite(siteFromSelection({ pnu: saved.parcels[0]!.pnu, address: saved.label })), [])
  const picker = usePicker(engineRef, onSaved)
  const { showSearched } = picker
  // The engine is built once per mount; it reaches the latest handlers through this ref, so
  // picking (which changes state) never rebuilds the map or moves the view.
  const latest = useRef({ picker, locate: (_target: Site, _withMarker: boolean): Promise<void> => Promise.resolve() })

  useEffect(() => {
    setTitle('대지 지도', site.label || undefined)
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
      showSearched(parcel.geometry)
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
  }, [showSearched])
  useEffect(() => { latest.current = { picker, locate } })

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
      engine.onClick((event) => latest.current.picker.handleClick(event))
      engine.onHover((at) => latest.current.picker.handleHover(at))
      // The opening view, once: `?pnu=`/`?address=`, else the saved site, else the default.
      if (requestedSite) return latest.current.locate(requestedSite, false)
      if (!(await openSaved())) await latest.current.locate({ ...defaultSite }, false)
    }

    /** The last saved site, when there is one; false opens the default instead. */
    async function openSaved(): Promise<boolean> {
      try {
        const saved = await latestSite()
        if (!saved || disposed) return false
        setStatus({ kind: 'busy', text: '선택한 대지를 불러오는 중' })
        await latest.current.picker.restore(saved)
        if (disposed) return true
        setSite(siteFromSelection({ pnu: saved.parcels[0]!.pnu, address: saved.label }))
        setStatus({ kind: 'idle' })
        return true
      } catch (error) {
        console.error('[site-map] Saved site unavailable; opening the default site.', error)
        return false
      }
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
  }, [params.engine, requestedSite])

  /** Both views stay mounted; the switch only shows one. The URL changes by replaceState, never by navigation. */
  function switchView(next: View) {
    if (next === view) return
    setView(next)
    if (next === '3d') setOpened3d(true)
    try { window.localStorage.setItem(VIEW_KEY, next) } catch { /* the choice is only a convenience */ }
    const url = new URL(window.location.href)
    url.searchParams.set('view', next)
    window.history.replaceState(window.history.state, '', url)
  }

  const pick3d = useCallback((at: LngLat) => latest.current.picker.handleClick({ at, pixel: [0, 0], shift: false }), [])

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
    <div className="site-map" data-engine={engineKind ?? undefined} data-view={view}>
      {/* Providers restyle their target (Naver makes it position: relative), so they get an inner element. */}
      <div aria-label={`${site.label} 지도`} className="site-map-canvas" role="img"><div ref={mapRef} /></div>

      {opened3d && <World3D active={view === '3d'} drawn={picker.drawn} onPick={pick3d} />}

      <div aria-label="보기" className="site-map-views" role="group">
        {(['2d', '3d'] as const).map((option) => (
          <button aria-pressed={view === option} key={option} onClick={() => switchView(option)} type="button">{option.toUpperCase()}</button>
        ))}
      </div>

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
        {picker.notice && <span data-kind="error">{picker.notice}</span>}
        {engineKind && <small>{engineLabels[engineKind]}</small>}
      </div>

      {picker.card && (
        <SiteCard
          adding={picker.adding}
          onAddingChange={picker.setAdding}
          onClose={picker.close}
          onRemove={picker.remove}
          onSelect={() => void picker.select()}
          state={picker.card}
        />
      )}
      <p aria-live="polite" className="site-map-live">{picker.live}</p>
    </div>
  )
}
