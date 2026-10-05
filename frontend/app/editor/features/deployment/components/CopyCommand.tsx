import { useState } from 'react'
import { Button } from '@/elements/workspace'

export function CopyCommand({
  text,
  label,
  disabled = false,
}: {
  text: string
  label: string
  disabled?: boolean
}) {
  const [message, setMessage] = useState('')
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="secondary"
        size="sm"
        disabled={disabled}
        aria-label={label}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text)
            setMessage('Copied!')
          } catch {
            setMessage('Copy failed. Select and copy the command below.')
          }
        }}
      >
        {label}
      </Button>
      <span role="status" className="text-body-small">
        {message}
      </span>
    </div>
  )
}
