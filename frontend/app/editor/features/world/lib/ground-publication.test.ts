import { expect, test } from 'bun:test'
import { publishableGround } from './ground-publication'
import type { ContextReply } from './context-masses'

test('only known installed coverage gaps allow publication of usable ground', () => {
  const receipt = { revision: 'a'.repeat(64), retrieved: new Date().toISOString(), complete_bbox: [126, 37, 127, 38] }
  const source = { status: 'ok', record: { ground: receipt, cover: receipt }, features: { type: 'FeatureCollection', features: [] } } as ContextReply
  expect(publishableGround(source)).toBe(true)
  expect(publishableGround({ ...source, gaps: ['roads: No installed road centrelines in this viewport; this does not establish absence of roads'] })).toBe(true)
  expect(publishableGround({ ...source, gaps: ['carriageways: 3 centreline(s) without lanes left out'] })).toBe(true)
  expect(publishableGround({ ...source, record: {}, gaps: ['carriageways: 3 centreline(s) without lanes left out'] })).toBe(false)
  for (const gap of ['cover: source unavailable', 'roads: source unavailable', 'cadastre: invalid source geometry', 'missing_roads']) {
    expect(publishableGround({ ...source, gaps: [gap] })).toBe(false)
  }
})
