import { expect, test } from 'bun:test'
import { demTerrain } from './terrain'
import { createTerrainHeightContract } from './terrain-height-contract'

function provider(contract: ReturnType<typeof createTerrainHeightContract>) {
  class Provider {
    tilingScheme = { tileXYToRectangle: () => ({ west:127,east:127.01,south:37,north:37.01 }) }
    constructor(public options: any) {}
  }
  return demTerrain({ CustomHeightmapTerrainProvider: Provider, Math: { toDegrees: (n: number) => n } },
    () => 999, () => null, () => {}, undefined, async () => null, () => {}, async () => { throw Error('legacy archive must not run') }, contract)
}
const policy = { archiveSha256: 'a'.repeat(64), minLevel: 11, maxLevel: 17 }

test('provider and baker use identical resolved grid including documented ellipsoid zero', async () => {
  const contract = createTerrainHeightContract(async () => null, policy), p = provider(contract)
  const lon = 127.11, lat = 37.73, width = 180 / 2 ** 17
  const x = Math.floor((lon+180)/width), y = Math.floor((90-lat)/width)
  try {
    const display = await p.options.callback(x,y,17)
    const baked = await contract.samplePosition(lon,lat)
    expect(display.every((height: number) => height === 0)).toBe(true)
    expect(await p.sampleHeight(lon,lat)).toBe(baked.height)
    expect(await p.sampleHeightDetails(lon,lat)).toEqual(baked)
    expect(baked.ellipsoidZero).toBe(true); expect(baked.sourceLevels).toEqual([-1])
  } finally { p.dispose() }
})

test('provider never turns a transport failure into camera-dependent fallback ground', async () => {
  let fail = true
  const contract = createTerrainHeightContract(async () => { if (fail) throw Error('HTTP 503'); return new Float32Array(1089).fill(45) }, policy)
  const p = provider(contract)
  try {
    await expect(p.options.callback(1,1,17)).rejects.toThrow('HTTP 503')
    fail = false
    expect((await p.options.callback(1,1,17))[0]).toBe(45)
    expect(await p.sampleHeight(127.11,37.73)).toBe(45)
  } finally { p.dispose() }
})
