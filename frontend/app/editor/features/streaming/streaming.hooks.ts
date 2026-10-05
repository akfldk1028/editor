import { useEffect, useRef } from 'react'
import { SCROLL_THRESHOLD } from './streaming.constants'

/**
 * Smart auto-scroll: scrolls to bottom when user is near the bottom,
 * but respects manual scroll-up. Re-engages when user scrolls back down.
 */
export function useAutoScroll(
  containerRef: React.RefObject<HTMLDivElement | null>,
  deps: unknown[],
) {
  const isNearBottomRef = useRef(true)

  // Track user scroll position
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    function handleScroll() {
      if (!el) return
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      isNearBottomRef.current = distFromBottom <= SCROLL_THRESHOLD
    }

    el.addEventListener('scroll', handleScroll, { passive: true })
    return () => el.removeEventListener('scroll', handleScroll)
  }, [containerRef])

  // Auto-scroll when deps change and user is near bottom
  useEffect(() => {
    if (isNearBottomRef.current && containerRef.current) {
      containerRef.current.scrollTo({ top: containerRef.current.scrollHeight, behavior: 'smooth' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
