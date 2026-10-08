# Editor frontend — memory index (read this first)

Working memory for any AI session on the editor **frontend** (`D:\Data\25_ACE\editor\frontend`,
the Next app is `frontend/app/editor`). Read this index, then the file for your task. Facts
carry dates; update the matching file when you learn something durable. Upstream Pascal
editor rules (3D viewer/editor layers) are in the repo-root `AGENTS.md` and `docs/architecture/`
— this folder covers the 25_ACE platform side that was added on top.

Who owns what (2026-10-06):
- Since 2026-10-06 **one editor session owns both frontend and backend** (the two roles below are
  held by the same session; it is modularizing both — see `05-decisions.md`).
- **Editor frontend session** (you): `frontend/` — pages, API proxies, workspace (AG) UI, law/
  design/planm screens.
- **Editor backend session**: `backend/` — see `../../backend/memory/MEMORY.md`. Every backend
  path the UI calls must exist there (guards below).
- **Orchestrator session**: `D:\Data\25_ACE\agents\*`. The UI reaches agents only through the
  backend (`/api/v1/platform/...`), never directly.

| File | Read when |
|---|---|
| [01-shape.md](01-shape.md) | finding a page/feature, what came from ARR/AG |
| [02-backend-contract.md](02-backend-contract.md) | calling the backend, adding an API client or proxy |
| [03-run-and-test.md](03-run-and-test.md) | starting, ports, tests, type checks |
| [04-pitfalls.md](04-pitfalls.md) | before debugging something odd |
| [05-decisions.md](05-decisions.md) | dated log of decisions |

## Quick pointers (2026-10-08)
- Shell: `/dwg` = `features/shell` (Shell.tsx, layout/, artifact-host/, conversation/, sidebar/, `artifact-types.ts`, `registry.ts`).
- Artifacts: `features/artifacts/<id>/{manifest.ts, ui/, model/, api/, lib/}` — site-map (default), cad, system. Rule in 01-shape.md.
- Site map: click = whole parcel, Shift = bundle, save → `api/selection.ts`; run panel `ui/SiteRunPanel.tsx` → Orchestrator.
- Dev server: `bun run dev -- --webpack --hostname 127.0.0.1 --port 3003` (03-run-and-test.md); restart daily.
- Decisions log: 05-decisions.md (newest first).
