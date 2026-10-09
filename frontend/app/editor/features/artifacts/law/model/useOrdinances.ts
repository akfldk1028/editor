'use client'

import { useEffect, useState } from 'react'
import { discoverOrdinances, type OrdinanceDiscovery } from '../api/ordinances'
import type { ReferenceSite } from '../api/reference'
import { citedOrdinances } from '../lib/ordinances'
import type { Review } from '../lib/review'

export type OrdinanceState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: OrdinanceDiscovery }
  | { kind: 'error'; text: string }

const CACHE_MAX = 20
/** The backend walks every search page; past this the screen says so and offers a retry instead of waiting on. */
const TIMEOUT_MS = 60_000
const cache = new Map<string, OrdinanceDiscovery>()

/** The parcel's ordinance list once per (parcel, date, cited ordinances); a refresh bypasses the cache. */
export function useOrdinances(review: Review, site: ReferenceSite, refresh = 0): OrdinanceState {
  const refs = citedOrdinances(review)
  const key = JSON.stringify([site.pnu, site.assessmentDate, refs])
  const [state, setState] = useState<OrdinanceState>(() => {
    const cached = cache.get(key)
    return cached ? { kind: 'ready', data: cached } : { kind: 'loading' }
  })
  useEffect(() => {
    const cached = refresh === 0 ? cache.get(key) : undefined
    if (cached) {
      setState({ kind: 'ready', data: cached })
      return
    }
    const controller = new AbortController()
    let timedOut = false
    const timer = setTimeout(() => { timedOut = true; controller.abort() }, TIMEOUT_MS)
    const [pnu, assessmentDate, cited] = JSON.parse(key) as [string, string, ReturnType<typeof citedOrdinances>]
    setState({ kind: 'loading' })
    discoverOrdinances({ pnu, assessmentDate }, cited, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        if (cache.size >= CACHE_MAX) cache.delete(cache.keys().next().value!)
        cache.set(key, data)
        setState({ kind: 'ready', data })
      })
      .catch((error: unknown) => {
        if (timedOut) setState({ kind: 'error', text: '관할 조례 조회가 60초를 넘겼습니다. 조례가 없다는 뜻은 아닙니다.' })
        else if (!controller.signal.aborted) setState({ kind: 'error', text: error instanceof Error ? error.message : '관할 조례 목록을 받지 못했습니다.' })
      })
      .finally(() => clearTimeout(timer))
    return () => { clearTimeout(timer); controller.abort() }
  }, [key, refresh])
  return state
}
