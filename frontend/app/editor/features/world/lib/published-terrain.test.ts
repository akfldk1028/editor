import { expect, test } from 'bun:test'
import { createPublishedTerrainReader } from './published-terrain'

test('published measured grid loads directly and shares its catalog across requests', async () => {
  const calls: string[] = []
  const read = createPublishedTerrainReader(async url => {
    calls.push(url)
    return Response.json(url.endsWith('catalog.json') ? { version: 'snapshot-1', tiles: ['17/1/2', '17/2/2'] }
      : { dataset: { vrt_sha256: 'current' }, size: 33, heights: Array(1089).fill(93.25) })
  })
  const grids = await Promise.all([read('17/1/2', 'current'), read('17/2/2', 'current')])
  expect(grids.map(g => g?.[0])).toEqual([93.25, 93.25])
  expect(calls.filter(url => url.endsWith('catalog.json'))).toHaveLength(1)
  expect(calls).toContain('/api/map-data/world-terrain/snapshot-1/17-1-2.json')
  expect(await read('17/3/2', 'current')).toBeUndefined()
  expect(calls).toHaveLength(4)
})

test('missing or corrupt static terrain permits the measured API fallback', async () => {
  const absent = createPublishedTerrainReader(async () => new Response('', { status: 404 }))
  expect(await absent('17/1/2', 'current')).toBeUndefined()
  const corrupt = createPublishedTerrainReader(async url => Response.json(url.endsWith('catalog.json')
    ? { version: 'snapshot-1', tiles: ['17/1/2'] } : { dataset: { vrt_sha256: 'current' }, size: 33, heights: Array(1089).fill(null) }))
  expect(await corrupt('17/1/2', 'current')).toBeUndefined()
})

test('a running map discovers newly published regions without reloading the viewer', async () => {
  let now = 0, available = false, catalogs = 0
  const read = createPublishedTerrainReader(async url => {
    if (url.endsWith('catalog.json')) {
      catalogs++
      return Response.json({ version: 'snapshot-1', tiles: available ? ['17/3/2'] : [] })
    }
    return Response.json({ dataset: { vrt_sha256: 'current' }, size: 33, heights: Array(1089).fill(42) })
  }, () => now)
  expect(await read('17/3/2', 'current')).toBeUndefined()
  available = true
  now = 60001
  expect((await read('17/3/2', 'current'))?.[0]).toBe(42)
  expect(catalogs).toBe(2)
})

test('regional publication keeps previous coverage until replacement tiles exist', async () => {
  const calls: string[] = []
  const read = createPublishedTerrainReader(async url => {
    calls.push(url)
    return Response.json(url.endsWith('catalog.json')
      ? { version: 'new', tiles: ['17/1/2'], fallback: { version: 'old', tiles: ['17/1/2', '17/2/2'] } }
      : { dataset: { vrt_sha256: 'current' }, size: 33, heights: Array(1089).fill(22) })
  })
  await read('17/1/2', 'current')
  await read('17/2/2', 'current')
  expect(calls).toContain('/api/map-data/world-terrain/new/17-1-2.json')
  expect(calls).toContain('/api/map-data/world-terrain/old/17-2-2.json')
})


test('stale and unproven baked tiles cannot override the live DEM', async () => {
  for (const dataset of [undefined, { vrt_sha256: 'old' }]) {
    const read = createPublishedTerrainReader(async url => Response.json(url.endsWith('catalog.json')
      ? { version: 'snapshot', tiles: ['17/1/2'] }
      : { size: 33, heights: Array(1089).fill(22), dataset }))
    expect(await read('17/1/2', 'current')).toBeUndefined()
  }
})


test('an obsolete snapshot manifest skips its tile downloads', async () => {
  const calls: string[] = []
  const read = createPublishedTerrainReader(async url => {
    calls.push(url)
    return Response.json(url.endsWith('catalog.json') ? { version: 'old', tiles: ['17/1/2', '17/2/2'] }
      : url.endsWith('local-source.json') ? { vrt_sha256: 'old-vrt' }
      : { size: 33, heights: Array(1089).fill(22), dataset: { vrt_sha256: 'old-vrt' } })
  })
  expect(await read('17/1/2', 'current')).toBeUndefined()
  expect(await read('17/2/2', 'current')).toBeUndefined()
  expect(calls).toEqual(['/api/map-data/world-terrain/catalog.json', '/api/map-data/world-terrain/old/local-source.json'])
})

test('explicit unexpired display snapshot survives unrelated live coverage expansion', async () => {
  const digest = 'a'.repeat(64), notices: string[] = []
  const policy = { vrt_sha256: digest, sampler: 'SiteContext terrain.dem._heights_at', expiresAt: 2000 }
  const read = createPublishedTerrainReader(async url => Response.json(url.endsWith('catalog.json')
    ? { version: 'prepared', tiles: ['17/1/2'], displaySnapshot: policy }
    : url.endsWith('local-source.json') ? { vrt_sha256: digest, sampler: policy.sampler }
    : { size: 33, heights: Array(1089).fill(22), dataset: { vrt_sha256: digest, sampler: policy.sampler } }), () => 1000, version => notices.push(version))
  expect((await read('17/1/2', 'new-national-vrt'))?.[0]).toBe(22)
  expect(notices).toEqual(['prepared'])
  expect((await read('17/1/2', ''))?.[0]).toBe(22)
})

test('expired display snapshots and sampler mismatches cannot override live data', async () => {
  for (const expiresAt of [500, 2000]) {
    const digest = 'b'.repeat(64)
    const read = createPublishedTerrainReader(async url => Response.json(url.endsWith('catalog.json')
      ? { version: 'prepared', tiles: ['17/1/2'], displaySnapshot: { vrt_sha256: digest, sampler: 'bilinear', expiresAt } }
      : url.endsWith('local-source.json') ? { vrt_sha256: digest, sampler: 'bilinear' }
      : { size: 33, heights: Array(1089).fill(22), dataset: { vrt_sha256: digest, sampler: 'nearest' } }), () => 1000)
    expect(await read('17/1/2', 'live')).toBeUndefined()
  }
})
