# Decisions and contract changes (newest first)

Write one dated line per decision; link the commit. Contract changes to agent doors must also
be told to the Orchestrator session.

- 2026-10-08 `1ce68ad9` `GET /api/v1/platform/status` (modules/platform/status/: registry.py reads
  infra/config/services.json, probes.py httpx 3 s/20 s cache, service.py merges Orchestrator list_agents when up);
  `/platform/agents` returns structured 503 `{agents:[], orchestrator:{state:'down',error}}` when the Orchestrator
  is unreachable (frontend listAgents maps !ok -> 연결 실패). Shell artifact `features/artifacts/system/` (FSD
  segments) polls it every 10 s. Live: 22 rows, up = backend/dwg/site-context/scene.
- 2026-10-08 `1c5e2823` agent-host supervisor `infra/host/` (policy/probe/processes/state/supervise/status/cli):
  detached daemon, adopts live listeners (no duplicate ports), 3 failures -> backoff 5/10/20/60 s restart, logs
  `logs/host/<id>.*`, pids `runtime/host/`. `bun run host:start|stop|status`. backend/dwg/pascalMcp are now
  `lifecycle: persistent`; product.mjs reuses host-run services. Measured: backend kill -> health 200 in 13.8 s.
  Daemon pid 11520 guards `backend` only (dwg not yet, RAM). Agents start only with `--with-agents` (their owners').
- 2026-10-08 `a978fce0` run door also accepts a site run: `schemas/site_run.py` — exactly {goal, pnu[, building_type]},
  goal in {limits}, pnu 19 digits (regex restated there: schemas sit below modules in the layer contract, so
  modules.land.pnu cannot be imported). RunService/adapter unchanged; Orchestrator REQUEST_KEYS has no `parcels`.
- 2026-10-08 (Frontend session, plan P1) service registry: `infra/config/services.json` grew from 7 lifecycle
  rows to 22 schema-checked entries (editor 5, orchestrator 1, agent 15, infra 1) and became the only place a
  port lives; `infra/host/registry.mjs` derives URLs, `infra/dev/runtime.mjs` reads it (keys `source_owner` ->
  `owner_repo`, `planAgent` -> `plan`). `bun run host:check` (infra/host/*.test.mjs) proves a2a.ps1, the
  catalogs, the owners' serve scripts and editor_api.py agree with it. Findings for the Orchestrator session:
  a2a.ps1 lists 15 agents (not 16); SiteContext's serve-a2a.sh reads SITE_A2A_URL while everyone else says
  SITE_CONTEXT_A2A_URL; Program/KMass/Systems/DomainExpert/Interior read no *_A2A_URL at all (catalog-only).
- 2026-10-07 (MasterPlan session, user-approved result change: "커밋하고 진행해 비교를 해야지") planner:
  compact_basement_search now defaults on, and a capped basement budget keeps one solve for the row-and-aisle
  family. 고산 (district plan incl. 차량출입불허구간, practice programme) 0+50 -> 22+28, one gate, entrance
  0.78 m / ramp 6.2 m from practice ALT1. 16-parcel corpus: totals and pass/fail identical, 2 split changes.
  masterplan_engine 205 passed. Evidence: MasterPlan runs/siting-eval/{baseline,fix1-default}-20261007.
- 2026-10-07 (MasterPlan session) `8ed39f9d` planner compact-slab pass: a ValueError from one degenerate
  candidate no longer aborts plan_site (고산 target_surface_stalls=30 crashed). Results change only where
  plan_site used to raise. The uncommitted rank change (road openings before excavation) was REVERTED — it
  changed default results and moved nothing on 14 parcels. Untracked `masterplan/siting_terms.py` +
  `tests/masterplan_engine/test_siting_terms.py` are measurement only (imported by nothing in the engine);
  any future generation work there will be opt-in behind an option, default results hash-identical.

- 2026-10-07 Final review at `d6ac0845`: backend suite (minus masterplan_engine, which sits under another
  session's uncommitted edits) 2119 passed / 3 skipped / 1 failed / 15 errors — the failure set is identical at
  b427e1bc (`test_mass_native_cli[generate_massv2]`, `provider_parity/test_maas_creative_floor_portfolio` x15).
  Agent doors 24/24 same across all 13 refactor commits; HEAD vs b427 differs only in parking-count (other
  sessions' law/ordinance commits). 71 agent-imported paths and 113 imported names resolve; planm sources net
  diff none; lint-imports kept. Removed pyc-only leftover dirs (adapters/vworld, cli, core/geometry) — they made
  old paths import as empty namespace packages. Trap: after moving a package, delete its old dir's __pycache__.
- 2026-10-07 Structure from researched practice (FastAPI 'Bigger Applications', zhanymkanov/fastapi-best-practices
  after Netflix Dispatch, Kraken + import-linter): `db167db3` every domain owns its routers/clients —
  `modules/{land,design,workspace,platform,planm_runs}/routers/`, `modules/law/router.py`, `modules/land/vworld/`,
  `modules/design/dependencies.py`, `modules/regulations/extraction.py`; `api/` keeps only the agent doors
  (routes_agent_providers, agent_providers/, routes_design_runtime, design_runtime/). 102 routes identical.
  `fb8fb3f6` layer contract in pyproject `[tool.importlinter]`: route_inventory > main|cli > api > modules >
  adapters > core|schemas|contracts; 2 ignored imports with reasons; `test_import_layers.py`; `lint-imports`.
- 2026-10-07 `194f0744` + `4887d59c` REVERTED the engine move (2dfb5b40) and the cli split (65045d70).
  Reason: `agents/planm/scripts/import_from_editor.py` re-imports the floor-plan engine from this repo BY PATH
  (`backend/engine/**`, `backend/app/cli.py`, the 17 engine packages generation_loop, layout_generator,
  validator, visual_review, basic_design, alternative_composer, building_quality, egress_graph,
  circulation_planner, core_planner, area_ledger, program_prior, mass_analyzer, llm_planner,
  local_topology_planner, generator_adapters, precedent_retriever + planm_execution, schemas, grid services).
  These are planm's (Plan Agent's) engine sources, to be deleted here after the editor is re-pointed to
  planm (branch `plan-agent-repoint`) — never move or split them. Grouping them into `modules/building/`
  was cancelled for the same reason. Net diff over all 160 planm sources vs b427e1bc: none.
- 2026-10-07 RULE: `D:/Data/25_ACE/agents/**` and `editor/agents/**` are read-only for the editor session.
  Agent code imports 71 editor module paths directly (MassAgent/KMass/MasterPlan scripts+tests, Lawagent
  tests) — check they all still resolve before any move.
- 2026-10-07 `1013b5b8` route inventory tool moved from `core/` to `app/route_inventory.py` (beside main).
- 2026-10-06 `2dfb5b40` [REVERTED by 194f0744 — planm sources] `backend/engine/` -> `backend/app/core/geometry/`;
  21 importers updated, no shim; 824 tests same; agent doors 24/24 identical.
- 2026-10-06 Verified: agent doors answer byte-identically before/after each refactor commit
  (65045d70 94b08e71 f14f7806 4999585d 2fc0c8c4 cda1a007 57ef5810 05c42ec4; 24 calls via TestClient:
  parking-count x5, 11 law ops, basement-storey x2, plan_site x5 incl. ramp_gosan, ramp_overhead).
  The only door change today is parking-count from `d4ee05b9` (other session's ordinance data).
- 2026-10-06 RULE (user): existing agent logic must not change yet — land/reference calculators,
  masterplan engine, maas/delivered, maas/parking. Moves/splits only with identical result hashes.
  HOLD: unifying `regulations` with `land/reference` (UI `/land` still reads the old ordinance
  data in `regulations/data`; agents read the 163-jurisdiction set in `land/reference/data`).
  Reference case: `D:/Data/25_ACE/data/projects/01_example/Alt1|Alt2` (고산 공공1 real alternatives).
- 2026-10-06 `cda1a007` adapters/vworld/ (moved on to `modules/land/vworld/` in db167db3), `57ef5810` adapters/workspace/ (+ one-time catalog migration
  of stored tool providers, live on next backend restart), `05c42ec4` maas/delivered/ + maas/parking/.
- 2026-10-06 `2fc0c8c4` regulations/land split modules are packages like `cli/`:
  `regulations/{calculator,setbacks}/`, `services/{regulation_calculator,setback_geometry}/`
  (533 hashes identical, 421 pass after rebasing onto `d4ee05b9`; ORDINANCE_DIR re-pointed;
  import_design_runtime.py maps package destinations to `__init__.py`).
- 2026-10-06 PENDING: branch `pkg/masterplan` `2d0e82e0` (`masterplan/{planner,rows,validation}/`,
  plan_site hashes identical, 205 pass). Held: another session has uncommitted edits to
  planner.py/planner_rank.py/joint.py (+ new siting_terms.py). Cherry-pick after they commit;
  their planner_rank edits land in `planner/rank.py`.
- Folder rule (user, 10-06): a split module becomes a package (`foo/__init__.py` + parts), never
  prefix siblings (`foo_rules.py`). Existing flat conventions (`design_runtime/*_views.py`) stay.
- 2026-10-06 Modularization round 1 (platform core, pure moves, originals stay the public import path):
  `65045d70` cli.py -> `cli/` package [REVERTED by 4887d59c — planm source]; `94b08e71` design_runtime views.py -> 7 modules; `f14f7806`
  masterplan planner/rows/validation -> siblings (plan_site hashes identical; planner.py still 835 —
  `_plan_site_fixed` is one closure-heavy function, splitting it is a refactor); `4999585d`
  regulations + land/reference calculator/setbacks split (385 output hashes identical; the two
  diverged copies were NOT merged). Monkeypatched names and their callers stayed in the original
  module. `backend/scripts/import_design_runtime.py` + `source-manifest.json` still hash the
  pre-split files — do not re-run the importer over them (it would overwrite or flag the splits).
  Agent doors unchanged. Not done: research code under `design/generation` (book_language, massv2).
- 2026-10-06 `1ec08619` Delivered mass export by content: `/bundle` door, `files/` and
  `package.zip` routes, hrefs on results. Mass ships its cycle; nothing reads Mass's disk.
- 2026-10-06 `5ddd2b35` A2A_TOKEN on agent doors; planm stages travel as bundles
  (planm-stage-bundle/v1).
- 2026-10-06 `792b4644` Local OAuth for workspace models (EDITOR_MODEL_AUTH); API keys only in
  deployment.
- 2026-10-06 `f82d804a` Planning engine: 209/209 (bounded large-site search, single-loaded rows,
  direct two-bay aisles, exact curved ramps, design target without Law count follows dad68f5).
- 2026-10-06 `009a5b1e` 차량출입불허구간 enforced for ramps/connectors/surface entrances;
  validation placement_stage scope fix.
- 2026-10-06 `ef2eb0e6` `ramp_overhead` planning op; `law/agent/parking-count` provider op.
- 2026-10-05~06 ARR + AG absorbed into the editor (workspace keys/tool policy/validate-test/
  seeds/Replay/deep-analysis SSE; route inventory + api-surface guards; 18449 declared in
  services.json). ARR/AG are no longer run or called.
- 2026-10-06 Datum DEM is a VRT. `NGII_DEM_LOCAL_PATH` (sdd env) now names
  `D:/Data/NGII_DEM/ngii_dem.vrt`, which SiteContext rewrites when it adds a WFS contour tile
  for a parcel outside the installed mosaic (`tiles/wfs_<x>_<y>.tif`, mosaic listed last, so it
  wins). `elevation_api._get_ngii_dem_src` reopens when the file's mtime changes. Changed by the
  Orchestrator session; Site owns the tiles (agents/SiteContextAgent `dem.ensure_cover`).
- 2026-10-06 Ordinance caps for all 163 jurisdictions (`d4ee05b9`), generator in
  `law/reference/scripts/ordinance_batch/`. Calculator looks up the 시 of an 일반구
  (`ordinance_codes`). Known: the original `fetch_ordinance_caps.parse_caps` misread "1,500" as
  500 and spaced zone names; the rebuild parser replaced its values. Re-run the three scripts
  rather than `fetch_ordinance_caps.py` alone. Changed by the Orchestrator session.
- 2026-10-06 `d467c0d8` Datum heights over HTTP: `ELEVATION_PROVIDER=sitecontext_ngii` (sdd env, with
  `SITE_CONTEXT_AGENT_URL`) makes both datum engines POST points to SiteContextAgent
  `/site/ground-heights` instead of opening its DEM file - strict, no fallback. Law grades it
  `calculated` (`ngii_1to5000_sitecontext_dem`). Live: 고산 59.89 m, 1168010100108230026 26.07 m.
  `ngii_local_dem` stays for a same-host install. Changed by the Orchestrator session.
- 2026-10-07 World view W0+W1 (`/world`): our own CesiumJS 1.122 from jsDelivr (no VWorld SDK, no ion
  token) with clean white context masses. `GET /api/v1/land/context-buildings?lat&lon&radius_m` ->
  `adapters/scene_agent.py` -> SceneAgent `POST /scene/context-buildings` (SiteContext footprints +
  SceneAgent height rule; each mass says measured / estimated / unknown, unknown drawn pale). Base map
  toggle: plain white or VWorld 2D via the existing tiles route. Env `SCENE_AGENT_URL` (default
  127.0.0.1:8310). Existing `/map` `/law` `/design` untouched; their move onto this view is W2-W4 in
  agents/SceneAgent/docs/editor-world-plan.md. If VWorld SDK already loaded `window.Cesium` in the tab,
  it is reused. Changed by the Orchestrator session.
- 2026-10-07 `/world` anywhere: search by 주소/PNU (`locateParcel`, parcel outline drawn), open with
  `?pnu=` / `?q=` / `?lat&lon`, and the camera's view is filled cell by cell (~440 m cells, radius 320 m,
  ≤30 cells per move, 3 in parallel, failed cells retried on the next move, buildings de-duplicated by
  id). Site now also keeps 건물정보 footprints the 1:5,000 map lacks (agents/SiteContextAgent `2312bde`;
  고산 300 m 76 -> 161). Changed by the Orchestrator session.
- 2026-10-07 `/world` ground layer: `GET /api/v1/land/context-ground` -> SceneAgent `/scene/context-ground`
  = 연속지적도 parcels by 지목 class (SiteContext `site_ground_cover`: road / paved / green / water / farm /
  forest / lot) + carriageways (NGII centreline x recorded width; no width -> left out and counted).
  Road parcel = whole right of way, so the pavement reads around the darker carriageway. Toggles:
  건물 / 바닥. No 보도 layer exists in VWorld WFS; NGII road-surface polygons are stale in new towns
  (고산 2 %). Changed by the Orchestrator session.
- 2026-10-07 `/world` diagram ground (the site-analysis look the user pointed at): road parcels a grey channel at
  0.3 m, every other parcel a white block 0.3-0.8 m with a dashed edge, the site a red dashed outline; land cover
  inside lots (환경부 세분류 토지피복 2025 via Site `site_land_cover`, clipped to non-road parcels by SceneAgent) is a
  toggle, off by default. Carriageways are no longer drawn (the grey road parcel reads as the street); SceneAgent
  still returns them (lanes x 3.25 m capped by NGII rvwd, which is the whole road width). Ground floats above the
  globe because flat polygons at ~0 m z-fight with it. Changed by the Orchestrator session.
- 2026-10-07 W2 `/design` on the clean world: `SiteMapPanel` has an engine toggle (깔끔한 3D default / 브이월드);
  the engine change remounts the inner `SiteMap`, which calls `useWorld3D` or `useVworld3D` (same actions:
  highlightParcel, clearHighlight, flyTo, setBuildingsVisible, viewerRef), so the mass / setback / datum renderers
  are unchanged. `features/world/hooks/use-world-3d.ts` now owns the world (WorldView uses it too); the globe is a
  flat CustomHeightmapTerrainProvider at the site's §119 datum (`setGroundLevel`) so masses placed at their datum
  stand on the ground; setBuildingsVisible(false) hides the context buildings on the site. SceneAgent now drops
  map-only buildings that no longer stand (no storeys/height and <20 % built-up in 환경부 토지피복 2025, or >50 % on a
  road/river parcel): 고산 56, 종로 74. Changed by the Orchestrator session.
- 2026-10-07 W4 `/law` on the clean world: `features/world/components/MapEngine.tsx` mounts either engine and hands
  its actions up (`onActions`); `useMapLawSearch` no longer calls `useVworld3D` - it keeps the actions in its refs
  (`bindMap`) and exposes `onMapClick`, so switching engine (button "지도: 깔끔한 3D / 브이월드", clean default)
  remounts only the map and the chat survives. `useWorld3D` gained drawSetbackLines / clearSetbackLines (same
  colours and layer name as VWorld), the VWorld opening view, and flies to a highlighted parcel far from view. A
  search by PNU now fetches the parcel outline (`locateParcel`) so either engine can show and reach the site.
  `/map` is the 2D OpenLayers map and was left as it is. Changed by the Orchestrator session.
- 2026-10-07 W5 terrain in the clean world (toggle 지형, on by default): `GET /api/v1/land/terrain-heights`
  (box <= 0.1 deg, size 2..33, rows north->south) -> SiteContext `/site/ground-heights` (NGII DEM, all or nothing);
  `features/world/lib/terrain.ts` is a CustomHeightmapTerrainProvider (levels 13-15 asked, coarser levels and any
  refusal flat at the fallback level, at most 2 tile requests in flight so the context layers keep browser
  connections). Ground layers drape on the terrain; masses stand on SceneAgent's DEM base height (`base_m`), never
  on Cesium's RELATIVE_TO_GROUND - a zero-area footprint made TerrainOffsetProperty compute a NaN centre and stop
  rendering; rings with < 3 distinct corners are dropped. Backend 18449 restarted to serve the route.
  Changed by the Orchestrator session.
- 2026-10-07 review fixes to the world view (independent review of all 10-07 world commits): our Cesium 1.122 is
  kept off the globals and lent with a count (`acquireCesium`) only while a clean viewer is mounted, so a /law or
  /design engine switch never mixes it with the VWorld SDK's 1.99 (verified clean->vworld->clean->vworld:
  1.122 / 1.99 / 1.122 / 1.99; a stacked release under StrictMode had left window.Cesium empty). /design records
  the site in both branches (`setSite`) so old buildings never show through the mass; a cell is done when both
  requests settle (no unhandled rejections when the backend is down); a replaced DEM provider stops fetching;
  the site outline is redrawn on a terrain toggle; /law re-shows the site and setback lines after a switch.
  "handler is not a function" on switching to VWorld comes from the dev overlay `agentation` wrapping the VWorld
  SDK's requestAnimationFrame, not from this code. Changed by the Orchestrator session.
- 2026-10-08 floating context masses in the clean world (user: masses still float): on /world the fallback ground is
  0 m, every DEM tile coarser than level 13 or refused was flat at 0, and tiles were served in arrival order 2 at a
  time (5-12 s each) while Cesium asked out to the horizon - the ground under the camera stayed flat 0 for minutes
  and the masses, at absolute DEM heights (~60 m at 고산), hung in the air (no shadows, so it hardly showed). Now:
  masses stand RELATIVE_TO_GROUND on the terrain as drawn, their foot sunk by the DEM fall from centre to lowest
  corner (SceneAgent `top_m - height_m - base_m`) + 12 m, globe.depthTestAgainstTerrain on with terrain; rings with
  no area are dropped too (the old NaN stop came from zero-area rings). terrain.ts: waiting tiles are served nearest
  the camera focus first, levels 12-15 are asked at 33 x 33 (as fast as 17 x 17), a 5xx is asked once more, and a refused tile is filled from its
  nearest answered ancestor instead of flat 0 (that cut 60-100 m cliffs). Measured on 고산 /world (drawn ground under every
  corner): 615 masses, none on flat 0 after ~60 s, 1 with a 3.5 m gap (an apartment over a 24 m terrace edge). Backend 18449 (gone, no log) and the hung dev server 3003 (`write EPIPE`) were restarted
  with the documented commands. Changed by the Orchestrator session.
