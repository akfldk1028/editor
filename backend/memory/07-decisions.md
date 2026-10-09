# Decisions and contract changes (newest first)

- 2026-10-09 Source-bound pedestrian placement: apply_placement_moves now accepts pedestrian_route (keep/front_start/front_middle/front_end) plus explicit positive pedestrian_width_m. Requires source-attributed pedestrian_frontage and fixed ground building zone; never substitutes vehicle frontage. New pedestrian_route_design is realized before parking, preserves source reservations, and serializes corridor/centerline/proposed facade entrance. Independent validation rejects missing features and conflicts; doors, slopes, accessibility and complete arrival network remain pending. Consumer support for Law-reviewed pedestrian_approach/reserved-area geometry is in MasterPlan synthesis. 45 focused engine tests passed. Actual Site/Law Gosan receipt has 72 reviewed clauses but no confirmed pedestrian approach geometry; no completed real-parcel route claimed. No new route URL, shared-service restart or external message.

Write one dated line per decision; link the commit. Contract changes to agent doors must also
be told to the Orchestrator session.

- 2026-10-09 MasterPlan AI placement loop: added `apply_placement_moves` to the existing planning operations door (request+moves -> request/applied/unresolved). Bounded symbolic proposals become engine inputs; authored geometry, legal evidence, area and count constraints remain protected. Piloti support/clearance remains unverified. Existing plan_site defaults are unchanged. Live :18449 accepted the new operation without a restart; focused move/operation tests passed. Agent integration/evidence: `agents/MasterPlanagent/docs/superpowers/plans/2026-10-09-ai-placement-loop.md`. No inbound A2A contract changed.

- 2026-10-09 Codex `dc561d44`: rows geometry batching, same-process mean 17.7846 → 4.7454 s (mine 5.0323/4.4584); 3 golden outputs + full WKB/metadata + Yeoksam x2/Gosan hashes identical, 1,000 differential rows exact, engine 208 passed/0 failed across 37 files incl. both runtime budgets; details in `docs/handoff/codex-rows-performance-20261009.md` §6. No push.

- 2026-10-08 P4 `b0eb964a`: `run_results/` = `common.py` (loads_tolerant + coercions) · `agents/{site,law,review}.py`
  (`TOOL`, `AGENT`, `parse`; law also `law_from_response`) · `agents/__init__.py` `PARSERS` · `parse.py` composes.
  Contract and fixture results unchanged (78 tests). A new agent's step = one module in `agents/` + its row in parse.py.
- 2026-10-08 P2 `6c746035` `modules/platform/goals.py` + `GET /api/v1/platform/capabilities`: the goal catalog (id, label,
  owner sequence, inputs, `available` = editor door takes it — health/limits/specialist_review restated from
  orchestrator/editor_runs.py — and `offer`); unopened flows (program, masterplan, mass, elevation) listed unavailable.
  P3 `bbbd7d13`: `modules/platform/routing/` package — `rules.py`, `roles/<agent>.py` (law/site/masterplan/mass/program/
  elevation: patterns + keywords from the A2A card skills), `route(text, assessment_date, role)` → Route kind skill|goal|ask
  (pattern ≥0.9 → keyword winner 0.7 → tie/none asks 0.3; picked role 0.9). `ask_law` answers all three kinds in one shape
  (`answer` for skill, `handoff` for goal, `route.choices` for ask); `AskCreate.role`. Golden set
  `tests/fixtures/routing/golden.json` (30; wrong role = failure, ask allowed; 29/30). Hand-over shape for the Orchestrator
  question door (memory §11).
- 2026-10-08 `a7689389` `modules/platform/routing.py` — the interim question router as a rule table
  (`RULES`: law_ordinance 0.95 → law_article 0.9 → law_search 0.6 default; each `Route` = agent, skill, args, confidence,
  reason; `to_dict()` rides on `/platform/ask` as `route`). Shape = what the Orchestrator's question door should return
  (memory `multi-agent-routing-research`). `ask.plan` now delegates to it.
- 2026-10-08 `b894aee4` `POST /api/v1/platform/law-analysis` — the law artifact's analysis from the Law
  Agent: `modules/platform/ask.analyze_land` gathers `law_land_analyze` (full=True, include_law=True; the `raw` key is
  the ARR-shaped analysis) and `law_parcel_limits` (caps; parsed with `run_results.law_from_response` into the run
  contract's `law` shape), one span per hop under one trace; `summary` (zones, unmatched, zone areas, restrictions,
  assessment status, missing evidence) for the conversation; `limits` null + `limits_error` when only that call fails.
  Schema `LawAnalysisCreate` strict (pnu 19 digits, building_type ≤64, floor_area_m2 > 0, ISO date). ~10 s live.
- 2026-10-08 `14778a6f` `POST /api/v1/platform/ask` — a typed question for the Law Agent. `adapters/law_agent.py`
  speaks A2A JSON-RPC with plain httpx (method `SendMessage`; text part `{"tool","args"}`; reply = completed task's status
  message text; `metadata.version` = code that answered; `message/send` is NOT the method name in a2a-sdk 1.0). The editor's
  trace record rides on `message.metadata.trace`; the hop is one `invoke_agent law` span. `modules/platform/ask.py`: `plan`
  (조례명+제N조 → law_ordinance, else law_search limit 8), `normalize` (search items / ordinance+matches, legal_evidence
  verbatim), `ask_law`. `schemas/ask.py` strict. Same-origin only; 503 unavailable / 502 refused. Env `LAW_A2A_URL`
  (registry `host_env`), default :8301. Deviation on record: editor→Law Agent directly (hub-and-spoke says via the
  Orchestrator) until the Orchestrator session adds a question door — then this adapter becomes that door's client.
- 2026-10-08 `39c4b8dd` `run_results/parse.py` reads more of each agent's answer, keyed to the agents' own code
  (SiteContextAgent `facts.py` SITE_KEYS, Lawagent ordinance receipt): site `facts[]` {key, confidence, source, as_of,
  summary} from `state_patch` (a cut answer keeps the first facts); law `ground_capacity_m2`, `far_capacity_m2`, `zones`,
  `national_*_ceiling_pct`, `articles{bcr,far,height}`, `height{status,limit_m}`, `ordinance.sources[]` (name,
  ordinance_id, edition_id, effective_date, law.go.kr url), `ordinance.limitations[]`, `evidence{floor_height_m,
  datum_measured, frontage_grade, legal_floor_section_count}`. Every old key unchanged. Fixture `limits-single-683`
  = live 산곡동 683 run whose Law answer fits the cap. Backend process must be replaced to serve it (host daemon
  restarts it in ~8 s after a kill).
- 2026-10-08 `928f9f51` `modules/platform/run_results/` parses a run's communications into a stable UI contract
  (steps, site, law, review, missing_evidence_all; tolerant of the owner's 8,000-char response_text cut) —
  `GET /platform/runs/{id}/results`, `GET /platform/projects/{id}/runs/latest?goal&pnu` (fetches <=10 newest runs
  to match pnu; the owner list carries no request). Fixtures from live runs in tests/fixtures/run_results/.
- 2026-10-08 (feat: run results) `modules/platform/run_results/parse.py` reads a run's communications into one UI shape
  (`GET /runs/{id}/results?project_id=`; `GET /projects/{id}/runs/latest?goal=&pnu=` = newest run for a parcel, at most 10
  runs fetched whole since the owner's list carries no request). Tolerant: a response cut at the Orchestrator's 8000-char
  cap is closed at its last complete value, so Law's numbers (parcel_area_m2, bcr_pct, far_pct, max_storeys, policy_id)
  survive but its `ordinance` receipt (sent last, after `policy`/`evidence`) is lost for policy parcels like 684-1 ->
  `law.ordinance: null` + `notes[]`. Fixtures = the three live 684-1 runs. TELL ORCHESTRATOR/LAW: put `ordinance`
  before `policy`/`evidence` or raise the cap; Law still ignores the project's assessment_date (finding evidence null);
  `revision_triage` task state is `failed` while its answer says `needs_evidence` (the UI prefers the answer).
- 2026-10-08 `8aadbfd1` site run door also takes `assessment_date` (real YYYY-MM-DD) and `parcels` (1..50, unique,
  parcels[0]==pnu); 45 tests. Orchestrator boundary now accepts it (their 56563ec). Known: adapter drops the owner's
  409 detail (`OwnerRejected` -> generic message); Law still reports assessment_date null although the project stores it.
- 2026-10-08 Infra review at `9bd8d015`: host:check 28/28, infra/dev 26/26, lint-imports KEPT, inventory current,
  backend 67 (status/trace/site-run/selections/doors), frontend tsc 0 + 228; agent doors 24/24 identical to the
  10-07 review fingerprint; agents repos: no launcher/catalog change (their dirty files are other sessions' docs);
  host daemon pid 11520 keeps backend (listener pid shown is the uvicorn child of the launcher pid in
  runtime/host/backend.json); runtime/trace, runtime/host, logs/host ignored; services.json holds no secrets.
- 2026-10-08 `3b38eccb` W3C trace context on runs: `core/tracing.py` (stdlib; JSONL recorder at EDITOR_TRACE_DIR >
  EDITOR_PLATFORM_DATA_DIR/trace > runtime/trace), `RunService.submit` starts/continues a trace and records one
  span `invoke_agent orchestrator` (OTel GenAI keys + run_id), adapter sends `traceparent` on every Orchestrator
  call (no rows for polling GETs), response carries `trace_id`, `GET /platform/runs/{id}/trace`. Retry = new trace.
  CONTRACT REQUEST to Orchestrator/agents: read traceparent, child spans per A2A call, forward header, echo it,
  health version+started_at (see global memory this-session-owns-the-orchestrator §5).
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
- 2026-10-09 (MasterPlan session) rows performance handed to Codex: docs/handoff/codex-rows-performance-20261009.md.
  Profile: 85 % of row_candidates is per-stall shapely box() (220k calls, 29.6 s) and the shapely decorator's
  inspect.signature (644k calls, 21.9 s). Constraint: outputs byte-identical (golden WKT, parcel hashes), then speed.
- 2026-10-08 (MasterPlan session) rows.py: `row_candidates` received the enclosed ground floor as
  `occupied_footprint` but cut the road corridor, the ramp's open part, the at-grade landing and the turn bay
  against the whole footprint, so under a piloti no row scheme ever had an entrance (고산 with the practice
  building: 0-12 surface stalls, failing generic plan). They now cut against the enclosed floor; without a
  piloti the enclosed floor IS the footprint (new test asserts identity). Verified: 역삼 geometry hashes
  unchanged, test_rows_piloti 3/3, rows/aisle/core/joint files 45 passed; the two time-budget tests
  (bounded_packing <12 s, rows_runtime <15 s) fail on HEAD too on this machine today (2.4 GB free; HEAD vs
  working copy benchmark 23-24 s vs 25-27 s, same output). Piloti clear height is still only a pending review.
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
- 2026-10-08 review fix: the terrain tile queue (features/world/lib/terrain.ts) never lets the camera-focus lookup throw
  (a destroyed viewer stopped waiting tiles); use-world-3d returns null focus for a destroyed viewer. Changed by the
  Orchestrator session (editor 92faac61).
- 2026-10-08 review of plan P1–P4 (routing/goals/parsers): the Law role table holds no single-character keyword
  ('법' sat inside 방법/법인 and tied every "배치 방법" question with MasterPlan); statutes are named whole (건축법,
  주차장법, 국토의 계획, 법률) and parking/height phrasings are Law's (주차 대수·주차 몇·높이 몇·높이 상한·최고 높이).
  Golden set 34 sentences, 34/34, wrong role 0 — add the sentence to `tests/fixtures/routing/golden.json` whenever a
  live question routes wrongly. Live on 684-1: ask kinds skill/goal/ask all answer; `law-analysis` 28 s
  (59.92/249.67/5층, policy gosan-public1-molit-2026-334); the limits run parsed Site 5/8 (2 facts readable under the
  8,000-char cap), Law caps, Revision 4 actions, note `law_response_truncated`. Still the Orchestrator's: the
  `law_parcel_limits` request it sends carries only `pnu, building_type` — no `assessment_date` — so Law's district
  finding blocks the run ("Supply an explicit valid assessment date") although the editor sent the date.
- 2026-10-08 night (user: "룰 기반이 맞아? 오케스트라 에이전트 LLM이 판단해야지 — 논문·스타 레포 코드 보고 제대로"):
  **the conversation is routed by the Orchestrator's model, not a keyword table.** `routing/judge.py` is AutoGen
  Magentic-One's progress-ledger step copied in shape (`autogen_agentchat/teams/_group_chat/_magentic_one/`): team as
  `name: description` lines, JSON ledger `is_request_satisfied / next_speaker / instruction_or_question`, unknown speaker
  retried (MAX_JSON_RETRIES) never accepted, model = the workspace's `ClaudeCodeChatCompletionClient` (OAuth, no key).
  The Orchestrator is a participant: satisfied → `Route.kind='answer'` (its reply in `instruction`); itself
  unsatisfied → `ask`; a specialist → skill/goal with the instruction it gives. `situation.py` feeds it DATA (site, goal
  catalog, which agents the Orchestrator catalog says are `available`/`unavailable`) so "뭐 할 수 있어/누가 켜져 있어"
  is answered from state, never from prose in the prompt. Order: picked role / pattern → ledger → rule table only
  when `EDITOR_ROUTING_JUDGE=rules` or the model is silent (tests pin `EDITOR_MODEL_AUTH=api_key`, so they run rules;
  the ledger path is tested with fakes). 16/16 roles (`roles/*.py`), goal catalog 15 rows. Measured: rules 54/54;
  model v1 (plain decision) 50 right · 4 asked · 0 wrong · 5.5 s; the ledger with the situation 11–28 s per turn
  (CLI start + long answers) — the Orchestrator's own door should run this ledger over its live A2A cards and own the
  latency. Live 684-1: greeting / 켜진 에이전트 answered directly; 이격 질문 → limits with an instruction to Site;
  "매스 쌓아 봐" → explains the missing brief and the agents that are off, asks.
- 2026-10-09 (activation step 1, user "하나씩"): **agents are brought up at the call, not by hand.** `infra/host/cli.mjs ensure
  <ids> --json` = start + `ensure.mjs::waitHealthy` (parallel probes until every id answers or the deadline); backend
  `modules/platform/host.py::ensure` runs it and `POST /platform/host/ensure {agents, timeout_s}` (same-origin) answers
  `{requested, up, failed[{agent,error}], waited_s}` in agent ids (site_context ↔ site-context). Research in memory
  `agent-activation-research` (Dapr virtual actors, AutoGen factory, KEDA interceptor, OTP supervisor). Live: masterplan
  11 s, program/domain_expert ~40 s; **MassAgent's `scripts/serve-a2a.sh` launches server.py with the port unexpanded
  (`--port '${MASS_A2A_PORT:-18331}'` → "invalid int value")** so the host restarts it in a loop — agents/*, Orchestrator
  session's fix; `host:stop mass` ends the loop. Next steps: 2 = conversation calls ensure before a goal whose owners are
  down ("켜고 시작"), 3 = idle stop policy in the host.
  **Correction (10-09 00:10):** the Mass port bug was the editor host, not agents/*: `processes.mjs::readEnvFile` passed
  `export MASS_A2A_PORT="${MASS_A2A_PORT:-18331}"` literally. Fixed (shell-style `${NAME}` / `${NAME:-default}` expansion,
  innermost first; `processes.test.mjs`). The daemon loads the parser once — a host code change needs `host:stop` +
  `host:start`. After that `POST /host/ensure {mass, scene}` → both up in 7.1 s.
- 2026-10-09 activation A0 (design `plans/agent-activation-design-20261009.md`, optimisation review §11): host daemon
  survives a missing executable (`spawnDetached` handles the async 'error'; the entry just fails), probes every entry
  in parallel per tick (was sequential: n × 3 s), writes `runtime/host/health.json` each tick (ensure/status trust it
  for 10 s → `ensure` on up agents = 75 ms, no node-per-probe), appends `runtime/host/events.jsonl` (start/adopt/restart/
  stop/spawn-error/gave-up/ensure), gives up after `giveUpAfter` (6) restarts (`gave_up` state; ensure fails at once),
  `restart-daemon` ends only the daemon (killOne — killTree took the services with it, seen live) and `status` says
  STALE when host code/registry is newer than the daemon's `codeStamp`. Next: A1 leases + idle stop.
- 2026-10-09 activation A1: **leases + idle stop** (design §3). Registry agents carry `idle_timeout_s` (1800, scene 900) and
  `memory_mb` 90; `ensure --lease`/`touch` write `runtime/host/leases.json`; the daemon stops ≤ 2 idle entries per tick
  (lease ended + idle_timeout, never within 10 min of a start), forgets them from wanted, logs `idle-stop`. Backend
  `POST /host/ensure {lease_s}` and `POST /host/touch`. Live: scene auto-stopped 19 min after an unleased start; touch
  extends. Pitfall: the daemon restart adopts running processes with their real start time, so an agent started before
  A1 can be idle-stopped on the very first tick — intended, but surprising the first time.
- 2026-10-09 activation A2: the conversation wakes a goal's missing owners before submitting (`lib/goals/activation.ts`,
  `useSiteRun`, `useAsk` pre-warm 300 s, "켜고 시작 (n개)"), `GET /platform/host/status` (snapshot, 5 s cache), host snapshot
  probes the whole registry (compose agents read as up). **Door contract changed by the Orchestrator session (10-09):**
  texts no longer capped at 8,000 (Site ~30 KB, Law ~31 KB), `redacted: bool` per row, new steps `site_district_plan`
  and `law_review_district_plan`, `assessment_date` forwarded to Law, health carries `worker`. Editor schemas
  (`schemas/communications.py`, frontend `parseCommunications`) now bound texts at 262,144 and accept `redacted`;
  the 8,000 assumption elsewhere is only comments/notes. Pitfall (fixed 10-09 01:05): Next dev compiles `/api/scenes/[id]` lazily (6-9 s)
  and the first submission after a reload/HMR hit the backend's 8 s scene-check timeout (503). Now
  `PlatformScenes.TIMEOUT_S = 30` and the site card warms the route when a project is chosen — first click: scene
  9 ms, POST runs 202 in 810 ms. Live: run d8af521b full conversation in the browser.
- 2026-10-09 01:15 (user: "하드코딩 아니지 라우터? 최신으로 한 거고?"): the routing judge's team roster is now the agents'
  **live A2A cards** (`routing/cards.py`: registry `card_url` → description + skill ids, 60 s cache; role docstring only
  as fallback for a down agent). What remains written in the editor: the ledger prompt itself, the role fallback lines,
  and the keyword tables (used only when the model is off). Versions: AutoGen 0.7.5 client interface (Microsoft Agent
  Framework 1.0, 2026-04, keeps the same Magentic ledger pattern), A2A 1.0 cards, LangGraph 1.2.7 supervisor = same
  shape. Observed: mass/scene idle-stopped on schedule (lease 15:37Z + 1800 s) — the activation policy works unattended.
- 2026-10-09 infra I1 (user: "인프라 제대로 되어 있냐 → 해결해 제대로"): the two gaps closed. (1) The six compose-served agents
  (law, site-context, revision, plan, requirement, design-intent = ace-*-1) are `management: external` with
  `compose: {project, service}`; the host activates them with `docker compose up -d` only, never spawns their `start`
  (kept as the a2a.ps1 mirror for the derivation test), never adopts/kills Docker's listener, never idle-stops them.
  (2) No worker entry needed: the Orchestrator door (`--enable-submissions`) runs worker.standby itself (health
  `worker: running`); the hand-started worker was stopped and run be3f7c6b executed in 14 s. Also: Neo4j (no health
  URL) is up when its port listens. Caveat seen: the machine clock jumped ~8.5 h forward on 10-09 00:xx (events/leases
  are wall-clock ISO), which expired leases early — harmless here, but a clock step can idle-stop agents at once.
