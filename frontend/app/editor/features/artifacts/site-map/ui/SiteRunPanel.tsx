'use client'

import { useEffect, useState } from 'react'
import { defaultRunConditions, isValidDate, loadRunConditions, saveRunConditions } from '@/lib/orchestrator-runs/conditions'
import { ConditionsRow } from '@/lib/orchestrator-runs/ui/ConditionsRow'
import type { ShellApi } from '../../../shell/artifact-types'
import type { SavedSite } from '../lib/picks'

interface Props {
  site: SavedSite
  project?: string
  shell: ShellApi
}

export function SiteRunPanel({ site, shell }: Props) {
  const [conditions, setConditions] = useState(defaultRunConditions)
  useEffect(() => setConditions(loadRunConditions()), [])
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
  return (
    <div aria-label="법규 검토" className="site-card-run" role="group">
      <ConditionsRow onChange={setConditions} value={conditions} />
      <button className="artifact-primary site-card-select" disabled={!first || !isValidDate(conditions.assessmentDate)} onClick={start} type="button">
        법규 검토
      </button>
    </div>
  )
}
