import { useCallback, useEffect, useRef, useState } from 'react'
import type { FileAttachment } from '@/features/playground/api/execution-client'
import { Paperclip, X, FileText, Image } from 'lucide-react'
import { cn } from '@/lib/utils'

const MAX_FILE_SIZE = 5 * 1024 * 1024 // 5MB

interface FileUploadProps {
  files: FileAttachment[]
  onFilesChange: (files: FileAttachment[]) => void
  disabled?: boolean
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve((reader.result as string).split(',')[1] ?? '') // strip data:... prefix
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function getFileIcon(type: string) {
  if (type.startsWith('image/')) {
    return <Image className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
  }
  return <FileText className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FileUpload({ files, onFilesChange, disabled }: FileUploadProps) {
  const [error, setError] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const errorTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cleanup error timeout on unmount
  useEffect(() => {
    return () => {
      if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current)
    }
  }, [])

  const showError = useCallback((msg: string) => {
    if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current)
    setError(msg)
    errorTimeoutRef.current = setTimeout(() => setError(null), 4000)
  }, [])

  const processFiles = useCallback(async (fileList: File[]) => {
    const newFiles: FileAttachment[] = []
    for (const file of fileList) {
      if (file.size > MAX_FILE_SIZE) {
        showError(`"${file.name}" exceeds 5MB limit (${formatFileSize(file.size)})`)
        continue
      }
      // Only allow text and image types
      if (!file.type.startsWith('text/') && !file.type.startsWith('image/') && !isTextLikeType(file.type)) {
        showError(`"${file.name}" is not a supported file type. Only text and images are allowed.`)
        continue
      }
      try {
        const content = await readFileAsBase64(file)
        newFiles.push({ name: file.name, type: file.type, content })
      } catch {
        showError(`Failed to read "${file.name}"`)
      }
    }
    if (newFiles.length > 0) {
      onFilesChange([...files, ...newFiles])
    }
  }, [files, onFilesChange, showError])

  const handleFileSelect = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const fileList = e.target.files
    if (fileList) {
      processFiles(Array.from(fileList))
    }
    // Reset input so the same file can be re-selected
    e.target.value = ''
  }, [processFiles])

  const handleRemoveFile = useCallback((index: number) => {
    onFilesChange(files.filter((_, i) => i !== index))
  }, [files, onFilesChange])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!disabled) setIsDragOver(true)
  }, [disabled])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
    if (disabled) return
    const droppedFiles = Array.from(e.dataTransfer.files)
    if (droppedFiles.length > 0) {
      processFiles(droppedFiles)
    }
  }, [disabled, processFiles])

  return (
    <div
      className={cn(
        'flex flex-col gap-2',
        isDragOver && 'ring-2 ring-(--color-accent-primary) rounded-lg',
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* File list */}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {files.map((file, i) => (
            <span
              key={`${file.name}-${i}`}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-(--color-background-secondary) text-body-small text-(--color-text-secondary) max-w-[200px]"
            >
              {getFileIcon(file.type)}
              <span className="truncate">{file.name}</span>
              <button
                type="button"
                onClick={() => handleRemoveFile(i)}
                className="ml-0.5 p-0.5 rounded hover:bg-(--color-border-default) transition-colors focus:outline-none focus:ring-1 focus:ring-(--color-accent-primary)"
                aria-label={`Remove ${file.name}`}
                disabled={disabled}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Error message */}
      {error && (
        <p className="text-body-small text-(--color-semantic-error)" role="alert">
          {error}
        </p>
      )}

      {/* Attach button + hidden file input (exposed via getAttachButton / getPasteHandler) */}
      <button
        type="button"
        onClick={handleFileSelect}
        disabled={disabled}
        className={cn(
          'inline-flex items-center justify-center w-10 h-10 rounded-md transition-colors',
          'text-(--color-text-tertiary) hover:text-(--color-text-secondary) hover:bg-(--color-background-secondary)',
          'focus:outline-none focus:ring-2 focus:ring-(--color-accent-primary)/20',
          'disabled:opacity-50 disabled:cursor-not-allowed',
        )}
        aria-label="Attach file"
      >
        <Paperclip className="w-5 h-5" />
      </button>

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="text/*,image/*,.txt,.md,.json,.csv,.xml,.html,.css,.js,.ts,.tsx,.jsx,.py,.yaml,.yml,.log"
        onChange={handleFileInputChange}
        className="hidden"
        aria-hidden="true"
      />
    </div>
  )
}

/** Expose paste handler for parent to attach to input */
export { type FileUploadProps }

/** Check if a MIME type is text-like (covers application/json, etc.) */
function isTextLikeType(mime: string): boolean {
  const textLikeTypes = [
    'application/json',
    'application/xml',
    'application/javascript',
    'application/typescript',
    'application/x-yaml',
    'application/yaml',
    'application/csv',
    'application/x-python',
  ]
  return textLikeTypes.includes(mime)
}
