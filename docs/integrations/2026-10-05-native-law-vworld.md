# Native original LawChat and live VWorld

Current URLs: `http://127.0.0.1:3003/law` and `/map`. These are native Next App Router screens in `frontend/app/editor`, using Editor FastAPI on `http://127.0.0.1:18449`. No ARR server proxy was introduced.

## Implemented

- Ported the original connected LawChat view into `features/law`: hero/search, domain and streaming controls, messages, result cards/statistics, article detail/copy/close panel, map search, analysis mode/building toggle and progress display. Reused the already ported land cards; added the original VWorld3D hook and progress component. Kept original inline visual styling and animations. Native `/law` entry and workspace/map navigation now expose this view.
- Added native law search, domain search, domains, health, article and SSE routes plus an allowlisted Next BFF. Search preserves provider metadata/statistics; malformed card stages are normalized. Domain search never silently returns global fallback results. SSE reports observed start/result/error, not invented intermediate agent stages. Upstream requests abort when the browser request is cancelled.
- Added VWorld browser SDK configuration using explicit `VWORLD_BROWSER_API_KEY` and no-store responses; the server-only key is not used as an implicit browser fallback. Original ARR configuration was reused in the ignored local runtime profile without printing or committing its values.
- Removed the original hook's blanket ban on automated browsers; actual WebGL capability determines availability. Fixed the observed route-return defect: the singleton VWorld viewer remained detached after leaving LawChat. Its DOM/map are now retained and reattached; inactive rendering/events and owned SDK styles are suspended on departure. Building visibility synchronizes after initialization/reentry.
- Quick land analysis is the default. The original advanced-analysis control remains visible, and connection failure stays visible instead of disappearing with an empty progress panel. Its execution endpoint remains unfinished; no agent implementation was added.

## Live execution and evidence

The hidden literal `Start-Process` with uvicorn's explicit `--env-file` succeeded. Previous rejected compound commands do not mean all startup is blocked. No permission policy was changed. Latest backend PID39372, native frontend listener PID77168; recheck identity before any management. Older backend18447 was preserved.

- Native Next tile proxy200 PNG; live `/map` browser observed13 successful base-tile and12 successful WMS responses with no failures during observation. Inspected real cadastral/map imagery screenshot; that capture still has some pending outer tiles and is not proof every viewport tile finished.
- Real `/law` browser rendered textured VWorld3D buildings, map imagery and original SDK toolbar. Viewer camera was at about1725m; loader disappeared. Same-document `/law`→`/map`→`/law` now retains attached canvas, without a document reload.
- Real native law health200 and search/SSE200. The tested Korean search returned **zero results** from the configured law-light provider (`keyword_count:0`). This proves transport and empty-state behavior, not populated retrieval or article-source accuracy. The previous primary law endpoint timed out; this local runtime profile selects the responsive existing light provider directly.
- Final Chrome suite: **11 passed** in one run with `EDITOR_TEST_URL=http://127.0.0.1:3003` and `EDITOR_VERIFY_LIVE_VWORLD=1`. Includes original law search/result/detail/close/reset/reload fixture interactions, sidebar viewport bounds, real VWorld3D route return, previous land/map/Editor/catalog/dialogue/flow checks. Fixture results remain distinguishable from real provider evidence.
- Backend checks: **40 passed** across law routes/provider adapter, land map and existing law search tests. Native TypeScript passed. Earlier test invocations without required `EDITOR_TEST_URL` failed on `undefined/...`; the final configured suite above supersedes them.

Ignored screenshots: `test-results/law-live-3d.png`, `law-live-vworld.png`, `law-live-vworld-return.png`, `law-original-article.png`, `vworld-live-2d-complete.png` (filename does not imply all pending tiles completed).

## Local restart profile

Ignored `.superpowers/sdd/editor-law.env` contains provider values and Editor data/origin bindings. Current runtime uses `C:/Python313/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 18449 --env-file D:/Data/25_ACE/editor/.superpowers/sdd/editor-law.env`, working directory Editor. Launch hidden and redirect logs to `.superpowers/sdd/law-backend.{stdout,stderr}.log`. Native app's ignored `.env.local` points `EDITOR_BACKEND_URL` to18449. Do not copy secrets into tracked files or logs.

## Not complete

DesignPage, BookLanguagePage, parking/drawing/floor-plan workflows and remaining original routes still require full view/component migration. Law search index population, primary domain services, live article retrieval (including original Neo4j hierarchy), search-history persistence and advanced land-analysis streaming are not closed by this increment. The native article adapter currently uses the configured worker's law search/text contract and rejects ambiguous matches; no Neo4j parity claim. Original all-view/all-element requirement remains active. Shared agents remain separate and unfinished.
