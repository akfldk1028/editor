import type { RunContext } from '@/lib/orchestrator-runs/types'

/** A health run the browser asked for but may not have seen accepted: replaying the same key and versions resumes it, never doubles it. */
export interface PendingHealth { key: string; context: RunContext }
type PendingStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
const storageKey = (projectId: string) => `editor:pending-health:v1:${process.env.NEXT_PUBLIC_BASE_PATH || ''}:${projectId}`

export function readPendingHealth(storage: Pick<Storage, 'getItem'>, projectId: string): PendingHealth | null {
  try {
    const raw = storage.getItem(storageKey(projectId))
    if (raw === null) return null
    const value = JSON.parse(raw)
    if (!value || typeof value.key !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.key) ||
      !Number.isSafeInteger(value.context?.scene_revision) || value.context.scene_revision < 0 ||
      !value.context.source_versions || typeof value.context.source_versions !== 'object' || Array.isArray(value.context.source_versions) ||
      !Object.values(value.context.source_versions).every((v) => Number.isSafeInteger(v) && Number(v) >= 0)) throw new Error()
    return { key: value.key, context: { scene_revision: value.context.scene_revision, source_versions: value.context.source_versions } }
  } catch { throw new Error('이전 실행 요청을 복원하지 못했어요. 협업 패널의 실행 목록에서 접수 여부를 먼저 확인해 주세요.') }
}

export function savePendingHealth(storage: PendingStorage, projectId: string, attempt: PendingHealth) {
  try { storage.setItem(storageKey(projectId), JSON.stringify(attempt)) }
  catch { throw new Error('재시도 정보를 저장하지 못해 실행을 요청하지 않았어요. 브라우저 저장소를 확인해 주세요.') }
}

export function clearPendingHealth(storage: PendingStorage, projectId: string) {
  storage.removeItem(storageKey(projectId))
}
