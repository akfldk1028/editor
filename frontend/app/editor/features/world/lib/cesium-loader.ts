/**
 * CesiumJS for the world view, loaded from the CDN — no VWorld SDK, no Cesium ion token.
 *
 * The VWorld SDK also defines window.Cesium (an older build). If the user came here from a VWorld page
 * in the same tab, that one is already loaded and is reused: one Cesium per page.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
export const CESIUM_VERSION = '1.122.0'
const BASE = `https://cdn.jsdelivr.net/npm/cesium@${CESIUM_VERSION}/Build/Cesium/`

let loading: Promise<any> | null = null

export function loadCesium(): Promise<any> {
  const w = window as any
  if (w.Cesium?.Viewer) return Promise.resolve(w.Cesium)
  if (loading) return loading
  loading = new Promise((resolve, reject) => {
    w.CESIUM_BASE_URL = BASE
    const css = document.createElement('link')
    css.rel = 'stylesheet'
    css.href = `${BASE}Widgets/widgets.css`
    document.head.appendChild(css)
    const script = document.createElement('script')
    script.src = `${BASE}Cesium.js`
    script.async = true
    script.onload = () => (w.Cesium?.Viewer ? resolve(w.Cesium) : reject(new Error('Cesium did not define a Viewer')))
    script.onerror = () => {
      loading = null
      reject(new Error(`Cesium ${CESIUM_VERSION} could not be loaded from the CDN`))
    }
    document.head.appendChild(script)
  })
  return loading
}
