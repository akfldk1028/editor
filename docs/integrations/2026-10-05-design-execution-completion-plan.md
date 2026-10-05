# Editor design integration closure

The user authorized completing remaining integration work, preserving original views, algorithms and stored scenes. Editor owns the frontend/backend; shared agents remain in `D:/Data/25_ACE/agents`.

## Implementation boundaries

1. Merge historical Pascal scenes additively, with SQLite backup, collision rejection, foreign-key/integrity checks and a repeatable receipt. Never overwrite current scenes.
2. Decompose existing design components into domain geometry, renderer helpers, hooks and named views without replacing their JSX or behavior.
3. Absorb original design algorithms under `backend/app/modules/design/generation`; land geometry/regulation helpers under `modules/land/reference`; Django persistence under `adapters/design_storage`; original endpoint adapters under `api/design_runtime`. No top-level module aliases or dependency on a running ARR server.
4. Expose the engine through Editor FastAPI. Django is an in-process persistence/contract adapter with an Editor-owned SQLite database, not a second deployed backend. Existing native archive and boundary endpoints retain precedence.
5. Unify job execution, cancellation and SSE replay: database claims prevent duplicate runs, background computation survives subscriber disconnects, terminal results/events commit together, and stale execution leases become explicit interrupted failures.
6. Match Next BFF routes to original endpoint contracts, including UUIDs, detailed results, floor plans, interactive operations and exports. Preserve SSE event cursors and avoid a 60-second stream cutoff.
7. Verify real computation, HTTP contracts, original route/browser behavior, scene reopening and build/type gates; then record evidence and commit reviewable increments.

## Completion evidence required

- Scene counts/hashes and idempotent repeated preflight.
- Component type checks, geometry/graph tests and original route browser suite with live VWorld.
- Isolated database HTTP tests, start/cancel/replay/race/persistence failure tests, real design geometry and floor-plan outputs.
- Live frontend -> BFF -> Editor backend job run, persisted results and reconnectable SSE.
- Explicit identification of optional model/provider dependencies and unverified architectural/agent capabilities. Computational completion does not assert legal or architectural acceptance.

## Independent work

Scene migration and lifecycle: `scene_store_merge`; original component decomposition and collaboration boundary: `design_component_split`; source transplant and geometry verification: `design_engine_port_review`; root owns bootstrap, FastAPI/BFF wiring, integration validation, service operation, final review and commits.
