# Original frontend migration ledger

Main application: `frontend/app/editor`. Shared agents: `D:/Data/25_ACE/agents`, connected through the Editor backend. AG, AG-frontend and ARR are migration sources, not final runtime dependencies. The latest user request requires accounting for every original reachable screen; a route, mock test or copied component alone does not close a row. Preserve the lightweight UI and original interactions while replacing backend authority.

## Placement

- `app/`: native route entries/layouts and explicit API handlers.
- `features/land`: original AG-frontend land form and cards.
- `features/land-map`: original ARR 2D map, layers and analysis panel.
- `features/agent-dialogue`: original MAS panel plus project/run-bound record adapter.
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
| AG FlowPage / popup | `/flow` (planned) | Not ported. Scope channels by project/run, retain flow navigation/detail and cleanup. |
| ARR AGLightFlow / topology / direct command tabs | Native dialogue/design feature (planned) | Source inspected; not ported. Fixed configured topology must not be represented as observed A2A traffic. Preserve topology controls and meaningful agent selection. |
| ARR DesignPage | `/design` (planned) | Original control panel, maps, generation, candidates, inspector, Pareto, legal basis, daylight section, passport and interactive panels not yet native. Earlier PLANM implementation does not close this row. |
| ARR drawing/parking/3D and floor-plan generation | Within native design + Editor scene | Native backend work exists, but original full UI and real-project save/reopen loop still open. Preserve imported job/candidate/artifact identities. Native additive execution is not proof of all original algorithms. |
| ARR BookLanguagePage | `/design/language` (planned) | Not ported; trace real document/language services before connecting controls. |
| ARR LawChat | `/law` (planned) | Not ported; preserve chat and evidence/source behavior with Editor-owned service contract. |
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
