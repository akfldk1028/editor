'use client'

import type { LawAnalysis, OrdinanceReadingResult } from '../api/analyze'

/** The question keys in the user's words (the backend's QUESTIONS keys); an unknown key keeps its name. */
const LABELS: Record<string, string> = {
  site_subdivision_limit: '대지 분할 최소 면적', site_road_requirement: '6m 도로 접도 제외 규모(축사 등)', landscaping: '조경 면적 비율',
  on_site_open_space: '대지 안의 공지', public_open_space: '공개공지', sunlight_setback: '정북 일조 이격',
  bcr_by_zone: '용도지역별 건폐율 상한', far_by_zone: '용도지역별 용적률 상한', use_tables: '건축 가능 건축물 별표',
  parking_ratio: '부설주차장 설치기준', restricted_district: '주차장 설치제한지역',
}
const fmt = (value: number | null | undefined, unit: string | null | undefined) =>
  value === null || value === undefined ? null : `${value.toLocaleString('ko-KR')}${unit && unit !== '-' ? unit.replace('m2', '㎡') : ''}`

/**
 * What the jurisdiction's ordinances decide, as the model read them from the official text — every figure with its
 * article and the sentence it came from — and what the zone split excluded. Nothing here is computed by the editor.
 */
export function OrdinanceReadings({ analysis }: { analysis: LawAnalysis }) {
  const readings = Object.values(analysis.ordinance_reading ?? {}).filter((reading): reading is OrdinanceReadingResult => !!reading && !!reading.ordinance)
  const notes = analysis.zone_info?.zone_split?.notes ?? []
  if (!readings.length && !notes.length) return null
  return <section className="law-ordinance-readings" aria-label="관할 조례가 정한 값">
    {notes.length > 0 && <div className="law-ordinance-note"><strong>용도지역 분할</strong><ul>{notes.map((note) => <li key={note}>{note}</li>)}</ul></div>}
    {readings.map((reading) => {
      const items = Object.entries(reading.items ?? {})
      return <details className="law-ordinance-reading" key={reading.kind} open={reading.kind === 'building'}>
        <summary><strong>{reading.ordinance.name}</strong><span>시행 {reading.ordinance.effective_date ?? '—'} · 판본 {reading.ordinance.edition_id} · 모델이 원문에서 읽음, 인용 검증 {items.length}건{reading.dropped?.length ? ` · 제외 ${reading.dropped.length}건` : ''}</span></summary>
        {items.length === 0 ? <p className="law-note">이 조례에서 읽을 항목이 없었어요.</p> : <dl>
          {items.map(([key, item]) => <div key={key}>
            <dt>{LABELS[key] ?? key}</dt>
            <dd>
              {fmt(item.value, item.unit) && <span className="law-ordinance-value">{fmt(item.value, item.unit)}</span>}
              {item.by_scope?.length ? <ul>{item.by_scope.map((row) => <li key={row.scope}>{row.scope}: {fmt(row.value, item.unit) ?? row.text ?? '—'}</li>)}</ul> : null}
              <small>{item.article}{item.quote ? ` — “${item.quote}”` : ''}</small>
            </dd>
          </div>)}
        </dl>}
      </details>
    })}
  </section>
}
