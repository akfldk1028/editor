'use client'

import { BUILDING_TYPES } from '@/lib/building-types'

import type { RunConditions } from '../conditions'
import './conditions-row.css'

interface Props {
  value: RunConditions
  onChange(next: RunConditions): void
  disabled?: boolean
}

/**
 * The 조건 of a `limits` run, shared by the site card and the law artifact: 기준일 (required; the
 * backend refuses a run without a real date) and 용도 (the shared short list, or none).
 */
export function ConditionsRow({ value, onChange, disabled = false }: Props) {
  return (
    <div aria-label="조건" className="run-conditions" role="group">
      <label>
        <span>기준일</span>
        <input disabled={disabled} onChange={(event) => onChange({ ...value, assessmentDate: event.target.value })} required type="date" value={value.assessmentDate} />
      </label>
      <label>
        <span>용도</span>
        <select disabled={disabled} onChange={(event) => onChange({ ...value, buildingType: event.target.value })} value={value.buildingType}>
          <option value="">미지정</option>
          {BUILDING_TYPES.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
