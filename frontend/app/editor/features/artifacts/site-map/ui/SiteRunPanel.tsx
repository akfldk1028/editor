'use client'

import { useEffect, useState } from 'react'
import { defaultRunConditions, isValidDate, loadRunConditions, saveRunConditions } from '@/lib/orchestrator-runs/conditions'
import { ConditionsRow } from '@/lib/orchestrator-runs/ui/ConditionsRow'
import type { ShellApi } from '../../../shell/artifact-types'
import type { SavedSite } from '../lib/picks'
import { defaultLayoutInputs, type LayoutInputs, layoutBlocker, loadLayoutInputs, saveLayoutInputs } from '../lib/site-run'
import { useSiteRun } from '../model/useSiteRun'

interface Props {
  site: SavedSite
  project?: string
  shell: ShellApi
}

/**
 * Two things a saved site can start: 법규 검토 (the law artifact, as before) and 배치 설계 — the Orchestrator's
 * `masterplan` run (Site → Law → Program → DesignIntent → MasterPlan) with the design intent said in plain words
 * ("1층은 상가로 열고, 외장은 커튼월로"); its layout then shows in the 3D view over the parcel.
 */
export function SiteRunPanel({ site, project, shell }: Props) {
  const [conditions, setConditions] = useState(defaultRunConditions)
  const [inputs, setInputs] = useState<LayoutInputs>(defaultLayoutInputs)
  useEffect(() => { setConditions(loadRunConditions()); setInputs(loadLayoutInputs()) }, [])
  const run = useSiteRun(site, project)
  const first = site.parcels[0]
  const start = () => {
    if (!first || !isValidDate(conditions.assessmentDate)) return
    saveRunConditions(conditions)
    shell.openArtifact('law', {
      pnu: first.pnu, address: first.address || site.label, tab: 'review',
      parcelCount: String(site.parcels.length),
      assessmentDate: conditions.assessmentDate, buildingType: conditions.buildingType,
    })
  }
  const blocker = layoutBlocker(conditions, inputs)
  const busy = run.phase.kind === 'submitting' || (run.phase.kind === 'submitted' && !run.phase.stale && !['succeeded', 'failed', 'blocked', 'completed', 'rejected'].includes(run.phase.run.status))
  const layout = () => {
    if (!first || blocker || !run.ready) return
    saveRunConditions(conditions)
    saveLayoutInputs(inputs)
    void run.start('masterplan', inputs)
  }
  return (
    <div aria-label="법규 검토" className="site-card-run" role="group">
      <ConditionsRow onChange={setConditions} value={conditions} />
      <button className="artifact-primary site-card-select" disabled={!first || !isValidDate(conditions.assessmentDate)} onClick={start} type="button">
        법규 검토
      </button>
      <div aria-label="배치 설계" className="site-card-layout" role="group">
        <label>
          <span>연면적 ㎡</span>
          <input inputMode="decimal" onChange={(event) => setInputs({ ...inputs, floorAreaM2: event.target.value })} placeholder="예: 3000" value={inputs.floorAreaM2} />
        </label>
        <label>
          <span>바닥면적 ㎡</span>
          <input inputMode="decimal" onChange={(event) => setInputs({ ...inputs, footprintM2: event.target.value })} placeholder="예: 600 (건물이 땅에 닿는 면적)" value={inputs.footprintM2} />
        </label>
        <label>
          <span>설계 의도</span>
          <textarea maxLength={2000} onChange={(event) => setInputs({ ...inputs, intent: event.target.value })} placeholder="예: 1층은 상가로 도로 쪽에 열고, 2~5층 사무실, 외장은 커튼월로" rows={2} value={inputs.intent} />
        </label>
        <button className="artifact-primary site-card-select" disabled={!first || !!blocker || !run.ready || !run.chosen || busy} onClick={layout} title={blocker ?? (run.chosen ? undefined : '프로젝트를 먼저 골라 주세요')} type="button">
          {busy ? '배치 설계 중…' : '배치 설계'}
        </button>
        {blocker && <small className="site-card-layout-note">{blocker}</small>}
        {run.phase.kind === 'failed' && <small className="site-card-layout-note" data-kind="error">{run.phase.failure.kind === 'unavailable' ? 'Orchestrator에 연결할 수 없어요' : run.phase.failure.text}</small>}
      </div>
    </div>
  )
}
