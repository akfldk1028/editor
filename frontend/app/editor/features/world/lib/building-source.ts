import { configuredMapBase, mapAssetUrl } from './map-asset-url'
import { defaultMapReleaseReader, releaseAssetUrl, requireLegacyMapRelease } from './map-release'

const validHref = (value: unknown): value is string => typeof value === 'string'
  && /^(https?:\/\/|\/[^/])/.test(value) && /\.pmtiles(?:[?#]|$)/.test(value)

export async function loadBuildingSource(get: (url: string) => Promise<Response> = fetch, published = true, readRelease = defaultMapReleaseReader): Promise<{ href: string }> {
  const base = process.env.NEXT_PUBLIC_BASE_PATH || ''
  const publication = await readRelease()
  const release = publication ? requireLegacyMapRelease(publication) : undefined
  if (release) return { href:configuredMapBase('buildings') ? mapAssetUrl('buildings',release.buildings.href) : releaseAssetUrl(release.buildings.href) }
  const remote = configuredMapBase('buildings')
  if (remote) {
    const response = await get(`${remote}/latest.json`)
    if (!response.ok) throw new Error(`Building manifest: ${response.status}`)
    const manifest = await response.json()
    if (!/^\d{8}-[a-f0-9]{8}$/.test(manifest.version ?? '') || manifest.layer !== 'buildings') throw new Error('Invalid building archive manifest')
    return { href: `${remote}/${manifest.version}/buildings.pmtiles` }
  }
  // The baked scene already names its immutable nationwide source. Resolve that
  // static snapshot without waking SceneAgent merely to ask for the same URL.
  if (published) for (const url of [mapAssetUrl('world-buildings','latest.json'), `${base}/world-buildings/catalog.json`]) try {
    const response = await get(url)
    const catalog = response.ok ? await response.json() : null
    if (validHref(catalog?.source)) {
      const local = catalog.source.match(/^https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?\/scene\/tiles\/buildings\/(\d{8}-[0-9a-f]{8})\/buildings\.pmtiles$/)
      return { href: local ? `${base}/api/v1/land/building-tiles/${local[1]}/buildings.pmtiles` : catalog.source }
    }
  } catch { /* Older local publications retain the catalog/live manifest fallback. */ }
  const response = await get(`${base}/api/v1/land/context-tiles`)
  const manifest = await response.json()
  if (!response.ok) throw new Error(manifest.detail || `Building manifest: ${response.status}`)
  if (!validHref(manifest.href)) throw new Error('Invalid building archive URL')
  return { href: manifest.href }
}

