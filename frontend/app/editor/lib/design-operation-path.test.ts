import { describe, expect, test } from 'bun:test'
import { isDesignOperation } from './design-operation-path'

describe('design operation boundary', () => {
  const id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
  test('accepts engine UUID and original result/detail routes', () => {
    for (const path of [`jobs/${id}`, `jobs/${id}/stream`, `jobs/${id}/results/0`, `jobs/${id}/results/0/evidence`,
      'maas/single-executions/demo/manifest', 'maas/reference-assets/book/preview.png',
      'maas/portfolio-evaluations/run.1/candidates/source:mass+1/render',
      'maas/reference-assets/도면/입면 (1).png']) {
      expect(isDesignOperation('GET', path)).toBe(true)
    }
    for (const path of [`jobs/${id}/run`, `jobs/${id}/cancel`, `jobs/${id}/validate`,
      'maas/revision', `maas/revision/${id}/feedback`, 'masterplan/operations']) {
      expect(isDesignOperation('POST', path)).toBe(true)
    }
  })
  test('rejects unknown paths, traversal, bad identifiers and method mismatches', () => {
    for (const path of ['jobs/nope', 'unknown', 'maas/reference-assets/../secret', 'maas/reference-assets/%2e%2e/secret']) {
      expect(isDesignOperation('GET', path)).toBe(false)
    }
    expect(isDesignOperation('GET', `jobs/${id}/cancel`)).toBe(false)
    expect(isDesignOperation('POST', `jobs/${id}/stream`)).toBe(false)
  })
})
