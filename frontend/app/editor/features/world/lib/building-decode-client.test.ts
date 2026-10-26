import { expect, test } from 'bun:test'
import { BuildingDecoder } from './building-decode-client'

const tile = { z: 16, x: 0, y: 0, key: '16/0/0' }
function transport() {
  const sent: any[] = []
  const worker = { onmessage: null as any, onerror: null as any, onmessageerror: null as any, terminated: false,
    postMessage: (message: any, transfers: Transferable[]) => { sent.push(structuredClone(message, { transfer: transfers })) },
    terminate() { this.terminated = true },
  }
  return { worker, sent, decoder: new BuildingDecoder(() => worker as unknown as Worker, 1) }
}

test('worker transport transfers a copy, serializes requests and returns decoded footprints', async () => {
  const { worker, sent, decoder } = transport()
  const source = new Uint8Array([1, 2, 3])
  const first = decoder.decode(source, tile)
  const second = decoder.decode(source, tile)
  expect(source.byteLength).toBe(3)
  expect(sent).toHaveLength(1)
  expect([...new Uint8Array(sent[0].data)]).toEqual([1, 2, 3])
  const features = [{ key: 'a', ring: [[127, 37]], h: 10, z: 93, s: 'm', pnu: '' }]
  worker.onmessage({ data: { id: sent[0].id, features } })
  expect(await first).toEqual(features)
  expect(sent).toHaveLength(2)
  worker.onmessage({ data: { id: sent[1].id, features: [] } })
  expect(await second).toEqual([])
  decoder.dispose()
})

test('aborting a queued decode never sends it, and disposal rejects active work', async () => {
  const { worker, sent, decoder } = transport()
  const active = decoder.decode(new Uint8Array([1]), tile).catch(e => e)
  const controller = new AbortController()
  const queued = decoder.decode(new Uint8Array([2]), tile, controller.signal).catch(e => e)
  controller.abort()
  expect((await queued).name).toBe('AbortError')
  expect(sent).toHaveLength(1)
  decoder.dispose()
  expect((await active).name).toBe('AbortError')
  expect(worker.terminated).toBe(true)
})

test('worker startup failure rejects all pending work with a named error', async () => {
  const { worker, decoder } = transport()
  const first = decoder.decode(new Uint8Array(), tile).catch(e => e)
  const second = decoder.decode(new Uint8Array(), tile).catch(e => e)
  worker.onerror({ message: 'worker script blocked', preventDefault() {} })
  expect((await first).message).toContain('Building decode worker')
  expect((await second).message).toContain('worker script blocked')
  decoder.dispose()
})

test('aborting active work keeps the warm worker and starts the next tile after cancellation acknowledgement', async () => {
  const workers: ReturnType<typeof transport>[] = []
  const decoder = new BuildingDecoder(() => {
    const next = transport()
    workers.push(next)
    return next.worker as unknown as Worker
  }, 1)
  const controller = new AbortController()
  const aborted = decoder.decode(new Uint8Array([1]), tile, controller.signal).catch(e => e)
  const next = decoder.decode(new Uint8Array([2]), tile)
  controller.abort()
  expect((await aborted).name).toBe('AbortError')
  expect(workers[0]!.worker.terminated).toBe(false)
  expect(workers).toHaveLength(1)
  const worker = workers[0]!
  expect(worker.sent[1]).toEqual({ cancel: worker.sent[0].id })
  worker.worker.onmessage({ data: { id: worker.sent[0].id, error: 'cancelled' } })
  worker.worker.onmessage({ data: { id: worker.sent[2].id, features: [] } })
  expect(await next).toEqual([])
  decoder.dispose()
})

test('a bounded worker pool decodes two tiles concurrently and isolates cancellation', async () => {
  const workers: ReturnType<typeof transport>[] = []
  const decoder = new BuildingDecoder(() => {
    const next = transport(); workers.push(next)
    return next.worker as unknown as Worker
  }, 2)
  const abort = new AbortController()
  const first = decoder.decode(new Uint8Array([1]), tile, abort.signal).catch(e => e)
  const second = decoder.decode(new Uint8Array([2]), tile)
  const third = decoder.decode(new Uint8Array([3]), tile)
  expect(workers).toHaveLength(2)
  expect(workers.map(w => w.sent.length)).toEqual([1, 1])
  abort.abort()
  expect((await first).name).toBe('AbortError')
  expect(workers[1]!.worker.terminated).toBe(false)
  expect(workers).toHaveLength(2)
  workers[1]!.worker.onmessage({ data: { id: workers[1]!.sent[0].id, features: [] } })
  workers[0]!.worker.onmessage({ data: { id: workers[0]!.sent[0].id, error: 'cancelled' } })
  workers[0]!.worker.onmessage({ data: { id: workers[0]!.sent[2].id, features: [] } })
  expect(await second).toEqual([])
  expect(await third).toEqual([])
  decoder.dispose()
  expect(workers.every(w => w.worker.terminated)).toBe(true)
})
