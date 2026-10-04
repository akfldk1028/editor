import { lazy, Suspense, useEffect, useState } from "react";
import { resolveProductRoute } from "./routes";
import { DwgWorkspace } from "../integrations/dwg/workspace";

import { PlanmPlanningSurface } from "../features/planm-planning/PlanmPlanningSurface";
import "./styles.css";
const AgentsPage = lazy(() => import("../features/agent-workspace/agents/AgentsPage"));
const ProjectsPage = lazy(() => import("../features/agent-workspace/projects/ProjectsPage"));
const ProjectPage = lazy(() => import("../features/agent-workspace/projects/ProjectPage"));
const RunPage = lazy(() => import("../features/agent-workspace/runs/RunPage"));
const LandPage = lazy(() => import("../features/land-analysis/LandPage"));

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
  { path: "/agents", label: "Agents" },
  { path: "/projects", label: "Projects" },
  { path: "/land", label: "대지 분석" },
  { path: "/editor", label: "3D Editor", external: true },
];

type SurfacePath = string;


function surfaceFromLocation(pathname: string): SurfacePath {
  const route = resolveProductRoute(pathname);
  return route.kind === 'project' || route.kind === 'run' || route.kind === 'projects'
    ? pathname : `/${route.kind}`;
}

export function App() {
  const [surface, setSurface] = useState<SurfacePath>(() =>
    surfaceFromLocation(window.location.pathname),
  );
  const route = resolveProductRoute(surface);

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
        {surface === "/agents" ? (
          <Suspense fallback={<p role="status">화면을 불러오는 중…</p>}><AgentsPage /></Suspense>
        ) : route.kind === 'land' ? (
          <Suspense fallback={<p role="status">불러오는 중…</p>}><LandPage /></Suspense>
        ) : route.kind === 'projects' ? (
          <Suspense fallback={<p role="status">불러오는 중…</p>}><ProjectsPage /></Suspense>
        ) : route.kind === 'project' ? (
          <Suspense fallback={<p role="status">불러오는 중…</p>}><ProjectPage projectId={route.projectId} /></Suspense>
        ) : route.kind === 'run' ? (
          <Suspense fallback={<p role="status">불러오는 중…</p>}><RunPage runId={route.runId} /></Suspense>
        ) : surface === "/planm" ? (
          <PlanmPlanningSurface onOpenDwg={() => setSurface("/dwg")} />
        ) : (
          <DwgWorkspace />
        )}
      </section>
    </div>
  );
}
