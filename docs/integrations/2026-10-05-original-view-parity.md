# Original views and element parity

The user's correction is authoritative: integration includes the original views and every visual/interactive element, not only callable APIs. Preserve composition, dimensions, styles, icons, typography, animations, overlays, dialogs, nested tabs, and conditional loading/error/result states. A new simplified dashboard is not a replacement for an original screen.

## Source inventory

`node infra/dev/inventory-original-ui.mjs` reads the original ARR and AG-frontend trees without modifying them. Its output, `original-ui-elements.json`, records source hashes, imports, and every parsed JSX opening/self-closing element with line and attribute names. It currently contains:

| Source | TSX/CSS files, excluding tests | JSX occurrences |
| --- | ---: | ---: |
| ARR frontend | 202 | 3729 |
| AG-frontend | 72 | 1686 |
| Total | 274 | 5415 |

These are source occurrences, not counts of distinct features or rendered DOM nodes. Same-name native candidate paths only help locate comparisons; they are not proof of migration. Every record remains unverified. Non-TSX generated elements, third-party internals, public assets, fonts and actual browser states need further inspection. Components outside current routes stay accounted for; reachability and intended destination must be determined instead of silently dropping them or importing unused code.

## Confirmed view gaps and sequence

1. **ARR LandMap → native `/map`.** Original search bar, OpenLayers view, 420px analysis panel, loading overlay, skeleton and empty state exist in the native source. Compare each nested `BigStat`, `RegulationCard`, `LandInfoSummary`, `DatumInfoCard`, `LawArticlesList` and expanding regulation group in actual rendered states. Original style preservation and complete behavior are not closed by the earlier fixture screenshot. Validate real imagery, cadastral lines, selected parcel, regulatory overlays, repeated selection and errors.
2. **ARR LawChat → native `/law`.** Not yet ported. Preserve the combined chat/map composition, `ChatHeader`, `MessageList`, `HeroSearch`, `BottomInput`, streaming/model/status/clear/stop controls, `ResultDisplay`, `ArticleDetailPanel`, search progress states, `MapPanel`, map search and analysis mode controls, land result cards and `AgentProgressPanel`. The original VWorld 3D hook is used here via `use-map-law-search.ts`; replacing this with the 2D LandMap loses a view. Preserve the dialogue display without claiming that unfinished external agents work.
3. **ARR DesignPage → native `/design`.** Not yet ported. Preserve `ControlPanel`, `LegalBasisPanel`, `ConstraintSummary`, `DatumInfoCard`, `SunlightSectionDiagram`, `GenerationProgress`, `ParetoChart`, candidate `DesignList`, `DesignInspector`, `MassExecutionPassportCard`, `FloorPlanViewer`, `SiteMapPanel`, `InteractiveDesignPanel` and `DefaultAgentFlowPanel`, together with the page's own selectors/buttons and conditional layouts. `SiteMapPanel` uses VWorld 3D, parcel highlighting and building visibility. Move the whole connected view, not detached unused components. Existing PLANM views do not satisfy this requirement.
4. **ARR BookLanguagePage → native `/design/language`.** Preserve `BookLanguageFlow` and its nested network, portfolio filters/cards, execution graph, geometry/elevation/render/evidence panels and boundaries. A route stub or two-element parent page is not the complete view.
5. **Remaining original routes and shared chrome.** Account for ARR law/design/history/login/signup/settings and AG-frontend playground/history/comparison/build/MCP/gallery/settings views, their nested dialogs and shared navigation/layout/assets. Use the full source inventory with the route ledger; do not use a handpicked list of top-level pages as evidence of completeness.

For each route: read its complete dependency tree; retain original presentation in `features/<domain>`; use a thin Next App Router entry; adapt navigation and explicit same-origin backend contracts; compare original/native at the same viewport with the same inputs and open tabs/dialogs; exercise controls and save/reopen; only then close the route and its nested element rows. Styles must remain scoped so they do not alter the existing Editor canvas/tools.

## Backend pairing

ARR's Django root includes law, land and design. Native Editor should own migrated domain behavior; do not make ARR a permanent HTTP dependency or place a new `arr` domain folder in Editor.

The original land routes include analyze, agent-analysis stream, resolve/reverse, zones/stats, map-config, elevation-grid, parcel geometry, roads, datum, basement-storey, tile and WMS. Native land currently exposes only a subset; a tile endpoint does not replace the map-config/3D SDK or elevation-grid contracts.

Original design routes include jobs/run/cancel/stream/results/evidence/aesthetic/validate; site boundary and constraints; floor plans/program floor plans; masterplan operations; interactive patch/preview/operation; revisions/feedback; language/outcome graphs; portfolios/evaluations; executed masses/passports; geometry/book/reference/render/elevation assets. Pair each actual UI consumer with its native contract and preserved artifact identity. Do not infer route parity from a similarly named backend module.

## Actual provider evidence on 2026-10-05

The existing ARR backend `.env` contains a VWorld key. Its value was not printed or committed. With that key, the native Editor adapter returned a real PNG (39787 bytes). In-process native FastAPI requests using real VWorld responses verified tile200, address resolution200 with coordinates, reverse200 with PNU/geometry and parcel geometry200. These calls used ASGI transport, not the running Next proxy.

The first native ASGI cadastral WMS call returned502. A subsequent direct provider request returned200/image-png (1784 bytes). This does not establish stable WMS behavior or browser display; investigate and repeat the native path before closing cadastral verification.

The configured hidden backend18449 launch was rejected before execution by the execution tool with `blocked by policy`; no detailed reason was supplied. No policy was changed, no alternative launch was attempted after that rejection, and no existing process was stopped. Current listening services include native frontend3003 and backend18447. That backend still lacks this provider configuration; live native VWorld display remains unverified. Permission settings alone do not explain the rejection.

## This increment

Delivered the reproducible source-element inventory and corrected the integration/verification scope. No new original view is claimed migrated by this audit. Next implementation starts with the original connected views above, preserving all their child elements and states; shared-agent implementation remains outside this frontend/backend work.
