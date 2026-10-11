/** What the Site Agent says: its eight site facts (`sitecontextagent/facts.py` SITE_KEYS), and where a typed address is. Pure. */
import type { FeedInput } from '@/lib/orchestrator-runs/feed'
import { confidenceLabel, evidenceLabel, SITE_FACTS } from '@/lib/orchestrator-runs/labels'
import type { AskAnswer, RunResults, SiteLocateBody } from '@/lib/orchestrator-runs/types'

const SITE = 'site_context'

/** The site-map params that open the located parcel and select it (`pick`); null when nothing was found. */
export function siteLocateParams(body: SiteLocateBody): Record<string, string> | null {
  if (body.pnu) return { pnu: body.pnu, pick: '1' }
  if (body.coordinates) return { address: body.query, pick: '1' }
  return null
}

/** A message that was an address: found → the map opens on that parcel (the action repeats it); not found → pick on the map. */
export function siteLocatedLine(answer: AskAnswer): FeedInput {
  const body = answer.answer
  if (body?.kind !== 'site') throw new Error('siteLocatedLine takes a site_locate answer')
  const params = siteLocateParams(body)
  if (!params) {
    return { kind: 'progress', agent: SITE, tone: 'warn', text: `'${body.query}' 주소를 찾지 못했어요 — 지도에서 필지를 직접 찍어 주세요`, actions: [{ label: '지도 열기', artifact: 'site-map' }] }
  }
  return { kind: 'progress', agent: SITE, tone: 'ok', text: `지도에서 찾았어요 — ${body.address ?? body.pnu} · 이 필지를 대지로 선택해요`, actions: [{ label: '지도 보기', artifact: 'site-map', params }] }
}

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

/** The Site Agent's detailed turn for its `site_resolve` step. */
export const detail = siteFactsLine
