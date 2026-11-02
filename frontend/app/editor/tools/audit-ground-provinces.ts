import { readFile, writeFile } from 'node:fs/promises'
import { PMTiles } from 'pmtiles'
import Pbf from 'pbf'
import { VectorTile } from '@mapbox/vector-tile'
import { openLocalArchive } from './local-building-archive'

const [archivePath, recordsPath, output] = process.argv.slice(2)
if (!archivePath || !recordsPath || !output) throw new Error('Expected archive, missing-key-results, report paths')
const records = JSON.parse(await readFile(recordsPath, 'utf8')) as { key: string; after: number | null }[]
const byTile = new Map<string, Map<number, { key: string; filled: boolean }>>()
for (const record of records) {
  const parts = record.key.split('/'), index = Number(parts.pop()), tile = parts.join('/')
  if (parts.length !== 3 || !Number.isSafeInteger(index)) throw new Error('Invalid building source key')
  const group = byTile.get(tile) ?? new Map(), previous = group.get(index)
  group.set(index, { key: record.key, filled: Number.isFinite(record.after) && (previous?.filled ?? true) })
  byTile.set(tile, group)
}
const names: Record<string, string> = { '11':'서울','26':'부산','27':'대구','28':'인천','29':'광주','30':'대전','31':'울산','36':'세종','41':'경기','43':'충북','44':'충남','46':'전남','47':'경북','48':'경남','50':'제주','51':'강원','52':'전북' }
const counts = Object.fromEntries(Object.entries(names).map(([code,name]) => [code,{code,name,beforeMissing:0,newlyFilled:0,remaining:0}]))
counts.unknown = { code:'unknown',name:'시도 식별 미확인',beforeMissing:0,newlyFilled:0,remaining:0 }
const file = await openLocalArchive(archivePath), archive = new PMTiles(file)
try {
  for (const [tile, rows] of byTile) {
    const [z,x,y] = tile.split('/').map(Number), bytes = await archive.getZxy(z!,x!,y!)
    if (!bytes) throw new Error(`Missing source tile ${tile}`)
    const layer = new VectorTile(new Pbf(new Uint8Array(bytes.data))).layers.buildings
    if (!layer) throw new Error(`Missing source building layer ${tile}`)
    for (const [index, row] of rows) {
      const feature = layer.feature(index), prefix = String(feature.properties.p ?? '').slice(0,2)
      const code = prefix === '42' ? '51' : prefix === '45' ? '52' : prefix
      const count = counts[code] ?? counts.unknown!
      count.beforeMissing++;count.newlyFilled += Number(row.filled);count.remaining += Number(!row.filled)
    }
  }
} finally { await file.close() }
const result = { unit:'unique source tile feature keys, not cross-tile deduplicated physical buildings', sourceArchive:archivePath, baselineRecords:recordsPath, provinces:Object.values(counts),
  beforeMissing:Object.values(counts).reduce((n,r)=>n+r.beforeMissing,0),newlyFilled:Object.values(counts).reduce((n,r)=>n+r.newlyFilled,0) }
await writeFile(output,JSON.stringify(result,null,2));console.log(JSON.stringify(result))
