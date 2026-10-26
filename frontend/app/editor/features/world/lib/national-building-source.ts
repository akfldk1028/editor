/** Publication proof required before removing runtime-vector coverage. */
export type NationalBuildingSource = {
  schema: 'world-buildings/national-v1'
  url: string
  sourceSha256: string
  terrainVrtSha256: string
  catalogRevision: string
  coverageSha256: string
  materialRevision: 'neutral-opaque-v1'
  hierarchy: 'replace-coarse-ancestors-v1'
  coverage: { expectedRegions: number; completeRegions: number; missingRegions: number; partialRegions: number }
}

/** An absent candidate preserves the existing installation; an invalid one must not mix sources. */
export function validateNationalBuildingSource(value: unknown, terrainVrt: string, catalogRevision: string): NationalBuildingSource | undefined {
  if (value === undefined) return undefined
  const source = value as NationalBuildingSource | null
  const sha = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
  const coverage = source?.coverage
  if (!source || source.schema !== 'world-buildings/national-v1'
    || source.materialRevision !== 'neutral-opaque-v1' || source.hierarchy !== 'replace-coarse-ancestors-v1'
    || !sha(source.sourceSha256) || !sha(source.coverageSha256)
    || !sha(source.terrainVrtSha256) || source.terrainVrtSha256 !== terrainVrt
    || !sha(source.catalogRevision) || source.catalogRevision !== catalogRevision
    || !coverage || !Number.isSafeInteger(coverage.expectedRegions) || coverage.expectedRegions <= 0
    || coverage.completeRegions !== coverage.expectedRegions || coverage.missingRegions !== 0 || coverage.partialRegions !== 0
    || typeof source.url !== 'string' || !source.url.endsWith('/tileset.json')) throw new Error('Incomplete or inconsistent national building publication')
  const url = new URL(source.url, 'https://map.invalid/')
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash
    || source.url.split('/').some(part => part === '..' || part === '.')) throw new Error('Invalid national building URL')
  return source
}
