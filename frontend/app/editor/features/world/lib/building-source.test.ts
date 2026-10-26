import type { MapRelease } from './map-release'
import { expect, test } from 'bun:test'
import { loadBuildingSource } from './building-source'

test('local prepared archive is served through the backend without an agent port', async () => {
  const get = async () => Response.json({source: 'http://127.0.0.1:8310/scene/tiles/buildings/20261009-2f30a80f/buildings.pmtiles'})
  expect(await loadBuildingSource(get)).toEqual({href: '/api/v1/land/building-tiles/20261009-2f30a80f/buildings.pmtiles'})
})

test('published catalog starts the versioned archive without waiting for the live service', async () => {
  const calls: string[] = []
  const get = async (url: string) => {
    calls.push(url)
    if (url.endsWith('catalog.json')) return Response.json({ version: 1, source: 'https://tiles.example/v3/buildings.pmtiles', regions: [] })
    throw new Error('live service must not delay the published snapshot')
  }
  expect(await loadBuildingSource(get)).toEqual({ href: 'https://tiles.example/v3/buildings.pmtiles' })
  expect(calls).toHaveLength(2)
})

test('absent or invalid published source falls back to the live manifest', async () => {
  for (const response of [new Response('', { status: 404 }), Response.json({ source: 'javascript:invalid' })]) {
    const get = async (url: string) => url.endsWith('catalog.json') ? response : Response.json({ href: '/tiles/v4/buildings.pmtiles' })
    expect(await loadBuildingSource(get)).toEqual({ href: '/tiles/v4/buildings.pmtiles' })
  }
})

test('a live refusal remains an error instead of an invented archive', async () => {
  const get = async (url: string) => url.endsWith('catalog.json') ? new Response('', { status: 404 })
    : Response.json({ detail: 'archive unavailable' }, { status: 503 })
  await expect(loadBuildingSource(get)).rejects.toThrow('archive unavailable')
})

test('national release refuses vector source without any fallback fetch', async () => {
  let calls = 0
  await expect(loadBuildingSource(async () => { calls++; return Response.json({}) }, true,
    async () => ({ schema: 'ace-map-release-v2' }) as MapRelease)).rejects.toThrow('no legacy')
  expect(calls).toBe(0)
})
