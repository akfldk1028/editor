'use client'

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'

import type { LngLat, MapEngine, MapPointer, ParcelSet } from './engine'
import { boundsCenter, lotLabel, parcelBounds, parcelRings, type ParcelLook } from './layers/parcelOutline'
import { ParcelCache } from './parcelCache'
import { NoParcelError, nextPicks, parcelAt, previewSite, saveSite, savedPicks, siteOutlines, type Pick, type SavedSite, type SiteBundle } from './selection'
import type { CardState } from './SiteCard'

/** A second plain click this soon is the tail of a double click and is ignored (double-click zoom is off); Shift-clicks always count. */
const DOUBLE_CLICK_MS = 300
/** The pointer must rest this long before the parcel under it is previewed. */
const HOVER_REST_MS = 250
/** Below this zoom parcels are too small to preview on hover. */
const HOVER_MIN_ZOOM = 16
const NOTICE_MS = 2500

interface Drawing { parcels: ParcelSet; labels: { at: LngLat; text: string }[]; picks: Pick[] }
const empty: Drawing = { parcels: { geometries: [], outline: null, look: 'site' }, labels: [], picks: [] }

function drawing(cache: ParcelCache, picks: Pick[], geometries: Record<string, object | null>, outline: object | null, look: ParcelLook, site?: SiteBundle): Drawing {
  const shapes = picks.map((pick) => geometries[pick.pnu] ?? cache.get(pick.pnu)?.geometry ?? null)
  const labels = picks.flatMap((pick, index) => {
    const bounds = parcelBounds(parcelRings(shapes[index]))
    const address = site?.parcels.find((parcel) => parcel.pnu === pick.pnu)?.address ?? cache.get(pick.pnu)?.address ?? ''
    return bounds ? [{ at: boundsCenter(bounds), text: lotLabel(address, pick.pnu) }] : []
  })
  return { parcels: { geometries: shapes.filter((shape): shape is object => shape !== null), outline: picks.length > 1 ? outline : null, look }, labels, picks }
}

/** Esc belongs to a focused field or an open popover first; the picker only takes it when neither is in play. */
function escapeIsElsewhere(event: KeyboardEvent): boolean {
  const target = event.target instanceof Element ? event.target : null
  if (target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return true
  try {
    return document.querySelector(':popover-open') !== null
  } catch {
    return false
  }
}

/**
 * Picking a site on the map: click = that parcel alone (the only pick: deselect),
 * Shift+click (or the card's 필지 추가 toggle) adds/removes a parcel, the server
 * describes the bundle, and 이 대지로 선택 saves it under `scope`. Also the
 * hover preview and cursor states.
 */
export function usePicker(engineRef: RefObject<MapEngine | null>, onSaved: (site: SavedSite) => void, scope: string) {
  const cache = useRef(new ParcelCache(20))
  const state = useRef({ busy: false, lastClick: -Infinity, hoverTimer: undefined as number | undefined,
    hoverBusy: false, hoverAt: null as LngLat | null, adding: false, generation: 0 })
  /** What the map shows when nothing unsaved is picked: the searched site or the saved selection. */
  const baseline = useRef<Drawing>(empty)
  const current = useRef<Drawing>(empty)
  const [card, setCard] = useState<CardState | null>(null)
  const [adding, setAddingState] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [live, setLive] = useState('')
  /** What is drawn now, for views that mirror the 2D map (the 3D view). */
  const [drawn, setDrawn] = useState<ParcelSet>(empty.parcels)
  const noticeTimer = useRef<number | undefined>(undefined)
  /** The describe request in flight; the next describe, close and unmount abort it. */
  const describing = useRef<AbortController | null>(null)
  /** The saved-site restore in flight; aborted on unmount only. */
  const restoring = useRef<AbortController | null>(null)

  const draw = useCallback((drawing: Drawing, fit = false) => {
    current.current = drawing
    setDrawn(drawing.parcels)
    engineRef.current?.showParcels(drawing.parcels, fit)
    engineRef.current?.setLabels(drawing.labels)
  }, [engineRef])

  const busy = useCallback((value: boolean) => {
    state.current.busy = value
    engineRef.current?.setBusy(value)
  }, [engineRef])

  const say = useCallback((text: string) => {
    window.clearTimeout(noticeTimer.current)
    setNotice(text)
    noticeTimer.current = window.setTimeout(() => setNotice(null), NOTICE_MS)
  }, [])

  /** Describe `picks` on the server and show them; an empty bundle goes back to the baseline. */
  const describe = useCallback(async (picks: Pick[]) => {
    const generation = ++state.current.generation
    describing.current?.abort()
    describing.current = null
    if (picks.length === 0) {
      draw(baseline.current)
      setCard(null)
      return
    }
    draw(drawing(cache.current, picks, {}, null, 'picked'))
    setCard({ kind: 'loading', count: picks.length })
    const controller = new AbortController()
    describing.current = controller
    try {
      const site = await previewSite(picks, controller.signal)
      if (generation !== state.current.generation) return
      draw(drawing(cache.current, picks, site.geometries, site.outline, 'picked', site))
      setCard({ kind: 'ready', site, save: 'idle' })
    } catch (error) {
      if (generation !== state.current.generation || controller.signal.aborted) return
      setCard({ kind: 'error', text: error instanceof Error ? error.message : '필지 정보를 불러오지 못했습니다.' })
    }
  }, [draw])

  /** The parcel under the click is painted as soon as its outline is known (at once when cached); the cursor alone shows the wait. */
  const pick = useCallback(async ({ at, shift }: MapPointer) => {
    if (!engineRef.current || state.current.busy) return
    busy(true)
    try {
      let parcel = cache.current.find(at)
      if (!parcel) {
        parcel = await parcelAt(at)
        cache.current.add(parcel)
      }
      engineRef.current?.setHover(null)
      engineRef.current?.setMarker(null)
      // A plain click starts a new bundle; adding extends what is drawn (a saved site too).
      // Painted now; the facts follow (a later pick supersedes this one), so the next click need not wait.
      void describe(nextPicks(current.current.picks, { pnu: parcel.pnu, at }, shift || state.current.adding))
    } catch (error) {
      if (error instanceof NoParcelError) say(error.message)
      else say(error instanceof Error ? error.message : '필지를 찾지 못했습니다.')
    } finally {
      busy(false)
    }
  }, [busy, describe, engineRef, say])

  /** A click picks at once; ignored mid-lookup and right after another click. */
  const handleClick = useCallback((event: MapPointer) => {
    const now = performance.now()
    if (state.current.busy || (!event.shift && now - state.current.lastClick < DOUBLE_CLICK_MS)) return
    state.current.lastClick = now
    void pick(event)
  }, [pick])

  /** Rest → preview the parcel under the pointer: cached outlines first, at most one request in flight. */
  const handleHover = useCallback((at: LngLat | null) => {
    const hover = state.current
    window.clearTimeout(hover.hoverTimer)
    hover.hoverAt = at
    const engine = engineRef.current
    if (!engine) return
    if (!at) return engine.setHover(null)
    hover.hoverTimer = window.setTimeout(async () => {
      if (engine.getZoom() < HOVER_MIN_ZOOM) return engine.setHover(null)
      const show = (parcel: { pnu: string; geometry: object } | null) => {
        const picked = current.current.picks.some((item) => item.pnu === parcel?.pnu)
        engine.setHover(parcel && !picked ? parcel.geometry : null)
      }
      const known = cache.current.find(at)
      if (known || hover.hoverBusy) return show(known)
      hover.hoverBusy = true
      try {
        const parcel = await parcelAt(at)
        cache.current.add(parcel)
        // Show it only if the pointer is still over it.
        if (hover.hoverAt && cache.current.find(hover.hoverAt)?.pnu === parcel.pnu) show(parcel)
      } catch {
        engine.setHover(null)
      } finally {
        hover.hoverBusy = false
      }
    }, HOVER_REST_MS)
  }, [engineRef])

  const remove = useCallback((pnu: string) => {
    void describe(current.current.picks.filter((item) => item.pnu !== pnu))
  }, [describe])

  /**
   * Saves what is drawn now. The bundle is snapshotted before the request: a pick made while it is
   * in flight does not change what is saved, and the answer then only moves the baseline.
   */
  const select = useCallback(async () => {
    if (card?.kind !== 'ready') return
    const { site } = card
    const snapshot = current.current
    const generation = state.current.generation
    setCard({ kind: 'ready', site, save: 'saving' })
    try {
      const saved = await saveSite(snapshot.picks, scope)
      const committed: Drawing = { ...snapshot, parcels: { ...snapshot.parcels, look: 'saved' } }
      baseline.current = committed
      setLive(`${saved.label} 선택됨`)
      onSaved(saved)
      if (generation !== state.current.generation) return
      draw(committed)
      setCard({ kind: 'ready', site: saved, save: 'saved' })
    } catch {
      if (generation === state.current.generation) setCard({ kind: 'ready', site, save: 'failed' })
    }
  }, [card, draw, onSaved, scope])

  /** Close / Esc: unsaved picks are dropped (back to the baseline); a saved site stays drawn. */
  const close = useCallback(() => {
    state.current.generation++
    describing.current?.abort()
    describing.current = null
    if (card?.kind !== 'ready' || card.save !== 'saved') draw(baseline.current)
    setCard(null)
  }, [card, draw])

  /** The searched (or default) parcel becomes the baseline. */
  const showSearched = useCallback((geometry: object) => {
    state.current.generation++
    baseline.current = { parcels: { geometries: [geometry], outline: null, look: 'site' }, labels: [], picks: [] }
    draw(baseline.current, true)
    setCard(null)
  }, [draw])

  /**
   * The saved site, redrawn from its PNUs: the card shows the saved facts at once and only outlines are
   * fetched again (none were stored). A pick made while the outlines load wins: the answer then only
   * becomes the baseline, nothing is drawn or fitted.
   */
  const restore = useCallback(async (saved: SavedSite) => {
    const picks = savedPicks(saved)
    const generation = state.current.generation
    setCard({ kind: 'ready', site: saved, save: 'saved' })
    restoring.current?.abort()
    const controller = new AbortController()
    restoring.current = controller
    const shapes = await siteOutlines(picks.map((pick) => pick.pnu), controller.signal)
    baseline.current = drawing(cache.current, picks, shapes.geometries, shapes.outline, 'saved', saved)
    if (generation !== state.current.generation) return
    draw(baseline.current, true)
  }, [draw])

  const setAdding = useCallback((value: boolean) => {
    state.current.adding = value
    setAddingState(value)
  }, [])

  // Capture phase, so the picker (the inner owner) hears Esc before the shell's window listener,
  // which skips an event the picker consumed (it un-maximizes the panel otherwise).
  useEffect(() => {
    if (!card) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || escapeIsElsewhere(event)) return
      event.preventDefault()
      close()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [card, close])

  useEffect(() => () => {
    window.clearTimeout(state.current.hoverTimer)
    window.clearTimeout(noticeTimer.current)
    describing.current?.abort()
    restoring.current?.abort()
  }, [])

  return { card, adding, setAdding, notice, live, drawn, handleClick, handleHover, remove, select, close, showSearched, restore }
}
