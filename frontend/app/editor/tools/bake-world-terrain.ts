import { mkdir, readFile, writeFile, rename } from 'node:fs/promises'
import { resolve, join } from 'node:path'

// Geographic (Cesium) tiles, not the Web Mercator grid used by building PMTiles.
// bun tools/bake-world-terrain.ts west south east north minLevel maxLevel version
const [west, south, east, north, minLevel = 11, maxLevel = 17] = process.argv.slice(2, 8).map(Number)
const version = process.argv[8]
if (![west, south, east, north, minLevel, maxLevel].every(Number.isFinite)
  || west! < 124 || east! > 133 || south! < 33 || north! > 39 || west! >= east! || south! >= north!
  || !Number.isInteger(minLevel) || !Number.isInteger(maxLevel) || minLevel < 11 || maxLevel > 17 || minLevel > maxLevel
  || !version || !/^[a-zA-Z0-9_-]+$/.test(version)) throw new Error('Expected Korea bounds, levels 11..17, immutable snapshot version')
const output = resolve(process.env.WORLD_TERRAIN_OUTPUT || 'public/world-terrain')
const folder = join(output, version), origin = process.env.WORLD_API_ORIGIN || 'http://127.0.0.1:3003'
await mkdir(folder, { recursive: true })
const old = await readFile(join(output, 'catalog.json'), 'utf8').then(JSON.parse).catch(() => null)
if (old && old.version !== version) throw new Error('Use a separate output directory for a new terrain snapshot')
const tiles = new Set<string>(old?.tiles || []), failed: { key: string; error: string }[] = []
const valid = (v: any) => v?.size === 33 && Array.isArray(v.heights) && v.heights.length === 1089
  && v.heights.every((h: unknown) => typeof h === 'number' && Number.isFinite(h) && h !== -9999 && Math.abs(h) <= 12000)
const publish = async () => {
  await writeFile(join(output, 'catalog.next.json'), JSON.stringify({ version, grid: 'Cesium.GeographicTilingScheme', size: 33,
    source: 'SiteContext measured terrain-heights; missing samples excluded', tiles: [...tiles] }))
  await rename(join(output, 'catalog.next.json'), join(output, 'catalog.json'))
}
for (let level = minLevel; level <= maxLevel; level++) {
  const width = 180 / 2 ** level
  const minX = Math.floor((west! + 180) / width), maxX = Math.ceil((east! + 180) / width) - 1
  const minY = Math.floor((90 - north!) / width), maxY = Math.ceil((90 - south!) / width) - 1
  for (let x = minX; x <= maxX; x++) for (let y = minY; y <= maxY; y++) {
    const key = `${level}/${x}/${y}`, file = join(folder, `${level}-${x}-${y}.json`)
    const saved = await readFile(file, 'utf8').then(JSON.parse).catch(() => null)
    if (valid(saved)) { tiles.add(key); continue }
    const query = new URLSearchParams({ west: String(x * width - 180), east: String((x + 1) * width - 180),
      north: String(90 - y * width), south: String(90 - (y + 1) * width), size: '33' })
    try {
      const response = await fetch(`${origin}/api/v1/land/terrain-heights?${query}`, { signal: AbortSignal.timeout(30000) })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const body = await response.json(), tile = { size: 33, heights: body.heights, sampledAt: new Date().toISOString() }
      if (!valid(tile)) throw new Error('No complete measured grid')
      await writeFile(`${file}.next`, JSON.stringify(tile)); await rename(`${file}.next`, file)
      tiles.add(key); await publish()
      console.log(`Published ${key}`)
    } catch (error) { failed.push({ key, error: String(error) }); console.error(`Missing ${key}: ${error}`) }
  }
}
await publish()
await writeFile(join(output, 'last-bake-report.json'), JSON.stringify({ bounds: [west, south, east, north], minLevel, maxLevel, failed }, null, 2))
console.log(`Published ${tiles.size} measured grids; ${failed.length} missing`)
if (failed.length) process.exitCode = 2
