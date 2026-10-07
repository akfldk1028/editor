# Decisions (newest first)

One dated line per decision with its commit.

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
