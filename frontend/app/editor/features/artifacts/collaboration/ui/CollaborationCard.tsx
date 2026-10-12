'use client'

import { Workflow } from 'lucide-react'
import { useMemo } from 'react'

import type { RunSummary } from '@/lib/orchestrator-runs/types'

import { runStatusLine, runTone } from '../lib/status'
import { toTranscript } from '../lib/transcript'
import FlowGraph from './FlowGraph'

interface Props {
  run: RunSummary
  /** Opens the 협업 artifact on this run's record. */
  onOpen(): void
  /** Agent names the conversation's folders do not know (from the live catalog). */
  names?: Readonly<Record<string, string>>
}

/**
 * What the Orchestrator and the agents said in one run, as a card another artifact can show: one status line, the
 * compact graph of the run's participants, and a way into the full record. The classes are the host's (`law-card`
 * style), so it reads like the panel around it.
 */
export function CollaborationCard({ run, onOpen, names = {} }: Props) {
  const transcript = useMemo(() => toTranscript(run), [run])
  const status = runStatusLine(run, transcript.messages, names)
  return (
    <section aria-label="협업 흐름" className="law-card">
      <h2>협업 흐름 <span className="law-badge" data-tone={runTone(run.status)}>{status}</span></h2>
      <FlowGraph compact messages={transcript.messages} />
      <p className="law-sub"><button className="law-link" onClick={onOpen} type="button"><Workflow aria-hidden="true" size={11} />협업 패널에서 대화 기록 보기</button></p>
    </section>
  )
}
