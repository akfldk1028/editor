import { requiredValue } from '../../lib/required-value';
import type {
  MassOverallStatus,
  MassPortfolioCard,
  MassPortfolioManifest,
  MassStageName,
} from '../../lib/mass-portfolio-types'
import type { NetworkEdge, NetworkNode } from './LanguageNetworkCanvas'

export const MASS_STAGE_ORDER = [
  'unitbox', 'matrix4', 'book', 'compile', 'geometry', 'law',
  'capacity', 'parking', 'program', 'vlm', 'selection', 'mass_result',
]

export interface MassPortfolioFilters {
  program: string
  overallStatus: MassOverallStatus | ''
  gate: MassStageName | ''
  gateStatus: 'pass' | 'failed' | 'not_evaluated' | ''
}

export interface AdaptedMassPortfolio {
  cards: MassPortfolioCard[]
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  stageOrder: string[]
}

const SHARED_STAGES = [
  ['unitbox', 'BASEVOLUME · UNITBOX'],
  ['matrix4', '4×4 AFFINE MATRIX'],
  ['book', 'BOOK ARCHITECTURAL LANGUAGE'],
  ['compile', 'GEOMETRY COMPILE'],
  ['geometry', 'GEOMETRY EVIDENCE'],
  ['law', 'LAW HARD GATE'],
  ['capacity', 'CAPACITY HARD GATE'],
  ['parking', 'PARKING HARD GATE'],
  ['program', 'PROGRAM HARD GATE'],
  ['vlm', 'VLM REVIEW · INDEPENDENT'],
  ['selection', 'FINAL SELECTION'],
] as const

export function adaptMassPortfolio(manifest: MassPortfolioManifest): AdaptedMassPortfolio {
  const cards = manifest.candidates.map((candidate): MassPortfolioCard => ({
    selectionKey: [candidate.run_id, candidate.candidate_id, candidate.program_hash, candidate.geometry_hash].join('/'),
    runId: candidate.run_id,
    program: candidate.program_slug,
    candidateId: candidate.candidate_id,
    programHash: candidate.program_hash,
    geometryHash: candidate.geometry_hash,
    overallStatus: candidate.overall_status,
    selected: candidate.selected,
    previewUrl: candidate.preview_url,
    terminalReasons: candidate.terminal_reasons,
    integrityFailures: candidate.integrity_failures,
    lineage: candidate.lineage,
    stages: candidate.stages,
  }))
  const nodes: NetworkNode[] = SHARED_STAGES.map(([stage, label]) => ({
    id: `mass-stage:${stage}`,
    kind: 'mass_language_stage',
    stage,
    label,
    authority: 'computed',
    attributes: { stage },
  }))
  const edges: NetworkEdge[] = SHARED_STAGES.slice(1).map(([stage], index) => ({
    id: `mass-edge:${requiredValue(SHARED_STAGES[index])[0]}:${stage}`,
    source: `mass-stage:${requiredValue(SHARED_STAGES[index])[0]}`,
    target: `mass-stage:${stage}`,
    kind: 'language_lineage',
    scope: 'execution',
  }))
  cards.forEach((card, index) => {
    const nodeId = `mass-candidate:${index}:${card.geometryHash.slice(0, 12)}`
    nodes.push({
      id: nodeId,
      kind: 'mass_candidate',
      stage: 'mass_result',
      label: `${String(index + 1).padStart(2, '0')} · ${card.candidateId} · ${card.overallStatus.toUpperCase()}`,
      authority: 'observed',
      attributes: { ...card, preview_url: card.previewUrl, overall_status: card.overallStatus },
    })
    edges.push({
      id: `mass-edge:compile:${index}`,
      source: 'mass-stage:selection',
      target: nodeId,
      kind: 'evaluated_candidate',
      scope: 'execution',
    })
  })
  return { cards, nodes, edges, stageOrder: [...MASS_STAGE_ORDER] }
}

export function filterMassPortfolioCards(
  cards: readonly MassPortfolioCard[],
  filters: MassPortfolioFilters,
): MassPortfolioCard[] {
  return cards.filter((card) => (
    (!filters.program || card.program === filters.program)
    && (!filters.overallStatus || card.overallStatus === filters.overallStatus)
    && (!filters.gate || !filters.gateStatus || card.stages[filters.gate]?.status === filters.gateStatus)
  ))
}
