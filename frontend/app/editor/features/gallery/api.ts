import type { Gallery, GalleryConfig } from '@/lib/contracts/workspace'
import { workspaceRequest } from '@/lib/workspace-request'
export const galleryAPI = {
  list: () => workspaceRequest<Gallery[]>('galleries'),
  sync: async (input: string) => {
    const url = new URL(input)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
      throw new Error('Enter an HTTP or HTTPS gallery URL without credentials.')
    const response = await fetch(url, {
      credentials: 'omit',
      headers: { Accept: 'application/json' },
      signal: AbortSignal.timeout(30000),
    })
    if (!response.ok) throw new Error(`Gallery download failed (${response.status})`)
    const document = (await response.json()) as Gallery | GalleryConfig
    const config = 'config' in document ? document.config : document
    return workspaceRequest<Gallery>('galleries', {
      method: 'POST',
      body: JSON.stringify({ config }),
    })
  },
}
