import type { Component, ComponentConfig, TeamConfig } from '@/lib/contracts/workspace'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useValidateComponent } from '../hooks/useTeams'
export function ValidationBadge({
  component,
}: {
  component: Component<TeamConfig> | null | undefined
}) {
  const { data: validation, isLoading } = useValidateComponent(
    component as Component<ComponentConfig> | null | undefined,
  )
  if (isLoading || !validation) return null
  if (validation.is_valid) {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs text-(--color-semantic-success)"
        title={validation.warnings.map((item) => item.error).join('\n')}
      >
        <CheckCircle2 className="w-3.5 h-3.5" />
        JSON valid
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1 text-xs text-(--color-semantic-error)"
      title={validation.errors.map((e) => `${e.field}: ${e.error}`).join('\n')}
    >
      <AlertTriangle className="w-3.5 h-3.5" />
      {validation.errors.length} error{validation.errors.length !== 1 ? 's' : ''}
    </span>
  )
}
