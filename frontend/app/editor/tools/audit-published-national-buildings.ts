import { readFile, writeFile, rename } from 'node:fs/promises'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { regionAssetsComplete } from './building-publication-safety'

const root = 'D:/Data/25_ACE/editor/frontend/app/editor/public/world-buildings'
const output = 'D:/Data/NGII_DEM/national-published-assets-audit.json'
const bytes = await readFile(join(root, 'catalog.json'))
const catalog = JSON.parse(bytes.toString('utf8'))
const signature = createHash('sha256').update(bytes).digest('hex')
let checked = 0
const invalid: string[] = []
const startedAt = Date.now()
const checkpoint = async (state: string) => {
  await writeFile(output + '.tmp', JSON.stringify({ state, pid: process.pid, startedAt,
    checkedAt: Date.now(), checked, total: catalog.regions.length, invalid, catalogSha256: signature,
    scope: 'All referenced mesh file headers/lengths, tileset structure, footprints JSON/count, and ground provenance. Not visual quality or loading speed.' }, null, 2))
  await rename(output + '.tmp', output)
}
await checkpoint('running')
for (let index = 0; index < catalog.regions.length; index += 8) {
  const batch = catalog.regions.slice(index, index + 8)
  const results = await Promise.all(batch.map(async (region: any) => ({ id: region.id, valid: await regionAssetsComplete(root, region) })))
  for (const result of results) { checked++; if (!result.valid) invalid.push(result.id) }
  if (checked % 256 === 0) { await checkpoint('running'); console.log(JSON.stringify({ checked, total: catalog.regions.length, invalid: invalid.length })) }
}
const current = await readFile(join(root, 'catalog.json'))
await checkpoint(createHash('sha256').update(current).digest('hex') === signature ? 'complete' : 'catalog_changed_requires_followup')
console.log(JSON.stringify({ checked, invalid }))
