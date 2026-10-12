import type { ConversationLocated, ConversationSnapshot, ConversationSubmission } from './types'

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)

export function parseConversation(value: unknown): ConversationSnapshot {
  if (!object(value) || typeof value.conversation_id !== 'string' || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0 ||
    !['idle', 'working', 'failed'].includes(String(value.status)) || !(value.error === null || typeof value.error === 'string') ||
    !Array.isArray(value.messages) || !Array.isArray(value.artifacts) ||
    value.messages.some((row: unknown) => !object(row) || typeof row.id !== 'string' || !['user', 'assistant'].includes(String(row.role)) ||
      !(row.agent === null || typeof row.agent === 'string') || typeof row.text !== 'string' || typeof row.at !== 'string' || !Number.isFinite(Date.parse(row.at))) ||
    value.artifacts.some((row: unknown) => !object(row) || !['id', 'owner', 'title', 'status'].every((key) => typeof row[key] === 'string') || !object(row.data))) {
    throw new Error('대화 응답을 읽지 못했어요. 다시 연결해 주세요.')
  }
  return value as unknown as ConversationSnapshot
}

function path(projectId: string) {
  return `${process.env.NEXT_PUBLIC_BASE_PATH || ''}/api/v1/platform/projects/${encodeURIComponent(projectId)}/conversation`
}

async function read(response: Response) {
  if (!response.ok) throw new Error(`대화에 연결하지 못했어요 (${response.status}). 같은 메시지로 다시 시도할 수 있어요.`)
  return parseConversation(await response.json())
}

export async function getConversation(projectId: string, conversationId: string, signal?: AbortSignal) {
  return read(await fetch(`${path(projectId)}?conversation_id=${encodeURIComponent(conversationId)}`, { signal, cache: 'no-store' }))
}

/** A message that was one address comes back located by the editor (`{located}`, 200) instead of as the owner's snapshot. */
export function parseLocated(value: unknown): ConversationLocated | null {
  if (!object(value) || !('located' in value)) return null
  const body = value.located
  if (!object(body) || body.kind !== 'site' || typeof body.query !== 'string' || !(body.pnu === null || typeof body.pnu === 'string') ||
    !(body.address === null || typeof body.address === 'string') || !(body.error === null || typeof body.error === 'string') ||
    !(body.coordinates === null || (object(body.coordinates) && typeof body.coordinates.x === 'number' && typeof body.coordinates.y === 'number'))) {
    throw new Error('대화 응답을 읽지 못했어요. 다시 연결해 주세요.')
  }
  return value as unknown as ConversationLocated
}

/**
 * The door's answer to a message: the owner's snapshot (with `located` when the message named a site the editor
 * found — the message went to the owner, the map moves too), or `{located}` alone when the message was one address.
 */
export async function postConversation(projectId: string, body: ConversationSubmission): Promise<(ConversationSnapshot & Partial<ConversationLocated>) | ConversationLocated> {
  // Once dispatched, a message belongs to the server even when the user changes projects or sends another.
  const response = await fetch(path(projectId), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!response.ok) throw new Error(`대화에 연결하지 못했어요 (${response.status}). 같은 메시지로 다시 시도할 수 있어요.`)
  const value = await response.json()
  if (object(value) && 'located' in value && !('conversation_id' in value)) return parseLocated(value)!
  const snapshot = parseConversation(value)
  const located = parseLocated(value)
  return located ? { ...snapshot, located: located.located } : snapshot
}
