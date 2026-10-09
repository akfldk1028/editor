import { askLaw, ensureAgents } from '@/lib/orchestrator-runs/api'
import { RUN_LEASE_S } from '@/lib/goals/activation'
import type { ReviewRef } from '../lib/review'
import { fetchOrdinanceBody, type OrdinanceAnnex } from './ordinances'

export interface ReferenceSite { pnu: string; address?: string; assessmentDate: string }
export interface ReferenceText { text: string; url?: string; edition?: string; effective?: string; annexes?: OrdinanceAnnex[] }
const normalized = (text: string) => text.replace(/\s/g, '')

export async function loadReference(ref: ReviewRef, site: ReferenceSite, signal: AbortSignal): Promise<ReferenceText> {
  if (ref.kind !== 'ordinance' && (!ref.article || !ref.hang_ids?.length)) {
    throw new Error('정확한 조문 식별자가 아직 확보되지 않았습니다. 관할 조례·조문을 확인해야 합니다.')
  }
  // A whole ordinance whose dated edition is already verified (discovery gave its edition): the official record's
  // full text — every article, the annexes, the supplementary provisions — read by edition, no agent round trip.
  if (ref.kind === 'ordinance' && !ref.article && ref.url && ref.edition_id) {
    const body = await fetchOrdinanceBody({ name: ref.instrument, edition_id: ref.edition_id, assessment_date: site.assessmentDate }, signal)
    const supplement = body.supplement?.content ? `\n\n${body.supplement.content}` : ''
    return { text: body.articles.map((article) => article.content).join('\n\n') + supplement, url: body.ordinance.url || ref.url,
      edition: ref.edition_id, effective: body.ordinance.effective_date ?? ref.effective_date, annexes: body.annexes }
  }
  const ready = await ensureAgents(['law'], RUN_LEASE_S, signal)
  if (!ready.up.includes('law')) throw new Error('원문 조회 서비스를 준비하지 못했습니다.')
  const result = await askLaw({
    text: '선택한 조문의 원문을 보여 주세요.', role: 'law', pnu: site.pnu, address: site.address, assessment_date: site.assessmentDate,
    clause: { item_id: 'source-article', title: ref.instrument, reason: '검토 근거 원문 조회', status: 'needs_check', basis: ref.article ?? ref.instrument, refs: [{
      instrument: ref.instrument, kind: ref.kind, article: ref.article, clause: null,
      ...(ref.hang_ids?.[0] ? { hang_id: ref.hang_ids[0] } : {}), ...(ref.edition_id ? { edition_id: ref.edition_id } : {}),
    }] },
  }, signal)
  const answer = result.answer
  if (answer?.kind === 'ordinance' && normalized(answer.ordinance.name ?? '') === normalized(ref.instrument)) {
    // A name-only reference resolves the dated ordinance through the agent. Its official
    // edition URL opens the entire ordinance; do not invent a specific article or excerpt.
    if (!ref.article && answer.ordinance.url) return { text: '', url: answer.ordinance.url, edition: answer.ordinance.edition_id ?? undefined, effective: answer.ordinance.effective_date ?? undefined }
    const text = answer.matches.filter(row => row.article === ref.article).map(row => row.text).filter(Boolean).join('\n\n')
    if (text) return { text, url: answer.ordinance.url ?? undefined, edition: answer.ordinance.edition_id ?? undefined, effective: answer.ordinance.effective_date ?? undefined }
  }
  if (answer?.kind === 'search' && result.tool === 'law_article') {
    const parts = ref.hang_ids![0]!.split('::')
    const articleIndex = parts.findIndex(part => /^제\d+조(의\d+)?$/.test(part))
    const expected = parts.slice(0, articleIndex >= 0 ? articleIndex + 1 : parts.length).join('::')
    const text = answer.items.filter(row => row.id === expected || row.id?.startsWith(`${expected}::`)).map(row => row.text).filter(Boolean).join('\n\n')
    if (text) return { text }
  }
  throw new Error('해당 조문의 원문을 받지 못했습니다. 법규가 없다는 뜻은 아닙니다.')
}
