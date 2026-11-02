import { readFile, writeFile } from 'node:fs/promises'
import { PMTiles } from 'pmtiles'
import Pbf from 'pbf'
import { VectorTile } from '@mapbox/vector-tile'
import { openLocalArchive } from './local-building-archive'
import { decodeBuildings } from '../features/world/lib/building-geometry'

const report = JSON.parse(await readFile('D:/Data/NGII_DEM/national-buildings-pass-3.json', 'utf8'))
const source = await openLocalArchive('D:/Data/25_ACE/agents/SceneAgent/runs/tiles/20261009-2f30a80f/buildings.pmtiles')
const archive = new PMTiles(source)
const points: { region: string; key: string; pnu: string; point: number[] }[] = []
try {
  for (const [index, region] of report.missingRegions.entries()) {
    const [, x, y] = region.key.split('/').map(Number)
    for (let dx = 0; dx < 4; dx++) for (let dy = 0; dy < 4; dy++) {
      const tile = { z: 16, x: x * 4 + dx, y: y * 4 + dy, key: `16/${x * 4 + dx}/${y * 4 + dy}` }
      const data = await archive.getZxy(tile.z, tile.x, tile.y)
      if (!data) continue
      const features = await decodeBuildings(new Uint8Array(data.data), tile, Pbf, VectorTile)
      for (const feature of features) if (!Number.isFinite(feature.z)) {
        points.push({ region: region.key, key: feature.key, pnu: feature.pnu, point: feature.ring[0]! })
      }
    }
    if (index % 50 === 0) console.log(JSON.stringify({ regions: index + 1, points: points.length }))
  }
  await writeFile('D:/Data/NGII_DEM/national-gap-candidate-points.json', JSON.stringify(points))
  console.log(JSON.stringify({ complete: true, regions: report.missingRegions.length, points: points.length }))
} finally { await source.close() }
