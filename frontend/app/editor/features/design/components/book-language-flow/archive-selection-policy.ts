import type {
  CreativeMassCard,
  ExecutedMassManifest,
} from '../../lib/language-system-types'

export interface RecentMassCard {
  key: string
  runId: string
  executionId: string
  massIndex: number
  label: string
  operationLabel: string
  previewUrl: string
  selected: boolean
}


export function reconcileExecutedMassArchive(
  current: ExecutedMassManifest | null,
  incoming: ExecutedMassManifest,
): ExecutedMassManifest {
  if (!current || current.archive_revision === incoming.archive_revision) {
    return current ?? incoming
  }
  const knownRunIds = new Set(current.runs.map((run) => run.run_id))
  const incomingSelectionIsNew = !knownRunIds.has(incoming.selected_run_id)
  const incomingSelectionIsReplayable = incoming.runs.some(
    (run) => run.run_id === incoming.selected_run_id && run.replayable,
  )
  if (incomingSelectionIsNew && incomingSelectionIsReplayable) {
    return incoming
  }
  if (current.selected_run_id !== incoming.selected_run_id) {
    return {
      ...current,
      runs: incoming.runs,
      run_count: incoming.run_count,
      archive_revision: incoming.archive_revision,
    }
  }
  return incoming
}

export function resolveSelectedMassIndex(
  archive: ExecutedMassManifest,
  selectedMassIndex: number,
): number {
  return archive.masses.some((mass) => mass.index === selectedMassIndex)
    ? selectedMassIndex
    : (archive.masses[0]?.index ?? 1)
}

export function latestReplayableRunId(
  archive: ExecutedMassManifest,
): string {
  // Imported records have no reliable execution timestamps. Keep the server's
  // explicit selection instead of inferring recency from missing dates.
  if (archive.editor_provenance) return archive.selected_run_id
  const replayable = archive.runs.filter((run) => run.replayable)
  const planAware = replayable.filter(
    (run) => Boolean(run.floor_capacity_plan_hash?.trim()),
  )
  const acceptedVlmMasses = replayable.filter(
    (run) => isSingleExecution(run.run_id, run.run_type)
      && run.full_flow_status === 'accepted'
      && run.vlm_status === 'live_scored'
      && run.vlm_hard_pass === true,
  )
  const freshSyntheses = replayable.filter(
    (run) => isSingleExecution(run.run_id, run.run_type)
      && run.execution_mode === 'fresh_synthesis',
  )
  const siteBound = replayable.filter(hasResolvedSite)
  return (
    planAware.length > 0
      ? planAware
      : acceptedVlmMasses.length > 0
      ? acceptedVlmMasses
      : freshSyntheses.length > 0
      ? freshSyntheses
      : siteBound.length > 0
        ? siteBound
        : replayable
  )
    .reduce((latest, run) => (
      !latest || run.created_at > latest.created_at ? run : latest
    ), null as ExecutedMassManifest['runs'][number] | null)
    ?.run_id ?? archive.selected_run_id
}

function isSingleExecution(runId: string, runType?: string): boolean {
  return runType === 'single_execution' || runId.startsWith('single-execution:')
}

function hasResolvedSite(run: ExecutedMassManifest['runs'][number]): boolean {
  if (run.site_context_status) {
    return run.site_context_status === 'site_bound'
  }
  if (isSingleExecution(run.run_id, run.run_type)) {
    return false
  }
  const value = run.pnu?.trim()
  return Boolean(value && value !== 'PNU_UNRESOLVED' && value !== 'NOT EVALUATED')
}

export function buildRecentMassCards(
  archive: ExecutedMassManifest,
  selectedMassIndex = archive.masses[0]?.index ?? 1,
  limit = 24,
): RecentMassCard[] {
  if (!isSingleExecution(archive.selected_run_id)) {
    return archive.masses.slice(0, limit).map((mass): RecentMassCard => ({
      key: mass.archive_key,
      runId: mass.run_id,
      executionId: mass.variant_id,
      massIndex: mass.index,
      label: mass.label,
      operationLabel: mass.operation_label,
      previewUrl: mass.preview_url,
      selected: mass.run_id === archive.selected_run_id && mass.index === selectedMassIndex,
    }))
  }
  const selectedMass = archive.masses[0]
  const selectedGeometryHash = archive.masses
    .find((mass) => mass.index === selectedMassIndex)
    ?.geometry_hash
  const seenGeometryHashes = new Set<string>()
  const singleExecutions = archive.runs
    .filter((run) => run.replayable && isSingleExecution(run.run_id, run.run_type))
  const siteBoundExecutions = singleExecutions.filter(hasResolvedSite)
  const singleExecutionCards = (
    siteBoundExecutions.length > 0 ? siteBoundExecutions : singleExecutions
  )
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .filter((run) => {
      const geometryHash = run.geometry_hash?.trim()
      if (!geometryHash) return true
      if (seenGeometryHashes.has(geometryHash)) return false
      seenGeometryHashes.add(geometryHash)
      return true
    })
    .slice(0, limit)
    .map((run): RecentMassCard => {
      const executionId = run.run_id.slice('single-execution:'.length)
      const currentMass = run.run_id === archive.selected_run_id ? selectedMass : undefined
      const selected = run.run_id === archive.selected_run_id
        || Boolean(
          selectedGeometryHash
          && run.geometry_hash
          && selectedGeometryHash === run.geometry_hash,
        )
      return {
        key: `${run.run_id}:1`,
        runId: run.run_id,
        executionId,
        massIndex: currentMass?.index ?? 1,
        label: currentMass?.label || executionId,
        operationLabel: currentMass?.operation_label || 'EXECUTED MASS',
        previewUrl: run.thumbnail_url
          || `/design/maas/single-executions/${executionId}/thumbnail/`,
        selected,
      }
    })

  if (singleExecutionCards.length > 0) {
    return singleExecutionCards
  }

  return archive.masses.slice(0, limit).map((mass): RecentMassCard => ({
    key: mass.archive_key,
    runId: mass.run_id,
    executionId: mass.variant_id,
    massIndex: mass.index,
    label: mass.label,
    operationLabel: mass.operation_label,
    previewUrl: mass.preview_url,
    selected: mass.run_id === archive.selected_run_id && mass.index === selectedMassIndex,
  }))
}

export function selectCreativePortfolioMembers(
  cards: readonly CreativeMassCard[],
): CreativeMassCard[] {
  return [...cards]
}
