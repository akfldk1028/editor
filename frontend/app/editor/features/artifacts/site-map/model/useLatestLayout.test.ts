import { describe, expect, it } from 'bun:test'

import type { MassForms, RunMasterplan } from '@/lib/orchestrator-runs/types'
import { defaultForm, overlayOf, withForm } from './useLatestLayout'

const ring = [[127.1, 37.7], [127.1002, 37.7], [127.1002, 37.7002], [127.1, 37.7002]]

function form(id: string, gfa: number, reaches: boolean | null) {
  return { id, form: id, label: id === 'inscribe' ? '중정형' : '기본 매스', footprint_m2: 500, coverage_of_zone: 0.8, gfa_m2: gfa,
    height_m: 17.5, storeys: 5, reaches_target: reaches, thumbnail_svg: '<svg/>', volumes: [{ ring, base_m: 0, top_m: 17.5 }] }
}

const forms: MassForms = {
  status: 'succeeded', truncated: false, revised: false, first_verdict: null, verdict: { status: 'fits', reason: null, needed_footprint_m2: null, shortfall_m2: null },
  zone_m2: 600, gfa_target_m2: 3000, pattern: [], alternatives: [form('plain', 2800, false), form('inscribe', 3010, true)],
}

const plan = {
  status: 'succeeded', code: null, task_id: 't', truncated: false, intent: null,
  layout: { crs: 'EPSG:4326', layers: [], features: [], footprint_m2: 600, site_area_m2: 2500, coverage_pct: 24, storeys: 5, storey_height_m: 3.5, height_m: 17.5, height_basis: '가정' },
} as unknown as RunMasterplan

describe('Mass forms on the layout overlay', () => {
  it('opens with the first form that reaches the target, else the first', () => {
    expect(defaultForm(forms)).toBe('inscribe')
    expect(defaultForm({ ...forms, alternatives: [form('plain', 1, false)] })).toBe('plain')
    expect(defaultForm(null)).toBeNull()
  })

  it('stands the chosen form on the zone and names it in the caption', () => {
    const overlay = overlayOf(plan, 'abcdef0123', forms)
    const chosen = withForm(overlay, 'inscribe')
    expect(chosen?.layout.mass?.volumes).toHaveLength(1)
    expect(chosen?.caption).toContain('중정형')
    expect(chosen?.caption).toContain('3,010')
    expect(withForm(overlay, 'missing')).toBe(overlay)            // an unknown pick leaves the box
    expect(overlay?.layout.mass).toBeUndefined()
  })
})
