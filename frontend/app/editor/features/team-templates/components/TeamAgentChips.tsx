import { closestCenter, DndContext, type DragEndEvent, type useSensors } from '@dnd-kit/core'
import { rectSortingStrategy, SortableContext } from '@dnd-kit/sortable'
import type { AgentConfig, Component } from '@/lib/contracts/workspace'
import { SortableChip } from './SortableChip'

interface TeamAgentChipsProps {
  isEditing: boolean
  sensors: ReturnType<typeof useSensors>
  handleDragEnd: (event: DragEndEvent) => void
  chipIds: string[]
  selectedParticipants: Component<AgentConfig>[]
  selectedNodeLabel: string | null
  handleNodeClick: (label: string) => void
}

export function TeamAgentChips({
  isEditing,
  sensors,
  handleDragEnd,
  chipIds,
  selectedParticipants,
  selectedNodeLabel,
  handleNodeClick,
}: TeamAgentChipsProps) {
  return isEditing ? (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={chipIds} strategy={rectSortingStrategy}>
        <div
          className="mt-3 flex flex-wrap gap-2"
          role="group"
          aria-label="Reorder agents by dragging"
        >
          {selectedParticipants.map((p, i) => {
            const chipName = p.label ?? p.config?.name ?? `agent-${i}`
            return (
              <SortableChip
                key={chipName}
                id={chipName}
                name={p.config?.name ?? `agent-${i}`}
                isSelected={chipName === selectedNodeLabel}
                onClick={() => handleNodeClick(chipName)}
              />
            )
          })}
        </div>
      </SortableContext>
    </DndContext>
  ) : (
    <div className="mt-3 flex flex-wrap gap-2">
      {selectedParticipants.map((p, i) => {
        const chipName = p.label ?? p.config?.name ?? `agent-${i}`
        const isSelected = chipName === selectedNodeLabel
        return (
          <span
            key={chipName}
            role="button"
            tabIndex={0}
            aria-pressed={isSelected}
            className={`text-xs px-2 py-1 rounded-full cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary) ${
              isSelected
                ? 'bg-(--color-accent-primary) text-white'
                : 'bg-(--color-background-secondary) text-(--color-text-secondary)'
            }`}
            onClick={() => handleNodeClick(chipName)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                handleNodeClick(chipName)
              }
            }}
          >
            {p.config?.name ?? `agent-${i}`}
          </span>
        )
      })}
    </div>
  )
}
