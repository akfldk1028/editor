import { useEffect, type RefObject } from "react";

/**
 * Places a native `popover` element next to its trigger each time it opens.
 * The popover itself (top layer, light dismiss, Escape) is the platform's;
 * this only computes fixed coordinates, so it works without CSS anchor
 * positioning and never leaves the viewport.
 */
export function usePopoverAnchor(
  popoverRef: RefObject<HTMLElement | null>,
  anchorRef: RefObject<HTMLElement | null>,
  placement: "below" | "above" = "below"
) {
  useEffect(() => {
    const popover = popoverRef.current;
    if (!popover) return;
    const place = (event: Event) => {
      if ((event as ToggleEvent).newState !== "open") return;
      const anchor = anchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const gap = 6;
      popover.style.position = "fixed";
      popover.style.margin = "0";
      popover.style.inset = "auto";
      popover.style.right = `${Math.max(8, window.innerWidth - rect.right)}px`;
      popover.style.maxWidth = `calc(100vw - 16px)`;
      if (placement === "below") {
        popover.style.top = `${rect.bottom + gap}px`;
        popover.style.maxHeight = `${Math.max(160, window.innerHeight - rect.bottom - gap - 8)}px`;
      } else {
        popover.style.bottom = `${window.innerHeight - rect.top + gap}px`;
        popover.style.maxHeight = `${Math.max(160, rect.top - gap - 8)}px`;
      }
    };
    popover.addEventListener("beforetoggle", place);
    return () => popover.removeEventListener("beforetoggle", place);
  }, [anchorRef, placement, popoverRef]);
}

export function closePopover(element: HTMLElement | null) {
  const popover = element?.closest<HTMLElement>("[popover]");
  try {
    popover?.hidePopover();
  } catch {
    // Already closed.
  }
}
