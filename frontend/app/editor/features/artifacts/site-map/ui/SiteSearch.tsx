'use client'

import { Search } from 'lucide-react'
import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useId, useRef, useState } from 'react'

import { type SearchCandidate, type SearchResult, searchParcels } from '../../../land-map/lib/land-api-client'
import {
  BADGES, candidateDetail, candidateKey, enterAction, enterTarget, moveActive, rowsAreCurrent, SEARCH_DEBOUNCE_MS,
  searchNotice, shouldSearch,
} from '../lib/site-search'

/** A list opened from outside the box: the conversation's address matched several parcels, or none exactly. */
export interface SearchShown { query: string; result: SearchResult }

interface Props {
  /** Where the map is now ([west, south, east, north]), so nearer matches rank first. */
  bbox: () => readonly [number, number, number, number] | null
  onChoose: (candidate: SearchCandidate) => void
  shown: SearchShown | null
}

/**
 * The map's search box: candidates as the user types (after a short pause) and on Enter, chosen with the
 * arrow keys or the pointer. Enter on a single exact parcel opens it at once; everything else is listed.
 */
export function SiteSearch({ bbox, onChoose, shown }: Props) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<SearchResult | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [busy, setBusy] = useState(false)
  const request = useRef<AbortController | null>(null)
  const timer = useRef<number | undefined>(undefined)
  /** The text the shown result answers; Enter on the same text reuses it. */
  const answered = useRef('')
  /** The text in the box now: an answer for any other text arrived late and is dropped. */
  const typed = useRef('')
  /** The rows on screen answer an older text (the next search is waiting): shown dimmed, never chosen. */
  const [stale, setStale] = useState(false)
  const listId = useId()

  useEffect(() => {
    if (!shown) return
    request.current?.abort()
    window.clearTimeout(timer.current)
    answered.current = shown.query.trim()
    typed.current = shown.query.trim()
    setStale(false)
    setQuery(shown.query)
    setResult(shown.result)
    setFailed(null)
    setActive(-1)
    setOpen(true)
  }, [shown])

  useEffect(() => () => {
    request.current?.abort()
    window.clearTimeout(timer.current)
  }, [])

  const run = useCallback(async (text: string): Promise<SearchResult | null> => {
    request.current?.abort()
    const controller = new AbortController()
    request.current = controller
    setBusy(true)
    try {
      const answer = await searchParcels(text, bbox(), controller.signal)
      if (controller.signal.aborted || typed.current !== text) return null
      answered.current = text
      setStale(false)
      setResult(answer)
      setFailed(null)
      setActive(-1)
      setOpen(true)
      return answer
    } catch (error) {
      if (controller.signal.aborted || typed.current !== text) return null
      setResult(null)
      setFailed(error instanceof Error ? error.message : '주소 검색에 실패했어요.')
      setOpen(true)
      return null
    } finally {
      if (request.current === controller) setBusy(false)
    }
  }, [bbox])

  function change(text: string) {
    setQuery(text)
    typed.current = text.trim()
    setStale(!rowsAreCurrent(answered.current, text))
    setActive(-1)
    window.clearTimeout(timer.current)
    if (!shouldSearch(text)) {
      request.current?.abort()
      setBusy(false)
      setResult(null)
      setFailed(null)
      setOpen(false)
      return
    }
    timer.current = window.setTimeout(() => void run(text.trim()), SEARCH_DEBOUNCE_MS)
  }

  function choose(candidate: SearchCandidate) {
    setOpen(false)
    setActive(-1)
    onChoose(candidate)
  }

  async function enter() {
    window.clearTimeout(timer.current)
    const text = query.trim()
    if (!shouldSearch(text)) return
    typed.current = text
    const answer = rowsAreCurrent(answered.current, text) && result ? result : await run(text)
    if (!answer) return
    const action = enterAction(answer)
    if (action.kind !== 'list') choose(action.candidate)
    else setOpen(true)
  }

  const rows = result?.candidates ?? []
  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return // a Hangul syllable still being composed
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (stale) return
      setOpen(true)
      setActive((current) => moveActive(current, event.key === 'ArrowDown' ? 1 : -1, rows.length))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const target = enterTarget(answered.current, query, open, active, rows.length)
      if (target === 'search') void enter()
      else choose(rows[target]!)
    } else if (event.key === 'Escape' && open) {
      event.preventDefault()
      setOpen(false)
      setActive(-1)
    }
  }

  const notice = failed ?? (result ? searchNotice(result) : null)
  const expanded = open && (rows.length > 0 || Boolean(notice) || busy)
  return (
    <>
      <form className="site-map-search" onSubmit={(event: FormEvent) => event.preventDefault()} role="search">
        <Search aria-hidden="true" size={14} />
        <input
          aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
          aria-autocomplete="list"
          aria-controls={listId}
          aria-expanded={expanded}
          aria-label="주소 또는 PNU 검색"
          autoComplete="off"
          onBlur={() => setOpen(false)}
          onChange={(event) => change(event.target.value)}
          onFocus={() => { if (result || failed) setOpen(true) }}
          onKeyDown={keyDown}
          placeholder="주소, 지번, 도로명, 장소 또는 PNU"
          role="combobox"
          type="search"
          value={query}
        />
      </form>
      {expanded && (
        <div className="site-map-results">
          {(notice || (busy && !rows.length)) && (
            <p className="site-map-results-note" data-kind={result?.status === 'unavailable' || failed ? 'error' : undefined}>
              {notice ?? '찾는 중…'}
            </p>
          )}
          {rows.length > 0 && (
            <ul aria-busy={stale} aria-label="검색 결과" data-stale={stale ? 'true' : undefined} id={listId} role="listbox">
              {rows.map((candidate, index) => {
                const detail = candidateDetail(candidate)
                return (
                  <li
                    aria-selected={index === active}
                    data-substituted={candidate.substituted ? 'true' : undefined}
                    id={`${listId}-${index}`}
                    key={candidateKey(candidate)}
                    onClick={() => { if (!stale) choose(candidate) }}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => setActive(index)}
                    role="option"
                  >
                    <span className="site-map-results-badge" data-kind={candidate.kind}>{BADGES[candidate.kind]}</span>
                    <span className="site-map-results-text">
                      <b>{candidate.label}</b>
                      {detail && <small>{detail}</small>}
                    </span>
                    {candidate.exact && (candidate.kind === 'lot' || candidate.kind === 'road') && <small className="site-map-results-exact">일치</small>}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
    </>
  )
}
