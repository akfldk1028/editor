# Run and test (2026-10-06)

## Start
- Whole stack: `bun run plan:dev` from the editor root (`node infra/dev/product.mjs`): backend
  18449, frontend 5173 (base path `/editor` for the Pascal editor surface), standalone editor
  3002, MCP bridge 3917. Every port lives in `infra/config/services.json` (schema-checked;
  `infra/host/registry.mjs` reads it, `runtime.mjs` holds no literal; `bun run host:check`).
- Dev server (2026-10-09, the host runs it): `bun run host:start editor` from the editor root keeps the
  registered `editor` entry (port 3002) alive: `bun run dev --filter editor -- --webpack --hostname 127.0.0.1
  --port 3002` through turbo, log `logs/host/editor.{log,err}`; `bun run host:status` shows it; a code change
  is live by HMR. The backend's env file names this port as `EDITOR_PUBLIC_URL`, or the browser's POST doors
  (ask, ordinances, runs) answer 403. The manual 3003 instance of 10-07 is retired.
- The route handlers need `EDITOR_BACKEND_URL` (e.g. `http://127.0.0.1:18449`).

- By hand (same thing, when the daemon is not wanted): from `frontend/app/editor`,
  `EDITOR_BACKEND_URL=http://127.0.0.1:18449 bun run dev -- --webpack --hostname 127.0.0.1 --port 3002`
  (`EDITOR_BACKEND_URL` also sits in `frontend/app/editor/.env.local`). **`--webpack` is required**:
  Next 16 defaults to Turbopack, which cannot resolve `@dwg/contracts`' `./cad.js` -> `cad.ts` imports
  (only the webpack config has `extensionAlias`); /dwg fails and the error sticks to every later page.
  22 pages answered 200 on 2026-10-07; /dwg and both ordinance doors 200 on 3002 on 2026-10-09.

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
