import { expect, test } from 'bun:test'
import { validateNationalBuildingSource } from './national-building-source'

const candidate = {
  schema: 'world-buildings/national-v1', url: 'national/version/tileset.json',
  sourceSha256: 'a'.repeat(64), terrainVrtSha256: 'b'.repeat(64), catalogRevision: 'c'.repeat(64), coverageSha256: 'd'.repeat(64),
  materialRevision: 'neutral-opaque-v1', hierarchy: 'replace-coarse-ancestors-v1',
  coverage: { expectedRegions: 26248, completeRegions: 26248, missingRegions: 0, partialRegions: 0 },
}
const check = (value: unknown) => validateNationalBuildingSource(value, candidate.terrainVrtSha256, candidate.catalogRevision)

test('only a complete source and matching pinned terrain/catalog qualify for prebuilt-only', () => {
  expect(check(undefined)).toBeUndefined()
  expect(check(candidate)).toBe(candidate)
  for (const change of [
    { coverage: { ...candidate.coverage, missingRegions: 681 } },
    { coverage: { ...candidate.coverage, partialRegions: 111 } },
    { coverage: { ...candidate.coverage, completeRegions: 1 } },
    { terrainVrtSha256: 'e'.repeat(64) }, { catalogRevision: 'f'.repeat(64) },
    { hierarchy: 'flat-regions' }, { materialRevision: 'mixed' },
  ]) expect(() => check({ ...candidate, ...change })).toThrow()
})

test('candidate URLs cannot escape the version or carry credentials', () => {
  for (const url of ['../tileset.json', 'https://user:secret@host/tileset.json', 'file:///tileset.json']) {
    expect(() => check({ ...candidate, url })).toThrow()
  }
  expect(check({ ...candidate, url: 'https://tiles.example/national/v1/tileset.json' })?.url).toContain('https://')
})
