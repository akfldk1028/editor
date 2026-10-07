/** Resolves once the element has a non-zero box (the panel may still be laying out), or after `timeoutMs`. */
export function whenSized(element: HTMLElement, timeoutMs = 2000): Promise<void> {
  return new Promise((resolve) => {
    const started = performance.now()
    const check = () => {
      const { width, height } = element.getBoundingClientRect()
      if ((width > 0 && height > 0) || performance.now() - started > timeoutMs) resolve()
      else requestAnimationFrame(check)
    }
    check()
  })
}

/** Calls `onResize` with the element's size whenever it changes (panel resize, maximize, layout mode). */
export function observeSize(element: HTMLElement, onResize: (width: number, height: number) => void): () => void {
  if (typeof ResizeObserver === 'undefined') return () => undefined
  const observer = new ResizeObserver(([entry]) => {
    if (entry) onResize(entry.contentRect.width, entry.contentRect.height)
  })
  observer.observe(element)
  return () => observer.disconnect()
}
