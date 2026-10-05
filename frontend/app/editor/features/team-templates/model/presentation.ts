import type { AgentConfig, Component, TerminationConfig } from '@/lib/contracts/workspace'
import type { TeamResponse } from '../api'
export function downloadJSON(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
export function getParticipants(team: TeamResponse) {
  const config = team.component?.config as Record<string, unknown> | undefined
  return (config?.participants ?? []) as Component<AgentConfig>[]
}
export function getTermination(team: TeamResponse): Component<TerminationConfig> | undefined {
  const config = team.component?.config as Record<string, unknown> | undefined
  return config?.termination_condition as Component<TerminationConfig> | undefined
}
export const PATTERN_COLORS: Record<
  string,
  'primary' | 'success' | 'warning' | 'error' | 'default'
> = {
  sequential: 'primary',
  selector: 'success',
  handoff: 'warning',
  debate: 'error',
  reflection: 'success',
  custom: 'default',
}
