'use client'

import { useEffect, useRef } from 'react'
import { rememberConversationLawRun } from '@/lib/design-conversation/context'

import { getResults } from './api'
import { detailFor } from '@/lib/agents'

import { dismissFeed, projectFeed } from './feed'
import { evidenceCard, lawBasisLine, relayLine, resultLine, resultPrompt, stepChanges, stepState, submittedLine } from './feed-lines'
import { isTerminal } from './labels'
import type { RunSummary } from './types'
import { asksForLot } from '@/lib/run-question/lots'

export interface RunFeedContext {
  projectId: string | null
  conversationId: string
  /** The site the run is about; the result line's 법규 결과 보기 opens the law artifact on it. */
  pnu: string
  address?: string
  project?: string
}

const SITE_TOOL = 'site_resolve'
const LAW_TOOL = 'law_parcel_limits'
const REVIEW_TOOL = 'revision_triage'
const OPEN_STATES = new Set(['running', 'queued', 'pending'])


/**
 * Posts the conversation of one followed run, each line once (feed keys): the receipt; while a step
 * runs, the Orchestrator's "<Agent>에게 <tool> 요청 중" (dismissed when the step ends); each step's own
 * short line, replaced by that agent's detailed answer once `GET /runs/{id}/results` has parsed it —
 * Site's eight facts, Law's numbers with their articles and its legal basis, Revision's findings —
 * then the Orchestrator's verdict with the missing evidence and its question. The results door is
 * the one parser of agent answers.
 */
export function useRunFeed(run: RunSummary | null, context: RunFeedContext): void {
  const previous = useRef<RunSummary | null>(null)
  const fetched = useRef(new Set<string>())
  /** Result fetches in flight; a new poll must not cancel them, unmount does. */
  const inFlight = useRef(new Set<AbortController>())
  /** The Orchestrator's busy relay line per running tool, dismissed when the tool reports. */
  const relays = useRef(new Map<string, number>())
  /** Each tool's short step line, dismissed when the agent's detailed answer replaces it. */
  const briefs = useRef(new Map<string, number>())
  const { projectId, conversationId, pnu, address, project } = context

  useEffect(
    () => () => {
      for (const controller of inFlight.current) controller.abort()
      for (const id of relays.current.values()) dismissFeed(id)
      inFlight.current.clear()
      relays.current.clear()
      briefs.current.clear()
      previous.current = null
    },
    [projectId, conversationId, pnu],
  )

  useEffect(() => {
    const postFeed = projectFeed(projectId, conversationId)
    if (!run) {
      previous.current = null
      return
    }
    const prev = previous.current?.run_id === run.run_id ? previous.current : null
    previous.current = run
    const key = (name: string) => `${projectId}:${conversationId}:${run.run_id}:${name}`
    if (!prev) postFeed({ kind: 'system', key: key('submitted'), run_id: run.run_id, agent: 'orchestrator', text: submittedLine(run) })
    for (const change of stepChanges(prev, run)) {
      const relay = relays.current.get(change.tool)
      if (relay !== undefined) {
        dismissFeed(relay)
        relays.current.delete(change.tool)
      }
      if (change.tone === 'busy') {
        const posted = postFeed({ ...relayLine(change), key: key(change.key), run_id: run.run_id })
        if (posted) relays.current.set(change.tool, posted.id)
        continue
      }
      const posted = postFeed({ kind: 'progress', key: key(change.key), run_id: run.run_id, agent: change.agent ?? 'orchestrator', text: change.text, tone: change.tone })
      if (posted) briefs.current.set(change.tool, posted.id)
    }

    const done = (tool: string) => run.communications.some((comm) => comm.tool === tool && !OPEN_STATES.has(stepState(comm)))
    const lawDone = run.communications.some((comm) => comm.tool === LAW_TOOL && stepState(comm) === 'succeeded')
    const ended = isTerminal(run.status)
    if (ended) {
      for (const id of relays.current.values()) dismissFeed(id)
      relays.current.clear()
    }
    if (!projectId) return
    const wanted = [...(done(SITE_TOOL) ? ['site'] : []), ...(lawDone ? ['law'] : []), ...(ended ? ['result'] : [])].filter((name) => !fetched.current.has(key(name)))
    if (wanted.length === 0) return
    for (const name of wanted) fetched.current.add(key(name))
    const controller = new AbortController()
    inFlight.current.add(controller)
    const target = { pnu, ...(address ? { address } : {}), ...(project ? { project } : {}) }
    const replace = (tool: string) => {
      const brief = briefs.current.get(tool)
      if (brief !== undefined) {
        dismissFeed(brief)
        briefs.current.delete(tool)
      }
    }
    getResults(projectId, run.run_id, controller.signal)
      .finally(() => inFlight.current.delete(controller))
      .then((results) => {
        if (controller.signal.aborted) return
        if (lawDone) rememberConversationLawRun(projectId, pnu, run.run_id, results)
        const detail = (tool: string, name: string) => {
          const line = detailFor(tool)?.(results)
          if (line && postFeed({ ...line, key: key(name), run_id: run.run_id })) replace(tool)
        }
        if (wanted.includes('site')) detail(SITE_TOOL, 'site')
        if (wanted.includes('law')) {
          detail(LAW_TOOL, 'law')
          const basis = lawBasisLine(results, target)
          if (basis) postFeed({ ...basis, key: key('law-basis'), run_id: run.run_id })
        }
        if (ended) {
          detail(REVIEW_TOOL, 'revision')
          const failed = results.status === 'failed'
          postFeed({ kind: failed ? 'error' : 'result', key: key('result'), run_id: run.run_id, agent: 'orchestrator', text: resultLine(results), card: evidenceCard(results) ?? undefined })
          const prompt = resultPrompt(results, target)
          const lots = results.status === 'waiting_input' && asksForLot(results.pending_request) && results.pending_request
            ? { type: 'lots' as const, projectId, runId: run.run_id, question: results.pending_request } : undefined
          postFeed({ kind: 'prompt', key: key('prompt'), run_id: run.run_id, agent: 'orchestrator', text: prompt.text, actions: prompt.actions, ...(lots ? { card: lots } : {}) })
        }
      })
      .catch(() => {
        if (controller.signal.aborted) return
        for (const name of wanted) fetched.current.delete(key(name))
        if (ended) postFeed({ kind: 'error', key: key('result-error'), run_id: run.run_id, agent: 'orchestrator', text: '검토 결과를 읽지 못했어요 — 법규 패널에서 다시 확인해 주세요' })
      })
  }, [run, projectId, conversationId, pnu, address, project])
}
