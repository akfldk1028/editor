# Native flow integration checkpoint

Authoritative app: `frontend/app/editor`. This is one migration increment, not whole AG/ARR completion.

## Implemented

- Removed global scene/plugin import from `app/client-bootstrap.tsx`; kept synchronous bootstrap imports in root Editor and `components/scene-loader.tsx`. Unrelated workspace pages no longer acquire this bootstrap through the global wrapper.
- Added native `/flow` using original ARR AGLightFlow nodes, SVG edges, toolbar and viewport controls under `features/agent-flow`. No old ARR HTTP server dependency was introduced.
- Shared project/run loading, owner/branch validation, cancellation, polling and failure handling with `/dialogue`. Links preserve project/run scope; keyed route instances clear stale selection when query scope changes.
- Graph uses only stored communication participants and directed pairs. Missing transport stays unknown; no configured topology, PASS node or running animation pretends to be live A2A.
- Node selection exposes original requests/responses; original fullscreen/Escape, labels, grid/reset and viewport controls retained. Reduced the feedback curve so its label remains inside the fitted viewport. Explicit icon/header colors prevent the Editor's light theme from obscuring the dark graph.
- Pinned `@xyflow/react` 12.10.1 with lockfile update, matching the installed original UI version.

## Fresh verification

- Seven Bun tests passed: observed graph/empty graph (2), wrapper bundle isolation (1), native mount prefix (1), parcel lookup/error/cancellation-signal behavior (3).
- Full native-app `tsc --noEmit` passed.
- Headless Chrome rendered the real RunFlow component with explicitly labeled fixture data and generated native Tailwind CSS. Fullscreen/Escape, labels, selection/details, grid/reset and edge-label viewport containment passed with zero page errors. Screenshot: `.superpowers/sdd/native-flow-preview/flow.png` (local ignored evidence).
- Initial local package copy created multiple d3-selection instances. Replaced its private dependency tree with a flat isolated closure, preserving the prior tree in `.superpowers/sdd/native-flow-preview/nested-dependencies-backup`. Then the Bun 1.3.11 preview bundle still omitted d3-transition's prototype side effects. The esbuild preview retained them and passed. This is an offline harness result, not proof of Next/Webpack bundling. No product source workaround for a preview bundler was added.
- Added `tests/flow-route.spec.cjs` to the native migration suite for project scope, controls, timeline navigation and reload. It has NOT been executed against Next: hidden server startup was previously rejected by tool policy; no alternate startup bypass was attempted.

## Open

Native frontend server recovery, direct route/reload/return-to-Editor checks, actual APIs and live A2A remain unverified. No assertion of full visual parity or real-project completion follows from fixture component tests.

Next: port original ARR DesignPage control/maps/candidate/inspector/Pareto/legal/daylight/passport/interactive panels and drawing/parking/floor-plan/3D workflows against Editor-owned contracts. Preserve archived source/job/candidate identity, scene revision and native execution guards. Existing PLANM UI and additive-only execution do not close that migration. AG Playground/streaming/stop, flow popup, catalog mutations, history/build/MCP/gallery/settings/law/language also remain open in the route ledger.

Shared Systems, DomainExpert and InteriorDesign remain unfinished. They stay in `D:/Data/25_ACE/agents`; catalog connectivity is not service completion.
