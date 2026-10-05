# Frontend review after the migration correction

Scope: original AG-frontend/ARR routers versus native Editor routes; current map search, catalog, dialogue, API mount configuration and global bootstrap. This is source/contract review with targeted tests, not a fresh browser or visual-parity signoff. Native server startup remained rejected in the preceding recovery attempt; no alternate launch was attempted for this review.

Follow-up: [native flow integration](2026-10-05-native-flow-integration.md) adds `/flow` and fixes the global bootstrap coupling in source, with a passing bundle regression. Root/scene routes retain registration. Findings below describe the pre-fix review baseline; actual Next runtime and original whole-screen parity remain open.

## Findings, ordered by impact

1. **P1 — Most original product screens are absent from native routing.** AG-frontend `src/app/router.tsx` exposes Playground, build, MCP, gallery, history, deploy, settings and flow. ARR `src/routers/index.tsx` exposes law, design, design/language and settings subroutes. Native Editor currently adds only land, map, agents and dialogue to the original scene app. Existing PLANM routes and backend algorithms do not supply these original screens. Users cannot reach the original chat, flow, design/parking/floorplan/3D workflows from native Editor. Still open; use the full route ledger to implement actual screens, not empty route placeholders.

2. **P1 — Every new read-only page inherits the entire Editor/plugin bootstrap.** `app/layout.tsx` wraps all routes in `ClientBootstrap`; that statically imports `lib/bootstrap.ts`, which imports `@pascal-app/editor` and external host plugins. The recorded Webpack import trace reaches the manifold worker's unsupported `node:module` through exactly this chain, and `/agents` returned500 in the recovery attempt. Thus a 3D/export dependency failure also blocks catalog and dialogue. Still open: separate editing-route initialization from unrelated feature routes while preserving synchronous node registration before every Viewer mount. Do not simply remove registration or claim a bundler switch fixes the architectural coupling.

3. **P1 — Agent surfaces provide only a subset of original operations.** Native `features/agents/AgentsPage.tsx` only fetches the catalog and refreshes it; registration, deletion and live health actions from original AgentsPage are absent. Native `features/agent-dialogue/DialoguePage.tsx` polls stored requests/responses every10 seconds. It does not replace original Playground input/streaming/stop, flow popup or ARR topology/direct-command tabs. Still open. Catalog availability and a populated transcript are not full frontend or agent-execution parity.

4. **P2 — Searching a PNU updated the analysis panel without locating/highlighting that parcel. Fixed in this increment.** The previous `LandMap.handleSearch` only resolved addresses, skipped PNU map location entirely and never called `highlightParcel` after search. Added native parcel-boundary lookup for PNU; addresses without a returned PNU use coordinate reverse lookup. Search fits the resulting boundary and highlights it. New selections/unmount abort pending location work; lookup failures remain visible alongside analysis results. A real-browser camera/overlay check is still required.

5. **P2 — Mounted pages and their API requests used separate configuration values. Fixed in this increment.** `next.config.ts` used `PASCAL_BASE_PATH`, while new API clients used `NEXT_PUBLIC_BASE_PATH`, which was never derived from it. With only `/editor` configured, links target `/editor/...` but fetch calls target root `/api/...`. The public API prefix is now generated from the same Next basePath at build time. No private backend URL or credentials are exported.

## Verification

- Regression first failed for missing parcel-location behavior/export, then3 location tests passed: normalized PNU boundary request with cancellation signal, address-without-PNU reverse lookup, and explicit provider failure.
- Base-path regression reproduced `undefined` versus `/editor`, then passed after configuration was unified.
- Combined4 tests passed; full native-app TypeScript check and diff whitespace check passed.
- Map browser case now intercepts parcel-boundary failure and asserts its visible message, but was not rerun. No claim of new screenshots, real VWorld imagery or live A2A verification.
- Original AG/ARR sources, shared agents and persisted scene/design artifacts are unchanged.

## Next implementation order

Resolve native frontend runtime/route bootstrap separation; verify original Editor render/save/reopen and all current feature routes; then port original design/map/parking/floorplan/3D and chat/flow screens with their complete controls. Use [the route ledger](native-editor-route-ledger.md) for the remaining original menus. Functional completion requires actual APIs and real-project interaction evidence in addition to matching layout.
