# Decisions (newest first)

One dated line per decision with its commit.

- 2026-10-06 Workspace models run locally on the Claude Code login (backend
  `EDITOR_MODEL_AUTH=oauth`); `/settings` keys are for deployment. (backend `792b4644`)
- 2026-10-05~06 ARR and AG frontends absorbed: AG workspace pages under `(workspace)/`, AG
  frontend unit tests ported to `bun:test` (8 files), labels "Editor Workspace" / "에디터
  워크스페이스", Studio provider names mapped to `autogen_agentchat`. ARR screens `/law`,
  `/map`, `/design` moved; design client URLs lost their trailing slashes, the land
  proxy became `app/api/v1/land/[...path]` (streams SSE), and `lib/api-surface.test.ts` +
  backend `route-inventory.json` guard against dead calls.
