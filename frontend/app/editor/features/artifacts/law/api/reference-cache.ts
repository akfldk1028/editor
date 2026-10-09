import { loadReference, type ReferenceSite, type ReferenceText } from './reference'
import type { ReviewRef } from '../lib/review'

export function createReferenceCache(loader = loadReference, now = Date.now) {
  const completed = new Map<string, { at: number; value: ReferenceText }>()
  const pending = new Map<string, Promise<ReferenceText>>()
  return (ref: ReviewRef, site: ReferenceSite, refresh = false): Promise<ReferenceText> => {
    const key = JSON.stringify([site.pnu, site.assessmentDate, ref.kind, ref.instrument, ref.article, ref.edition_id, ref.hang_ids])
    const cached = completed.get(key)
    if (!refresh && cached && now() - cached.at < 300_000) return Promise.resolve(cached.value)
    const running = pending.get(key)
    if (running) return running
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => {
        controller.abort()
        reject(new Error('원문 조회가 지연되고 있습니다. 공식 원문 링크로 먼저 확인하거나 다시 조회해 주세요.'))
      }, 45_000)
    })
    // Keep one bounded request alive across article switches and React remounts.
    const request = Promise.race([loader(ref, site, controller.signal), timeout]).then(value => {
      if (completed.size >= 64) completed.delete(completed.keys().next().value!)
      completed.set(key, { at: now(), value })
      return value
    }).finally(() => { clearTimeout(timer); pending.delete(key) })
    pending.set(key, request)
    return request
  }
}

export const loadCachedReference = createReferenceCache()
