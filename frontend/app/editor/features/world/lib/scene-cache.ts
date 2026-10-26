const PREFIX = 'world-source-v1-'
const writes = new Map<string, Promise<void>>()
const address = (key: string) => new URL(`/__world_source__/${encodeURIComponent(key)}`, location.origin).href

/** Only validated public map data belongs here, never project or conversation results. */
export async function readSceneCache<T>(bucket: string, key: string, ttl: number): Promise<T | undefined> {
  if (typeof caches === 'undefined' || typeof location === 'undefined') return undefined
  try {
    const cache = await caches.open(PREFIX + bucket)
    const response = await cache.match(address(key))
    if (!response) return undefined
    const at = Number(response.headers.get('x-world-saved-at'))
    if (!at || Date.now() - at >= ttl) return undefined
    return await response.json() as T
  } catch { return undefined }
}

export function writeSceneCache(bucket: string, key: string, value: unknown, limit: number): Promise<void> {
  if (typeof caches === 'undefined' || typeof location === 'undefined') return Promise.resolve()
  const task = (writes.get(bucket) ?? Promise.resolve()).then(async () => {
    const cache = await caches.open(PREFIX + bucket)
    await cache.put(address(key), Response.json(value, { headers: { 'x-world-saved-at': String(Date.now()) } }))
    const keys = await cache.keys()
    for (const old of keys.slice(0, Math.max(0, keys.length - limit))) await cache.delete(old)
  }).catch(() => {})
  writes.set(bucket, task)
  return task
}
