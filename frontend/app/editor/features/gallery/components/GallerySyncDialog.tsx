/**
 * GallerySyncDialog - Sync gallery from a remote URL
 */

import { Button, Card, Input } from '@/elements/workspace'
import { truncateError } from '@/lib/display-error'
import { RefreshCw, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useSyncGallery } from '../hooks/useGallery'

interface GallerySyncDialogProps {
  open: boolean
  onClose: () => void
}

export function GallerySyncDialog({ open, onClose }: GallerySyncDialogProps) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const syncMutation = useSyncGallery()

  useEffect(() => {
    if (open) {
      setUrl('')
      setError(null)
    }
  }, [open])

  const handleSync = useCallback(async () => {
    if (!url.trim()) return
    try {
      await syncMutation.mutateAsync(url.trim())
      onClose()
    } catch (e) {
      setError(truncateError(e instanceof Error ? e.message : 'Sync failed'))
    }
  }, [url, syncMutation, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-label="Sync gallery from URL"
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <Card className="w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-heading-small">Sync Gallery</h2>
          <button
            onClick={onClose}
            aria-label="Close sync dialog"
            className="p-1 rounded hover:bg-(--color-background-secondary) text-(--color-text-tertiary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-body-small text-(--color-text-secondary) mb-3">
          Enter a URL to a gallery JSON file to sync templates.
        </p>

        <Input
          autoFocus
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/gallery.json"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && url.trim()) handleSync()
          }}
        />

        {error && <p className="text-sm text-(--color-semantic-error) mt-3">{error}</p>}

        <div className="flex justify-end gap-2 mt-4">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSync}
            disabled={!url.trim() || syncMutation.isPending}
          >
            <RefreshCw
              className={`w-4 h-4 mr-1.5 ${syncMutation.isPending ? 'animate-spin' : ''}`}
            />
            {syncMutation.isPending ? 'Syncing...' : 'Sync'}
          </Button>
        </div>
      </Card>
    </div>
  )
}
