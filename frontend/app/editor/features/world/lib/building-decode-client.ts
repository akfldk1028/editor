import type { BuildingTile, Footprint } from './building-geometry'

type Job = {
  id: number; data: Uint8Array | ArrayBuffer; tile: BuildingTile
  resolve(features: Footprint[]): void; reject(error: Error): void
  cleanup(): void
}

class DecodeWorker {
  private worker: Worker | null = null
  private queue: Job[] = []
  private active: Job | null = null
  private sequence = 0
  private disposed = false
  private timeout: ReturnType<typeof setTimeout> | null = null

  constructor(private createWorker = () => new Worker(new URL('./building-decode.worker.ts', import.meta.url), { type: 'module', name: 'building-decode' })) {}

  decode(data: Uint8Array | ArrayBuffer, tile: BuildingTile, signal?: AbortSignal): Promise<Footprint[]> {
    if (this.disposed || signal?.aborted) return Promise.reject(new DOMException('Building decode cancelled', 'AbortError'))
    return new Promise((resolve, reject) => {
      const job: Job = { id: ++this.sequence, data, tile, resolve, reject, cleanup: () => signal?.removeEventListener('abort', abort) }
      const abort = () => {
        if (this.active === job) this.worker?.postMessage({ cancel: job.id })
        else this.queue = this.queue.filter(item => item !== job)
        job.cleanup()
        reject(new DOMException('Building decode cancelled', 'AbortError'))
        this.pump()
      }
      signal?.addEventListener('abort', abort, { once: true })
      this.queue.push(job)
      this.pump()
    })
  }

  private pump() {
    if (this.disposed || this.active || !this.queue.length) return
    const job = this.queue.shift()!
    this.active = job
    try {
      if (!this.worker) {
        this.worker = this.createWorker()
        this.worker.onmessage = event => {
          const current = this.active
          if (!current || event.data.id !== current.id) return
          this.active = null
          if (this.timeout !== null) clearTimeout(this.timeout)
          this.timeout = null
          current.cleanup()
          if (event.data.error) current.reject(new Error(`Building decode worker: ${event.data.error}`))
          else current.resolve(event.data.features)
          this.pump()
        }
        this.worker.onerror = event => { event.preventDefault(); this.fail(event.message || 'script failed') }
        this.worker.onmessageerror = () => this.fail('invalid worker response')
      }
      // PMTiles may cache its response buffer; transferring that original would corrupt the cache.
      const data = job.data instanceof Uint8Array ? job.data.slice().buffer : job.data.slice(0)
      this.worker.postMessage({ id: job.id, data, tile: job.tile }, [data])
      this.timeout = setTimeout(() => this.fail('timed out after 30 seconds'), 30_000)
    } catch (error) { this.fail(error instanceof Error ? error.message : String(error)) }
  }

  private stopWorker() {
    if (this.timeout !== null) clearTimeout(this.timeout)
    this.timeout = null
    this.worker?.terminate()
    this.worker = null
  }

  private fail(reason: string) {
    const jobs = [...(this.active ? [this.active] : []), ...this.queue]
    this.active = null; this.queue = []
    this.stopWorker()
    for (const job of jobs) { job.cleanup(); job.reject(new Error(`Building decode worker: ${reason}`)) }
  }

  dispose() {
    this.disposed = true
    const jobs = [...(this.active ? [this.active] : []), ...this.queue]
    this.active = null; this.queue = []
    this.stopWorker()
    for (const job of jobs) { job.cleanup(); job.reject(new DOMException('Building decode cancelled', 'AbortError')) }
  }
}

export class BuildingDecoder {
  private lanes: { decoder: DecodeWorker; pending: number }[]
  private disposed = false

  constructor(createWorker?: () => Worker, concurrency = typeof navigator === 'undefined' ? 1
    : Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 2))) {
    this.lanes = Array.from({ length: Math.max(1, Math.min(4, Math.floor(concurrency) || 1)) },
      () => ({ decoder: new DecodeWorker(createWorker), pending: 0 }))
  }

  decode(data: Uint8Array | ArrayBuffer, tile: BuildingTile, signal?: AbortSignal): Promise<Footprint[]> {
    if (this.disposed || signal?.aborted) return Promise.reject(new DOMException('Building decode cancelled', 'AbortError'))
    const lane = this.lanes.reduce((best, next) => next.pending < best.pending ? next : best)
    lane.pending++
    return lane.decoder.decode(data, tile, signal).finally(() => { lane.pending-- })
  }

  dispose() {
    this.disposed = true
    for (const lane of this.lanes) lane.decoder.dispose()
  }
}
