# Known traps (2026-10-06)

- **"Not the Next.js you know."** `frontend/app/editor/AGENTS.md`: this Next version differs from
  training data — read `node_modules/next/dist/docs/` before using an API you are unsure of.
- **Dead calls.** A client URL with no backend route used to slip through (the `/law` deep
  analysis called a route that did not exist; the land proxy could not stream it). Keep
  `api-surface.test.ts` green and add the proxy path when you add a backend path.
- **Trailing slashes** cause backend 308 redirects; build URLs without them.
- **`NEXT_PUBLIC_*` is inlined at build time**; changing it needs a rebuild, and a remapped port
  can break pages that fetch their own API (see `infra/docker/docker-compose.yml` comment).
- **Running server is a build.** Port 3003 serves `next start`; edits do nothing until rebuilt
  and restarted.
- **Model keys.** A failing OpenAI key in `/settings` is expected locally (no credits); the
  backend uses the local Claude Code login (oauth) for workspace runs.
- **Turbopack dev breaks on `@dwg/contracts`** (`./cad.js` not resolved). Run `next dev --webpack`; a
  compile error from one page is then served for every page until restart.
- **Proxy 404 "Unknown platform/PLANM operation"** is the proxy allowlist, not a missing backend route.
- **Map selection UX (user, 2026-10-07):** a click selects the whole parcel polygon (fill + outline); never draw
  points/markers/ripples at the click location — it looks wrong. Progress = cursor only; the only overlay on the
  map besides parcels is one info card. A site can be several parcels (합필): Shift+click adds/removes.
