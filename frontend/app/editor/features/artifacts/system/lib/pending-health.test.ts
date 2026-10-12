import { expect, test } from 'bun:test'

import { clearPendingHealth, readPendingHealth, savePendingHealth } from './pending-health'

const memory = () => {
  const data = new Map<string, string>()
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v) }, removeItem: (k: string) => { data.delete(k) } }
}

test('an uncertain submission survives a new client instance with its original key and versions', () => {
  const storage = memory()
  const attempt = { key: 'stable-key', context: { scene_revision: 2, source_versions: { site: 3 } } }
  savePendingHealth(storage, 'p1', attempt)
  expect(readPendingHealth(storage, 'p1')).toEqual(attempt)
  expect(readPendingHealth(storage, 'p2')).toBeNull()
  clearPendingHealth(storage, 'p1')
  expect(readPendingHealth(storage, 'p1')).toBeNull()
})

test('a corrupt saved attempt is refused rather than replayed', () => {
  const storage = memory()
  storage.setItem(`editor:pending-health:v1:${process.env.NEXT_PUBLIC_BASE_PATH || ''}:p1`, '{"key":"bad key","context":{}}')
  expect(() => readPendingHealth(storage, 'p1')).toThrow('복원하지 못했어요')
})
