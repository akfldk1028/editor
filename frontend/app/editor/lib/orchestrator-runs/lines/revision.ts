/** What the Revision Agent says: its triage, finding by finding. Pure. */
import type { FeedInput, FeedTone } from '../feed'
import { actionLabel, agentLabel, categoryLabel, evidenceLabel, stateLabel } from '../labels'
import type { RunResults } from '../types'

/**
 * The Revision Agent's triage as it wrote it: its verdict code and every finding it weighed — what,
 * who raised it, its category, the recommended action and who should carry it out. Null before it ran.
 */
export function revisionLine(results: RunResults): FeedInput | null {
  const review = results.review
  if (!review) return null
  const items = review.actions.map((action) => ({
    title: evidenceLabel(action.finding ?? '—'),
    by: agentLabel(action.raised_by),
    category: categoryLabel(action.category),
    action: actionLabel(action.recommended_action),
    owners: action.recommended_agents.map(agentLabel).join(', '),
  }))
  const verdict = review.code ? stateLabel(review.code) : stateLabel(review.status)
  const text = `재검토 판정: ${verdict}${items.length ? ` — 제기 ${items.length}건` : ''}`
  const tone: FeedTone = review.status === 'succeeded' || review.status === 'completed' ? 'ok' : 'warn'
  return { kind: 'progress', agent: 'revision', tone, text, ...(items.length ? { card: { type: 'findings', items } } : {}) }
}
