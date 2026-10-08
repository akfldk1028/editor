/**
 * The agent network as the conversation knows it — ONE table for all sixteen agents plus the two
 * parties around them (the Orchestrator, the user). Everything that names an agent (turn labels,
 * marks, tool ownership, relay diagrams) reads from here; adding an agent is one row. The Orchestrator's
 * live catalog (`/platform/agents`) says which are up; this says what to call them and what they do.
 */
export interface AgentSpec {
  id: string
  /** Network name, in English (user, 2026-10-08); what the agent says stays Korean. */
  name: string
  /** Other ids the network uses for the same agent (hyphenated A2A ids). */
  aliases?: readonly string[]
  /** Tools this agent answers, with their Korean labels; `<id>_health` is implied for every agent. */
  tools?: Readonly<Record<string, string>>
}

export const ORCHESTRATOR = 'orchestrator'
export const USER = 'user'

export const AGENTS: readonly AgentSpec[] = [
  { id: ORCHESTRATOR, name: 'Orchestrator Agent' },
  { id: USER, name: '사용자' },
  { id: 'site_context', name: 'Site Agent', aliases: ['site-context', 'site'], tools: { site_resolve: '대지 사실 확인' } },
  { id: 'law', name: 'Law Agent', tools: {
    law_parcel_limits: '법규 한계', law_land_analyze: '법규 분석', law_search: '법령 검색', law_ordinance: '조례 조문', law_article: '조문',
    law_review_district_plan: '지구단위계획 검토', law_review_program: '프로그램 법규 검토', law_review_design_state: '설계 법규 검토',
    law_parking_design_rules: '주차 설계 기준', law_ground_datum: '지반고 기준', law_basement_storey: '지하층 판정',
  } },
  { id: 'revision', name: 'Revision Agent', tools: { revision_triage: '재검토 판정' } },
  { id: 'masterplan', name: 'MasterPlan Agent', tools: { masterplan_design: '배치 설계' } },
  { id: 'mass', name: 'Mass Agent' },
  { id: 'kmass', name: 'KMass Agent' },
  { id: 'program', name: 'Program Agent', tools: { program_from_brief: '프로그램 번역' } },
  { id: 'requirement', name: 'Requirement Agent' },
  { id: 'design_intent', name: 'DesignIntent Agent', aliases: ['design-intent'] },
  { id: 'elevation', name: 'Elevation Agent' },
  { id: 'plan', name: 'Plan Agent', aliases: ['planm'] },
  { id: 'systems', name: 'Systems Agent' },
  { id: 'domain_expert', name: 'DomainExpert Agent', aliases: ['domain-expert'] },
  { id: 'interior', name: 'Interior Agent' },
  { id: 'scene', name: 'Scene Agent' },
  { id: 'cost', name: 'Cost Agent' },
]

const BY_ID = new Map<string, AgentSpec>()
for (const agent of AGENTS) {
  BY_ID.set(agent.id, agent)
  for (const alias of agent.aliases ?? []) BY_ID.set(alias, agent)
}

/** The canonical id for an id or alias; unknown ids stay as they are. */
export const canonicalAgent = (agent: string): string => BY_ID.get(agent)?.id ?? agent

export const agentSpec = (agent: string | null | undefined): AgentSpec | null => (agent ? BY_ID.get(agent) ?? null : null)

/** The agent that owns a tool: the one listing it, else the one whose id prefixes it (`law_*`, `masterplan_*`). */
export function toolOwner(tool: string): string | null {
  for (const agent of AGENTS) if (agent.tools && tool in agent.tools) return agent.id
  const stem = tool.endsWith('_health') ? tool.slice(0, -'_health'.length) : tool
  for (const agent of AGENTS) {
    if (stem === agent.id || stem.startsWith(`${agent.id}_`)) return agent.id
    for (const alias of agent.aliases ?? []) if (stem === alias || stem.startsWith(`${alias}_`)) return agent.id
  }
  return null
}

/** The Korean label of a tool, or null when no agent lists it. */
export function toolSpecLabel(tool: string): string | null {
  for (const agent of AGENTS) {
    const label = agent.tools?.[tool]
    if (label) return label
  }
  return null
}
