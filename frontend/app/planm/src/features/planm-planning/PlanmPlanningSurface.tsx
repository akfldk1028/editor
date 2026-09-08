import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import PlanmPlanning from "./PlanmPlanning";
import styles from "./styles.css?inline";

interface Props {
  onOpenDwg(): void;
}

export function PlanmPlanningSurface({ onOpenDwg }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [mount, setMount] = useState<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const shadow = host.shadowRoot ?? host.attachShadow({ mode: "open" });
    shadow.replaceChildren();
    const style = document.createElement("style");
    style.textContent = styles;
    const root = document.createElement("div");
    root.className = "planm-surface";
    shadow.append(style, root);
    setMount(root);
    return () => setMount(null);
  }, []);

  return (
    <div className="planm-shadow-host" ref={hostRef}>
      {mount && createPortal(<PlanmPlanning onOpenDwg={onOpenDwg} />, mount)}
    </div>
  );
}
