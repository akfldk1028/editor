import type { MassEvaluationStatus, MassOverallStatus } from '../../lib/mass-portfolio-types'

export function MassStatusBadge({ status }: { status: MassEvaluationStatus | MassOverallStatus }) {
  return <span className="mass-status-badge" data-status={status}>{status.replace('_', ' ').toUpperCase()}</span>
}
