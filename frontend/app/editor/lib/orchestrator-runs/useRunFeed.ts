'use client'

import { useEffect, useRef } from 'react'

import { getResults } from './api'
import { postFeed } from './feed'
import { evidenceCard, lawCard, lawLine, resultLine, resultPrompt, stepChanges, stepState, submittedLine } from './feed-lines'
import { isTerminal } from './labels'
import type { RunSummary } from './types'

export interface RunFeedContext {
  projectId: string | null
  /** The site the run is about; the result line's 법규 결과 보기 opens the law artifact on it. */
  pnu: string
  address?: string
  project?: string
}

const LAW_TOOL = 'law_parcel_limits'

/**
 * Posts the feed lines of one followed run, each once (feed keys): the receipt, every step state
 * change (with its tone), Law's numbers as stat tiles as soon as its step succeeded, the verdict with
 * the missing evidence as chips, and then the question — "법규를 보시겠어요?" — with 법규 보기 as its answer.
 * Numbers come from `GET /runs/{id}/results`, the one parser of agent answers.
 */
export function useRunFeed(run: RunSummary | null, context: RunFeedContext): void {
  const previous = useRef<RunSummary | null>(null)
  const fetched = useRef(new Set<string>())
  /** Result fetches in flight; a new poll must not cancel them, unmount does. */
  const inFlight = useRef(new Set<AbortController>())
  const { projectId, pnu, address, project } = context

  useEffect(
    () => () => {
      for (const controller of inFlight.current) controller.abort()
    },
    [],
  )

  useEffect(() => {
    if (!run) {
      previous.current = null
      return
    }
    const prev = previous.current?.run_id === run.run_id ? previous.current : null
    previous.current = run
    const key = (name: string) => `${run.run_id}:${name}`
    if (!prev) postFeed({ kind: 'system', key: key('submitted'), run_id: run.run_id, text: submittedLine(run) })
    for (const change of stepChanges(prev, run)) postFeed({ kind: 'progress', key: key(change.key), run_id: run.run_id, text: change.text, tone: change.tone })

    const lawDone = run.communications.some((comm) => comm.tool === LAW_TOOL && stepState(comm) === 'succeeded')
    const ended = isTerminal(run.status)
    if (!projectId || !(lawDone || ended)) return
    const wanted = [...(lawDone ? ['law'] : []), ...(ended ? ['result'] : [])].filter((name) => !fetched.current.has(key(name)))
    if (wanted.length === 0) return
    for (const name of wanted) fetched.current.add(key(name))
    const controller = new AbortController()
    inFlight.current.add(controller)
    getResults(projectId, run.run_id, controller.signal)
      .finally(() => inFlight.current.delete(controller))
      .then((results) => {
        if (controller.signal.aborted) return
        const law = lawLine(results)
        if (law) postFeed({ kind: 'progress', key: key('law'), run_id: run.run_id, text: law, tone: 'ok', card: lawCard(results) ?? undefined })
        if (ended) {
          const failed = results.status === 'failed'
          postFeed({ kind: failed ? 'error' : 'result', key: key('result'), run_id: run.run_id, text: resultLine(results), card: evidenceCard(results) ?? undefined })
          const prompt = resultPrompt(results, { pnu, ...(address ? { address } : {}), ...(project ? { project } : {}) })
          postFeed({ kind: 'prompt', key: key('prompt'), run_id: run.run_id, text: prompt.text, actions: prompt.actions })
        }
      })
      .catch(() => {
        if (controller.signal.aborted) return
        for (const name of wanted) fetched.current.delete(key(name))
        if (ended) postFeed({ kind: 'error', key: key('result-error'), run_id: run.run_id, text: '검토 결과를 읽지 못했어요 — 법규 패널에서 다시 확인해 주세요' })
      })
  }, [run, projectId, pnu, address, project])
}
