'use client'

import { statusLabel, traceLabel } from '@/lib/orchestrator-runs/labels'
import type { RunSummary } from '@/lib/orchestrator-runs/types'

import { goalLabel, runTone } from '../lib/status'

interface Props {
  runs: readonly RunSummary[]
  selected: string | null
  onSelect: (runId: string) => void
}

/** The project's runs, newest first: what each was for, where it stands, and its short id. */
export function RunList({ runs, selected, onSelect }: Props) {
  if (!runs.length) return <p className="collab-note">이 프로젝트에 저장된 실행이 없어요. 법규 패널의 검토 시작이나 시스템 패널의 연결 점검이 실행을 만들어요.</p>
  return (
    <ul className="collab-runs">
      {runs.map((run) => (
        <li key={run.run_id}>
          <button aria-pressed={selected === run.run_id} onClick={() => onSelect(run.run_id)} type="button">
            <strong>{goalLabel(run.goal)}</strong>
            <span className="collab-status" data-tone={runTone(run.status)}>{statusLabel(run.status)}</span>
            <code title={run.run_id}>{traceLabel(run.run_id)}</code>
          </button>
        </li>
      ))}
    </ul>
  )
}
