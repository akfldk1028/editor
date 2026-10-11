export function cadastralTileSource(src: string, zoom: number): string | null {
  try {
    const url = new URL(src)
    const path = url.pathname.match(/^\/styles\/([^/]+)\/([^/]+)\/(\d+)\/\d+\/\d+\.png$/)
    const layers = url.searchParams.get('mt')?.split('.') ?? []
    if (!url.hostname.endsWith('.map.naver.net') || !path || Number(path[3]) !== zoom || !layers.includes('lp')) return null
    return `${url.hostname}/${path[1]}/${path[2]}?mt=${layers.join('.')}`
  } catch { return null }
}

export function captureCadastralRaster(element: HTMLElement, zoom: number): { raster: ImageData; sourceId: string } | null {
  const bounds = element.getBoundingClientRect()
  if (!bounds.width || !bounds.height) return null
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bounds.width)
  canvas.height = Math.round(bounds.height)
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return null
  let sourceId: string | null = null
  try {
    for (const image of element.querySelectorAll<HTMLImageElement>('img[crossorigin="anonymous"]')) {
      const box = image.getBoundingClientRect()
      if (!box.width || !box.height || box.right <= bounds.left || box.left >= bounds.right || box.bottom <= bounds.top || box.top >= bounds.bottom) continue
      const source = cadastralTileSource(image.currentSrc || image.src, zoom)
      // Unknown layers, mixed tile generations and incomplete tiles cannot validate a contour.
      if (!source || (sourceId && sourceId !== source) || !image.complete || !image.naturalWidth) return null
      sourceId = source
      context.drawImage(image, box.left - bounds.left, box.top - bounds.top, box.width, box.height)
    }
    return sourceId ? { raster: context.getImageData(0, 0, canvas.width, canvas.height), sourceId } : null
  } catch { return null }
}
