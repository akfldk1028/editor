'use client'

import type { MassForms } from '@/lib/orchestrator-runs/types'

const OWNER = { masterplan: 'MasterPlan', mass: 'Mass' } as const
const ROLE = { propose: '배치 제안', review: '매스 검토', revise: '배치 수정', re_review: '매스 재검토' } as const

function stateClass(state: string): string {
  if (state === 'succeeded') return 'done'
  if (state === 'running' || state === 'pending') return 'running'
  if (state === 'failed') return 'failed'
  return 'other'
}

/** An SVG Mass drew, shown as an image: an <img> runs no script the drawing might carry. */
function thumbnailUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

/**
 * MasterPlan <-> Mass on the 3D map: the order the two took (제안 → 검토 → 수정 → 재검토), Mass's verdict on the
 * zone in its own words, and its forms as thumbnails the person picks from - the pick stands in the 3D view.
 */
export default function MassFormsPanel({ forms, chosen, onChoose }: { forms: MassForms; chosen: string | null; onChoose(formId: string): void }) {
  const first = forms.first_verdict
  return (
    <aside aria-label="매스 안" className="mass-forms">
      <ol aria-label="협업 순서" className="mass-forms-pattern">
        {forms.pattern.map((step, index) => (
          <li data-state={stateClass(step.state)} key={`${step.role}-${index}`}>
            <span className="mass-forms-owner">{OWNER[step.owner]}</span>
            <span>{ROLE[step.role]}</span>
          </li>
        ))}
      </ol>
      {forms.revised && first?.reason && <p className="mass-forms-note">처음 구역은 작았어요 — {first.reason} 그래서 MasterPlan이 구역을 넓혀 다시 배치했어요.</p>}
      {!forms.revised && forms.verdict?.status === 'footprint_too_small' && forms.verdict.reason && <p className="mass-forms-note" data-kind="warn">{forms.verdict.reason}</p>}
      <div className="mass-forms-grid" role="listbox" aria-label="매스 안 고르기">
        {forms.alternatives.map((form) => form.id && (
          <button aria-selected={form.id === chosen} className="mass-forms-card" key={form.id} onClick={() => onChoose(form.id!)} role="option" type="button">
            {form.thumbnail_svg ? <img alt="" src={thumbnailUrl(form.thumbnail_svg)} /> : <span className="mass-forms-blank" />}
            <strong>{form.label ?? form.id}</strong>
            <small>
              {form.gfa_m2 != null ? `연면적 ${Math.round(form.gfa_m2).toLocaleString()}㎡` : '연면적 미상'}
              {form.reaches_target === false ? ' · 목표 미달' : form.reaches_target ? ' · 목표 충족' : ''}
            </small>
          </button>
        ))}
      </div>
      {forms.truncated && !forms.alternatives.length && <p className="mass-forms-note">Mass의 답이 잘려 안을 읽지 못했어요.</p>}
    </aside>
  )
}
