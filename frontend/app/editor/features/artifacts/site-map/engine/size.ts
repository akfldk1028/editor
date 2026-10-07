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

/**
 * Calls `onResize` with the element's size whenever it changes (splitter drag, sidebar, maximize,
 * window), at most once per animation frame.
 */
export function observeSize(element: HTMLElement, onResize: (width: number, height: number) => void): () => void {
  if (typeof ResizeObserver === 'undefined') return () => undefined
  let frame = 0
  let size: [number, number] | null = null
  const observer = new ResizeObserver(([entry]) => {
    if (!entry) return
    size = [entry.contentRect.width, entry.contentRect.height]
    frame ||= requestAnimationFrame(() => {
      frame = 0
      if (size) onResize(...size)
    })
  })
  observer.observe(element)
  return () => {
    cancelAnimationFrame(frame)
    observer.disconnect()
  }
}
