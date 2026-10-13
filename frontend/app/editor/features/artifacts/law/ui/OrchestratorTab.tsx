'use client'

import { Check, ExternalLink, Play, RotateCcw, Workflow } from 'lucide-react'
import dynamic from 'next/dynamic'

import { actionLabel, agentForTool, agentLabel, askedFieldsLabel, evidenceLabel, isTerminal, stateLabel, statusLabel, toolLabel } from '@/lib/orchestrator-runs/labels'
import { failureText } from '@/lib/orchestrator-runs/submit'
import type { RunResults, RunStep, RunSummary } from '@/lib/orchestrator-runs/types'
import { ConditionsRow } from '@/lib/orchestrator-runs/ui/ConditionsRow'

import type { ShellApi } from '../../../shell/artifact-types'
import { compareLaw, differingRows } from '../lib/orchestrator-compare'
import type { Summary } from '../lib/summary'
import { useOrchestratorReview } from '../model/useOrchestratorReview'

interface Props {
  pnu: string
  address: string
  /** The shell's `?project=`. */
  project?: string
  shell: ShellApi
  /** The editor's own 요약 numbers, when its analysis has arrived; shown beside the run's Law numbers. */
  editor: Summary | null
}

/** The pipeline a `limits` run walks; a step not yet in the communications shows as 대기. */
const PIPELINE = ['site_resolve', 'law_parcel_limits', 'revision_triage'] as const
const base = () => process.env.NEXT_PUBLIC_BASE_PATH || ''
/** The run's agent-to-agent record as the 협업 artifact draws it (its exported card), client-only. */
const CollaborationCard = dynamic(() => import('../../collaboration/ui/CollaborationCard').then((module) => ({ default: module.CollaborationCard })), { ssr: false, loading: () => <p className="law-note"><span aria-hidden="true" className="loading-mark" /> 협업 흐름을 그리는 중</p> })

/** 오케스트레이터 검토: what the Orchestrator's run (대지 → 법규 → 검토 조정) returned for this parcel. */
export function OrchestratorTab({ pnu, address, project, shell, editor }: Props) {
  const review = useOrchestratorReview(pnu, address, project)
  const { projects, chosen, setChosen, conditions, setConditions, ready, phase, submitting, failure, start, reload } = review
  const live = phase.kind === 'run' && !isTerminal(phase.run.status)
  const canStart = Boolean(chosen) && ready && !submitting && !live

  const startForm = (
    <div className="law-orch-start">
      <ConditionsRow disabled={!chosen || submitting || live} onChange={setConditions} value={conditions} />
      <button className="artifact-primary" disabled={!canStart} onClick={() => void start()} type="button">
        {submitting ? <><span aria-hidden="true" className="loading-mark" /><span>검토 요청 중</span></> : <><Play aria-hidden="true" size={12} /><span>{phase.kind === 'run' ? '다시 검토' : '검토 시작'}</span></>}
      </button>
      {failure && (
        <p className="law-note" data-kind="error" role="alert">
          {failureText(failure)}
          {failure.kind === 'unavailable' && <button className="law-link" onClick={() => shell.openArtifact('system')} type="button">시스템 보기</button>}
        </p>
      )}
    </div>
  )

  return (
    <div className="law-orch">
      {projects.kind === 'loading' && <p className="law-note"><span aria-hidden="true" className="loading-mark" /> 프로젝트를 확인하는 중</p>}
      {projects.kind === 'error' && <p className="law-note" data-kind="error" role="alert">{projects.text}</p>}
      {projects.kind === 'none' && <p className="law-note" data-kind="error">{projects.reason}</p>}
      {projects.kind === 'choose' && (
        <label className="law-orch-project">
          <span>검토를 보낼 프로젝트</span>
          <select disabled={live} onChange={(event) => setChosen(projects.projects.find((binding) => binding.project_id === event.target.value) ?? null)} value={chosen?.project_id ?? ''}>
            <option value="">선택하세요</option>
            {projects.projects.map((binding) => <option key={binding.project_id} value={binding.project_id}>{binding.owner_project_id} · {binding.branch_id}</option>)}
          </select>
        </label>
      )}
      {chosen && phase.kind === 'loading' && <p className="law-note"><span aria-hidden="true" className="loading-mark" /> 최근 검토 실행을 찾는 중</p>}
      {phase.kind === 'error' && (
        <p className="law-note" data-kind="error" role="alert">{phase.text}<button className="law-link" onClick={reload} type="button">다시 확인</button></p>
      )}
      {chosen && phase.kind === 'empty' && (
        <div className="law-empty">
          <Workflow aria-hidden="true" size={24} />
          <p>아직 검토 실행이 없어요</p>
          <small>검토 시작을 누르면 오케스트레이터가 대지 → 법규 → 검토 조정 순서로 이 필지를 검토해요.</small>
          {startForm}
        </div>
      )}
      {phase.kind === 'run' && (
        <>
          <RunHead onReload={reload} projectId={chosen?.project_id ?? ''} results={phase.results} run={phase.run} stale={phase.stale} />
          <Timeline results={phase.results} run={phase.run} />
          <CollaborationCard onOpen={() => shell.openArtifact('collaboration', { ...(chosen ? { project: chosen.project_id } : {}), run: phase.run.run_id, tab: 'log' })} run={phase.run} />
          <LawCard editor={editor} results={phase.results} />
          <Evidence results={phase.results} />
          {!live && <section aria-label="새 검토" className="law-card">{startForm}</section>}
        </>
      )}
    </div>
  )
}

function RunHead({ run, results, stale, projectId, onReload }: { run: RunSummary; results: RunResults | null; stale: boolean; projectId: string; onReload(): void }) {
  const open = !isTerminal(run.status)
  const waiting = run.status === 'waiting_input'
  const asked = waiting ? askedFieldsLabel(run.pending_fields) : ''
  const verdict = !open && results?.review?.code === 'needs_user_input' ? '보류 — 근거 보충 필요' : statusLabel(run.status)
  const href = `${base()}/runs/${encodeURIComponent(run.run_id)}?project_id=${encodeURIComponent(projectId)}`
  return (
    <section aria-label="검토 실행" className="law-card law-orch-head">
      <h2>
        {open ? <span aria-hidden="true" className="loading-mark" /> : <Check aria-hidden="true" size={14} />}
        검토 실행 <span className="law-badge" data-tone={open ? undefined : run.status === 'failed' || waiting ? 'warn' : results?.review?.code === 'needs_user_input' ? 'warn' : 'ok'}>{verdict}</span>
        {open && <small>3초마다 확인</small>}
        {stale && <small>· 상태 확인 지연</small>}
      </h2>
      {waiting && (
        <p className="law-note" data-kind="warn" role="status">
          오케스트레이터가 검토를 시작하기 전에 {asked || '조건'}을 물어요{run.pending_note ? ` — ${run.pending_note}` : ''}. 아래에서 {asked || '조건'}을 고르고 다시 검토를 누르면 대지 → 법규 순서로 이어가요.
        </p>
      )}
      <p className="law-sub law-orch-ids">
        {[results?.request?.building_type ? `용도 ${results.request.building_type}` : null,
          results?.request && results.request.parcels.length > 1 ? `필지 ${results.request.parcels.length}개` : null].filter(Boolean).join(' · ')}
        <a href={href} rel="noopener" target="_blank">실행 보기<ExternalLink aria-hidden="true" size={11} /></a>
        <button className="law-link" onClick={onReload} type="button"><RotateCcw aria-hidden="true" size={11} />다시 확인</button>
      </p>
    </section>
  )
}

function stepDetail(tool: string, step: RunStep | undefined, results: RunResults | null): string | null {
  if (!step) return null
  if (tool === 'site_resolve' && results?.site) {
    const { facts_known, facts_total, facts_missing, code } = results.site
    if (code) return evidenceLabel(code)
    const facts = facts_known !== null && facts_total !== null ? `${facts_known}/${facts_total} 사실 확인` : null
    const missing = facts_missing.length ? `부족: ${facts_missing.map(evidenceLabel).join(', ')}` : null
    return [facts, missing].filter(Boolean).join(' · ') || step.summary
  }
  if (tool === 'law_parcel_limits' && results?.law) {
    const law = results.law
    const parts = [law.bcr_pct !== null ? `건폐율 ${law.bcr_pct}%` : null, law.far_pct !== null ? `용적률 ${law.far_pct}%` : null, law.max_floors !== null ? `${law.max_floors}층` : null].filter(Boolean)
    return parts.join(' · ') || step.summary
  }
  if (tool === 'revision_triage' && results?.review) return results.review.code ? stateLabel(results.review.code) : step.summary
  return step.summary
}

function Timeline({ run, results }: { run: RunSummary; results: RunResults | null }) {
  const steps: RunStep[] = results?.steps ?? run.communications.map((comm) => ({ task_id: comm.task_id, agent: comm.agent, tool: comm.tool, state: comm.state, summary: null, truncated: comm.truncated }))
  const extra = steps.filter((step) => !PIPELINE.includes(step.tool as (typeof PIPELINE)[number]))
  const rows = [...PIPELINE.map((tool) => ({ tool, step: steps.find((step) => step.tool === tool) })), ...extra.map((step) => ({ tool: step.tool ?? '—', step }))]
  return (
    <section aria-label="단계" className="law-card">
      <h2>단계 <small>대지 → 법규 → 검토 조정</small></h2>
      <ol className="law-steps">
        {rows.map(({ tool, step }) => {
          const state = tool === 'revision_triage' && results?.review?.status ? results.review.status : step?.state ?? 'queued'
          const detail = stepDetail(tool, step, results)
          return (
            <li data-state={state} key={tool}>
              <b>{agentLabel(agentForTool(tool, step?.agent))}</b>
              <span>{toolLabel(tool)}</span>
              <em>{stateLabel(state)}</em>
              {detail && <small>{detail}</small>}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function LawCard({ results, editor }: { results: RunResults | null; editor: Summary | null }) {
  const law = results?.law ?? null
  const rows = compareLaw(law, editor)
  const differing = differingRows(rows)
  return (
    <section aria-label="법규 결과" className="law-card">
      <h2>
        법규 결과 <small>{law ? stateLabel(law.status) : '대기'}</small>
        {differing > 0 && <span className="law-badge" data-tone="warn">에디터 분석과 {differing}곳 다름</span>}
      </h2>
      <table className="law-table law-compare">
        <thead><tr><th scope="col">항목</th><th scope="col">오케스트레이터 (Law)</th><th scope="col">에디터 분석</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr data-differs={row.differs === true ? 'true' : undefined} key={row.label}>
              <th scope="row">{row.label}</th>
              <td><b>{row.run}</b></td>
              <td>
                <b>{row.editor}</b>
                {row.differs === true && <mark className="law-diff" title="두 값이 달라요">≠</mark>}
                {row.differs === false && <span className="law-same" title="두 값이 같아요">=</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!editor && <p className="law-sub">에디터 분석은 요약 탭의 분석이 끝나면 함께 보여요.</p>}
      {law && (
        <dl className="law-kv">
          <div><dt>정책</dt><dd>{law.policy_id ?? '—'}{law.parcel_label ? ` · ${law.parcel_label}` : ''}</dd></div>
          <div><dt>조례 영수증</dt><dd><Receipt law={law} /></dd></div>
        </dl>
      )}
      {law && law.sources.length > 0 && (
        <details className="law-sources">
          <summary>법적 근거 {law.sources.length}건</summary>
          <ul className="law-list">{law.sources.map((source, index) => <li key={`${source.title}-${index}`}>{source.title ?? '—'}{source.date ? ` (${source.date})` : ''}</li>)}</ul>
        </details>
      )}
    </section>
  )
}

function Receipt({ law }: { law: NonNullable<RunResults['law']> }) {
  if (!law.ordinance) {
    return <span className="law-orch-warn">{law.truncated ? '전달되지 않음 — Law 응답이 8,000자에서 잘렸어요 (오케스트레이터 통신 상한)' : '없음'}</span>
  }
  const { articles, edition_id, effective_date, assessment_date } = law.ordinance
  return (
    <span>
      {articles.length ? articles.join(' · ') : '조문 —'}
      {edition_id && ` · 판본 ${edition_id}`}
      {effective_date && ` · 시행 ${effective_date}`}
      {assessment_date && ` · 기준일 ${assessment_date}`}
    </span>
  )
}

/** The `missing_evidence` codes inside a finding's evidence object (Law's district review carries them there). */
function missingCodes(evidence: unknown): string[] {
  if (!evidence || typeof evidence !== 'object' || Array.isArray(evidence)) return []
  const codes = (evidence as { missing_evidence?: unknown }).missing_evidence
  return Array.isArray(codes) ? codes.filter((code): code is string => typeof code === 'string') : []
}

function Evidence({ results }: { results: RunResults | null }) {
  const actions = results?.review?.actions ?? []
  const covered = new Set(actions.flatMap((action) => [action.finding, ...missingCodes(action.evidence)]))
  const codes = (results?.missing_evidence_all ?? []).filter((code) => !covered.has(code) && !code.includes(': '))
  if (actions.length === 0 && codes.length === 0) return null
  return (
    <section aria-label="부족한 근거" className="law-card">
      <h2>부족한 근거 <small>{actions.length + codes.length}</small></h2>
      <ol className="law-actions">
        {actions.map((action, index) => (
          <li key={`${action.finding}-${index}`}>
            <b>{evidenceLabel(action.finding ?? '—')}</b>
            <small>{agentLabel(action.raised_by)} 제기{action.recommended_agents.length ? ` · 담당 ${action.recommended_agents.map(agentLabel).join(', ')}` : ''}</small>
            <p>→ {actionLabel(action.recommended_action)}</p>
            {missingCodes(action.evidence).length > 0 && (
              <ul className="law-chips">{missingCodes(action.evidence).map((code) => <li key={code}>{evidenceLabel(code)}</li>)}</ul>
            )}
          </li>
        ))}
        {codes.map((code) => <li key={code}><b>{evidenceLabel(code)}</b></li>)}
      </ol>
    </section>
  )
}
