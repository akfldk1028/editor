# Original frontend migration ledger

Main application: `frontend/app/editor`. Shared agents remain in `D:/Data/25_ACE/agents` and connect through the native Editor backend. AG, AG-frontend and ARR are retained migration sources; copying a route alone does not establish functional or visual parity.

Current execution record: [native dialogue, workbenches and provider cutover](2026-10-05-completion-execution.md). The common header and sidebar expose 20 product destinations, including the original CAD and PLANM surfaces, Playground and MCP. Fresh production verification passed 61 migration browser cases (live VWorld and design execution enabled) and 7 product navigation cases. Per-feature evidence and any later targeted fixes are recorded in that execution record.

Requirements are developed through agent dialogue. A partial review is a useful next question, not a demand that the user arrive with an already completed design. Keep runtime connectivity, functional integration, owner implementation status and engineering acceptance separate.

Original visual inventory: [original views and nested elements](2026-10-05-original-view-parity.md), covering 274 TSX/CSS files and 5415 JSX occurrences. The inventory count is not a claim that every conditional element was manually verified. Earlier dated integration reports remain historical evidence, superseded by the current record where their runtime status differs.

## Placement

- `app/`: native route entries/layouts and explicit API handlers.
- `features/land`: original AG-frontend land form and cards.
- `features/land-map`: original ARR 2D map, layers and analysis panel.
- `features/law`: original ARR LawChat, search/results/article panels, using shared land-map cards and VWorld3D.
- `features/agent-dialogue`: original MAS panel plus project/run-bound record adapter.
- `features/agent-flow`: original ARR node/edge/toolbar UI over the same bound run records; `/flow` and `/dialogue` retain project/run query scope.
- `features/agents`: original catalog grid/search/details bound to owner catalog.
- `elements/workspace`: primitive controls; `components/workspace`: composed shell/providers and scoped theme. Feature-specific components remain under their owning `features/<domain>`.
- Backend `modules/` owns domain behavior; `adapters/` owns external services. Do not introduce an `arr` backend folder or permanent proxy to old AG/ARR apps.

## Screen and interaction accounting

| Original surface | Native destination | Current status / remaining closure |
|---|---|---|
| Editor scene canvas, tools and saved scenes | Existing `/`, `/scene/*` | Native runtime recovered. Additive merge retains current data: 7 scenes, 10 revisions, 2 events. Historical 321-node building reopened and visibly rendered in 3D. Full original tool parity remains separate. |
| AG LandPage | `/land` | Ported original cards/form/theme; intercepted result rendering tested. Real analysis/provider/storage flow still needs aligned runtime verification. |
| ARR LandMap | `/map` | Original viewport/search/layers/panel retained. Native live VWorld cadastral imagery and 3D route-return checks pass; selection cancellation is covered. Every historical overlay combination is not claimed. |
| ARR MASDialoguePanel | `/dialogue` | Original records/cards/filter/payload view uses bound owner runs. Actual specialist A2A, full original-request retrieval, human-readable follow-up proposals and owner questions verified. Exact source versions and dirty flags remain intact. |
| AG AgentsPage | `/agents` | Grid/search/details use the live owner catalog: 12 available, 2 HTTP providers declared, 1 local and 10 undeclared roles. The three specialists are available; catalog connectivity does not mean their full roles are implemented. |
| AG PlaygroundPage and LiveAgentFlow | `/playground` | Original session/input/streaming/history/attachment/flow views restored over native execution. Real UserProxy task, pending-input reload, answer, persisted history and stop pass. Model libraries load in the isolated environment; real model calls need a key saved in `/settings`. Static workbenches, the editor's own land/law tools and HTTP MCP workbenches load; FunctionTool, code executors, stdio MCP and browser agents are refused by name (`adapters/workspace_tool_policy.py`). A Replay-client run proves a real AssistantAgent executes through the runner. |
| AG FlowPage / popup | `/playground/flow` | Original popup and live graph use a per-tab channel. Actual popup connection and message flow verified. `/flow` separately retains ARR recorded A2A communications. |
| ARR AGLightFlow / topology / direct command tabs | `/flow` | Original node/edge/toolbar UI ported with bound observed request/response records, fullscreen/Escape, labels, grid/reset and selection details. Offline Chrome component interactions passed. Native route/API execution, original configured topology and direct command tabs remain open. No fabricated A2A edges. |
| ARR DesignPage | `/design` | Original composition retained and decomposed. Native original ten-algorithm run, journaled streaming, persisted geometry, cancellation and metric floor plan verified through the browser. Interactive geometry and all five floor algorithms have HTTP tests. MAAS performance/acceptance and every conditional original state require their own evidence. |
| ARR drawing/parking/3D and floor-plan generation | Within native design + Editor scene | Native backend work exists, but original full UI and real-project save/reopen loop still open. Preserve imported job/candidate/artifact identities. Native additive execution is not proof of all original algorithms. |
| ARR BookLanguagePage | `/design/language` | Original graph/tabs/evidence retained. 18 saved MASS groups merge with fresh single executions; source identities/hashes preserved. 54 valid creative runs and 124 evaluation runs imported; 23 invalid creative runs quarantined. Native single execution and actual asset responses verified. Exact replay of every historical AST and full original metadata parity remain open. |
| ARR LawChat | `/law` | Original connected view ported with native law BFF/FastAPI and real VWorld3D. Fixture search/card/detail/close/reset/reload and live map return passed. "AI 심화 분석" is native: `GET /api/v1/land/agent-analyze/stream` runs the seeded Land Swarm Analysis Team in-process (`modules/land/agent_analysis.py`) with the ARR event contract; it needs a saved model key in `/settings`. Populated provider retrieval and original article hierarchy/history remain open. |
| AG History and session comparison | `/history` | Original list/detail/comparison views and native archive/reload verified. Native Playground execution now writes actual persisted run messages. Import of an unlocated original AG database is not claimed. |
| Native project/run pages | `/projects`, `/runs` | Exist as native routes bound to Orchestrator projects and runs (`features/agent-dialogue`). Preserve implemented bindings, idempotency, immutable candidates, executions and source revisions. |
| PLANM floor-plan runs | `/planm` | Native page over `/api/v1/planm/runs*`; stages execute in the Plan Agent (`agents/planm`, port 8309) which the backend calls over HTTP. |
| DWG workspace | `/dwg` | Native page over the DWG provider gateway (`infra/services/dwg`, :4317). |
| Saved scenes | `/scenes` | Native scene list beside the `/scene/*` canvas routes. |
| AG team builder / JSON / validation | `/build` | Original controls, graph, JSON import/save/reload retained. Native execution consumes the saved team snapshot; capability checks distinguish executable templates from unsupported components. |
| AG MCP workbench | `/mcp` | Original connection/tool/resource views restored with native backend-owned sessions. Real stdio connection, add(17,25)=42, resource read and disconnect verified. HTTP/SSE transports are implemented; the live browser proof uses stdio. |
| AG gallery/import/sync | `/gallery` | Original six categories/cards/detail/import/sync dialogs ported. Real import into native templates verified. "Test" calls `POST /api/v1/workspace/validate/test`: a model is loaded and sent one prompt; agents, teams, terminations, tools and workbenches are loaded only. A fresh catalog is seeded with the RoundRobin team, the Land Swarm Analysis Team and one gallery (`modules/workspace/seeds.py`). External sync remains open; original New Gallery stays disabled. |
| AG/ARR settings | `/settings` | Original AG settings sections ported with versioned native persistence, language/theme/font controls; save/reload and scoped appearance verified. Saved environment values (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_OPENAI_*`, `OLLAMA_HOST`) fill model clients at run and test time without touching the process environment (`adapters/workspace_credentials.py`). ARR settings parity remains open. |
| AG deployment/status surface | `/deploy` | Native useful guide/configuration/environment/API/status sections ported into feature components. Commands target Editor; health/version, copy/reset, navigation/reload and failure states verified. Environment draft does not configure the runtime. Full unified container/cloud deployment remains unavailable; existing PLANM Docker subset stays separate. |
| ARR history/authentication/settings subroutes | Native route mapping still required | Account for source routes explicitly; do not recreate localStorage guest fallback as server authorization. |

## Completion evidence required per row

Original visual comparison; direct load/reload/back navigation; controls and actual backend contracts; project isolation and request cancellation; explicit empty/error/partial states; persisted result identity; and a run without the old AG/ARR roots serving requests. Mock browser tests are rendering evidence only. Systems, DomainExpert and InteriorDesign remain unfinished independent of catalog connectivity.

Current verification limits and pending work are maintained in the execution record linked above. Keep old source and historical artifacts until their native ownership and exact retained identities are verified.
