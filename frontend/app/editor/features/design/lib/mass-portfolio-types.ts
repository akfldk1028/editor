export type MassEvaluationStatus = 'pass' | 'failed' | 'not_evaluated'
export type MassOverallStatus = 'selected' | 'legal_pass' | 'failed' | 'not_evaluated'
export type MassStageName = 'geometry' | 'law' | 'capacity' | 'parking' | 'program' | 'vlm' | 'selection'

export interface MassStageEvaluation {
  stage: string
  status: MassEvaluationStatus
  reasons: string[]
  evidence: Record<string, unknown>
}

export type MassStageEvaluations = Record<MassStageName, MassStageEvaluation>

export interface MassPortfolioCandidate {
  schema_version: string
  run_id: string
  program_slug: string
  candidate_id: string
  program_hash: string
  geometry_hash: string
  overall_status: MassOverallStatus
  selected: boolean
  integrity_failures: string[]
  terminal_reasons: string[]
  preview_path: string
  preview_url: string
  lineage: Record<string, unknown>
  finalized: boolean
  stages: MassStageEvaluations
}

export interface MassPortfolioManifest {
  schema_version: string
  run_id: string
  pnu: string
  candidate_count: number
  status_counts: Partial<Record<MassOverallStatus, number>>
  candidates: MassPortfolioCandidate[]
}

export interface MassPortfolioCard {
  selectionKey: string
  runId: string
  program: string
  candidateId: string
  programHash: string
  geometryHash: string
  overallStatus: MassOverallStatus
  selected: boolean
  previewUrl: string
  terminalReasons: string[]
  integrityFailures: string[]
  lineage: Record<string, unknown>
  stages: MassStageEvaluations
}
