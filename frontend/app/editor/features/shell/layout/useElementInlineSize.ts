import { useLayoutEffect, useState, type RefObject } from "react";

/**
 * Tracks an element's inline size with a ResizeObserver, so layout decisions
 * follow the workspace's own width (the same box its CSS container queries
 * read) rather than the viewport.
 */
export function useElementInlineSize(ref: RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState(() => typeof window === "undefined" ? 0 : window.innerWidth);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(element.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[entries.length - 1];
      if (!entry) return;
      const size = entry.contentBoxSize?.[0]?.inlineSize ?? entry.contentRect.width;
      setWidth(size);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return width;
}
