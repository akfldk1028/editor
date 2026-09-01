import { useState } from "react";
import { DwgWorkspace } from "../integrations/dwg/workspace";

import { PlanmPlanningSurface } from "../features/planm-planning/PlanmPlanningSurface";
import "./styles.css";

type ProductSurface = "dwg" | "planm";

export function App() {
  const [surface, setSurface] = useState<ProductSurface>("dwg");

  return (
    <div className="product-shell">
      <nav aria-label="Product workspace" className="product-switcher">
        <strong>PLAN / DWG</strong>
        <button
          aria-current={surface === "dwg" ? "page" : undefined}
          onClick={() => setSurface("dwg")}
        >
          DWG Workspace
        </button>
        <button
          aria-current={surface === "planm" ? "page" : undefined}
          onClick={() => setSurface("planm")}
        >
          PLANM Planning
        </button>
      </nav>
      <section className="product-surface">
        {surface === "dwg" ? (
          <DwgWorkspace />
        ) : (
          <PlanmPlanningSurface onOpenDwg={() => setSurface("dwg")} />
        )}
      </section>
    </div>
  );
}
