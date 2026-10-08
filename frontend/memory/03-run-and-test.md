# Run and test (2026-10-06)

## Start
- Whole stack: `bun run plan:dev` from the editor root (`node infra/dev/product.mjs`): backend
  18449, frontend 5173 (base path `/editor` for the Pascal editor surface), standalone editor
  3002, MCP bridge 3917. Every port lives in `infra/config/services.json` (schema-checked;
  `infra/host/registry.mjs` reads it, `runtime.mjs` holds no literal; `bun run host:check`).
- Currently (2026-10-06) a production build is served manually by
  `next start --hostname 127.0.0.1 --port 3003` (started by another session). A code change is
  live there only after `next build` and a restart of that process.
- The route handlers need `EDITOR_BACKEND_URL` (e.g. `http://127.0.0.1:18449`).

- Dev server (2026-10-07, used by the editor session): from `frontend/app/editor`,
  `EDITOR_BACKEND_URL=http://127.0.0.1:18449 bun run dev -- --webpack --hostname 127.0.0.1 --port 3003`
  (port 3003 matches `EDITOR_PUBLIC_URL` in `.superpowers/sdd/editor-law.env`). **`--webpack` is required**:
  Next 16 defaults to Turbopack, which cannot resolve `@dwg/contracts`' `./cad.js` -> `cad.ts` imports
  (only the webpack config has `extensionAlias`); /dwg fails and the error sticks to every later page.
  Logs: `logs/frontend-3003.{log,err}`. 22 pages answered 200 on 2026-10-07.

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
