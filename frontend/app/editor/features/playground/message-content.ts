export function messageContent(value: unknown): { content: string; images: string[] } {
  const text: string[] = []
  const images: string[] = []
  for (const item of Array.isArray(value) ? value : [value]) {
    if (typeof item === 'string') text.push(item)
    else if (item && typeof item === 'object' && 'data' in item && typeof item.data === 'string'
      && /^[A-Za-z0-9+/=]+$/.test(item.data)) {
      // AutoGen Image.model_dump serializes its image as PNG base64.
      images.push(`data:image/png;base64,${item.data}`)
    } else if (item != null) text.push(JSON.stringify(item))
  }
  return { content: text.join('\n'), images }
}
