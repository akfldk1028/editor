import { expect, test } from 'bun:test'
import { mapAssetUrl } from './map-asset-url'

test('local assets retain the application base path and remote URLs stay independent', () => {
  const before = process.env.NEXT_PUBLIC_BASE_PATH
  process.env.NEXT_PUBLIC_BASE_PATH = '/editor'
  try { expect(mapAssetUrl('terrain', 'archive.json')).toBe('/editor/api/map-data/world-terrain/archive.json') }
  finally { if (before === undefined) delete process.env.NEXT_PUBLIC_BASE_PATH; else process.env.NEXT_PUBLIC_BASE_PATH = before }
})

test('versioned remote roots resolve existing catalog paths without local prefixes', () => {
  const name = 'NEXT_PUBLIC_WORLD_BUILDINGS_BASE_URL', before = process.env[name]
  process.env[name] = 'https://assets.example/world-buildings/v1/'
  try {
    expect(mapAssetUrl('world-buildings', '/world-buildings/region/tileset.json')).toBe('https://assets.example/world-buildings/v1/region/tileset.json')
    expect(mapAssetUrl('world-buildings', 'https://assets.example/kept.json')).toBe('https://assets.example/kept.json')
    expect(() => mapAssetUrl('world-buildings', '../secret')).toThrow()
  } finally { if (before === undefined) delete process.env[name]; else process.env[name] = before }
})
