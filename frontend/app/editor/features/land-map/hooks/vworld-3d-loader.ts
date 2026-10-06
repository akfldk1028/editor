/**
 * Vworld 3D SDK loader — 동적 전역(vw/ws3d/Cesium) 접근 + 스크립트 로드
 * (use-vworld-3d.ts 에서 분리)
 */

// ---------------------------------------------------------------------------
// Dynamically-loaded globals accessor
// ---------------------------------------------------------------------------

/* eslint-disable @typescript-eslint/no-explicit-any */
export const getVw = (): any => (window as any).vw
export const getWs3d = (): any => (window as any).ws3d
export const getCesium = (): any => (window as any).Cesium

// ---------------------------------------------------------------------------
// Script loader (idempotent — 한 번만 로드)
//
// 핵심 문제: webglMapInit.js.do 부트스트랩이 document.write()로 3개
// 하위 스크립트(Cesium 등)를 주입하는데, 동적 <script>에서
// document.write()는 브라우저가 무시함.
//
// 해결: document.write를 오버라이드 → <script> 태그로 부트스트랩 로드
//       → 인터셉트한 URL들을 순차 <script> 태그로 로드 → poll vw.Map
//
// <script> 태그 로딩은 CORS 면제 (fetch와 다름).
// ---------------------------------------------------------------------------

let scriptPromise: Promise<void> | null = null
export const sdkStyles = new Set<HTMLLinkElement>()

export function canCreateWebGLContext(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(
      canvas.getContext('webgl2') ||
        canvas.getContext('webgl') ||
        canvas.getContext('experimental-webgl'),
    )
  } catch {
    return false
  }
}

function appendScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = src
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('VWorld 지도 스크립트를 불러오지 못했습니다.'))
    document.head.appendChild(s)
  })
}

function waitForVwMap(timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs
    const check = () => {
      if (getVw()?.Map) {
        resolve()
        return
      }
      if (Date.now() > deadline) {
        reject(new Error('vw.Map 가용 타임아웃'))
        return
      }
      setTimeout(check, 100)
    }
    check()
  })
}

export async function loadVworldScript(apiKey: string): Promise<void> {
  if (getVw()?.Map) return
  if (scriptPromise) return scriptPromise

  scriptPromise = (async () => {
    const subScripts: string[] = []
    const subStyles: string[] = []
    const origWrite = document.write.bind(document)
    document.write = ((html: string) => {
      const scriptMatch = html.match(/src=['"]([^'"]+)['"]/)
      if (scriptMatch?.[1]) {
        subScripts.push(scriptMatch[1].replace(/^http:\/\//, 'https://'))
      }
      const styleMatch = html.match(/href=['"]([^'"]+\.css[^'"]*)['"]/)
      if (styleMatch?.[1]) {
        subStyles.push(styleMatch[1].replace(/^http:\/\//, 'https://'))
      }
    }) as typeof document.write

    try {
      // 1) jQuery 로드 — VWViewerStartup이 $ 의존
      if (!(window as any).jQuery) {
        await appendScript('https://code.jquery.com/jquery-3.7.1.min.js')
      }

      // 2) 부트스트랩 <script> 로드 (CORS 면제)
      await appendScript(`https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=${apiKey}`)

      // 3) 전역변수 http→https 강제 (Cesium 워커 등이 이 변수 참조)
      const w = window as any
      for (const k of ['vworldUrl', 'vworld2DCache', 'vworldBaseMapUrl', 'vworldStyledMapUrl']) {
        if (w[k]) w[k] = w[k].replace('http://', 'https://')
      }

      // 4) 수집한 CSS/하위 스크립트 로드 (Cesium → VW → OL, 순서 중요)
      for (const href of subStyles) {
        if (document.querySelector(`link[href="${href}"]`)) continue
        const link = document.createElement('link')
        link.rel = 'stylesheet'
        link.href = href
        sdkStyles.add(link)
        document.head.appendChild(link)
      }
      for (const src of subScripts) {
        await appendScript(src)
      }

      // 5) vw.Map 가용 대기
      await waitForVwMap(15_000)
    } catch (e) {
      scriptPromise = null
      throw e
    } finally {
      document.write = origWrite
    }
  })()

  return scriptPromise
}
