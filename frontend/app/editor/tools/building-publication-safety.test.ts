import { expect, test } from 'bun:test'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { preservesCoverage, createUnpublishedRegionFolder, readBuildingCatalog, regionAssetsComplete, readRegionFilter, retainPublishedKeys, groupBuildingRegions, mergePublishedFootprints } from './building-publication-safety'
import { enrichLayeredGround } from './building-ground-layers'
import type { Footprint } from '../features/world/lib/building-geometry'

test('coordinate groups retain every prior duplicate until that exact region is replaced', () => {
  const first = { z: 14, x: 1, y: 2, id: 'first' }, last = { ...first, id: 'last' }
  const other = { z: 14, x: 2, y: 2, id: 'other' }
  const groups = groupBuildingRegions([first, other, last])
  expect(groups.get('14/1/2')).toEqual([first, last])
  const replacement = { ...first, id: 'verified-new' }
  groups.set('14/1/2', [replacement])
  expect([...groups.values()].flat()).toEqual([replacement, other])
  for (const bad of [{ z: 16, x: 1, y: 2 }, { z: 14, x: -1, y: 2 }, { z: 14, x: 1, y: 16384 }, { z: 14, x: '1', y: 2 }]) {
    expect(() => groupBuildingRegions([bad as any])).toThrow('Invalid building region coordinates')
  }
})

test('all previous rows merge distinct components and keep the last identical component', () => {
  const a = { key: '16/4/8/1', ring: [[1, 1], [2, 1], [1, 2]], h: 10, s: 'm', z: 20 } as Footprint
  const b = { ...a, ring: [[3, 3], [4, 3], [3, 4]], z: 30 }
  const latest = { ...a, z: 25 }
  const holed = { ...a, holes: [[[1.1, 1.1], [1.2, 1.1], [1.1, 1.2]]] }
  const merged = mergePublishedFootprints([[a, b], [latest, holed]])
  expect(merged).toEqual([latest, b, holed])
  const absent = new Map<string, Footprint[]>([['16/4/8', []]])
  expect(retainPublishedKeys(absent, merged)).toBe(3)
  expect(absent.get('16/4/8')!.map(f => f.z)).toEqual([25, 30, 20])
  const authoritative = new Map([['16/4/8', [{ ...a, z: 99 }]]])
  expect(retainPublishedKeys(authoritative, merged)).toBe(0)
  expect(authoritative.get('16/4/8')).toHaveLength(1)
})

test('retained published geometry can receive new precision without freezing its entire region', async () => {
  const retained = {key:'16/1/1/old',ring:[[127,37],[127.001,37],[127,37.001]],h:10,s:'m',z:62.78} as Footprint
  const decoded = {...retained,key:'16/1/1/new',z:50} as Footprint
  const leaves = new Map([['16/1/1',[decoded]]])
  expect(retainPublishedKeys(leaves,[retained,decoded])).toBe(1)
  const features = leaves.get('16/1/1')!
  await enrichLayeredGround(features,{precise:{revision:'fine',sample:async points => ({heights:points.map(()=>83.405),source:{fileSignature:'fine'}} as any)}})
  expect(features.map(f=>f.z)).toEqual([83.405,83.405])
  expect(retained.z).toBe(62.78)
  expect(features[1]!.h).toBe(10)
  expect(features[1]!.s).toBe('m')
  expect(()=>retainPublishedKeys(new Map(),[retained])).toThrow('Cannot retain')
})

test('retaining an absent feature key preserves its separate published polygon components', () => {
  const first = {key:'16/1/1/part',ring:[[127,37],[127.001,37],[127,37.001]],h:10,s:'m',z:12} as Footprint
  const second = {...first,ring:[[127.01,37],[127.011,37],[127.01,37.001]]} as Footprint
  const leaves = new Map<string,Footprint[]>([['16/1/1',[]]])
  expect(retainPublishedKeys(leaves,[first,second])).toBe(2)
  expect(leaves.get('16/1/1')!.map(f=>f.ring)).toEqual([first.ring,second.ring])
})

test('ordinary resume cannot remove previously published leaf coverage', () => {
  expect(preservesCoverage({ coverage: ['a', 'b'] }, ['a'])).toBe(false)
  expect(preservesCoverage({ coverage: ['a', 'b'] }, ['a', 'b', 'c'])).toBe(true)
  expect(preservesCoverage({}, ['a'])).toBe(false)
})

test('repeated digest publication never rewrites its live folder', async () => {
  const root = await mkdtemp(join(tmpdir(), 'publication-'))
  try {
    const first = await createUnpublishedRegionFolder(root, 'tile-digest')
    await writeFile(join(first.folder, 'live'), 'published')
    const next = await createUnpublishedRegionFolder(root, 'tile-digest')
    expect(next.folder).not.toBe(first.folder)
    expect(await readFile(join(first.folder, 'live'), 'utf8')).toBe('published')
  } finally { await rm(root, { recursive: true }) }
})

test('unreadable existing catalog must not silently start an empty publication', async () => {
  const root = await mkdtemp(join(tmpdir(), 'catalog-')), path = join(root, 'catalog.json')
  try {
    expect((await readBuildingCatalog(path)).regions).toEqual([])
    await writeFile(path, '{truncated')
    await expect(readBuildingCatalog(path)).rejects.toThrow()
  } finally { await rm(root, { recursive: true }) }
})

test('resume verifies referenced child binaries, including their length headers', async () => {
  const root = await mkdtemp(join(tmpdir(), 'resume-')), folder = join(root, 'r')
  try {
    await mkdir(folder)
    await writeFile(join(folder, 'footprints.json'), '[]')
    await writeFile(join(folder, 'tileset.json'), JSON.stringify({ root: { content: { uri: 'root.b3dm' }, children: [{ content: { uri: 'child.b3dm' } }] } }))
    const bytes = Buffer.alloc(28); bytes.write('b3dm'); bytes.writeUInt32LE(1, 4); bytes.writeUInt32LE(28, 8)
    await writeFile(join(folder, 'root.b3dm'), bytes)
    expect(await regionAssetsComplete(root, { id: 'r' })).toBe(false)
    await writeFile(join(folder, 'child.b3dm'), bytes)
    expect(await regionAssetsComplete(root, { id: 'r' })).toBe(true)
    expect(await regionAssetsComplete(root, { id: 'r', groundPolicy: 'local-dem', groundRevision: 'expected' })).toBe(false)
    expect(await regionAssetsComplete(root, { id: 'r', groundPolicy: 'layered-ground-v1', groundRevision: 'expected' })).toBe(false)
    await writeFile(join(folder, 'ground-source.json'), JSON.stringify({ fileSignature: 'expected' }))
    expect(await regionAssetsComplete(root, { id: 'r', groundPolicy: 'local-dem', groundRevision: 'expected' })).toBe(true)
    expect(await regionAssetsComplete(root, { id: 'r', groundPolicy: 'layered-ground-v1', groundRevision: 'expected' })).toBe(true)
    expect(await regionAssetsComplete(root, { id: 'r', groundPolicy: 'layered-ground-v1', groundRevision: 'other' })).toBe(false)
    await writeFile(join(folder, 'footprints.json'), '{broken')
    expect(await regionAssetsComplete(root, { id: 'r' })).toBe(false)
    await writeFile(join(folder, 'footprints.json'), '[]')
    expect(await regionAssetsComplete(root, { id: 'r', counts: { measured: 1 } })).toBe(false)
    await writeFile(join(folder, 'child.b3dm'), bytes.subarray(0, 12))
    expect(await regionAssetsComplete(root, { id: 'r' })).toBe(false)
  } finally { await rm(root, { recursive: true }) }
})

test('a targeted publication list selects exact region keys and rejects malformed regions', async () => {
  const root = await mkdtemp(join(tmpdir(), 'region-filter-')), path = join(root, 'regions.json')
  try {
    await writeFile(path, JSON.stringify(['14/13958/6338', '14/13959/6337', '14/13958/6338']))
    const selected = await readRegionFilter(path)
    expect(selected ? [...selected] : undefined).toEqual(['14/13958/6338', '14/13959/6337'])
    await writeFile(path, JSON.stringify(['15/13958/6338']))
    await expect(readRegionFilter(path)).rejects.toThrow('Invalid region filter')
  } finally { await rm(root, { recursive: true }) }
})
