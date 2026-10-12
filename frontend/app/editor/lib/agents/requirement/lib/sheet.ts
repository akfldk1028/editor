/**
 * The Requirement Agent's conversation artifacts as one sheet. The owner sends the brief one field per
 * artifact (`requirements.<field>.r1`, data `{value: …}` or the structured brief itself, status per field);
 * the conversation shows them as a single card that fills in as the user talks: each field in the user's
 * words, filled or not yet. Pure.
 */
import type { ConversationArtifact } from '@/lib/design-conversation/types'

const PREFIX = 'requirements.'
/** Display order and labels; fields the owner adds later fall to the end under their own key. */
const FIELDS: readonly [key: string, label: string][] = [
  ['raw_brief', '원문 요청'],
  ['structured_brief', '정리된 조건'],
  ['must_have', '꼭 필요한 것'],
  ['nice_to_have', '있으면 좋은 것'],
  ['priorities', '우선순위'],
  ['assumptions', '가정'],
  ['unknowns', '아직 확인할 것'],
]

export interface SheetField { key: string; label: string; value: unknown; filled: boolean }
export interface RequirementsSheet { fields: SheetField[]; filled: number; total: number; stale: boolean; artifacts: ConversationArtifact[] }

const fieldOf = (artifact: ConversationArtifact): string | null => {
  const name = artifact.title.startsWith(PREFIX) ? artifact.title : artifact.id.startsWith(PREFIX) ? artifact.id : null
  return name ? name.slice(PREFIX.length).split('.')[0]! : null
}

/** The structured brief's own keys, in the user's words; keys the owner adds later keep their name. */
const BRIEF_KEYS: Record<string, string> = { building_type: '용도', pnu: '지번', address: '주소', site_area: '대지면적', floor_area: '연면적', floors: '층수', budget: '예산', schedule: '일정', operator: '운영 주체', capacity: '정원' }

/** `{value: x}` is the owner's wrapper for a plain field; anything else is the field itself, its keys translated. */
function unwrap(data: Record<string, unknown>): unknown {
  const keys = Object.keys(data)
  if (keys.length === 1 && keys[0] === 'value') return data.value
  return Object.fromEntries(Object.entries(data).map(([key, value]) => [BRIEF_KEYS[key] ?? key, value]))
}

function isFilled(value: unknown): boolean {
  if (value === null || value === undefined) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (Array.isArray(value)) return value.some(isFilled)
  if (typeof value === 'object') return Object.values(value as Record<string, unknown>).some(isFilled)
  return true
}

/** Splits the owner's artifacts: the requirements sheet (null when there is none) and everything else, in order. */
export function requirementsSheet(artifacts: readonly ConversationArtifact[]): { sheet: RequirementsSheet | null; rest: ConversationArtifact[] } {
  const own = artifacts.filter((artifact) => artifact.owner === 'requirement' && fieldOf(artifact) !== null)
  const rest = artifacts.filter((artifact) => !own.includes(artifact))
  if (!own.length) return { sheet: null, rest }
  const byField = new Map(own.map((artifact) => [fieldOf(artifact)!, artifact]))
  const order = [...FIELDS.map(([key]) => key), ...[...byField.keys()].filter((key) => !FIELDS.some(([known]) => known === key))]
  const labels = new Map(FIELDS)
  const fields = order.filter((key) => byField.has(key)).map((key) => {
    const value = unwrap(byField.get(key)!.data)
    return { key, label: labels.get(key) ?? key.replaceAll('_', ' '), value, filled: isFilled(value) }
  })
  return {
    sheet: { fields, filled: fields.filter((field) => field.filled).length, total: fields.length, stale: own.some((artifact) => artifact.status === 'stale'), artifacts: own },
    rest,
  }
}
