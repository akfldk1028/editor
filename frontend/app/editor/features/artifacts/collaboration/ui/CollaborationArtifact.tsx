'use client'

import { RotateCcw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { agentLabel, traceLabel } from '@/lib/orchestrator-runs/labels'
import type { Hop } from '@/lib/orchestrator-runs/types'

import { ArtifactChrome } from '../../../shell/artifact-host/ArtifactChrome'
import type { ArtifactProps } from '../../../shell/artifact-types'
import { collaborationArtifact } from '../manifest'
import { composeConversation, transcriptOf } from '../lib/scope'
import { type LedgerScope, useLedger } from '@/lib/ledger'

import { goalLabel, runStatusLine, runTone } from '../lib/status'
import { type CollaborationMessage, toTranscript } from '../lib/transcript'
import { useAgentCatalog } from '../model/useAgentCatalog'
import { useCollaboration } from '../model/useCollaboration'
import { useLinkedRuns } from '../model/useLinkedRuns'
import { useLiveFlow } from '../model/useLiveFlow'
import { AgentPanel } from './AgentPanel'
import FlowGraph from './FlowGraph'
import { RunList } from './RunList'
import { Transcript } from './Transcript'
import './collaboration.css'

/** One empty record for every render, so a canvas without a run is not laid out again on each click. */
const NO_MESSAGES: readonly CollaborationMessage[] = []
const NO_HOPS: readonly Hop[] = []

/**
 * 협업: what the agents said to each other, from the 협업 장부 — this conversation's calls (and the runs it started)
 * by default, or one run when the opener or the 실행 tab named it — as a graph, as readable messages, and the runs to choose from.
 */
export default function CollaborationArtifact({ tab = 'flow', params, shell }: ArtifactProps) {
  const { projects, chosen, setChosen, runs, run, selected: selectedRun, select, load, stale, reload, goals } = useCollaboration(params)
  const [agent, setAgent] = useState<string | null>(null)
  const { entries, live, names } = useAgentCatalog()
  const flow = useLiveFlow(chosen?.project_id ?? null)
  const scope = useMemo<LedgerScope | null>(
    () => (selectedRun ? { run_id: selectedRun } : chosen ? { conversation_id: flow.conversationId } : null),
    [selectedRun, chosen, flow.conversationId],
  )
  const ledger = useLedger(scope)
  const linked = useLinkedRuns(chosen?.project_id ?? null, selectedRun ? NO_HOPS : ledger.hops)
  // What is on the canvas: one run's calls (its record while the ledger has none of them), else the conversation's ledger
  // with the live lines no one has recorded yet.
  const transcript = useMemo(() => {
    if (selectedRun) {
      const recorded = ledger.hops.some((hop) => hop.operation !== 'start_run')
      const record = !recorded && run ? toTranscript(run).messages.map((message, index) => ({ ...message, at: index + 1 })) : []
      return transcriptOf(composeConversation([...ledger.messages, ...record], []))
    }
    return transcriptOf(composeConversation([...ledger.messages, ...linked], flow.messages))
  }, [selectedRun, ledger.hops, ledger.messages, run, linked, flow.messages])
  const waiting = flow.waitingOn && !selectedRun ? `${names[flow.waitingOn] ?? agentLabel(flow.waitingOn)}에게 묻는 중` : null
  const status = waiting ?? (run && selectedRun ? runStatusLine(run, transcript.messages, names) : null)
  const { setTitle, setTab } = shell
  const refresh = useCallback(() => { reload(); ledger.reload() }, [reload, ledger.reload])

  // `shell.openArtifact('collaboration', {tab})` lands on that tab; each open (new params object) applies it once.
  const [appliedParams, setAppliedParams] = useState<typeof params | null>(null)
  useEffect(() => {
    if (appliedParams === params) return
    setAppliedParams(params)
    const wanted = params.tab
    if (wanted && collaborationArtifact.tabs?.some((candidate) => candidate.id === wanted)) setTab(wanted)
  }, [params, appliedParams, setTab])
  const effectiveTab = appliedParams === params ? tab : params.tab ?? tab

  useEffect(() => {
    setTitle('협업', run && selectedRun ? `${goalLabel(run.goal, goals)} · ${status ?? ''}` : status ?? undefined)
  }, [setTitle, run, selectedRun, status, goals])

  const busy = load.kind === 'loading' || ledger.load.kind === 'loading'
  const empty = transcript.messages.length === 0 && ledger.load.kind === 'ready' && !!chosen
  return (
    <>
      <ArtifactChrome
        actions={
          <button className="artifact-primary" disabled={busy} onClick={refresh} type="button">
            <RotateCcw aria-hidden="true" size={12} /><span>다시 확인</span>
          </button>
        }
      />
      <div aria-busy={busy} className="collab-artifact">
        {projects.kind === 'loading' && <p className="collab-note"><span aria-hidden="true" className="loading-mark" /> 프로젝트를 확인하는 중</p>}
        {projects.kind === 'error' && <p className="collab-note" data-kind="error" role="alert">{projects.text}</p>}
        {projects.kind === 'none' && <p className="collab-note" data-kind="error">{projects.reason}</p>}
        {projects.kind === 'choose' && (
          <label className="collab-project">
            <span>프로젝트</span>
            <select onChange={(event) => setChosen(projects.projects.find((binding) => binding.project_id === event.target.value) ?? null)} value={chosen?.project_id ?? ''}>
              <option value="">선택하세요</option>
              {projects.projects.map((binding) => <option key={binding.project_id} value={binding.project_id}>{binding.owner_project_id} · {binding.branch_id}</option>)}
            </select>
          </label>
        )}
        {load.kind === 'error' && <p className="collab-note" data-kind="error" role="alert">{load.text}</p>}
        {ledger.load.kind === 'error' && <p className="collab-note" data-kind="error" role="alert">{ledger.load.text}</p>}
        {status && (
          <div className="collab-head">
            <h2>{run && selectedRun ? goalLabel(run.goal, goals) : '이 대화'}</h2>
            <span className="collab-status" data-tone={waiting ? 'busy' : run && selectedRun ? runTone(run.status) : 'ok'}>{status}</span>
            {run && selectedRun && <span className="collab-ids">실행 <code title={run.run_id}>{traceLabel(run.run_id)}</code>{stale && ' · 상태 확인 지연'}</span>}
          </div>
        )}
        {effectiveTab === 'runs' && <RunList goals={goals} onSelect={(id) => { select(id); setTab('flow') }} runs={runs} selected={selectedRun} />}
        {effectiveTab === 'flow' && (
          <>
            <FlowGraph catalog={entries} live={live} messages={transcript.messages.length ? transcript.messages : NO_MESSAGES} onSelect={setAgent} selected={agent} />
            {agent
              ? <AgentPanel agent={agent} entry={entries.find((entry) => entry.id === agent)} key={agent} names={names} onClose={() => setAgent(null)} transcript={transcript} />
              : <p className="collab-note">{empty ? '이 대화에서는 아직 에이전트를 부르지 않았어요. 물어보거나 검토를 시작하면 여기에 그려져요.' : '에이전트를 누르면 이 대화에서 한 말과 할 수 있는 일이 보이고, 바로 물어볼 수 있어요.'}</p>}
          </>
        )}
        {effectiveTab === 'log' && !empty && <Transcript names={names} onSelect={setAgent} selected={agent} transcript={transcript} />}
        {effectiveTab === 'log' && empty && (
          <p className="collab-note">이 대화에서는 아직 에이전트를 부르지 않았어요. 법규 패널에서 물어보거나 검토를 시작하면 여기에 기록이 쌓여요.</p>
        )}
      </div>
    </>
  )
}
