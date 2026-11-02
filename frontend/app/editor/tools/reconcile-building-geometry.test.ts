import { expect, test } from 'bun:test'
import { reconcilePublishedGeometry } from './reconcile-building-geometry'
import type { Footprint } from '../features/world/lib/building-geometry'

const outer = [[127,37],[127.001,37],[127.001,37.001],[127,37.001],[127,37]]
const hole = [[127.0002,37.0002],[127.0008,37.0002],[127.0008,37.0008],[127.0002,37.0008],[127.0002,37.0002]]
const old: Footprint = { key:'16/1/2/49', pnu:'published', ring:outer, z:68.91234567890123, h:3.4, s:'m' }
const raw: Footprint = { ...old, z:12, h:100, pnu:'raw', s:'u', holes:[hole] }

test('geometry reconciliation preserves every published datum and only restores decoded holes', () => {
  const before = JSON.stringify(old), decodedBefore = JSON.stringify(raw)
  const [next] = reconcilePublishedGeometry([old],[raw])
  expect(next).toEqual({...old,holes:[hole]})
  expect(Object.is(next!.z,old.z)).toBe(true)
  expect(next!.ring[0]).toEqual(old.ring[0])
  expect(JSON.stringify(old)).toBe(before)
  expect(JSON.stringify(raw)).toBe(decodedBefore)
  next!.holes![0]![0]![0]=0
  expect(raw.holes![0]![0]![0]).toBe(127.0002)
})

test('multiple polygons sharing a feature key match by exact outer component, not array order', () => {
  const shifted = outer.map(([x,y])=>[x!+.01,y!])
  const second: Footprint = {...old,ring:shifted,z:102,h:24,s:'e'}
  const [firstNext,secondNext] = reconcilePublishedGeometry([old,second],[{...raw,ring:shifted,holes:undefined},raw])
  expect(firstNext!.holes).toEqual([hole])
  expect(secondNext).toEqual(second)
  expect(secondNext!.z).toBe(102)
})

test('missing or changed source component aborts instead of losing a published building or its ground', () => {
  expect(()=>reconcilePublishedGeometry([old],[])).toThrow('Missing decoded')
  expect(()=>reconcilePublishedGeometry([old],[{...raw,ring:[...outer].reverse()}])).toThrow('Missing decoded')
  expect(()=>reconcilePublishedGeometry([old],[{...raw,key:'other'}])).toThrow('Missing decoded')
})

test('ambiguous source topology and duplicate published components abort before producing candidates', () => {
  expect(()=>reconcilePublishedGeometry([old],[raw,{...raw,holes:undefined}])).toThrow('Ambiguous decoded')
  expect(()=>reconcilePublishedGeometry([old,{...old,z:70}],[raw])).toThrow('Duplicate published')
  expect(reconcilePublishedGeometry([old],[raw,structuredClone(raw)])).toHaveLength(1)
})

test('a previously retained hole cannot silently disappear from matching raw metadata', () => {
  expect(()=>reconcilePublishedGeometry([{...old,holes:[hole]}],[{...raw,holes:undefined}])).toThrow('Published holes')
})

test('source-only buildings never expand coverage during geometry-only migration', () => {
  const result=reconcilePublishedGeometry([old],[raw,{...raw,key:'new-key'}])
  expect(result).toHaveLength(1)
  expect(result[0]!.key).toBe(old.key)
})

test('invalid ground or topology blocks migration rather than emitting corrupt assets', () => {
  expect(()=>reconcilePublishedGeometry([{...old,z:undefined}],[raw])).toThrow('Invalid published')
  expect(()=>reconcilePublishedGeometry([old],[{...raw,holes:[[[NaN,37],[127,37],[127,38]]]}])).toThrow('Invalid decoded')
})
