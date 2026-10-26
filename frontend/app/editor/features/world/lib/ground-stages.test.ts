import { expect, test } from 'bun:test'
import { GroundStages, nextGroundRequest } from './ground-stages'

const road = (id: string, width: number) => ({ properties: { id, layer: 'carriageway', width_m: width } })
test('motion defers full cells, keeps previews available and resumes full detail after settling', () => {
  const queue = [{ cellKey: 'a', detail: 'full' as const }, { cellKey: 'b', detail: 'roads' as const }]
  expect(nextGroundRequest(queue, [], new Set(['a']), false)).toBe(1)
  expect(nextGroundRequest(queue.slice(0, 1), [], new Set(['a']), false)).toBe(-1)
  expect(nextGroundRequest(queue.slice(0, 1), [], new Set(['a']), true)).toBe(0)
  expect(nextGroundRequest(queue, [], new Set(['a']), false, false)).toBe(-1)
})
function fixture() {
  const drawn = new Map<string, any>()
  const stages = new GroundStages((_previous, next, id) => { if (next) drawn.set(id, next); else drawn.delete(id) })
  const apply = (cell: string, detail: 'roads' | 'full', features: any[]) => {
    const batch = stages.begin(cell, detail)!
    for (const f of features) batch.apply(f)
    batch.finish()
  }
  return { stages, drawn, apply }
}

test('full roads replace preview geometry and retire missing roads, late preview cannot regress', () => {
  const { stages, drawn, apply } = fixture()
  apply('a', 'roads', [road('shared', 4), road('retired', 6)])
  apply('a', 'full', [road('shared', 8)])
  expect([...drawn.values()].map(f => f.properties.width_m)).toEqual([8])
  expect(stages.begin('a', 'roads')).toBeNull()
})

test('overlapping cells retain ownership and complete geometry wins over a later preview', () => {
  const { drawn, apply } = fixture()
  apply('a', 'roads', [road('shared', 4)])
  apply('b', 'roads', [road('shared', 4)])
  apply('a', 'full', [])
  expect(drawn.size).toBe(1)
  apply('b', 'full', [road('shared', 8)])
  apply('c', 'roads', [road('shared', 5)])
  expect([...drawn.values()][0].properties.width_m).toBe(8)
  apply('b', 'full', [])
  expect([...drawn.values()][0].properties.width_m).toBe(5)
  apply('c', 'full', [])
  expect(drawn.size).toBe(0)
})

test('interrupted incremental replacement keeps old coverage and superseded batches cannot mutate', () => {
  const { stages, drawn, apply } = fixture()
  apply('a', 'roads', [road('old', 4)])
  const interrupted = stages.begin('a', 'full')!
  interrupted.apply(road('new', 8))
  expect(drawn.size).toBe(2)
  const replacement = stages.begin('a', 'full')!
  expect(interrupted.current()).toBe(false)
  interrupted.apply(road('stale', 10))
  interrupted.finish()
  replacement.apply(road('new', 9))
  replacement.finish()
  expect([...drawn.values()].map(f => f.properties.id)).toEqual(['new'])
})

test('preview requests retain capacity; full requests use idle slots after previews are dispatched', () => {
  const queue = [{ cellKey: 'a', detail: 'full' as const }, { cellKey: 'b', detail: 'full' as const }]
  expect(nextGroundRequest(queue, [{ detail: 'full' }], new Set(['a', 'b']))).toBe(0)
  expect(nextGroundRequest([...queue, { cellKey: 'c', detail: 'roads' }], [{ detail: 'full' }], new Set(['a']))).toBe(2)
  expect(nextGroundRequest([...queue, { cellKey: 'c', detail: 'roads' }], [{ detail: 'full' }], new Set())).toBe(2)
  expect(nextGroundRequest(queue, [], new Set(['b']))).toBe(1)
  expect(nextGroundRequest(queue, [], new Set())).toBe(-1)
})

test('retiring a cell preserves shared roads and invalidates interrupted writes', () => {
  const { stages, drawn, apply } = fixture()
  apply('a', 'full', [road('shared', 8), road('only-a', 4)])
  apply('b', 'roads', [road('shared', 5)])
  const interrupted = stages.begin('a', 'full')!
  stages.retire('a')
  interrupted.apply(road('late', 10))
  expect(interrupted.current()).toBe(false)
  expect([...drawn.values()].map(f => f.properties.width_m)).toEqual([5])
  stages.retire('b')
  expect(drawn.size).toBe(0)
  expect(stages.begin('a', 'roads')).not.toBeNull()
})

