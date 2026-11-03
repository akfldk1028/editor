import { expect, test } from 'bun:test'
import { prefetchSavedSite } from './saved-site-prefetch'

test('fetch starts before engine readiness; reading after readiness reuses the one request', async () => {
  const events: string[] = []
  const pending = prefetchSavedSite(async () => { events.push('fetch'); return 'saved' })
  await Promise.resolve()
  expect(events).toEqual(['fetch'])
  events.push('engine ready')
  const saved = await pending.read()
  events.push(`restore ${saved}`)
  expect(events).toEqual(['fetch', 'engine ready', 'restore saved'])
  expect(await pending.read()).toBe('saved')
})

test('failed engine can abandon and cancel the prefetch without an unhandled rejection', async () => {
  let signal!: AbortSignal
  const pending = prefetchSavedSite(async received => { signal = received; throw Error('offline') })
  pending.abort()
  await Promise.resolve()
  expect(signal.aborted).toBe(true)
  await expect(pending.read()).rejects.toThrow('offline')
})
