import type { FileAttachment } from '@/features/playground/api/execution-client'

/** Clipboard paste → image / large-text file attachments (PlaygroundPage 입력창) */
export function handleClipboardPaste(
  e: React.ClipboardEvent,
  setFiles: React.Dispatch<React.SetStateAction<FileAttachment[]>>,
) {
  // Handle image paste from clipboard
  const items = Array.from(e.clipboardData.items)
  const imageItems = items.filter((item) => item.type.startsWith('image/'))

  if (imageItems.length > 0) {
    e.preventDefault()
    const imageFiles: File[] = []
    for (const item of imageItems) {
      const file = item.getAsFile()
      if (file) imageFiles.push(file)
    }
    if (imageFiles.length > 0) {
      // Read images and add to files
      Promise.all(
        imageFiles.map(async (file) => {
          const reader = new FileReader()
          return new Promise<FileAttachment>((resolve, reject) => {
            reader.onload = () => {
              resolve({
                name: file.name || `pasted-image-${Date.now()}.png`,
                type: file.type,
                content: (reader.result as string).split(',')[1] ?? '',
              })
            }
            reader.onerror = () => reject(reader.error)
            reader.readAsDataURL(file)
          })
        }),
      )
        .then((newAttachments) => {
          setFiles((prev) => [...prev, ...newAttachments])
        })
        .catch(() => {
          /* Silently ignore paste read failures */
        })
    }
    return
  }

  // Handle large text paste -> auto-convert to file attachment
  const pastedText = e.clipboardData.getData('text/plain')
  if (pastedText.length > 1500) {
    e.preventDefault()
    const content = btoa(unescape(encodeURIComponent(pastedText)))
    setFiles((prev) => [
      ...prev,
      {
        name: `pasted-text-${Date.now()}.txt`,
        type: 'text/plain',
        content,
      },
    ])
  }
}
