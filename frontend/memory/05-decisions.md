# Decisions (newest first)

One dated line per decision with its commit.

- 2026-10-08 `a978fce0` saved site -> Orchestrator: card shows "검토 시작 (법규·한계)" (site-map/run/: site-run.ts,
  useSiteRun.ts, SiteRunPanel.tsx); project = shell ?project= else the only binding else select; request
  {goal:'limits', pnu: parcels[0].pnu} via POST /platform/projects/{id}/runs (Idempotency-Key site-<sel>-<n>),
  polls /platform/runs/{id} every 3 s; Orchestrator down -> Korean error + retry. Bundles send only the first
  PNU until Orchestrator accepts `parcels[]` (requested). `agent-dialogue/runs.ts` gained generic submitRun.
- 2026-10-08 `588ac348` reopening a saved site uses its stored facts + `POST /land/selections/outlines` (outlines only,
  own memory cache, cap = MAX_PARCELS 50) instead of the preview (whose 20-new-PNU budget broke large restores).
- 2026-10-08 UI/UX review fixes `65c5755d` (site-map+shell) `3a63f1c8` (CAD pkg, Korean labels) `12aa371e` (backend):
  save/restore races (snapshot+generation), AbortController, click policy (plain click in bundle = only that parcel;
  re-click sole parcel = deselect; Shift/추가 = add/remove), Esc inner-first + defaultPrevented, hidden 3D stops
  render loop, narrow keeps ArtifactHost mounted (hidden+inert; Naver size from outer element), focus restore,
  separator hit 20px, prefs saved on drag end, Korean copy, dark tokens, role=application. Backend: per-PNU facts+
  geometry memory cache (10 min, 500, never disk), no reverse geocode (addr from parcel layer), selections.scope
  (land.sqlite v5, `latest?scope=`, site-map passes ?project= else default). Dev server on webpack grows to ~15 GB over a day:
  restart it daily until the production build (/_global-error prerender failure) is fixed.
- 2026-10-07 `06f1dae9` site-map 3D: World3D uses useWorld3D directly, creates the engine only once the site is
  known, places the camera instantly (flyTo + completeFlight, verified within 1.5 km) -> first context request at
  고산, 305 buildings in 15-18 s, no Seoul requests. Cause was order: engine opened at MAP_CONFIG_3D.center (Seoul),
  queued ~30 Seoul cells (PARALLEL=3, ~23 s each via SceneAgent). Context cells are uncached (7-23 s each).
  REQUESTS for the features/world owner (not done by us): (1) useWorld3D({initialCenter}) opening there;
  (2) public instant setView(lng,lat); (3) drop far queued cells (queue+asked) on a >1.5 km move; (4) ringOf
  must handle MultiPolygon (non-contiguous bundles draw only the first parcel today). Speed plan: nearest-first
  cell loading + cancel off-screen (world), one bbox request instead of 26 cells, SceneAgent parallel upstream
  calls (agents session), long-term nationwide building PMTiles.
- 2026-10-07 `1636df69` backend + `17b047f5` frontend: site selection. Click = whole parcel polygon (no points),
  Shift+click/카드 토글 = 묶음(합필) add/remove, union outline, contiguity (shapely 0.05 m). API
  `POST /land/selections/preview` (no save), `POST /land/selections`, `GET /land/selections[?limit]`,
  `GET /land/selections/latest` (404 if none). land.sqlite v4 `site_selections` (facts+sources+contiguity,
  no geometry/raw Vworld). Map engine created once (callbacks via refs), no pan/zoom on click, no router
  navigation (history.replaceState only), resize() via ResizeObserver, [2D|3D] toggle (3D = features/world,
  lazy, both kept alive, `?view=3d`). Outline vs Naver 지적편집도 offset 1.2-1.8 m measured at 686-2 only =
  source data difference (no transform in code). Open: 3D highlight not visually checked; terrain-heights
  502 in 3D (world feature); narrow-panel card sheet not live-verified; preview re-fetches facts per click.
- 2026-10-07 `2a5404ea` editor-owned shell `features/shell/` (Shell, layout/, artifact-host/, conversation/,
  sidebar/, artifact-types.ts contract, registry.ts) + right panel = artifact modules `features/artifacts/<id>/`
  (manifest + lazy component; ArtifactChrome fills header/menu). CAD is artifact `cad`, using only the CAD
  package public entry (`@click-around/workspace` public.ts: DwgWorkspaceProvider, DwgSidebar,
  DwgConversation, useDwgArtifact...). `c9a91919` default artifact `site-map`: engine adapter (naver when
  NEXT_PUBLIC_NAVER_MAP_KEY_ID is set -> naver.maps CadastralLayer 지적편집도, colors as given; else / on auth
  failure OpenLayers + Vworld as given), parcel red dashed outline + search marker only, default PNU
  4115011300106840001 (고산 공공1), `?artifact= ?pnu= ?address= ?engine=`. New features = new
  `features/artifacts/<id>/` folder + registry entry. Naver key: NCP Maps app `editor`, Dynamic Map only,
  URLs 127.0.0.1:3003, localhost:3003, 127.0.0.1:3005; key in frontend/app/editor/.env.local (ignored).
  Open: CAD e2e specs for the old frame need moving to the shell; CAD styles.css still duplicates shell tokens;
  backend only accepts Origin :3003 (3005 POSTs 403).
- 2026-10-07 `c424ea49` /dwg shell rebuilt: modes by own width (layoutModes.ts single source, CSS checked by
  unit test): wide>=1200 sidebar 240 [200..320] + rail 56, artifact 45% (stored as ratio, prefs v3); medium
  768-1199 sidebar drawer; narrow<768 one panel ([대화|도면] switch). One header row; chat column 48rem,
  bubble/plain replies, model chip in composer; artifact header = title + Run agents + ⋯ menu (Ctrl+K) + close;
  3 tabs. 11 widths: no overflow, min font 11, 0 buttons <24px. Unit 37/37, tsc 0. e2e specs updated but NOT
  run (playwright chromium not installed). Open: dwg styles.css 570 lines (>500); editor global top nav (20
  links) still scrolls horizontally above the shell -> move into the shell sidebar when features come in.
- 2026-10-07 /dwg responsive rebuild (user: "반응형웹이 아닌데 제대로 해, 최신기술로"): platform CSS only —
  container queries (mode by the workspace's own width: wide >=1200 / medium 768-1199 / narrow <768),
  grid+clamp, dvh, :has(), View Transitions; no new npm dep (risk of a 2nd React from
  infra/services/dwg/node_modules). Numbers from research: sidebar 260 [220..360] (ChatGPT), chat column
  max 48rem centered, artifact beside chat only while chat >= 320px else overlay (Claude), artifact default
  45% min 360; narrow = one panel at a time; type 11/12/14/16, targets >= 28px.
  Sources: openskillindex ChatGPT sidebar CSS, aiuxplayground Claude artifacts, chatjs chat-layout,
  servicetitan artifact-panel-layout, shadcn resizable. Module findings: shell lives inside the CAD package
  and is CAD-specific; app/dwg/page.tsx deep-imports src/app/App instead of the package export (public.ts).
- 2026-10-07 User: `/dwg` (Claude/ChatGPT-style 3 panels: sidebar | chat | artifact) is THE fixed shell —
  every feature will go inside it. Its code lives in `infra/services/dwg/apps/workspace` (layout: App.tsx,
  styles.css, useWorkspaceControls.ts breakpoints 1280/886, workspacePreferences.ts widths sidebar 320
  [280..420], chat min 500, artifact min 520). Layout audit 10-07 (1920..390): no page overflow, but chat
  1066px wide at 1920 while artifact stays 520 (27%); composer spans full chat width; 83/89 text items <12px
  (some 4-7px); artifact tabs overflow at all widths; global top nav (20 links) scrolls horizontally <1920;
  at 1280 artifact squeezed to 446 (<520 min); crossing below 1280 leaves the sidebar open as a covering
  overlay; <=886 artifact opens full-screen over the chat by default; at 390 the artifact close/maximize
  buttons are pushed off-screen (cannot close). CAD needs the gateway: `npm run gateway` in
  infra/services/dwg (:4317, EDITOR_DWG_BACKEND_URL in frontend/app/editor/.env.local).
- 2026-10-06 `d9992018` Split pieces live in the feature's own `components/`, `hooks/`, `lib/` —
  never as siblings of the page (user: "폴더구조 제대로 지키고").
- 2026-10-06 Modularization round 1 (pure splits, originals keep every export): `293cac0a` design
  (mass-entities 513, sunlight, facade-materials, DesignPage, BookLanguageFlow, execution-graph-model);
  `bbd24c52` workspace (PlaygroundPage 505, use-vworld-3d, layout-generator, TeamsPage, LawChat).
  Upstream Pascal files (`components/`, `elements/`, app `build-tab`/`viewer-toolbar`) are not split.
- 2026-10-06 Workspace models run locally on the Claude Code login (backend
  `EDITOR_MODEL_AUTH=oauth`); `/settings` keys are for deployment. (backend `792b4644`)
- 2026-10-05~06 ARR and AG frontends absorbed: AG workspace pages under `(workspace)/`, AG
  frontend unit tests ported to `bun:test` (8 files), labels "Editor Workspace" / "에디터
  워크스페이스", Studio provider names mapped to `autogen_agentchat`. ARR screens `/law`,
  `/map`, `/design` moved; design client URLs lost their trailing slashes, the land
  proxy became `app/api/v1/land/[...path]` (streams SSE), and `lib/api-surface.test.ts` +
  backend `route-inventory.json` guard against dead calls.
