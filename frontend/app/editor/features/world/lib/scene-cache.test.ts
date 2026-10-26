import { expect, test } from 'bun:test'
import { readSceneCache, writeSceneCache } from './scene-cache'

test('persistent map cache survives readers, expires data and bounds storage', async () => {
  const originalCaches = Object.getOwnPropertyDescriptor(globalThis, 'caches')
  const originalLocation = Object.getOwnPropertyDescriptor(globalThis, 'location')
  const entries = new Map<string, Response>()
  const cache = { match: async (key: string) => entries.get(key)?.clone(),
    put: async (key: string, response: Response) => { entries.set(key, response) },
    keys: async () => [...entries.keys()], delete: async (key: string) => entries.delete(key) }
  Object.defineProperty(globalThis, 'location', { configurable: true, value: { origin: 'http://localhost' } })
  Object.defineProperty(globalThis, 'caches', { configurable: true, value: { open: async () => cache } })
  try {
    await writeSceneCache('test', 'a', [12, 13], 2)
    expect(await readSceneCache('test', 'a', 60_000)).toEqual([12, 13])
    expect(await readSceneCache('test', 'a', 0)).toBeUndefined()
    await writeSceneCache('test', 'b', [14], 2)
    await writeSceneCache('test', 'c', [15], 2)
    expect(entries.size).toBe(2)
    expect(await readSceneCache('test', 'a', 60_000)).toBeUndefined()
    expect(await readSceneCache('test', 'c', 60_000)).toEqual([15])
  } finally {
    if (originalCaches) Object.defineProperty(globalThis, 'caches', originalCaches)
    else Reflect.deleteProperty(globalThis, 'caches')
    if (originalLocation) Object.defineProperty(globalThis, 'location', originalLocation)
    else Reflect.deleteProperty(globalThis, 'location')
  }
})
