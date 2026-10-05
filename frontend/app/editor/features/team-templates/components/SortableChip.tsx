import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { memo } from 'react'
export const SortableChip = memo(function SortableChip({
  id,
  name,
  isSelected,
  onClick,
}: {
  id: string
  name: string
  isSelected: boolean
  onClick: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
  })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }
  return (
    <span
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      aria-pressed={isSelected}
      className={`text-xs px-2 py-1 rounded-full cursor-grab active:cursor-grabbing transition-colors focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary) ${
        isSelected
          ? 'bg-(--color-accent-primary) text-white'
          : 'bg-(--color-background-secondary) text-(--color-text-secondary)'
      }`}
      onClick={onClick}
    >
      {name}
    </span>
  )
})
