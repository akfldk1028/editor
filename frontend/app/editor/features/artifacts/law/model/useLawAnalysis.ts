'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { analyzeSite, type LawAnalysis } from '../api/analyze'
import { latestSite, selectionScope } from '../api/site'
import { cacheKey, type Conditions } from '../lib/conditions'
import { lotLabel } from '../lib/summary'

/** Which parcel is analysed: `?pnu=` wins, else the first parcel of the scope's last saved site. */
export type Target =
  | { kind: 'resolving' }
  | { kind: 'none' }
  | { kind: 'error'; text: string }
  | { kind: 'site'; pnu: string; address: string; notice: string | null }

export type Phase =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; analysis: LawAnalysis }
  | { kind: 'error'; text: string }

const CACHE_MAX = 20

/**
 * Resolves the target parcel, then analyses it once per (pnu, 조건); results are kept in a small
 * in-hook cache so switching 조건 back and forth does not refetch. `rerun()` bypasses the cache.
 */
export function useLawAnalysis(params: Readonly<Record<string, string>>, conditions: Conditions) {
  const [target, setTarget] = useState<Target>({ kind: 'resolving' })
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const cache = useRef(new Map<string, LawAnalysis>())
  const active = useRef<AbortController | null>(null)
  const scope = selectionScope(params)
  const { pnu: pnuParam, address: addressParam } = params

  useEffect(() => {
    if (pnuParam) {
      setTarget({ kind: 'site', pnu: pnuParam, address: addressParam ?? '', notice: null })
      return
    }
    const controller = new AbortController()
    setTarget({ kind: 'resolving' })
    latestSite(scope, controller.signal)
      .then((saved) => {
        if (controller.signal.aborted) return
        const first = saved?.parcels[0]
        if (!saved || !first) return setTarget({ kind: 'none' })
        const notice = saved.parcels.length > 1 ? `묶음은 첫 필지(${lotLabel(first.address, first.pnu)}) 기준 — 합필 지원 준비 중` : null
        setTarget({ kind: 'site', pnu: first.pnu, address: first.address || saved.label, notice })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setTarget({ kind: 'error', text: error instanceof Error ? error.message : '선택한 대지를 불러오지 못했습니다.' })
      })
    return () => controller.abort()
  }, [pnuParam, addressParam, scope])

  const pnu = target.kind === 'site' ? target.pnu : null
  const key = pnu ? cacheKey(pnu, conditions) : null

  /** One request at a time: a new load (or unmount) aborts the one in flight. */
  const load = useCallback((targetPnu: string, targetKey: string, options: Conditions) => {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setPhase({ kind: 'loading' })
    analyzeSite(targetPnu, { buildingType: options.buildingType.trim(), floorAreaM2: options.floorAreaM2, assessmentDate: options.assessmentDate }, controller.signal)
      .then((analysis) => {
        if (controller.signal.aborted) return
        if (cache.current.size >= CACHE_MAX) cache.current.delete(cache.current.keys().next().value!)
        cache.current.set(targetKey, analysis)
        setPhase({ kind: 'ready', analysis })
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setPhase({ kind: 'error', text: error instanceof Error ? error.message : '법규를 분석하지 못했습니다.' })
      })
  }, [])

  useEffect(() => {
    if (!pnu || !key) {
      setPhase({ kind: 'idle' })
      return
    }
    const cached = cache.current.get(key)
    if (cached) setPhase({ kind: 'ready', analysis: cached })
    else load(pnu, key, conditions)
  }, [pnu, key, conditions, load])

  useEffect(() => () => active.current?.abort(), [])

  const rerun = useCallback(() => {
    if (!pnu || !key) return
    cache.current.delete(key)
    load(pnu, key, conditions)
  }, [pnu, key, conditions, load])

  return { target, phase, rerun }
}
