# Native route boundary review - 2026-10-05

Scope: the user requested another inspection after committing the original Editor verification. Starting HEAD: a9d0363e; working tree was clean. This is a review increment, not an application implementation change.

## Route ownership

| Routes | Composition | Feature owner / data boundary |
|---|---|---|
| `/` | Original editor composition | Shared editor/viewer/core packages; local blank canvas |
| `/scenes`, `/scene/[id]` | Original server pages and SceneLoader | Next `/api/scenes`, MCP SQLite store |
| `/land` | Workspace layout, thin page | `features/land`, `/api/v1/land` |
| `/map` | Dedicated map wrapper | `features/land-map`, land BFF |
| `/law` | Dedicated law wrapper | `features/law`, law BFF, shared land-map viewer |
| `/design`, `/design/language` | Shared design navigation, lazy page composition | `features/design`, design BFF |
| `/agents` | Workspace layout, thin page | `features/agents`, platform catalog |
| `/dialogue`, `/flow` | Workspace layout; project/run query handling | `features/agent-dialogue`, `features/agent-flow`, platform records |
| `/build` | Workspace layout, thin page | `features/team-templates`, `features/team-builder`, workspace BFF |
| `/gallery` | Workspace layout, thin page | `features/gallery`, workspace BFF |
| `/history` | Workspace layout, thin page | `features/history`, shared sessions API/hooks |
| `/settings` | Workspace layout, thin page | `features/settings/{api,components,hooks,model}`, workspace BFF |
| `/terms`, `/privacy` | Original static pages | No migrated workspace execution |

All 17 page files were enumerated; stripping route groups produces no duplicate native page URLs. Workspace entry pages are 3-8 lines and delegate feature implementations. The map/law/design wrappers intentionally preserve their own composition; they are not all children of the workspace sidebar layout.

Reviewed all six v1 route handler files, the common backend-request implementation, shared workspace layout/navigation, backend app registration, feature client endpoint references, and actual backend OpenAPI. Next forwards domain requests through backend-request and EDITOR_BACKEND_URL; no hardcoded legacy server port was found in the searched feature/page/workspace TS/TSX sources. Targeted searches found no feature imports or fetch calls inside elements/workspace or components/workspace. These are bounded static searches, not proof that every transitive dependency respects the architecture.

## Findings

### Execution contracts are incomplete (high priority)

The running FastAPI OpenAPI exposes only five operations under `/api/v1/design`: site-boundary, language-system, executed-masses listing, passport and preview. The design BFF allowlist and feature client expose many more operations, including jobs/run/cancel/stream, floor-plan, interactive operations and collaboration. A real GET `/api/v1/design/collaboration/health` returned 404. A successful page render therefore does not establish a working design execution backend. Preserve the original views while implementing the missing Editor-owned contracts; do not forward them back to ARR as a final architecture.

`features/land-map/hooks/use-agent-analyze.ts` still contains an agent analysis SSE endpoint without a corresponding native BFF handler or live OpenAPI route. No usage of this hook was found elsewhere within features/land-map, so this is retained unconnected code, not evidence of a currently reachable failing button. The attempted HTTP probe timed out during dev-server load; it is not recorded as an observed 404.

### Internal decomposition remains uneven (medium priority)

The route files are separated, but `SiteMapPanel.tsx` has 1,749 lines, `BookLanguageFlow.tsx` 1,360, `InteractiveDesignPanel.tsx` 1,078, and `DesignPage.tsx` 971. TeamsPage has 657 and LawChat 636. Line counts flag review/splitting candidates, not defects by themselves. Extract existing map controls, graph panels, interaction state and API orchestration by responsibility while preserving the original DOM and behavior. Do not split merely to satisfy a line-count threshold.

The original `/scenes` page returns an empty list on non-OK API responses, making API failure indistinguishable from no saved scenes. It also omits NEXT_PUBLIC_BASE_PATH in its server fetch, unlike `/scene/[id]`. Root-mounted runtime works; mounted deployment and a storage failure were not injected in this pass. These remain actionable source findings.

`next.config.ts` has typescript.ignoreBuildErrors=true. A successful Next build cannot replace the explicit TypeScript check.

### Earlier URL suspicion resolved

`/editor/1bf925e33e03` returned **307**, Location `/scene/1bf925e33e03`; following it returned 200. next.config.ts defines the redirect intentionally. No route alias or URL rewrite fix is needed.

### Existing runtime limitations remain

Core/editor/viewer/mcp workspace package links still resolve to the backup tree. The running Next process therefore does not validate an independent build of the real D: source tree. Current and baseline scene databases also remain separate. See the original Editor verification record; neither database nor package link was replaced in this review.

## Fresh validation

- Explicit TypeScript check: exit 0.
- Targeted backend suite: 14 passed (settings, catalog, sessions, design archive and workspace routes).
- Live OpenAPI: 78 operations grouped as planm 10, platform 33, land 10, law 6, design 5, workspace 14; no duplicate operationId values.
- Real BFF reads: workspace health/version, platform agents, land map-config and law health returned 200. Invalid workspace/platform paths returned 404; GET against land analyze and law search returned 405.
- Full browser suite with EDITOR_VERIFY_LIVE_VWORLD=1: **18 passed, 2 failed, 4.4 minutes**. History failed with ECONNRESET in cleanup; main Editor return failed its 5-second saved-scenes visibility assertion while still showing the land page. These are retained as first-pass failures.
- Both failed cases rerun, with no application/test changes: **2 passed, 14.5 seconds**. The rerun is not a clean full-suite pass or a root-cause fix. Next/backend listeners remained alive; Next working set was about 9.98 GB during investigation and a separate request also timed out. These observations suggest runtime contention but do not prove its cause. Timing/reliability remains open.
- The three records left by the failed History cleanup were identified by their exact test label `History verification 1791186526417` and IDs (sessions 9/10, team 29), then removed through normal APIs. No unrelated records were deleted.
- Fixture/interception tests establish their stated behavior only; they do not prove real agent execution or original full UI parity.

## Next implementation order

1. Make Editor package resolution and scene storage explicit and repeat original scene verification.
2. Implement and exercise the original design job/stream/cancel/result contract against Editor-owned services.
3. Correct scene-list error/empty semantics and verify mounted-base-path behavior.
4. Decompose the large design components with before/after interaction and visual evidence.
5. Complete the unported routes listed in native-editor-route-ledger.md; do not call planned Playground/MCP/deployment surfaces implemented.
