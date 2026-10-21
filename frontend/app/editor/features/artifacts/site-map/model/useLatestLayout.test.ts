import { describe, expect, it } from 'bun:test'

import type {
  LayoutAlternatives,
  LayoutCandidate,
  RunMasterplan,
  RunWithResults,
} from '@/lib/orchestrator-runs/types'
import { candidateOverlay, massQuestionOf, overlayOf, shownCandidate } from './useLatestLayout'

const plan = {
  status: 'succeeded',
  code: null,
  task_id: 't',
  truncated: false,
  intent: null,
  layout: {
    crs: 'EPSG:4326',
    layers: [],
    features: [],
    footprint_m2: 600,
    site_area_m2: 2500,
    coverage_pct: 24,
    storeys: 5,
    storey_height_m: 3.5,
    height_m: 17.5,
    height_basis: '가정',
  },
} as unknown as RunMasterplan

function candidate(id: string, label: string | null): LayoutCandidate {
  return {
    candidate_id: id,
    label,
    status: 'needs_evidence',
    preview_svg: '<svg/>',
    masterplan: plan,
  }
}

const set: LayoutAlternatives = {
  run_id: 'r1',
  index_revision: 1,
  selection_revision: 0,
  chosen_candidate_id: null,
  candidates: [candidate('a', '도로 쪽 배치'), candidate('b', null)],
}

describe('the layout the 3D view stands on the parcel', () => {
  it('draws a run layout with its storeys in the caption, nothing without one', () => {
    expect(overlayOf(plan, 'abcdef0123')?.caption).toBe('배치 abcdef01 · 5층 (가정) · 바닥 600㎡')
    expect(overlayOf({ ...plan, layout: null }, 'r')).toBeNull()
  })

  it('shows the candidate being looked at, else the pick, else the first', () => {
    expect(shownCandidate(set, 'b')?.candidate_id).toBe('b')
    expect(shownCandidate({ ...set, chosen_candidate_id: 'b' }, null)?.candidate_id).toBe('b')
    expect(shownCandidate(set, null)?.candidate_id).toBe('a')
    expect(shownCandidate(set, 'zzz')?.candidate_id).toBe('a') // a stale preview falls back
    expect(shownCandidate(null, 'a')).toBeNull()
  })

  it('names a candidate by its label and says whether it is the pick', () => {
    expect(candidateOverlay(candidate('a', '도로 쪽 배치'), 'r1', false)?.caption).toBe(
      '배치안 보기: 도로 쪽 배치 · 5층 · 바닥 600㎡',
    )
    expect(candidateOverlay(candidate('b', null), 'r1', true)?.caption).toBe(
      '고른 배치안: b · 5층 · 바닥 600㎡',
    )
    expect(candidateOverlay({ ...candidate('a', 'x'), masterplan: null }, 'r1', false)).toBeNull()
  })

  it("lists Mass's forms only while the mass run waits for the pick", () => {
    const waiting = {
      status: 'waiting_input',
      pending_request: {
        kind: 'mass_selection',
        fields: ['selected_mass_id'],
        candidates: [
          {
            selected_mass_id: 'book:a',
            jury_recommended: true,
            preview: { data_url: 'data:image/png;base64,AA==' },
          },
          { nope: true },
        ],
      },
    } as unknown as RunWithResults
    expect(massQuestionOf(waiting).map((c) => c.selected_mass_id)).toEqual(['book:a'])
    expect(massQuestionOf({ ...waiting, status: 'succeeded' })).toEqual([])
    expect(
      massQuestionOf({
        ...waiting,
        pending_request: { kind: 'district_lot', fields: ['lot'] },
      } as unknown as RunWithResults),
    ).toEqual([])
    expect(massQuestionOf(null)).toEqual([])
  })
})
