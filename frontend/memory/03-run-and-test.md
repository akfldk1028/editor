# Run and test (2026-10-06)

## Start
- Whole stack: `bun run plan:dev` from the editor root (`node infra/dev/product.mjs`): backend
  18449, frontend 5173 (base path `/editor` for the Pascal editor surface), standalone editor
  3002, MCP bridge 3917. Ports live in `infra/dev/runtime.mjs` (backend port from
  `infra/config/services.json`).
- Currently (2026-10-06) a production build is served manually by
  `next start --hostname 127.0.0.1 --port 3003` (started by another session). A code change is
  live there only after `next build` and a restart of that process.
- The route handlers need `EDITOR_BACKEND_URL` (e.g. `http://127.0.0.1:18449`).

## Test (from `frontend/app/editor`)
- Unit: `bun test lib features/...` — the exact list is the `test` script in
  `frontend/app/editor/package.json` (lib + 13 feature folders). `test:browser`: design hooks.
- Types: `bun run check-types` (`next typegen && tsc --noEmit`).
- Lint/format: `biome` (`bun run check` at the root).
- E2E: root `plan:test:frontend` / `plan:test:product` / `plan:test:browser` (Playwright).
- Route guard: `plan:check:routes`; API surface: `lib/api-surface.test.ts`.

## Commit
Same editor checkout as the backend (branch `docs/editor-platform-plan-20261004`, Codex also
edits). Stage only your files.
