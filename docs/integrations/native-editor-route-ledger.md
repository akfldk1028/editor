# Original frontend migration ledger

Main application: `frontend/app/editor`. Shared agents: `D:/Data/25_ACE/agents`, connected through the Editor backend. AG, AG-frontend and ARR are migration sources, not final runtime dependencies. The latest user request requires accounting for every original reachable screen; a route, mock test or copied component alone does not close a row. Preserve the lightweight UI and original interactions while replacing backend authority.

Latest scope correction: [original views and every nested element](2026-10-05-original-view-parity.md). The source inventory covers 274 TSX/CSS files and 5415 JSX occurrences across ARR and AG-frontend, all unverified. Full view composition, styles, assets, overlays and conditional states are required, not only API functionality. [Actual native runtime recovery](2026-10-05-native-runtime-recovered.md) supersedes the older runtime-blocked statements below; VWorld browser display and missing original routes remain open.

Latest implementation and runtime: [native original LawChat and live VWorld](2026-10-05-native-law-vworld.md). Native backend18449 is configured and running; real 2D cadastral imagery and 3D buildings rendered. Final native browser suite11 passed; law retrieval returned zero live results, and whole-product/view parity remains open.

Latest design increment: [original design workspace and archived evidence](2026-10-05-native-design-workspace.md). `/design` and `/design/language` now mount original views; original execution workflows remain open.

## Placement

- `app/`: native route entries/layouts and explicit API handlers.
- `features/land`: original AG-frontend land form and cards.
- `features/land-map`: original ARR 2D map, layers and analysis panel.
- `features/law`: original ARR LawChat, search/results/article panels, using shared land-map cards and VWorld3D.
- `features/agent-dialogue`: original MAS panel plus project/run-bound record adapter.
- `features/agent-flow`: original ARR node/edge/toolbar UI over the same bound run records; `/flow` and `/dialogue` retain project/run query scope.
- `features/agents`: original catalog grid/search/details bound to owner catalog.
- `features/workspace`: scoped shared visual components/theme; never changes the main Editor's global theme.
- Backend `modules/` owns domain behavior; `adapters/` owns external services. Do not introduce an `arr` backend folder or permanent proxy to old AG/ARR apps.

## Screen and interaction accounting

| Original surface | Native destination | Current status / remaining closure |
|---|---|---|
| Editor scene canvas, tools and saved scenes | Existing `/`, `/scene/*` | Preserved. Earlier same-document return rendered canvas/tools after loader disappearance. Current runtime recovery required. |
| AG LandPage | `/land` | Ported original cards/form/theme; intercepted result rendering tested. Real analysis/provider/storage flow still needs aligned runtime verification. |
| ARR LandMap | `/map` | Original 2D viewport/search/panel and native tile/WMS code ported. Browser contract test passed before latest cancellation changes. Live imagery, repeated parcel selection and geometry overlays still pending. |
| ARR MASDialoguePanel | `/dialogue` | Original timeline/cards/filter/JSON layout ported against bound owner records. Fixture browser checks passed. Live owner/A2A evidence still pending. No fallback benchmark data. |
| AG AgentsPage | `/agents` | Original grid/search/details/JSON layout adapted to owner catalog. Type checked; new browser case blocked by disk failure. Register/unregister and live health actions still open. |
| AG PlaygroundPage and LiveAgentFlow | `/playground` (planned) | Not ported into native Editor. Need original sessions, input, streaming, stop, agent detail, attachments and relevant helper interactions; native owner currently supports only health submission. Free-form execution needs a real contract, not a fabricated submit button. |
| AG FlowPage / popup | `/flow` (partial destination) | Native `/flow` currently hosts ARR's record-based graph. AG popup/channel/session operations are still not ported; this row remains open. |
| ARR AGLightFlow / topology / direct command tabs | `/flow` | Original node/edge/toolbar UI ported with bound observed request/response records, fullscreen/Escape, labels, grid/reset and selection details. Offline Chrome component interactions passed. Native route/API execution, original configured topology and direct command tabs remain open. No fabricated A2A edges. |
| ARR DesignPage | `/design` | Original composition ported, controls and live VWorld route return verified. Native boundary and land analysis adapters connected. Generation, streaming, cancellation, floor-plan, interactive execution and populated result parity remain open. |
| ARR drawing/parking/3D and floor-plan generation | Within native design + Editor scene | Native backend work exists, but original full UI and real-project save/reopen loop still open. Preserve imported job/candidate/artifact identities. Native additive execution is not proof of all original algorithms. |
| ARR BookLanguagePage | `/design/language` | Original graph/tabs/evidence composition ported. Native catalog snapshot and 18 saved MASS run groups connected, with verified image/passport bytes. New execution, creative portfolios, complete metadata and replay remain open. |
| ARR LawChat | `/law` | Original connected view ported with native law BFF/FastAPI and real VWorld3D. Fixture search/card/detail/close/reset/reload and live map return passed. Populated provider retrieval, original article hierarchy/history and advanced-analysis execution remain open. |
| AG History and session comparison | `/history` (planned) | Original list/detail/comparison not native. Bind real project/run history and distinguish transcript comparison from design artifact verification. |
| Native project/job/execution pages currently in PLANM | Native project/design routes (planned) | Preserve implemented bindings, idempotency, immutable candidates, executions and source revisions. Move UI into native Editor without replacing original design screens with simplified substitutes. |
| AG team builder / JSON / validation | `/build` (planned) | Not native. Earlier recommendation was deferred; not "migrated". Determine Editor-owned persistence/execution contract while preserving original reachable interactions. |
| AG MCP workbench | `/mcp` (planned) | Not native. Original generic MCP client differs from Pascal scene MCP; backend must own permitted connections/tool execution. |
| AG gallery/import/sync | `/gallery` (planned) | Not native. Preserve reachable actions; original disabled New Gallery is not an implemented feature. |
| AG/ARR settings | `/settings` (planned) | Scoped theme switching exists; complete settings pages, font/display behavior and server-owned secret/config interfaces remain open. |
| AG deployment/status surface | Native service/status route (planned) | Original mostly generates commands and reads health/version. Account for useful operations in Editor; do not retain Studio deployment as a final dependency or claim real deployment from generated text. |
| ARR history/authentication/settings subroutes | Native route mapping still required | Account for source routes explicitly; do not recreate localStorage guest fallback as server authorization. |

## Completion evidence required per row

Original visual comparison; direct load/reload/back navigation; controls and actual backend contracts; project isolation and request cancellation; explicit empty/error/partial states; persisted result identity; and a run without the old AG/ARR roots serving requests. Mock browser tests are rendering evidence only. Systems, DomainExpert and InteriorDesign remain unfinished independent of catalog connectivity.

Current test/runtime limitations are recorded in [the active correction checkpoint](2026-10-05-native-editor-ui-correction.md). Do not silently mark planned routes implemented or count the old PLANM surface as native parity.

Latest increment: [native flow and bootstrap verification](2026-10-05-native-flow-integration.md). The shared client wrapper no longer imports scene plugins; root Editor and scene loader retain synchronous registration. This source/bundle separation has passed checks, but native runtime recovery is not verified.

Subsequent wiring: [native frontend/backend connection](2026-10-05-native-backend-wiring.md) adds actual project binding and health submission controls/BFF routes plus the `editor:dev` native profile. Static/unit/component checks passed; the live Next/owner loop remains open. This does not close original design or Playground parity.
