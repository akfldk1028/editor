import { memo, useCallback } from 'react'
import { ShieldCheck, ShieldX, ShieldAlert, FileEdit, FileSearch, Terminal, Globe, Wrench } from 'lucide-react'
import { Button } from '@/elements/workspace'
import type { ToolApproval, ToolIcon } from '../tool-approval.types'

const ICON_MAP: Record<ToolIcon, typeof FileEdit> = {
  edit: FileEdit,
  read: FileSearch,
  execute: Terminal,
  fetch: Globe,
  generic: Wrench,
}

interface ToolApprovalCardProps {
  approval: ToolApproval
  queueLength: number
  onApprove: (id: string) => void
  onApproveAlways: (id: string) => void
  onReject: (id: string) => void
}

export const ToolApprovalCard = memo(function ToolApprovalCard({
  approval,
  queueLength,
  onApprove,
  onApproveAlways,
  onReject,
}: ToolApprovalCardProps) {
  const Icon = ICON_MAP[approval.icon] ?? Wrench

  const handleApprove = useCallback(() => onApprove(approval.id), [onApprove, approval.id])
  const handleAlways = useCallback(() => onApproveAlways(approval.id), [onApproveAlways, approval.id])
  const handleReject = useCallback(() => onReject(approval.id), [onReject, approval.id])

  return (
    <div
      className="mx-4 my-3 rounded-lg border-2 border-(--color-semantic-warning)/50 bg-(--color-surface-card) p-4 shadow-sm"
      role="alert"
      aria-label={`Tool approval request for ${approval.toolName}`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <ShieldAlert className="w-5 h-5 text-(--color-semantic-warning)" />
        <span className="text-sm font-semibold text-(--color-text-primary)">Tool Approval Required</span>
        {queueLength > 1 && (
          <span className="ml-auto text-xs text-(--color-text-tertiary)">
            +{queueLength - 1} more
          </span>
        )}
      </div>

      {/* Tool info */}
      <div className="flex items-start gap-3 mb-4 rounded-md bg-(--color-background-secondary) p-3">
        <div className="w-8 h-8 rounded-md flex items-center justify-center bg-(--color-accent-primary)/10 text-(--color-accent-primary) shrink-0">
          <Icon className="w-4 h-4" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-(--color-text-primary)">{approval.toolName}</p>
          <p className="text-xs text-(--color-text-tertiary) mt-0.5">from {approval.source}</p>
          {approval.args && (
            <pre className="mt-2 text-xs font-mono text-(--color-text-secondary) whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
              {approval.args}
            </pre>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={handleApprove} aria-label="Allow once">
          <ShieldCheck className="w-3.5 h-3.5 mr-1" />
          Allow Once
        </Button>
        <Button size="sm" variant="secondary" onClick={handleAlways} aria-label="Allow always">
          <ShieldCheck className="w-3.5 h-3.5 mr-1" />
          Allow Always
        </Button>
        <Button size="sm" variant="danger" onClick={handleReject} aria-label="Reject">
          <ShieldX className="w-3.5 h-3.5 mr-1" />
          Reject
        </Button>
      </div>
    </div>
  )
})
