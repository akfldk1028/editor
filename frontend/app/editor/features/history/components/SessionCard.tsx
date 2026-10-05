import { memo, useCallback } from 'react'
import { Card, Badge } from '@/elements/workspace'
import { Clock, MessageSquare } from 'lucide-react'

export const SessionCard = memo(function SessionCard({
  sessionId,
  sessionName,
  teamId,
  createdAt,
  isSelected,
  compareSlot,
  onSelect,
}: {
  sessionId: number
  sessionName: string
  teamId: number | undefined
  createdAt: string | undefined
  isSelected: boolean
  compareSlot: string | null
  onSelect: (id: number) => void
}) {
  const handleClick = useCallback(() => onSelect(sessionId), [onSelect, sessionId])
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onSelect(sessionId)
      }
    },
    [onSelect, sessionId],
  )

  return (
    <Card
      className={`flex items-center justify-between hover:shadow-lg transition-shadow cursor-pointer ${
        isSelected ? 'ring-2 ring-(--color-accent-primary)' : ''
      }`}
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      <div className="flex items-center gap-3">
        <MessageSquare className="w-5 h-5 text-(--color-text-tertiary)" aria-hidden="true" />
        <div>
          <p className="text-label">{sessionName}</p>
          <p className="text-body-small text-(--color-text-tertiary)">Team #{teamId}</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {compareSlot && <Badge variant="primary">{compareSlot}</Badge>}
        <Clock className="w-4 h-4 text-(--color-text-tertiary)" aria-hidden="true" />
        <span className="text-body-small text-(--color-text-tertiary)">
          {createdAt ? new Date(createdAt).toLocaleDateString() : 'N/A'}
        </span>
        <Badge>#{sessionId}</Badge>
      </div>
    </Card>
  )
})
