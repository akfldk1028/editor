import { expect, test } from 'bun:test'
import { createPublishedGroundReader, groundCellKey } from './published-ground'

test('published full cells serve both stages with one fetch and retain source geometry', async () => {
  const file = 'a'.repeat(64) + '.json', urls: string[] = []
  const source = { status: 'ok', gaps: [], record: { source: 'fixture', roads: { revision: 'local-roads-fixture' } }, features: { type: 'FeatureCollection', features: [
    { properties: { layer: 'carriageway', id: 1 }, geometry: { type: 'Polygon', coordinates: [] } },
    { properties: { layer: 'cover', id: 2 }, geometry: { type: 'Polygon', coordinates: [] } },
  ] } }
  const read = createPublishedGroundReader(async url => {
    urls.push(url)
    return Response.json(url.endsWith('catalog.json') ? { cells: {
      [groundCellKey(37.73, 127.1075, 320)!]: { file, sampledAt: new Date().toISOString() },
    } } : source)
  })
  const [roads, full] = await Promise.all([read(37.73,127.1075,320,'roads'),read(37.73,127.1075,320,'full')])
  expect(roads!.features!.features).toHaveLength(1)
  expect(full).toMatchObject(source)
  expect(full!.displaySnapshot!.expiresAt).toBeGreaterThan(Date.now())
  expect(urls).toHaveLength(2)
  expect(await read(37.73,127.1075,321,'full')).toBeUndefined()
})

test('expired snapshots and source gaps fall back to live data', async () => {
  const file = 'b'.repeat(64) + '.json', key = groundCellKey(37.73,127.1075,320)!
  let expired = true, files = 0
  const read = createPublishedGroundReader(async url => {
    if (url.endsWith('catalog.json')) return Response.json({ cells: { [key]: { file, sampledAt: expired ? '2020-01-01' : new Date().toISOString() } } })
    files++; return Response.json({ status: 'ok', gaps: ['missing_roads'], features: { type:'FeatureCollection', features: [] } })
  }, () => Date.now() + (expired ? 0 : 61000))
  expect(await read(37.73,127.1075,320,'full')).toBeUndefined()
  expect(files).toBe(0)
  expired = false
  expect(await read(37.73,127.1075,320,'full')).toBeUndefined()
  expect(files).toBe(1)
})


test('legacy ground snapshots cannot hide newly installed local roads', async () => {
  const file = 'd'.repeat(64) + '.json', key = groundCellKey(37.73,127.1075,320)!
  const read = createPublishedGroundReader(async url => Response.json(url.endsWith('catalog.json')
    ? { cells: { [key]: { file, sampledAt: new Date().toISOString() } } }
    : { status: 'ok', record: { roads: { source: 'old remote roads' } }, features: { type: 'FeatureCollection', features: [] } }))
  expect(await read(37.73,127.1075,320,'roads')).toBeUndefined()
  expect((await read(37.73,127.1075,320,'full'))?.status).toBe('ok')
})

test('installed road gaps preserve usable full geometry and the evidence warning', async () => {
  const file = 'e'.repeat(64) + '.json', key = groundCellKey(37.73,127.1075,320)!
  const receipt = { revision: 'a'.repeat(64), retrieved: new Date().toISOString(), complete_bbox: [126, 37, 127, 38] }
  const source = { status: 'ok', gaps: ['roads: No installed road centrelines in this viewport; this does not establish absence of roads'],
    record: { ground: receipt, cover: receipt },
    features: { type: 'FeatureCollection', features: [{ properties: { layer: 'cover' } }] } }
  const read = createPublishedGroundReader(async url => Response.json(url.endsWith('catalog.json')
    ? { cells: { [key]: { file, sampledAt: new Date().toISOString() } } } : source))
  expect(await read(37.73,127.1075,320,'full')).toMatchObject(source)
  expect(await read(37.73,127.1075,320,'roads')).toBeUndefined()
})
