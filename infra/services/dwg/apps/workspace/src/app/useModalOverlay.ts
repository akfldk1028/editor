import { useEffect, type RefObject } from "react";

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])"
].join(",");

interface Options {
  active: boolean;
  dialogRef: RefObject<HTMLElement | null>;
  restoreFocusRef?: RefObject<HTMLElement | null>;
  onClose(): void;
}

/** Owns the keyboard and background semantics shared by compact workspace overlays. */
export function useModalOverlay({ active, dialogRef, restoreFocusRef, onClose }: Options) {
  useEffect(() => {
    if (!active) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const backgrounds = [...document.querySelectorAll<HTMLElement>("[data-modal-background]")]
      .filter((element) => element !== dialog);
    const restoreBackgrounds = backgrounds.map((element) => ({
      element,
      ariaHidden: element.getAttribute("aria-hidden"),
      inert: element.inert
    }));
    for (const { element } of restoreBackgrounds) {
      element.setAttribute("aria-hidden", "true");
      element.inert = true;
    }

    const frame = window.requestAnimationFrame(() => focusable(dialog)[0]?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusable(dialog);
      if (elements.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const current = document.activeElement;
      const first = elements[0]!;
      const last = elements.at(-1)!;
      if (event.shiftKey && (current === first || !dialog.contains(current))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !dialog.contains(current))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKeyDown, true);
      for (const { element, ariaHidden, inert } of restoreBackgrounds) {
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
        element.inert = inert;
      }
      window.requestAnimationFrame(() => (restoreFocusRef?.current ?? restoreFocus)?.focus());
    };
  }, [active, dialogRef, onClose, restoreFocusRef]);
}

function focusable(dialog: HTMLElement): HTMLElement[] {
  return [...dialog.querySelectorAll<HTMLElement>(focusableSelector)]
    .filter((element) => !element.hasAttribute("disabled") && !element.getAttribute("aria-hidden"));
}
