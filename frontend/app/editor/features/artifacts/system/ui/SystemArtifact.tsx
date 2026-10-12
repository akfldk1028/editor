'use client'

import { Activity, RotateCcw } from 'lucide-react'
import { useEffect } from 'react'

import { useProjectBinding } from '@/lib/design-conversation/useProjectBinding'
import { traceLabel } from '@/lib/orchestrator-runs/labels'

import { ArtifactChrome } from '../../../shell/artifact-host/ArtifactChrome'
import type { ArtifactProps } from '../../../shell/artifact-types'
import { summarize } from '../lib/presentation'
import { useHealthRun } from '../model/useHealthRun'
import { useSystemStatus } from '../model/useSystemStatus'
import { StatusTable } from './StatusTable'
import './system.css'

/** 시스템: every service in infra/config/services.json with its live state, polled every 10 s, and a 연결 점검 run for the conversation's project. */
export default function SystemArtifact({ shell }: ArtifactProps) {
  const { phase, fetching, refresh } = useSystemStatus()
  const { chosen } = useProjectBinding()
  const health = useHealthRun(chosen)
  const { setTitle } = shell

  useEffect(() => {
    setTitle('시스템', phase.kind === 'ready' ? summarize(phase.status) : undefined)
  }, [setTitle, phase])

  return (
    <>
      <ArtifactChrome
        actions={
          <>
            <button className="artifact-primary" disabled={!chosen || health.state.kind === 'busy'} onClick={() => void health.submit()} title={chosen ? undefined : '대화 패널에서 프로젝트를 먼저 고르세요'} type="button">
              <Activity aria-hidden="true" size={12} /><span>{health.state.kind === 'busy' ? '접수 확인 중' : health.retrying ? '같은 점검 다시 확인' : '연결 점검 실행'}</span>
            </button>
            <button className="artifact-primary" disabled={fetching} onClick={refresh} type="button">
              <RotateCcw aria-hidden="true" size={12} /><span>다시 확인</span>
            </button>
          </>
        }
      />
      <div aria-busy={fetching} className="system-artifact">
        {health.state.kind === 'error' && <p className="system-note" data-kind="error" role="alert">{health.state.text}</p>}
        {health.state.kind === 'done' && (
          <p className="system-note" role="status">
            연결 점검 실행이 접수됐어요 · <code title={health.state.runId}>{traceLabel(health.state.runId)}</code>
            <button className="system-link" onClick={() => shell.openArtifact('collaboration', { ...(chosen ? { project: chosen.project_id } : {}), run: health.state.kind === 'done' ? health.state.runId : '', tab: 'flow' })} type="button">협업 패널에서 보기</button>
          </p>
        )}
        {phase.kind === 'loading' && <p className="system-note"><span aria-hidden="true" className="loading-mark" /> 상태를 확인하는 중</p>}
        {phase.kind === 'error' && <p className="system-note" data-kind="error" role="alert">{phase.text}</p>}
        {phase.kind === 'ready' && <StatusTable stale={phase.stale} status={phase.status} />}
      </div>
    </>
  )
}
