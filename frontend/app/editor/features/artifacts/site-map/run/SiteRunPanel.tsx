'use client'

import { AlertTriangle, Check, Copy, ExternalLink, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import type { SavedSite } from '../selection'
import { bundleNotice, isTerminal, statusLabel, traceLabel, type RunFailure } from './site-run'
import { useSiteRun, type RunPhase } from './useSiteRun'

interface Props {
  site: SavedSite
  /** The shell's `?project=`, when it names a project binding. */
  project?: string
}

const base = () => process.env.NEXT_PUBLIC_BASE_PATH || ''

const failureText = (failure: RunFailure) =>
  failure.kind === 'unavailable' ? '오케스트레이터에 연결할 수 없어요 — 켜진 뒤 다시 시도' : failure.text

/** Under the saved site: 검토 시작 sends `{goal: limits, pnu}` to the Orchestrator and follows the run. */
export function SiteRunPanel({ site, project }: Props) {
  const { projects, chosen, setChosen, phase, start } = useSiteRun(site, project)
  const notice = bundleNotice(site)
  const busy = phase.kind === 'submitting'

  return (
    <div aria-label="법규·한계 검토" className="site-card-run" role="group">
      {projects.kind === 'loading' && <p className="site-card-note">프로젝트를 확인하는 중</p>}
      {projects.kind === 'error' && <p className="site-card-note" data-kind="error">{projects.text}</p>}
      {projects.kind === 'none' && <p className="site-card-note" data-kind="error">{projects.reason}</p>}
      {projects.kind === 'choose' && (
        <label className="site-card-run-project">
          <span>검토를 보낼 프로젝트</span>
          <select
            disabled={busy || phase.kind === 'submitted'}
            onChange={(event) => setChosen(projects.projects.find((binding) => binding.project_id === event.target.value) ?? null)}
            value={chosen?.project_id ?? ''}
          >
            <option value="">선택하세요</option>
            {projects.projects.map((binding) => (
              <option key={binding.project_id} value={binding.project_id}>{binding.owner_project_id} · {binding.branch_id}</option>
            ))}
          </select>
        </label>
      )}
      {notice && chosen && phase.kind !== 'submitted' && (
        <p className="site-card-note" data-kind="notice"><AlertTriangle aria-hidden="true" size={12} />{notice}</p>
      )}

      {phase.kind === 'submitted' ? (
        <Submitted phase={phase} projectId={chosen?.project_id ?? ''} />
      ) : (
        <button className="artifact-primary site-card-select" disabled={!chosen || busy} onClick={() => void start()} type="button">
          {busy ? '검토 요청 중' : phase.kind === 'failed' ? <><RotateCcw aria-hidden="true" size={12} />다시 시도</> : '검토 시작 (법규·한계)'}
        </button>
      )}
      {phase.kind === 'failed' && <p className="site-card-note" data-kind="error" role="alert">{failureText(phase.failure)}</p>}
    </div>
  )
}

function Submitted({ phase, projectId }: { phase: Extract<RunPhase, { kind: 'submitted' }>; projectId: string }) {
  const { run, stale } = phase
  const open = !isTerminal(run.status)
  const href = `${base()}/runs/${encodeURIComponent(run.run_id)}?project_id=${encodeURIComponent(projectId)}`
  return (
    <div className="site-card-run-status" role="status">
      <p>
        {open ? <span aria-hidden="true" className="loading-mark" /> : <Check aria-hidden="true" size={14} />}
        <b>검토 요청됨</b> · run <code>{run.run_id}</code>
        {run.trace_id && <TraceId traceId={run.trace_id} />}
      </p>
      <p>
        상태: <b>{statusLabel(run.status)}</b>
        {stale && <small> · 상태 확인 지연</small>}
        <a href={href} rel="noopener" target="_blank">실행 보기<ExternalLink aria-hidden="true" size={11} /></a>
      </p>
    </div>
  )
}

/** `trace <first 8 hex>` with a button that copies the whole W3C trace id (for log/JSONL lookup). */
function TraceId({ traceId }: { traceId: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(traceId)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // No clipboard (insecure context): the full id stays in the title for manual copy.
    }
  }
  return (
    <>
      · trace <code title={traceId}>{traceLabel(traceId)}</code>
      <button aria-label={copied ? '추적 ID 복사됨' : '추적 ID 복사'} className="site-card-run-copy" onClick={() => void copy()} type="button">
        {copied ? <Check aria-hidden="true" size={11} /> : <Copy aria-hidden="true" size={11} />}
      </button>
    </>
  )
}
