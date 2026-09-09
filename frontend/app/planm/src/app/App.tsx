import { useEffect, useState } from "react";
import { DwgWorkspace } from "../integrations/dwg/workspace";

import { PlanmPlanningSurface } from "../features/planm-planning/PlanmPlanningSurface";
import "./styles.css";

/**
 * The product surfaces, addressed by path so a page can be linked and reloaded.
 *
 * `editor` is the Pascal 3D editor — a separate application proxied onto this
 * origin — so it is navigated to rather than rendered here.
 */
type Surface = {
  path: string;
  label: string;
  /** Rendered by another application, so navigated to rather than mounted. */
  external?: boolean;
};

const SURFACES: readonly Surface[] = [
  { path: "/dwg", label: "DWG Workspace" },
  { path: "/planm", label: "PLANM Planning" },
  { path: "/editor", label: "3D Editor", external: true },
];

type SurfacePath = string;

const DEFAULT_SURFACE: SurfacePath = "/dwg";

function surfaceFromLocation(pathname: string): SurfacePath {
  const match = SURFACES.find((surface) => pathname.startsWith(surface.path));
  return match ? match.path : DEFAULT_SURFACE;
}

export function App() {
  const [surface, setSurface] = useState<SurfacePath>(() =>
    surfaceFromLocation(window.location.pathname),
  );

  // Keep the address bar and the rendered surface in step, both ways, so the
  // back button and a pasted link behave the way any other page would.
  useEffect(() => {
    const onPopState = () => setSurface(surfaceFromLocation(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    if (surfaceFromLocation(window.location.pathname) !== surface) {
      window.history.pushState(null, "", surface);
    }
  }, [surface]);

  return (
    <div className="product-shell">
      <nav aria-label="Product workspace" className="product-switcher">
        <strong>PLAN / DWG</strong>
        {SURFACES.map((entry) =>
          entry.external ? (
            <a href={entry.path} key={entry.path} rel="noreferrer" target="_blank">
              {entry.label}
            </a>
          ) : (
            <button
              aria-current={surface === entry.path ? "page" : undefined}
              key={entry.path}
              onClick={() => setSurface(entry.path)}
              type="button"
            >
              {entry.label}
            </button>
          ),
        )}
      </nav>
      <section className="product-surface">
        {surface === "/planm" ? (
          <PlanmPlanningSurface onOpenDwg={() => setSurface("/dwg")} />
        ) : (
          <DwgWorkspace />
        )}
      </section>
    </div>
  );
}
