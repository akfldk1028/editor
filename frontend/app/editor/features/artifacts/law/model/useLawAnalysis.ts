'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { dismissFeed, projectFeed } from '@/lib/orchestrator-runs/feed'
import { askFailedLine, landAnalysisLine, landAnalysisLines } from '@/lib/orchestrator-runs/feed-lines'
import { currentConversation } from '@/lib/design-conversation/session'
import type { RunLaw } from '@/lib/orchestrator-runs/types'

import { AnalyzeError, analyzeSite, type LawAgentAnalysis, type LawAnalysis } from '../api/analyze'
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
  | { kind: 'ready'; analysis: LawAnalysis; limits: RunLaw | null; answer: LawAgentAnalysis }
  | { kind: 'error'; text: string }

const CACHE_MAX = 20

/**
 * Resolves the target parcel, then asks the Law Agent once per (pnu, 조건) — the request and its
 * answer reach the conversation (법규 요약 · site → "Law Agent에게 법규 분석 요청 중" → the Law Agent's
 * turn); results are kept in a small in-hook cache so switching 조건 back and forth neither refetches
 * nor re-posts. `rerun()` bypasses the cache.
 */
export function useLawAnalysis(params: Readonly<Record<string, string>>, conditions: Conditions, enabled = true) {
  const [target, setTarget] = useState<Target>({ kind: 'resolving' })
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const cache = useRef(new Map<string, LawAgentAnalysis>())
  const active = useRef<AbortController | null>(null)
  const scope = selectionScope(params)
  const { pnu: pnuParam, address: addressParam, parcelCount } = params

  useEffect(() => {
    if (pnuParam) {
      const notice = Number(parcelCount) > 1 ? `묶음은 첫 필지(${lotLabel(addressParam ?? '', pnuParam)}) 기준 — 합필 지원 준비 중` : null
      setTarget({ kind: 'site', pnu: pnuParam, address: addressParam ?? '', notice })
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
  }, [pnuParam, addressParam, parcelCount, scope])

  const pnu = target.kind === 'site' ? target.pnu : null
  const address = target.kind === 'site' ? target.address : ''
  const key = pnu ? cacheKey(pnu, conditions) : null

  /** One request at a time: a new load (or unmount) aborts the one in flight. */
  const load = useCallback((targetPnu: string, targetAddress: string, targetKey: string, options: Conditions) => {
    const postFeed = projectFeed(currentConversation().projectId)
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setPhase({ kind: 'loading' })
    const [bubble, asking] = landAnalysisLines(targetAddress || `PNU ${targetPnu}`, { buildingType: options.buildingType, assessmentDate: options.assessmentDate })
    postFeed(bubble!)
    const pending = postFeed(asking!)
    const lawTarget = { pnu: targetPnu, ...(targetAddress ? { address: targetAddress } : {}) }
    analyzeSite(targetPnu, { buildingType: options.buildingType.trim(), floorAreaM2: options.floorAreaM2, assessmentDate: options.assessmentDate }, controller.signal)
      .then((answer) => {
        if (controller.signal.aborted) return
        if (cache.current.size >= CACHE_MAX) cache.current.delete(cache.current.keys().next().value!)
        cache.current.set(targetKey, answer)
        postFeed(landAnalysisLine(answer, lawTarget))
        setPhase({ kind: 'ready', analysis: answer.analysis, limits: answer.limits, answer })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        postFeed(askFailedLine(error instanceof AnalyzeError ? error.status : null, null))
        setPhase({ kind: 'error', text: error instanceof Error ? error.message : '법규를 분석하지 못했습니다.' })
      })
      .finally(() => {
        if (pending) dismissFeed(pending.id)
      })
  }, [])

  useEffect(() => {
    if (!enabled) {
      active.current?.abort()
      setPhase((current) => current.kind === 'loading' ? { kind: 'idle' } : current)
      return
    }
    if (!pnu || !key) {
      setPhase({ kind: 'idle' })
      return
    }
    const cached = cache.current.get(key)
    if (cached) setPhase({ kind: 'ready', analysis: cached.analysis, limits: cached.limits, answer: cached })
    else load(pnu, address, key, conditions)
  }, [enabled, pnu, address, key, conditions, load])

  useEffect(() => () => active.current?.abort(), [])

  const rerun = useCallback(() => {
    if (!enabled || !pnu || !key) return
    cache.current.delete(key)
    load(pnu, address, key, conditions)
  }, [enabled, pnu, address, key, conditions, load])

  return { target, phase, rerun }
}
