'use client'

import { RotateCcw } from 'lucide-react'
import { useEffect } from 'react'

import { ArtifactChrome } from '../../../shell/artifact-host/ArtifactChrome'
import type { ArtifactProps } from '../../../shell/artifact-types'
import { summarize } from '../lib/presentation'
import { useSystemStatus } from '../model/useSystemStatus'
import { StatusTable } from './StatusTable'
import './system.css'

/** 시스템: every service in infra/config/services.json with its live state, polled every 10 s. */
export default function SystemArtifact({ shell }: ArtifactProps) {
  const { phase, fetching, refresh } = useSystemStatus()
  const { setTitle } = shell

  useEffect(() => {
    setTitle('시스템', phase.kind === 'ready' ? summarize(phase.status) : undefined)
  }, [setTitle, phase])

  return (
    <>
      <ArtifactChrome
        actions={
          <button className="artifact-primary" disabled={fetching} onClick={refresh} type="button">
            <RotateCcw aria-hidden="true" size={12} /><span>다시 확인</span>
          </button>
        }
      />
      <div aria-busy={fetching} className="system-artifact">
        {phase.kind === 'loading' && <p className="system-note"><span aria-hidden="true" className="loading-mark" /> 상태를 확인하는 중</p>}
        {phase.kind === 'error' && <p className="system-note" data-kind="error" role="alert">{phase.text}</p>}
        {phase.kind === 'ready' && <StatusTable stale={phase.stale} status={phase.status} />}
      </div>
    </>
  )
}
