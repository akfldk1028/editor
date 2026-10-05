/**
 * TeamDeleteDialog - Destructive confirmation dialog for deleting a team
 * Requires user to type the team name to confirm
 */

import { Button, Card, Input } from '@/elements/workspace'
import type { TeamResponse } from '@/features/team-templates/api'
import { truncateError } from '@/lib/display-error'
import { Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { getTeamName, useDeleteTeam } from '../hooks/useTeams'

interface TeamDeleteDialogProps {
  team: TeamResponse | null
  onClose: () => void
}

export function TeamDeleteDialog({ team, onClose }: TeamDeleteDialogProps) {
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const deleteMutation = useDeleteTeam()

  useEffect(() => {
    if (team) {
      setConfirmation('')
      setError(null)
    }
  }, [team])

  const name = team ? getTeamName(team) : ''
  const isConfirmed = confirmation === name

  const handleDelete = useCallback(async () => {
    if (!team || !isConfirmed) return
    try {
      await deleteMutation.mutateAsync(team.id)
      onClose()
    } catch (e) {
      setError(truncateError(e instanceof Error ? e.message : 'Failed to delete team'))
    }
  }, [team, isConfirmed, deleteMutation, onClose])

  if (!team) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="alertdialog"
      aria-modal="true"
      aria-label="Delete team confirmation"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <Card className="w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-heading-small text-(--color-semantic-error)">Delete Team</h2>
          <button
            onClick={onClose}
            aria-label="Close delete dialog"
            className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-body-medium text-(--color-text-secondary)">
          This action cannot be undone. Type{' '}
          <strong className="text-(--color-text-primary)">{name}</strong> to confirm deletion.
        </p>

        <Input
          autoFocus
          className="mt-3"
          value={confirmation}
          onChange={(e) => setConfirmation(e.target.value)}
          placeholder={name}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && isConfirmed) handleDelete()
          }}
        />

        {error && <p className="text-sm text-(--color-semantic-error) mt-3">{error}</p>}

        <div className="flex justify-end gap-2 mt-4">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleDelete}
            disabled={!isConfirmed || deleteMutation.isPending}
            className="bg-(--color-semantic-error) hover:bg-(--color-semantic-error)/90"
          >
            <Trash2 className="w-4 h-4 mr-1.5" />
            {deleteMutation.isPending ? 'Deleting...' : 'Delete Team'}
          </Button>
        </div>
      </Card>
    </div>
  )
}
