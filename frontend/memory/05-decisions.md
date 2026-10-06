# Decisions (newest first)

One dated line per decision with its commit.

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
