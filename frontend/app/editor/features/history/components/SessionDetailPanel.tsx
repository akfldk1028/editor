/**
 * SessionDetailPanel - Shows session runs and agent messages
 */

import { useState, useCallback } from 'react'
import { Card, Badge, Button } from '@/elements/workspace'
import { X, Trash2 } from 'lucide-react'
import { useSessionRuns } from '@/features/sessions/hooks/useSessions'
import { useDeleteSession } from '@/features/sessions/hooks/useSessions'
import { RunCard } from './RunCard'
import type { Run } from '@/lib/contracts/workspace'
import { truncateError } from '@/lib/display-error'

interface SessionDetailPanelProps {
  sessionId: number
  sessionName: string
  onClose: () => void
}

export function SessionDetailPanel({ sessionId, sessionName, onClose }: SessionDetailPanelProps) {
  const { data: sessionRuns, isLoading, error: loadError } = useSessionRuns(sessionId)
  const deleteMutation = useDeleteSession()
  const [expandedRun, setExpandedRun] = useState<number | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const runs = sessionRuns?.runs ?? []

  const handleToggleRun = useCallback((runId: number) => {
    setExpandedRun((prev) => (prev === runId ? null : runId))
  }, [])

  const handleDelete = useCallback(async () => {
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    try {
      await deleteMutation.mutateAsync(sessionId)
      onClose()
    } catch (e) {
      setError(truncateError(e instanceof Error ? e.message : 'Delete failed'))
      setConfirmDelete(false)
    }
  }, [confirmDelete, sessionId, deleteMutation, onClose])

  return (
    <Card className="relative" role="complementary" aria-label="Session detail">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="text-heading-small truncate">{sessionName}</h2>
          <Badge variant="default">#{sessionId}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            className="text-(--color-semantic-error) hover:bg-(--color-semantic-error)/10"
            aria-label="Delete session"
            title="Remove from history; stored execution evidence is retained"
          >
            <Trash2 className="w-3.5 h-3.5 mr-1" />
            {confirmDelete ? 'Confirm?' : ''}
          </Button>
          <button
            onClick={onClose}
            aria-label="Close session detail"
            className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-(--color-semantic-error) mb-3">{error}</p>}

      {loadError ? (
        <p role="alert">{loadError.message}</p>
      ) : isLoading ? (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-12 bg-(--color-background-secondary) rounded animate-pulse" />
          ))}
        </div>
      ) : runs.length === 0 ? (
        <p className="text-body-medium text-(--color-text-secondary) py-4 text-center">
          No runs in this session yet.
        </p>
      ) : (
        <div className="space-y-2">
          {runs.map((run: Run) => {
            return (
              <RunCard
                key={run.id}
                run={run}
                isExpanded={expandedRun === run.id}
                onToggle={() => handleToggleRun(run.id)}
              />
            )
          })}
        </div>
      )}
    </Card>
  )
}
