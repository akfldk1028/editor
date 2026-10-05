/**
 * TeamCreateDialog - Dialog for creating a new team
 * Name (required) + description (optional) + pattern selection
 */

import { Button, Card, Input } from '@/elements/workspace'
import type { PatternType } from '@/features/team-builder'
import { PatternSelector, patternToProvider } from '@/features/team-builder'
import { truncateError } from '@/lib/display-error'
import { Plus, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useCreateTeam } from '../hooks/useTeams'

interface TeamCreateDialogProps {
  open: boolean
  onClose: () => void
}

/** Build minimal team config for selected pattern */
function buildTeamConfig(pattern: PatternType): Record<string, unknown> {
  const base: Record<string, unknown> = {
    participants: [],
    max_turns: 10,
  }
  if (pattern === 'selector' || pattern === 'debate') {
    base.selector_prompt = 'Select the most appropriate agent for the current task.'
    base.allow_repeated_speaker = false
    base.model_client = {
      provider: 'autogen_ext.models.openai.OpenAIChatCompletionClient',
      component_type: 'model',
      config: { model: 'gpt-4o' },
    }
  }
  return base
}

export function TeamCreateDialog({ open, onClose }: TeamCreateDialogProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [pattern, setPattern] = useState<PatternType>('sequential')
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateTeam()

  useEffect(() => {
    if (open) {
      setName('')
      setDescription('')
      setPattern('sequential')
      setError(null)
    }
  }, [open])

  const handleCreate = useCallback(async () => {
    if (!name.trim()) return
    try {
      const provider = patternToProvider(pattern)
      const config = buildTeamConfig(pattern)
      await createMutation.mutateAsync({
        component: {
          provider,
          component_type: 'team',
          label: name.trim(),
          description: description.trim() || null,
          config,
        },
      })
      onClose()
    } catch (e) {
      setError(truncateError(e instanceof Error ? e.message : 'Failed to create team'))
    }
  }, [name, description, pattern, createMutation, onClose])

  const handlePatternSelect = useCallback((p: PatternType) => {
    setPattern(p)
  }, [])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="Create new team"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <Card className="w-full max-w-lg mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-heading-small">Create New Team</h2>
          <button
            onClick={onClose}
            aria-label="Close create dialog"
            className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
              Team Name <span className="text-(--color-semantic-error)">*</span>
            </label>
            <Input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Agent Team"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && name.trim()) handleCreate()
              }}
            />
          </div>

          <div>
            <label className="text-sm font-medium text-(--color-text-secondary) mb-1 block">
              Description
            </label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional team description..."
            />
          </div>

          <div>
            <label className="text-sm font-medium text-(--color-text-secondary) mb-2 block">
              Team Pattern
            </label>
            <PatternSelector currentPattern={pattern} onSelect={handlePatternSelect} />
          </div>
        </div>

        {error && <p className="text-sm text-(--color-semantic-error) mt-3">{error}</p>}

        <div className="flex justify-end gap-2 mt-6">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleCreate}
            disabled={!name.trim() || createMutation.isPending}
          >
            <Plus className="w-4 h-4 mr-1.5" />
            {createMutation.isPending ? 'Creating...' : 'Create Team'}
          </Button>
        </div>
      </Card>
    </div>
  )
}
