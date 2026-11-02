import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { createHash } from 'node:crypto'
import { cellsIn, CELL_RADIUS_M } from '../features/world/lib/context-cells'
import { groundSource, GroundSourceUnavailable } from './ground-source'
import { publishableGround } from '../features/world/lib/ground-publication'
import { refreshGroundRoads } from './refresh-ground-roads'
import { replacePublishedFile } from './replace-published-file'

// One publisher per output catalog. Geographic display snapshots, never legal analysis inputs.
const bounds = process.argv.slice(2, 6).map(Number) as [number, number, number, number]
if (bounds.length !== 4 || !bounds.every(Number.isFinite) || bounds[0] < 124 || bounds[2] > 132
  || bounds[1] < 33 || bounds[3] > 39 || bounds[0] >= bounds[2] || bounds[1] >= bounds[3]) throw new Error('Expected west south east north bounds in Korea')
const output = resolve(process.env.WORLD_GROUND_OUTPUT || 'public/world-ground')
const origin = process.env.WORLD_API_ORIGIN || 'http://127.0.0.1:18449'
const workers = Number(process.env.WORLD_GROUND_WORKERS || 2)
if (!Number.isInteger(workers) || workers < 1 || workers > 4) throw new Error('WORLD_GROUND_WORKERS must be 1..4')
await mkdir(output, { recursive: true })
const previous = await readFile(join(output, 'catalog.json'), 'utf8').then(JSON.parse).catch(() => null)
const catalog: { schema: string; cells: Record<string, { file: string; sampledAt: string }> } = {
  schema: 'world-ground/v1', cells: previous?.schema === 'world-ground/v1' ? previous.cells : {},
}
let publication = Promise.resolve()
const publish = () => publication = publication.then(async () => {
  await writeFile(join(output, 'catalog.next.json'), JSON.stringify(catalog))
  await replacePublishedFile(join(output, 'catalog.next.json'), join(output, 'catalog.json'))
})
const cells = cellsIn(bounds, { lon: (bounds[0] + bounds[2]) / 2, lat: (bounds[1] + bounds[3]) / 2 })
if (cells.length > 10000) throw new Error('Split large coverage into regional jobs (max10000 cells per job)')
const failed: { key: string; error: string }[] = []
let cursor = 0, reused = 0, completed = 0
let halted = false
const startedAt = Date.now()
const progress = () => publication = publication.then(async () => {
  await writeFile(join(output, 'bake-progress.next.json'), JSON.stringify({ bounds, total: cells.length,
    completed, reused, failed: failed.length, halted, visited: completed + reused + failed.length, elapsedSeconds: (Date.now() - startedAt) / 1000 }))
  await replacePublishedFile(join(output, 'bake-progress.next.json'), join(output, 'bake-progress.json'))
})
async function worker() {
  for (;;) {
    if (halted) return
    const cell = cells[cursor++]
    if (!cell) return
    const saved = catalog.cells[cell.key]
    let previousBody: any
    if (saved && /^[a-f0-9]{64}\.json$/.test(saved.file) && Date.now() - Date.parse(saved.sampledAt) < 86400000) {
      const bytes = await readFile(join(output, saved.file)).catch(() => null)
      if (bytes && createHash('sha256').update(bytes).digest('hex') + '.json' === saved.file) {
        const value = JSON.parse(bytes.toString())
        if (value.record?.roads?.revision || value.gaps?.length) { reused++; continue }
        previousBody = value
      }
    }
    try {
      const query = new URLSearchParams({ lat: String(cell.lat), lon: String(cell.lon), radius_m: String(CELL_RADIUS_M), detail: previousBody ? 'roads' : 'full' })
      const response = await groundSource(`${origin}/api/v1/land/context-ground?${query}`)
      let received = await response.json()
      if (previousBody && received.status !== 'ok') {
        // Re-read the full cell for fresh layer receipts when installed roads
        // are absent; an empty road reply cannot erase an existing preview.
        query.set('detail', 'full')
        received = await (await groundSource(`${origin}/api/v1/land/context-ground?${query}`)).json()
        previousBody = undefined
      }
      const body = previousBody ? refreshGroundRoads(previousBody, received) : received
      if (!publishableGround(body)) throw new Error(`Source unavailable; not published: ${JSON.stringify(body.gaps || body.reason)}`)
      const bytes = JSON.stringify(body), file = createHash('sha256').update(bytes).digest('hex') + '.json'
      const destination = join(output, file)
      const existing = await readFile(destination).catch(() => null)
      if (!existing || createHash('sha256').update(existing).digest('hex') + '.json' !== file) {
        const temporary = join(output, `${file}.${cell.key.replace(':', '-')}.next`)
        await writeFile(temporary, bytes)
        await replacePublishedFile(temporary, destination)
      }
      catalog.cells[cell.key] = { file, sampledAt: previousBody ? saved!.sampledAt : new Date().toISOString() }
      await publish(); completed++
      console.log(`Published ${cell.key} (${completed + reused}/${cells.length}, ${body.features.features.length} features)`)
    } catch (error) {
      if (error instanceof GroundSourceUnavailable) halted = true
      failed.push({ key: cell.key, error: String(error) }); console.error(`Missing ${cell.key}: ${error}`)
    }
    await progress()
  }
}
await Promise.all(Array.from({ length: workers }, () => worker()))
await publish()
await progress()
await writeFile(join(output, 'last-bake-report.json'), JSON.stringify({ bounds, completed, reused, failed, halted,
  unvisited: cells.length - completed - reused - failed.length }, null, 2))
console.log(JSON.stringify({ completed, reused, failed: failed.length }))
if (failed.length) process.exitCode = 2
