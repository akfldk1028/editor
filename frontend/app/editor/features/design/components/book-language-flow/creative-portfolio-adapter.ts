import type {
  CreativeMassCard,
  CreativePortfolioManifest,
} from '../../lib/language-system-types'
import type {
  NetworkEdge,
  NetworkNode,
} from './LanguageNetworkCanvas'


export interface AdaptedCreativePortfolio {
  cards: CreativeMassCard[]
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  stageOrder: string[]
}

export interface CreativePortfolioPage {
  page: number
  pageCount: number
  pageSize: number
  totalCount: number
  items: CreativeMassCard[]
}

export function creativeMassSelectionKey(
  card: Pick<
    CreativeMassCard,
    'portfolioRunId' | 'candidateId' | 'programHash' | 'geometryHash'
  >,
): string {
  return [
    card.portfolioRunId,
    card.candidateId,
    card.programHash,
    card.geometryHash,
  ].join('/')
}

export function adaptCreativePortfolio(
  manifest: CreativePortfolioManifest,
): AdaptedCreativePortfolio {
  const cards = manifest.candidates.map((candidate): CreativeMassCard => {
    const card = {
      portfolioRunId: candidate.run_id,
      candidateId: candidate.candidate_id,
      programHash: candidate.program_hash,
      geometryHash: candidate.geometry_hash,
      renderUrl: candidate.render_url,
      family: candidate.family,
      formClass: candidate.form_class,
      capacityBand: candidate.capacity_band,
      storeys: candidate.storeys,
      legalStatus: candidate.legal_status,
      morphologyDistance: candidate.morphology_distance,
      selectionKey: '',
    }
    card.selectionKey = creativeMassSelectionKey(card)
    return card
  })
  const cardByCandidateId = new Map(
    cards.map((card) => [card.candidateId, card]),
  )
  const familyStages = Array.from(new Set(cards.map((card) => (
    creativeFamilyStage(card.family)
  )))).sort()
  const nodes = manifest.graph.nodes.map((node): NetworkNode => {
    const candidateId = node.kind === 'creative_mass_candidate'
      ? candidateIdFromNode(node.id, node.attributes)
      : ''
    const card = cardByCandidateId.get(candidateId)
    return {
      id: node.id,
      kind: node.kind,
      stage: card ? creativeFamilyStage(card.family) : 'creative_portfolio',
      label: card
        ? `${card.candidateId} · ${card.family} · NOT EVALUATED`
        : `${manifest.run_id} · ${manifest.candidate_count} PRE-LEGAL MASSES`,
      authority: 'observed',
      attributes: {
        ...node.attributes,
        ...(card ?? {}),
        preview_url: card?.renderUrl,
        legal_status: card?.legalStatus ?? manifest.legal_review_status,
      },
    }
  })
  const edges = manifest.graph.edges.map((edge): NetworkEdge => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    kind: edge.kind,
    scope: 'execution',
  }))
  return {
    cards,
    nodes,
    edges,
    stageOrder: ['creative_portfolio', ...familyStages],
  }
}

export function creativePortfolioPage(
  cards: readonly CreativeMassCard[],
  requestedPage: number,
  pageSize = 25,
): CreativePortfolioPage {
  const safePageSize = Math.max(1, Math.floor(pageSize))
  const pageCount = Math.max(1, Math.ceil(cards.length / safePageSize))
  const page = Math.min(pageCount, Math.max(1, Math.floor(requestedPage)))
  const start = (page - 1) * safePageSize
  return {
    page,
    pageCount,
    pageSize: safePageSize,
    totalCount: cards.length,
    items: cards.slice(start, start + safePageSize),
  }
}

function creativeFamilyStage(family: string): string {
  return `creative_family:${family || 'unassigned'}`
}

function candidateIdFromNode(
  nodeId: string,
  attributes: Record<string, unknown>,
): string {
  const explicit = String(attributes.candidate_id ?? '')
  return explicit || nodeId.replace(/^creative:candidate:/, '')
}
