import { Badge, Input } from '@/elements/workspace'
import { Eye, EyeOff, Trash2 } from 'lucide-react'
import { memo, useCallback, useMemo, useState } from 'react'
import type { EnvironmentVariable } from '../model/types'
interface EnvVarRowProps {
  envVar: EnvironmentVariable
  onDelete: (name: string) => void
  onValueChange: (name: string, value: string) => void
}

export const EnvVarRow = memo(function EnvVarRow({
  envVar,
  onDelete,
  onValueChange,
}: EnvVarRowProps) {
  const [showValue, setShowValue] = useState(false)
  const isSecret = envVar.type === 'secret'

  const handleToggleVisibility = useCallback(() => {
    setShowValue((prev) => !prev)
  }, [])

  const handleDelete = useCallback(() => {
    onDelete(envVar.name)
  }, [onDelete, envVar.name])

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onValueChange(envVar.name, e.target.value)
    },
    [onValueChange, envVar.name],
  )

  const badgeVariant = useMemo(() => {
    switch (envVar.type) {
      case 'secret':
        return 'error' as const
      case 'number':
        return 'primary' as const
      case 'boolean':
        return 'warning' as const
      default:
        return 'default' as const
    }
  }, [envVar.type])

  return (
    <tr className="border-b border-(--color-border-default) last:border-b-0">
      <td className="py-2 pr-3">
        <span className="text-label-small font-mono">{envVar.name}</span>
      </td>
      <td className="py-2 pr-3">
        <div className="flex items-center gap-2">
          <Input
            type={isSecret && !showValue ? 'password' : 'text'}
            value={envVar.value}
            onChange={handleChange}
            aria-label={`Value for ${envVar.name}`}
            className="h-8 text-body-small font-mono"
          />
          {isSecret && (
            <button
              type="button"
              onClick={handleToggleVisibility}
              className="p-1 rounded text-(--color-text-tertiary) hover:text-(--color-text-primary) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
              aria-label={
                showValue ? `Hide value for ${envVar.name}` : `Show value for ${envVar.name}`
              }
            >
              {showValue ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          )}
        </div>
      </td>
      <td className="py-2 pr-3">
        <span className="inline-block">
          <Badge variant={badgeVariant}>{envVar.type}</Badge>
        </span>
      </td>
      <td className="py-2 pr-3">
        <span className="text-body-small text-(--color-text-tertiary)">
          {envVar.description ?? '-'}
        </span>
      </td>
      <td className="py-2">
        <button
          type="button"
          onClick={handleDelete}
          className="p-1 rounded text-(--color-text-tertiary) hover:text-(--color-semantic-error) focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)"
          aria-label={`Delete ${envVar.name}`}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </td>
    </tr>
  )
})
