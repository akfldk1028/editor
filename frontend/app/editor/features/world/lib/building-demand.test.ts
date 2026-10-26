import { expect, test } from 'bun:test'
import { BuildingTiles } from './building-tiles'

test('hidden fine replacements build before retiring the coarse parent; cached offscreen entries do not', () => {
  const tiles: any = Object.create(BuildingTiles.prototype)
  const fine = { tile: { key: 'fine' }, features: [], needsBuild: false }
  const cached = { tile: { key: 'cached' }, features: [], needsBuild: false }
  let samples = 0, scheduled = 0
  Object.assign(tiles, { work: new Map(), datumRebuilds: new Map(), desired: new Set(['fine']), previous: new Set(['coarse']),
    supplement: {}, inView: () => false, resolveDatums: () => { samples++ },
    buildGeometry: function* () {}, scheduleWork: () => { scheduled++ } })
  tiles.build(fine)
  expect(tiles.work.has(fine)).toBe(true)
  expect(scheduled).toBe(1)
  tiles.build(cached)
  expect(tiles.work.has(cached)).toBe(false)
  expect(cached.needsBuild).toBe(true)
  expect(samples).toBe(1)
})

test('baked-covered footprints without vector heights do not hold replacement readiness open', () => {
  const tiles: any = Object.create(BuildingTiles.prototype)
  const entry = { tile: { key: 'fine' }, primitives: [], features: [{ ring: [[127, 37]] }], needsBuild: true }
  Object.assign(tiles, { base: 'terrain', baked: { contains: () => true }, datums: new WeakMap(),
    supplement: {}, hideOnSite: false, viewer: { scene: { requestRender() {} } } })
  for (const _ of tiles.buildGeometry(entry, entry.features, false)) {}
  expect(entry.needsBuild).toBe(false)
})
