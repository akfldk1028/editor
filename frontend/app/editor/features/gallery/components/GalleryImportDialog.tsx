/**
 * GalleryImportDialog - Select a team template from a gallery to import
 */

import { Badge, Button, Card } from '@/elements/workspace'
import type { Component, Gallery, TeamConfig } from '@/lib/contracts/workspace'
import { truncateError } from '@/lib/display-error'
import { Download, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useImportGalleryTeam } from '../hooks/useGallery'

interface GalleryImportDialogProps {
  gallery: Gallery | null
  onClose: () => void
}

export function GalleryImportDialog({ gallery, onClose }: GalleryImportDialogProps) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const importMutation = useImportGalleryTeam()

  useEffect(() => {
    if (gallery) {
      setSelectedIndex(null)
      setError(null)
    }
  }, [gallery])

  const teams = gallery?.config?.components?.teams ?? []

  const handleImport = useCallback(async () => {
    if (selectedIndex === null || !teams[selectedIndex]) return
    try {
      await importMutation.mutateAsync(teams[selectedIndex])
      onClose()
    } catch (e) {
      setError(truncateError(e instanceof Error ? e.message : 'Import failed'))
    }
  }, [selectedIndex, teams, importMutation, onClose])

  if (!gallery) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="Import team from gallery"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <Card
        className="w-full max-w-lg mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-heading-small">Import from {gallery.config?.name ?? 'Gallery'}</h2>
          <button
            onClick={onClose}
            aria-label="Close import dialog"
            className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {teams.length === 0 ? (
          <p className="text-body-medium text-(--color-text-secondary) py-4 text-center">
            No team templates in this gallery.
          </p>
        ) : (
          <div className="space-y-2" role="radiogroup" aria-label="Select team to import">
            {teams.map((team: Component<TeamConfig>, i: number) => {
              const isSelected = selectedIndex === i
              const name = team.label ?? `Team ${i + 1}`
              const agentCount = (
                ((team.config as unknown as Record<string, unknown>)?.participants as unknown[]) ??
                []
              ).length
              return (
                <div
                  key={i}
                  role="radio"
                  aria-checked={isSelected}
                  tabIndex={isSelected ? 0 : -1}
                  onClick={() => setSelectedIndex(i)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelectedIndex(i)
                    }
                  }}
                  className={`p-3 rounded-lg border cursor-pointer transition-all ${
                    isSelected
                      ? 'ring-2 ring-(--color-accent-primary) border-(--color-accent-primary) bg-(--color-background-secondary)'
                      : 'border-(--color-border-default) hover:border-(--color-accent-primary)'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">{name}</span>
                    <div className="flex gap-1.5">
                      {agentCount > 0 && <Badge variant="default">{agentCount} agents</Badge>}
                      <Badge variant="outline">{team.provider?.split('.').pop() ?? 'Team'}</Badge>
                    </div>
                  </div>
                  {team.description && (
                    <p className="text-xs text-(--color-text-tertiary) mt-1">{team.description}</p>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {error && <p className="text-sm text-(--color-semantic-error) mt-3">{error}</p>}

        <div className="flex justify-end gap-2 mt-4">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleImport}
            disabled={selectedIndex === null || importMutation.isPending}
          >
            <Download className="w-4 h-4 mr-1.5" />
            {importMutation.isPending ? 'Importing...' : 'Import Team'}
          </Button>
        </div>
      </Card>
    </div>
  )
}
