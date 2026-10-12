'use client'

import { RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { traceLabel } from '@/lib/orchestrator-runs/labels'

import { ArtifactChrome } from '../../../shell/artifact-host/ArtifactChrome'
import type { ArtifactProps } from '../../../shell/artifact-types'
import { collaborationArtifact } from '../manifest'
import { goalLabel, runStatusLine, runTone } from '../lib/status'
import { toTranscript } from '../lib/transcript'
import { useAgentCatalog } from '../model/useAgentCatalog'
import { useCollaboration } from '../model/useCollaboration'
import { AgentPanel } from './AgentPanel'
import FlowGraph from './FlowGraph'
import { RunList } from './RunList'
import { Transcript } from './Transcript'
import './collaboration.css'

/** 협업: one run's agent-to-agent record as a graph, as readable messages, and the runs to choose from. */
export default function CollaborationArtifact({ tab = 'flow', params, shell }: ArtifactProps) {
  const { projects, chosen, setChosen, runs, run, selected: selectedRun, select, load, stale, reload } = useCollaboration(params)
  const [agent, setAgent] = useState<string | null>(null)
  const { entries, live, names } = useAgentCatalog()
  const transcript = useMemo(() => (run ? toTranscript(run) : null), [run])
  const status = run && transcript ? runStatusLine(run, transcript.messages, names) : null
  const { setTitle, setTab } = shell

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
    setTitle('협업', run ? `${goalLabel(run.goal)} · ${status ?? ''}` : undefined)
  }, [setTitle, run, status])

  return (
    <>
      <ArtifactChrome
        actions={
          <button className="artifact-primary" disabled={load.kind === 'loading'} onClick={reload} type="button">
            <RotateCcw aria-hidden="true" size={12} /><span>다시 확인</span>
          </button>
        }
      />
      <div aria-busy={load.kind === 'loading'} className="collab-artifact">
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
        {run && status && (
          <div className="collab-head">
            <h2>{goalLabel(run.goal)}</h2>
            <span className="collab-status" data-tone={runTone(run.status)}>{status}</span>
            <span className="collab-ids">실행 <code title={run.run_id}>{traceLabel(run.run_id)}</code>{stale && ' · 상태 확인 지연'}</span>
          </div>
        )}
        {effectiveTab === 'runs' && <RunList onSelect={(id) => { select(id); setTab('flow') }} runs={runs} selected={selectedRun} />}
        {effectiveTab === 'flow' && (
          <>
            <FlowGraph catalog={entries} live={live} messages={transcript?.messages ?? []} onSelect={setAgent} selected={agent} />
            {agent
              ? <AgentPanel agent={agent} entry={entries.find((entry) => entry.id === agent)} names={names} onClose={() => setAgent(null)} transcript={transcript} />
              : <p className="collab-note">에이전트를 누르면 이 실행에서 한 말과 할 수 있는 일이 보이고, 바로 물어볼 수 있어요.</p>}
          </>
        )}
        {effectiveTab === 'log' && transcript && <Transcript names={names} onSelect={setAgent} selected={agent} transcript={transcript} />}
        {effectiveTab === 'log' && !transcript && load.kind === 'ready' && chosen && (
          <p className="collab-note">이 프로젝트에 아직 실행이 없어요. 법규 패널에서 검토를 시작하면 여기에 기록이 쌓여요.</p>
        )}
      </div>
    </>
  )
}
