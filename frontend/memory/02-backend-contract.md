# Talking to the backend (2026-10-06)

## The path a request takes
Browser → Next route handler `app/api/v1/<domain>/[...path]/route.ts` → `lib/backend-request.ts`
→ FastAPI backend (`EDITOR_BACKEND_URL`, port 18449 in dev). Proxies exist for `design`,
`land` (+ `land/tiles`), `law`, `planm`, `platform`, `workspace`; plus `/api/scenes*`,
`/api/health`, `/api/[...cad]`, `/api/plugins/mint/...`.
- `backend-request.ts` refuses cross-site/cross-origin **changes** (403) and answers 503 when
  `EDITOR_BACKEND_URL` is unset. Streaming paths (ending `/stream`) are passed through
  (`/law` deep analysis is SSE: `GET /api/v1/land/agent-analyze/stream`).
- The design proxy forwards only paths `isDesignOperation()` accepts (`lib/design-operation-path.ts`).
  A new backend design path needs an entry there.

## Rules
- **No trailing slash** in client URLs (a backend 308 costs a round trip). The design client
  (`features/design/lib/api-client.ts`) builds `${BASE}/...` URLs and none end with `/` — keep it so.
- **Every client call must hit a real backend route.** Guards: `lib/api-surface.test.ts`
  (scans client files for `${BASE}/...`, `apiRoot}/...`, `workspaceRequest('...')`, literal
  `/api/v1/...`, calls the matching `route.ts`, and checks the path is in
  `backend/route-inventory.json`). A "dead call" (UI calling a route that does not exist — the
  original `/law` deep-analysis bug) fails this test.
- **Agent-only backend doors are not for the UI**: `/api/v1/{domain}/agent/{op}`,
  `design/masterplan/operations`, `design/maas/delivered-mass-export/{bundle,<hash>/...}` need
  the agent network token. Do not call them from the browser.
- The UI never calls an agent directly; Orchestrator data comes through `/api/v1/platform/*`.

## Model keys in the workspace UI
Locally the backend runs workspace models on the developer's Claude Code login
(`EDITOR_MODEL_AUTH=oauth`); keys in `/settings` matter for deployment (`api_key`). The stored
OpenAI key has no credits — a failing key test in `/settings` is expected locally.
