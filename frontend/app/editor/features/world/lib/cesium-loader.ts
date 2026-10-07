/**
 * CesiumJS 1.122 for the clean world, loaded from the CDN — no VWorld SDK, no Cesium ion token.
 *
 * The VWorld SDK brings its own, older Cesium on the same global (window.Cesium) and finds its workers through
 * the same CESIUM_BASE_URL. The two must never see each other's: ours is kept aside after loading and put on the
 * globals only while a clean-world viewer is mounted (acquireCesium returns a release that puts back what was
 * there), so switching engines in one tab never mixes builds.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
export const CESIUM_VERSION = '1.122.0'
const BASE = `https://cdn.jsdelivr.net/npm/cesium@${CESIUM_VERSION}/Build/Cesium/`

let ours: Promise<any> | null = null

function load(): Promise<any> {
  if (ours) return ours
  ours = new Promise((resolve, reject) => {
    const w = window as any
    const before = { Cesium: w.Cesium, base: w.CESIUM_BASE_URL }
    const restore = () => {
      w.Cesium = before.Cesium   // whatever (VWorld's) was there; ours is handed out by acquireCesium
      w.CESIUM_BASE_URL = before.base
    }
    w.CESIUM_BASE_URL = BASE
    const css = document.createElement('link')
    css.rel = 'stylesheet'
    css.href = `${BASE}Widgets/widgets.css`
    document.head.appendChild(css)
    const script = document.createElement('script')
    script.src = `${BASE}Cesium.js`
    script.async = true
    script.onload = () => {
      const C = w.Cesium
      restore()
      if (C?.Viewer && C.CustomHeightmapTerrainProvider) resolve(C)
      else reject(new Error('Cesium did not load as expected'))
    }
    script.onerror = () => {
      ours = null
      restore()
      reject(new Error(`Cesium ${CESIUM_VERSION} could not be loaded from the CDN`))
    }
    document.head.appendChild(script)
  })
  return ours
}

// Counted, not stacked: React (StrictMode, fast remounts) can release an early acquire after a later one, and the
// globals must stay ours until the last clean-world viewer is gone.
let holders = 0
let saved: { Cesium: any; base: any } | null = null

/** Our Cesium, put on the globals until the last `release()` (the design view's renderers read window.Cesium). */
export async function acquireCesium(): Promise<{ Cesium: any; release: () => void }> {
  const C = await load()
  const w = window as any
  if (holders === 0) saved = { Cesium: w.Cesium === C ? undefined : w.Cesium, base: w.CESIUM_BASE_URL === BASE ? undefined : w.CESIUM_BASE_URL }
  holders++
  w.Cesium = C
  w.CESIUM_BASE_URL = BASE
  let released = false
  return {
    Cesium: C,
    release: () => {
      if (released) return
      released = true
      holders--
      if (holders > 0 || !saved) return
      if (w.Cesium === C) w.Cesium = saved.Cesium
      if (w.CESIUM_BASE_URL === BASE) w.CESIUM_BASE_URL = saved.base
      saved = null
    },
  }
}
