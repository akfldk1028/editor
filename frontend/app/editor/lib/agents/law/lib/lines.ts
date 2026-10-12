/**
 * What the Law Agent says: the parcel's limits (tiles with their articles), its legal basis (links),
 * its land analysis, and its answers to typed questions (statute passages, ordinance articles). Pure.
 */
import type { FeedAction, FeedCard, FeedInput, FeedTone } from '@/lib/orchestrator-runs/feed'
import { agentLabel, evidenceLabel, frontageLabel, heightLabel, limitationLabel } from '@/lib/orchestrator-runs/labels'
import type { AskAnswer, LandAnalysisAnswer, LegalEvidence, RunLaw, RunResults } from '@/lib/orchestrator-runs/types'
import { excerpt, fmt, isoDate } from '@/lib/orchestrator-runs/format'
import { type LawTarget, lawParams } from '@/lib/orchestrator-runs/law-target'
import { askRolePrompt, handoffLine, orchestratorReplyLine } from '@/lib/agents/orchestrator/lib/lines'
import { siteLocatedLine } from '@/lib/agents/site/lib/lines'

const ORCHESTRATOR = 'orchestrator'

const LAW = 'law'

/** "법규 한계 (자연녹지지역): 건폐 20% · 용적 80% · 5층" — null until its numbers arrive. */
export function lawLine(results: RunResults): string | null {
  const law = results.law
  if (!law) return null
  const parts = [
    law.bcr_pct !== null ? `건폐 ${fmt(law.bcr_pct, 2)}%` : null,
    law.far_pct !== null ? `용적 ${fmt(law.far_pct, 2)}%` : null,
    law.max_floors !== null ? `${law.max_floors}층` : law.height.limit_m !== null ? `높이 ${law.height.limit_m} m` : null,
  ].filter((part): part is string => part !== null)
  if (!parts.length) return null
  return `법규 한계${law.zones.length ? ` (${law.zones.join(' · ')})` : ''}: ${parts.join(' · ')}`
}

/** Law's numbers as stat tiles under the law line, each with where it comes from. */
export function lawCard(results: RunResults): FeedCard | null {
  return results.law ? limitsCard(results.law) : null
}

/** The ordinance article and the national ceiling for the caps, the capacities Law derived, the height rule. */
export function limitsCard(law: RunLaw): FeedCard | null {
  const ceiling = (value: number | null) => (value !== null ? `국가 상한 ${fmt(value, 2)}%` : null)
  const hint = (...parts: (string | null)[]) => {
    const text = parts.filter((part): part is string => Boolean(part)).join(' · ')
    return text ? { hint: text } : {}
  }
  const items = [
    law.site_area_m2 !== null ? { label: '대지면적', value: `${fmt(law.site_area_m2, 1)}㎡` } : null,
    law.bcr_pct !== null ? { label: '건폐율', value: `${fmt(law.bcr_pct, 2)}%`, ...hint(law.articles.bcr, ceiling(law.national_bcr_ceiling_pct)) } : null,
    law.far_pct !== null ? { label: '용적률', value: `${fmt(law.far_pct, 2)}%`, ...hint(law.articles.far, ceiling(law.national_far_ceiling_pct)) } : null,
    law.ground_capacity_m2 !== null ? { label: '건축면적 상한', value: `${fmt(law.ground_capacity_m2, 1)}㎡`, hint: '건폐율 × 대지면적' } : null,
    law.far_capacity_m2 !== null ? { label: '연면적 상한', value: `${fmt(law.far_capacity_m2, 1)}㎡`, hint: '용적률 × 대지면적' } : null,
    law.max_floors !== null
      ? { label: '최고 층수', value: `${law.max_floors}층`, ...hint(law.articles.height) }
      : { label: '높이 제한', value: heightLabel(law.height.status, law.height.limit_m), ...hint(law.articles.height) },
  ].filter((item): item is { label: string; value: string; hint?: string } => item !== null)
  return items.length ? { type: 'stats', items } : null
}

/**
 * Law Agent's legal basis for this land — the ordinance receipt (source with its law.go.kr link,
 * articles, limitations) and Law's premises — with 관련 법규 보기, which opens every regulation and
 * article for the parcel (law artifact, 조문 tab). Null when Law sent nothing of the kind.
 */
export function lawBasisLine(results: RunResults, target: LawTarget): FeedInput | null {
  const law = results.law
  if (!law) return null
  const action: FeedAction = { label: '관련 법규 보기', artifact: 'law', params: lawParams(target, 'articles') }
  const items: { label: string; href?: string; note?: string }[] = []
  for (const source of law.ordinance?.sources ?? []) {
    const note = [source.edition_id ? `판본 ${source.edition_id}` : null, source.effective_date ? `시행 ${isoDate(source.effective_date)}` : null].filter(Boolean).join(' · ')
    items.push({ label: source.name ?? '조례', ...(source.url ? { href: source.url } : {}), ...(note ? { note } : {}) })
  }
  for (const article of law.ordinance?.articles ?? []) items.push({ label: article })
  for (const source of law.sources) items.push({ label: source.title ?? '—', ...(source.date ? { note: source.date } : {}) })
  for (const code of law.ordinance?.limitations ?? []) items.push({ label: limitationLabel(code), note: '유의' })
  const assumptions = [
    law.evidence.floor_height_m !== null ? `층고 ${law.evidence.floor_height_m} m 가정` : null,
    law.evidence.datum_measured === false ? '지반고 미측정' : law.evidence.datum_measured === true ? '지반고 측정' : null,
    frontageLabel(law.evidence.frontage_grade),
  ].filter((part): part is string => Boolean(part))
  const premise = assumptions.length ? ` · 전제: ${assumptions.join(', ')}` : ''
  if (law.ordinance) {
    const { assessment_date } = law.ordinance
    const dated = assessment_date ? ` (기준일 ${assessment_date})` : ''
    return { kind: 'progress', agent: LAW, tone: 'ok', text: `법적 근거 ${items.length}건${dated}${premise}`, card: items.length ? { type: 'links', items } : undefined, actions: [action] }
  }
  if (items.length) return { kind: 'progress', agent: LAW, tone: 'ok', text: `법적 근거 ${items.length}건${premise}`, card: { type: 'links', items }, actions: [action] }
  if (law.truncated) return { kind: 'progress', agent: LAW, tone: 'warn', text: `조례 영수증이 전달되지 않았어요 — Law 응답이 8,000자에서 잘렸어요${premise}`, actions: [action] }
  return null
}

/**
 * The moment a question is sent: the user's bubble and the request drawn — to the role the user
 * picked, else to the Orchestrator Agent, which decides whose question it is.
 */
export function askLines(text: string, role: string | null = null, clause: string | null = null): FeedInput[] {
  const to = role ?? ORCHESTRATOR
  return [
    // A question about one provision says which; a role picked from the choices shows the pick.
    { kind: 'user', text: clause ? `「${clause}」 — ${text}` : role ? `${agentLabel(role)}에게: ${text}` : text },
    { kind: 'progress', agent: ORCHESTRATOR, tone: 'busy', relay: { from: role ? ORCHESTRATOR : 'user', to },
      text: role ? `${agentLabel(role)}에게 묻는 중` : 'Orchestrator Agent가 담당을 고르는 중' },
  ]
}

/** Legal-evidence status words of the Law Agent's search/ordinance answers. */
function evidenceNote(evidence: LegalEvidence | null): string | null {
  if (!evidence) return null
  const parts = [
    evidence.assessment_date ? `기준일 ${evidence.assessment_date}` : null,
    evidence.currency_status === 'needs_evidence' || evidence.coverage_status === 'needs_evidence' ? '최신성·적용 범위는 확인 필요' : null,
  ].filter((part): part is string => Boolean(part))
  return parts.length ? parts.join(' · ') : null
}

/**
 * The Law Agent's answer as its turn: statute passages (`law_search`) or an ordinance article
 * (`law_ordinance`) as link cards, with 관련 법규 보기 when the conversation has a site.
 */
export function answerLine(answer: AskAnswer, target: LawTarget | null, needed: readonly string[] = []): FeedInput {
  if (answer.route.kind === 'ask') return askRolePrompt(answer)
  if (answer.route.kind === 'answer') return orchestratorReplyLine(answer)
  if (answer.route.kind === 'goal' || !answer.answer) return handoffLine(answer, needed)
  if (answer.answer.kind === 'site') return siteLocatedLine(answer.answer)
  const actions: FeedAction[] = target ? [{ label: '관련 법규 보기', artifact: 'law', params: lawParams(target, 'articles') }] : []
  const note = evidenceNote(answer.answer.legal_evidence)
  if (answer.answer.kind === 'ordinance') {
    const { ordinance, matches } = answer.answer
    const head = [ordinance.name, matches[0]?.article, matches[0]?.title ? `(${matches[0].title})` : null].filter(Boolean).join(' ')
    const edition = [ordinance.edition_id ? `판본 ${ordinance.edition_id}` : null, ordinance.effective_date ? `시행 ${ordinance.effective_date}` : null].filter(Boolean).join(' · ')
    const items = [
      ...(ordinance.name ? [{ label: `${ordinance.name} — law.go.kr`, ...(ordinance.url ? { href: ordinance.url } : {}), ...(edition ? { note: edition } : {}) }] : []),
      ...matches.map((match) => ({ label: [match.article, match.title].filter(Boolean).join(' ') || '조문', ...(match.text ? { note: excerpt(match.text)! } : {}) })),
    ]
    if (!matches.length) return { kind: 'progress', agent: LAW, tone: 'warn', text: `${ordinance.name ?? '조례'}에서 해당 조문을 찾지 못했어요`, actions }
    return { kind: 'progress', agent: LAW, tone: 'ok', text: `${head}${note ? ` · ${note}` : ''}`, card: { type: 'links', items }, actions }
  }
  const { items, total, degraded } = answer.answer
  if (!items.length) return { kind: 'progress', agent: LAW, tone: 'warn', text: `'${answer.question}' 관련 조문을 찾지 못했어요`, actions }
  const laws = [...new Set(items.map((item) => item.law).filter((law): law is string => Boolean(law)))]
  const text = `'${answer.question}' 관련 조문 ${total}건 — ${laws.slice(0, 3).join(', ')}${laws.length > 3 ? ` 외 ${laws.length - 3}` : ''}${degraded ? ' · 검색 일부 저하' : ''}${note ? ` · ${note}` : ''}`
  return {
    kind: 'progress',
    agent: LAW,
    tone: 'ok',
    text,
    card: { type: 'links', items: items.map((item) => ({ label: [item.law, item.kind ? `(${item.kind})` : null, item.article].filter(Boolean).join(' '), ...(item.text ? { note: excerpt(item.text)! } : {}) })) },
    actions,
  }
}

/** When the law artifact asks for a parcel's analysis: the user's bubble and the request drawn. */
export function landAnalysisLines(label: string, conditions: { buildingType?: string; assessmentDate?: string }): FeedInput[] {
  const use = conditions.buildingType?.trim()
  const detail = [conditions.assessmentDate ? `기준일 ${conditions.assessmentDate}` : null, use ? `용도 ${use}` : null].filter(Boolean).join(' · ')
  return [
    { kind: 'user', text: `법규 요약 · ${label}${detail ? ` · ${detail}` : ''}` },
    { kind: 'progress', agent: ORCHESTRATOR, tone: 'busy', relay: { from: ORCHESTRATOR, to: LAW }, text: 'Law Agent에게 법규 분석 요청 중' },
  ]
}

/**
 * The Law Agent's land analysis as its turn: the caps it set for the parcel (district policy or
 * ordinance, area-weighted) as tiles, the zones, how many restrictions, what evidence is missing.
 */
export function landAnalysisLine(answer: LandAnalysisAnswer, target: LawTarget): FeedInput {
  const { summary, limits } = answer
  const zones = summary.zones.length ? ` (${summary.zones.join(' · ')})` : ''
  const caps = limits && limits.bcr_pct !== null && limits.far_pct !== null
    ? `건폐 ${fmt(limits.bcr_pct, 2)}% · 용적 ${fmt(limits.far_pct, 2)}%${limits.max_floors !== null ? ` · ${limits.max_floors}층` : ''}${limits.policy_id ? ` · 지구단위 정책 ${limits.policy_id}` : ''}`
    : limits
      ? '상한 미확정'
      : `상한 미확정 (law_parcel_limits ${answer.limits_error ? '실패' : '없음'})`
  const missing = summary.missing_evidence.map(evidenceLabel)
  const text = `법규 요약${zones}: ${caps} · 제한 ${summary.restrictions.length}건${missing.length ? ` · 확인 필요: ${missing.slice(0, 3).join(', ')}${missing.length > 3 ? ` 외 ${missing.length - 3}` : ''}` : ''}`
  const tone: FeedTone = limits && limits.bcr_pct !== null && summary.permit_compliance_verified ? 'ok' : 'warn'
  return {
    kind: 'progress',
    agent: LAW,
    tone,
    text: `${text}\n\n이 대지에 어떤 용도의 건물과 공간을 계획하시나요? 원하는 용도·공간·설계 방향을 이야기해 주세요.`,
    ...(limits ? { card: limitsCard(limits) ?? undefined } : {}),
    actions: [{ label: '검토 조항 보기', artifact: 'law', params: lawParams(target, 'review') }, { label: '설계 방향 이야기하기', command: { kind: 'compose', draft: '이 대지에서 계획하는 용도와 원하는 공간은 ' } }],
  }
}

/** When the question could not be answered: the Law Agent is off (시스템 보기) or refused. */
export function askFailedLine(status: number | null, detail: string | null): FeedInput {
  if (status === 503 || status === null) {
    return { kind: 'error', agent: ORCHESTRATOR, text: 'Law Agent에 연결할 수 없어요 — 켜진 뒤 다시 물어보세요', actions: [{ label: '시스템 보기', artifact: 'system' }] }
  }
  return { kind: 'error', agent: ORCHESTRATOR, text: `Law Agent가 답하지 못했어요${detail ? ` — ${detail}` : ''}` }
}

/** The Law Agent's detailed turn for its `law_parcel_limits` step, once results are parsed. */
export function detail(results: RunResults): FeedInput | null {
  const text = lawLine(results)
  return text ? { kind: 'progress', agent: LAW, text, tone: 'ok', card: lawCard(results) ?? undefined } : null
}
