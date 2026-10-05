import { Badge, Button, Card } from '@/elements/workspace'
import type { Gallery } from '@/lib/contracts/workspace'
import { Download, GalleryHorizontalEnd } from 'lucide-react'
import { memo, useCallback } from 'react'
export const GalleryCard = memo(function GalleryCard({
  gallery,
  onImport,
  onSelect,
}: {
  gallery: Gallery
  onImport: () => void
  onSelect: () => void
}) {
  const config = gallery.config
  const name = config?.name ?? `Gallery #${gallery.id}`
  const description = config?.metadata?.description ?? 'Team template'
  const teamCount = config?.components?.teams?.length ?? 0
  const agentCount = config?.components?.agents?.length ?? 0
  const modelCount = config?.components?.models?.length ?? 0
  const toolCount = config?.components?.tools?.length ?? 0
  const totalCount = teamCount + agentCount + modelCount + toolCount

  const handleCardClick = useCallback(() => {
    onSelect()
  }, [onSelect])

  const handleCardKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onSelect()
      }
    },
    [onSelect],
  )

  const handleImportClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      onImport()
    },
    [onImport],
  )

  return (
    <Card
      className="hover:shadow-lg transition-shadow cursor-pointer"
      role="button"
      tabIndex={0}
      aria-label={`View gallery: ${name}`}
      onClick={handleCardClick}
      onKeyDown={handleCardKeyDown}
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-(--color-background-secondary) flex items-center justify-center shrink-0">
          <GalleryHorizontalEnd
            className="w-5 h-5 text-(--color-text-secondary)"
            aria-hidden="true"
          />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-heading-small truncate">{name}</h3>
          <p className="text-body-small text-(--color-text-tertiary) mt-1 line-clamp-2">
            {description}
          </p>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            {teamCount > 0 && (
              <span className="inline-block">
                <Badge variant="primary">{teamCount} teams</Badge>
              </span>
            )}
            {agentCount > 0 && (
              <span className="inline-block">
                <Badge variant="outline">{agentCount} agents</Badge>
              </span>
            )}
            {modelCount > 0 && (
              <span className="inline-block">
                <Badge variant="default">{modelCount} models</Badge>
              </span>
            )}
            {toolCount > 0 && (
              <span className="inline-block">
                <Badge variant="default">{toolCount} tools</Badge>
              </span>
            )}
            {totalCount === 0 && (
              <span className="text-body-small text-(--color-text-tertiary)">Empty</span>
            )}
          </div>
        </div>
      </div>
      <div className="flex gap-2 mt-4">
        <Button
          size="sm"
          variant="primary"
          onClick={handleImportClick}
          aria-label={`Import team from ${name}`}
        >
          <Download className="w-3.5 h-3.5 mr-1.5" aria-hidden="true" />
          Import
        </Button>
      </div>
    </Card>
  )
})
