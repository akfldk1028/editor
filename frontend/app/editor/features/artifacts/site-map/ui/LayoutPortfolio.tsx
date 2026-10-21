'use client'

import type { LayoutAlternatives, MassCandidate } from '@/lib/orchestrator-runs/types'

import { planSketch } from '../lib/plan-sketch'

/** An SVG MasterPlan drew, shown as an image: an <img> runs no script the drawing might carry. */
function svgUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

interface Props {
  alternatives: LayoutAlternatives | null
  preview: string | null
  onPreview(candidateId: string | null): void
  onChoose(candidateId: string): void
  choosing: boolean
  massCandidates: MassCandidate[]
  massStatus: string | null
  onChooseMass(selectedMassId: string): void
  massBusy: boolean
  error: string | null
}

/**
 * The portfolio on the 3D map: MasterPlan's layout candidates as drawings the person looks at (the 3D view stands
 * the one under the cursor on the parcel) and picks, then Mass's forms on the picked layout as its own images. Each
 * agent's own pictures; no report.
 */
export default function LayoutPortfolio({
  alternatives,
  preview,
  onPreview,
  onChoose,
  choosing,
  massCandidates,
  massStatus,
  onChooseMass,
  massBusy,
  error,
}: Props) {
  const chosen = alternatives?.chosen_candidate_id ?? null
  const shown = preview ?? chosen
  return (
    <aside aria-label="배치안과 매스안" className="layout-portfolio">
      {alternatives && (
        <section>
          <h3>배치안 {chosen ? '· 골랐어요' : '· 하나를 골라 주세요'}</h3>
          <div aria-label="배치안 고르기" className="layout-portfolio-grid" role="listbox">
            {alternatives.candidates.map((candidate, index) => {
              const layout = candidate.masterplan?.layout
              const facts = [
                layout?.footprint_m2 != null
                  ? `바닥 ${Math.round(layout.footprint_m2).toLocaleString()}㎡`
                  : null,
                layout?.coverage_pct != null ? `건폐 ${Math.round(layout.coverage_pct)}%` : null,
                layout?.storeys ? `${layout.storeys}층` : null,
              ]
                .filter(Boolean)
                .join(' · ')
              return (
                <button
                  aria-selected={candidate.candidate_id === shown}
                  className="layout-portfolio-card"
                  data-chosen={candidate.candidate_id === chosen || undefined}
                  key={candidate.candidate_id}
                  onClick={() => onPreview(candidate.candidate_id)}
                  onMouseEnter={() => onPreview(candidate.candidate_id)}
                  role="option"
                  type="button"
                >
                  {(candidate.preview_svg ?? planSketch(candidate.masterplan?.layout)) ? (
                    <img alt="" src={svgUrl(candidate.preview_svg ?? planSketch(candidate.masterplan?.layout)!)} />
                  ) : (
                    <span className="layout-portfolio-blank" />
                  )}
                  <strong>
                    {candidate.label ?? `배치안 ${index + 1}`}
                    {candidate.candidate_id === chosen ? ' ✓' : ''}
                  </strong>
                  <small>{facts || '치수 미상'}</small>
                </button>
              )
            })}
          </div>
          {shown && shown !== chosen && (
            <button
              className="artifact-primary layout-portfolio-confirm"
              disabled={choosing}
              onClick={() => onChoose(shown)}
              type="button"
            >
              {choosing ? '고르는 중…' : '이 배치로 할게요'}
            </button>
          )}
        </section>
      )}
      {(massCandidates.length > 0 || massStatus) && (
        <section>
          <h3>
            매스안 {massCandidates.length ? '· 마음에 드는 걸 골라 주세요' : `· ${massStatus}`}
          </h3>
          {massCandidates.length > 0 && (
            <div aria-label="매스안 고르기" className="layout-portfolio-grid" role="listbox">
              {massCandidates.map((candidate, index) => (
                <button
                  aria-selected={false}
                  className="layout-portfolio-card"
                  disabled={massBusy}
                  key={candidate.selected_mass_id}
                  onClick={() => onChooseMass(candidate.selected_mass_id)}
                  role="option"
                  type="button"
                >
                  {candidate.preview?.data_url ? (
                    <img alt="" src={candidate.preview.data_url} />
                  ) : (
                    <span className="layout-portfolio-blank" />
                  )}
                  <strong>
                    매스안 {index + 1}
                    {candidate.jury_recommended ? ' · 심사 추천' : ''}
                  </strong>
                  <small>
                    {candidate.shape_id ?? candidate.selected_mass_id.replace(/^book:/, '')}
                  </small>
                </button>
              ))}
            </div>
          )}
        </section>
      )}
      {error && (
        <p className="layout-portfolio-note" data-kind="warn">
          {error}
        </p>
      )}
    </aside>
  )
}
