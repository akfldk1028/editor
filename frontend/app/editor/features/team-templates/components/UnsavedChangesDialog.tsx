import { Button } from '@/elements/workspace'
import { AlertCircle } from 'lucide-react'
import { useEffect, useRef } from 'react'
export function UnsavedChangesDialog({
  onStay,
  onLeave,
}: {
  onStay: () => void
  onLeave: () => void
}) {
  const dialogRef = useRef<HTMLDivElement>(null)

  // Focus trap + Escape key
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return

    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button, [tabindex]:not([tabindex="-1"])',
    )
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    first?.focus()

    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onStay()
        return
      }
      if (e.key === 'Tab') {
        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault()
            last?.focus()
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault()
            first?.focus()
          }
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onStay])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onStay}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-label="Unsaved changes"
        className="bg-(--color-background-primary) rounded-xl shadow-xl p-6 max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-4">
          <AlertCircle className="w-6 h-6 text-(--color-semantic-warning) shrink-0" />
          <h2 className="text-heading-small">Unsaved Changes</h2>
        </div>
        <p className="text-body-medium text-(--color-text-secondary) mb-6">
          You have unsaved changes to this team. Leaving will discard them.
        </p>
        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onStay}>
            Stay
          </Button>
          <Button
            variant="primary"
            className="bg-(--color-semantic-error) hover:bg-(--color-semantic-error)/90"
            onClick={onLeave}
          >
            Leave
          </Button>
        </div>
      </div>
    </div>
  )
}
