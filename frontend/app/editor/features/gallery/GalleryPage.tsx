'use client'
import { Button, Card } from '@/elements/workspace'
import type { Gallery } from '@/lib/contracts/workspace'
import { Plus, RefreshCw } from 'lucide-react'
import { useCallback, useState } from 'react'
import { GalleryDetail, GalleryImportDialog, GallerySyncDialog } from './components'
import { GalleryCard } from './components/GalleryCard'
import { useGalleries } from './hooks/useGallery'

export function GalleryPage() {
  const { data: galleries, isLoading, error } = useGalleries()
  const [importTarget, setImportTarget] = useState<Gallery | null>(null)
  const [syncOpen, setSyncOpen] = useState(false)
  const [selectedGalleryId, setSelectedGalleryId] = useState<number | null>(null)

  const handleImport = useCallback((gallery: Gallery) => {
    setImportTarget(gallery)
  }, [])
  const handleCloseImport = useCallback(() => setImportTarget(null), [])
  const handleCloseSync = useCallback(() => setSyncOpen(false), [])

  const handleSelectGallery = useCallback((gallery: Gallery) => {
    setSelectedGalleryId(gallery.id ?? null)
  }, [])

  const handleBackToList = useCallback(() => {
    setSelectedGalleryId(null)
  }, [])

  // Find the selected gallery object
  const selectedGallery =
    selectedGalleryId !== null
      ? (galleries?.find((g: Gallery) => g.id === selectedGalleryId) ?? null)
      : null

  // -- Detail view --
  if (selectedGallery) {
    return (
      <div className="space-y-6">
        <GalleryDetail gallery={selectedGallery} onBack={handleBackToList} />
      </div>
    )
  }

  // -- List view --
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-display-medium">Gallery</h1>
          <p className="text-body-medium text-(--color-text-secondary) mt-1">
            Reusable agent team templates
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => setSyncOpen(true)}>
            <RefreshCw className="w-4 h-4 mr-2" />
            Sync Gallery
          </Button>
          <Button disabled title="Coming soon">
            <Plus className="w-4 h-4 mr-2" />
            New Gallery
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-(--color-semantic-error)">
          {error.message}
        </p>
      )}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <div className="h-4 bg-(--color-background-secondary) rounded w-3/4" />
              <div className="h-3 bg-(--color-background-secondary) rounded w-1/2 mt-3" />
              <div className="h-8 bg-(--color-background-secondary) rounded w-20 mt-4" />
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {galleries?.map((gallery: Gallery) => (
            <GalleryCard
              key={gallery.id}
              gallery={gallery}
              onImport={() => handleImport(gallery)}
              onSelect={() => handleSelectGallery(gallery)}
            />
          ))}
          {!error && (!galleries || galleries.length === 0) && (
            <Card className="col-span-full text-center py-12">
              <p className="text-body-large text-(--color-text-secondary)">
                No gallery items yet. Create templates from the Team Builder.
              </p>
            </Card>
          )}
        </div>
      )}

      {/* Dialogs */}
      <GalleryImportDialog gallery={importTarget} onClose={handleCloseImport} />
      <GallerySyncDialog open={syncOpen} onClose={handleCloseSync} />
    </div>
  )
}
