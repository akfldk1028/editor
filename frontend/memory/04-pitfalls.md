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
- **CSS edit under `next dev --webpack` drops every stylesheet** in open tabs (page renders unstyled, `styleSheets`
  still 14) until a full reload (seen twice 2026-10-08 editing agent-feed.css). The in-memory agent feed is lost on
  reload, so re-run the flow after the reload rather than trusting the half-styled page.
- **Map selection UX (user, 2026-10-07):** a click selects the whole parcel polygon (fill + outline); never draw
  points/markers/ripples at the click location — it looks wrong. Progress = cursor only; the only overlay on the
  map besides parcels is one info card. A site can be several parcels (합필): Shift+click adds/removes.
- **Naver 지적편집도 is the default cadastral layer (user, 2026-10-09) — do not replace it.** In re-platted districts
  (고산 공공주택지구, 961-3) Naver's lines differ from the Vworld 연속지적도 the parcel outline comes from, so the outline
  looks rotated/shifted against Naver's lines; the Vworld polygon is the registry one (278.4 m2 vs official 279.9).
  A Vworld GroundOverlay replacement was tried and reverted (e15c3115 → f64830f1). If alignment is revisited, add it as
  an optional toggle, never as the default.
