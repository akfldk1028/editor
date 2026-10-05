import { Badge, Button, Card } from '@/elements/workspace'
import type { TeamResponse } from '@/features/team-templates/api'
import { Play, Settings, Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { memo } from 'react'
import { getTeamName, getTeamPattern } from '../hooks/useTeams'
import { PATTERN_COLORS, getParticipants } from '../model/presentation'
import { useTeamStore } from '../model/team-store'
export const TeamCard = memo(function TeamCard({
  team,
  isSelected,
  onSelect,
  onDelete,
}: {
  team: TeamResponse
  isSelected: boolean
  onSelect: () => void
  onDelete: () => void
}) {
  const router = useRouter()
  const { selectTeam } = useTeamStore()
  const name = getTeamName(team)
  const pattern = getTeamPattern(team)
  const participants = getParticipants(team)

  return (
    <Card
      className={`hover:shadow-lg transition-shadow cursor-pointer ${isSelected ? 'ring-2 ring-(--color-accent-primary)' : ''}`}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-heading-small">{name}</h3>
          <p className="text-body-small text-(--color-text-tertiary) mt-1">
            {participants.length} agents
          </p>
        </div>
        <Badge variant={PATTERN_COLORS[pattern] ?? 'default'}>{pattern}</Badge>
      </div>
      <div className="flex gap-2 mt-4">
        <Button
          size="sm"
          variant="primary"
          onClick={(e) => {
            e.stopPropagation()
            selectTeam(team.id)
            router.push('/playground')
          }}
        >
          <Play className="w-3.5 h-3.5 mr-1.5" />
          Run
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={(e) => {
            e.stopPropagation()
            onSelect()
          }}
        >
          <Settings className="w-3.5 h-3.5 mr-1.5" />
          Edit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
          aria-label={`Delete team ${name}`}
          className="text-(--color-semantic-error) hover:bg-(--color-semantic-error)/10"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </Button>
      </div>
    </Card>
  )
})
