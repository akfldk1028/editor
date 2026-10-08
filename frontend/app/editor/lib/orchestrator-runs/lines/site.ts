/** What the Site Agent says: its eight site facts (`sitecontextagent/facts.py` SITE_KEYS). Pure. */
import type { FeedInput } from '../feed'
import { confidenceLabel, evidenceLabel, SITE_FACTS } from '../labels'
import type { RunResults } from '../types'

/**
 * The Site Agent's answer as its eight facts: each one established (with its confidence, date and a
 * one-line value), missing (its own SITE-* finding), or unread (the 8000-character cap cut the answer
 * before it). Null until the site step answered.
 */
export function siteFactsLine(results: RunResults): FeedInput | null {
  const site = results.site
  if (!site) return null
  if (site.code) return { kind: 'error', agent: 'site_context', text: `대지 사실 확인 실패 — ${evidenceLabel(site.code)}` }
  const read = new Map(site.facts.map((fact) => [fact.key, fact]))
  const missing = new Set(site.facts_missing)
  const items = SITE_FACTS.map((fact) => {
    const found = read.get(fact.key)
    if (missing.has(fact.code) || found?.confidence === 'unknown') return { label: fact.label, state: 'missing' as const, note: '미제공', critical: fact.critical }
    if (found) {
      const note = [found.summary, confidenceLabel(found.confidence), found.as_of].filter((part): part is string => Boolean(part)).join(' · ')
      return { label: fact.label, state: 'ok' as const, note, critical: fact.critical }
    }
    return { label: fact.label, state: 'unread' as const, note: '응답이 잘려 읽지 못함', critical: fact.critical }
  })
  const known = site.facts_known !== null && site.facts_total !== null ? `${site.facts_known}/${site.facts_total}` : `${items.filter((item) => item.state === 'ok').length}/${items.length}`
  const lacking = items.filter((item) => item.state === 'missing').map((item) => item.label)
  const text = `대지 사실 ${known} 확인${lacking.length ? ` — 미제공: ${lacking.join(', ')}` : ''}`
  return { kind: 'progress', agent: 'site_context', tone: lacking.length ? 'warn' : 'ok', text, card: { type: 'checks', items } }
}
