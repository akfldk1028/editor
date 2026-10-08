'use client'

import { type KeyboardEvent, useState } from 'react'

import { BUILDING_TYPES, type Conditions, parseArea, today } from '../lib/conditions'

interface Props {
  value: Conditions
  onChange(next: Conditions): void
}

const CUSTOM = '__custom'

/**
 * 조건 rows at the top of the ⋯ menu: 용도 (list or free text), 연면적, 기준일. Selects and the
 * date commit at once; typed fields commit on Enter or blur, so each keystroke is not an analysis.
 */
export function ConditionsMenu({ value, onChange }: Props) {
  const listed = value.buildingType === '' || BUILDING_TYPES.includes(value.buildingType)
  const [custom, setCustom] = useState(!listed)
  const [typeText, setTypeText] = useState(listed ? '' : value.buildingType)
  const [areaText, setAreaText] = useState(value.floorAreaM2 != null ? String(value.floorAreaM2) : '')

  const commitType = () => {
    const next = typeText.trim()
    if (next !== value.buildingType) onChange({ ...value, buildingType: next })
  }
  const commitArea = () => {
    const next = parseArea(areaText)
    if (next !== value.floorAreaM2) onChange({ ...value, floorAreaM2: next })
  }
  const onEnter = (commit: () => void) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      commit()
    }
  }

  return (
    <div aria-label="조건" className="menu-group law-conditions" role="group">
      <p className="law-conditions-title">조건</p>
      <label className="menu-field">
        <span>용도</span>
        <select
          onChange={(event) => {
            if (event.target.value === CUSTOM) return setCustom(true)
            setCustom(false)
            onChange({ ...value, buildingType: event.target.value })
          }}
          value={custom ? CUSTOM : value.buildingType}
        >
          <option value="">미지정</option>
          {BUILDING_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
          <option value={CUSTOM}>직접 입력…</option>
        </select>
      </label>
      {custom && (
        <label className="menu-field">
          <span>용도 직접 입력</span>
          <input onBlur={commitType} onChange={(event) => setTypeText(event.target.value)} onKeyDown={onEnter(commitType)} placeholder="예: 데이터센터" type="text" value={typeText} />
        </label>
      )}
      <label className="menu-field">
        <span>연면적 ㎡</span>
        <input inputMode="decimal" onBlur={commitArea} onChange={(event) => setAreaText(event.target.value)} onKeyDown={onEnter(commitArea)} placeholder="미지정" type="text" value={areaText} />
      </label>
      <label className="menu-field">
        <span>기준일</span>
        <input onChange={(event) => onChange({ ...value, assessmentDate: event.target.value || today() })} type="date" value={value.assessmentDate} />
      </label>
    </div>
  )
}
