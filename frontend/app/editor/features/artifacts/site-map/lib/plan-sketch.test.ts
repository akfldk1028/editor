import { describe, expect, it } from 'bun:test'

import type { RunLayout } from '@/lib/orchestrator-runs/types'
import { planSketch } from './plan-sketch'

const ring = [[127.108, 37.73], [127.109, 37.73], [127.109, 37.7305], [127.108, 37.7305], [127.108, 37.73]]
const layout = {
  crs: 'EPSG:4326',
  layers: ['site_boundary', 'building_footprint'],
  features: [
    { type: 'Feature', geometry: { type: 'Polygon', coordinates: [ring] }, properties: { layer: 'site_boundary', level: 0, area_m2: null } },
    { type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[127.1082, 37.7301], [127.1086, 37.7301], [127.1086, 37.7303], [127.1082, 37.7303], [127.1082, 37.7301]]] }, properties: { layer: 'building_footprint', level: 0, area_m2: 800 } },
  ],
} as unknown as RunLayout

describe('the plan sketch of a candidate', () => {
  it('draws the parcel outline and the footprint inside a 120x100 box', () => {
    const svg = planSketch(layout)!
    expect(svg.startsWith('<svg')).toBe(true)
    expect(svg).toContain('viewBox="0 0 120 100"')
    expect(svg).toContain('fill="#4a4a46"') // the footprint, filled
    expect(svg).toContain('fill="none" stroke="#8a8a85"') // the parcel, outlined
    // every coordinate lands inside the box
    const numbers = [...svg.matchAll(/[ML]([\d.]+) ([\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])])
    expect(numbers.length).toBeGreaterThan(5)
    expect(numbers.every(([x, y]) => x! >= 0 && x! <= 120 && y! >= 0 && y! <= 100)).toBe(true)
  })

  it('draws nothing without features', () => {
    expect(planSketch({ ...layout, features: [] })).toBeNull()
    expect(planSketch(null)).toBeNull()
  })
})
