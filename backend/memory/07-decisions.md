# Decisions and contract changes (newest first)

- 2026-10-11/12 (MasterPlan session) Placement-stage engine measured against practice ALT1 on 고산 (same parti already:
  entrance 0.8 m, rows 0°, ramp departure 6 m off; gaps were 22 vs 30 surface, a whole-parcel B1 plate, and a 20-bay level
  on a 28-bay corridor). Four changes, all result-changing by design: (1) joint.py `piloti_ground_variants` - in the
  placement stage the engine's own building zone competes against two enclosed-ground variants (a stall row, a row + aisle,
  cut from the face with the most open ground); authored footprints are never touched; the planner's existing
  "partial piloti ... require review" note carries the Mass hand-off. (2) planner_rank.py: a plan's own compacted plate wins
  the tie with its source (same bays/aisles/ramp; the declared envelope is the search domain, not the plan). (3) rows.py:
  the 확장형 zone sits at the closed end of the demand, the aisle is re-cut to the kept bays in `emit` (full-width access
  verified, cross-aisle plans the cut would sever keep their drive, no re-cut when a ramp hangs off the aisle), and the
  final sort puts min(provided, required) before the score as parking_modules/planning_rank do - a 19-bay plan on a
  shorter aisle was out-scoring the 20. (4) rows.py `stall_exclusion` + basement_layout passes the landings: bays were
  laid on the ramp landing and dropped afterwards (the 20th bay). 고산 placement default: 22+28 / 2,500 m2 plate →
  30+20 / 1,114 m2 plate, ramp at the aisle's west end as in practice, geometry passed, same with entry_approach
  straight_6m. Golden fixtures (rows_golden.py) change on all three cases (scores up, counts equal or higher) - not a
  byte-identical refactor. Tests: 61 (rows/joint/rank/compact/modules/circulation) passed; new test_rows_demand_trim.py,
  tests added to test_joint_placement.py and test_planning_rank.py. 16-parcel corpus not re-run yet.
  (5) validation.py: with no `ground_footprint` in the request, the drawn `building_ground_footprint` feature is the
  ground occupancy (containment + drive collision checked, piloti review pended) - the agent's independent
  re-validation sends the original request and failed the 11 bays under the overhang as stall_obstructions, which made
  the engine-passed plan ineligible for the whole AI loop (E3). Test in test_rows_piloti.py. Full engine suite not
  completed on this machine (two chunks timed out under load; 65 targeted tests passed).
  Review pass (same day, /code-review high, 9 findings, 7 applied): the re-cut keeps only the drive touching the
  entrance and clamps dead_end; the closed end keeps max(aisle, turn bay); for an entrance at the high-x end the
  rows are refilled from the demand's closed end (accessible bays sit at the row start, i.e. the far end there) -
  ONLY when the basement level asks (`demand_from_entrance`): on the ground that refill moved the bays off the
  closed end where the ramp attaches and the 5 m piloti variant collapsed to 0 + 50; outward normal from the
  rectangle centre (concave masses); the face is chosen on parcel minus vehicle-blocked ground; no variants for a
  basement-only strategy; the validator accepts a drawn ground floor only for a GENERATED mass (an authored footprint
  without a ground footprint stays enclosed) and the three shared checks run once; the generated ground footprint is
  relabelled, not "authored". Not applied: the compact tie-break being global (a tie between different sources is
  arbitrary either way). 고산 default and straight_6m both 30 + 20 / 1,114 m2 after the pass; 29 + 37 tests.
- 2026-10-10 (MasterPlan session, circulation integration E) planner.py: `accept_ramp` used `Point` without importing it,
  so every AI proposal carrying `entry_approach` died with NameError (A's 6 tests never reach that branch; pyflakes now
  clean across the package). Finding for A: `circulation_network.plan_entry_approach`/`connect_landing_to_aisle` are
  not called anywhere - `entry_approach` only filters ramp landings near frontage corners, it generates no straight
  approach or fork; only `prune_useless_aisle_branches` is wired (parking_modules.py:173). A/B/modules/moves: 49 passed.
- 2026-10-09 (Claude) Nationwide ordinance discovery, `modules/law/ordinances/`: `jurisdiction.py` (registry address by PNU
  from Vworld `addr` → 시·도 + 시·군·자치구 levels, a 일반구 only noted; each level cross-checked with the PNU code's
  `ordinance_overrides/<code>.json` snapshot, a conflict fails the whole lookup closed), `search.py` (law.go.kr lawSearch
  target=ordin, every page walked, nw=1 현행 / nw=2 연혁, `complete` truthful, OC stripped, 10-min cache), `service.py`
  (pass 1 current set per level × topic — topics = cited ordinance names minus government words + the statutory
  delegations 도시계획·건축·주차장; pass 2 exact-name history only for an edition starting after the date; pass 3 topic
  history only for a past date → `historical` apart with in_force unknown; 지자체기관명 ≠ level issuer → `excluded`
  jurisdiction_mismatch; generic '건축조례' attaches to the one ordinance it can mean, innermost first), `body.py`
  (lawService MST, accepted only as the same name/edition/in force: all 조문 with headings, 별표 title+kind+file link,
  부칙). Doors in the conversation router (same-origin): `POST /platform/ordinances` {pnu, assessment_date, refs[], topics[]}
  → {jurisdiction, topics, search{queries,complete,errors}, ordinances[], historical[], excluded[], coverage_complete:false};
  `POST /platform/ordinances/body` {name, edition_id, assessment_date}. Env `LAW_OC` in `.superpowers/sdd/editor-law.env`
  (law.go.kr user id, same as fetch_ordinance_caps default). Fix: `ordinance_discovery.agency` now reads 지자체기관명 (was
  always null) — agent door `/law/agent/ordinance-candidates` response otherwise unchanged. Live: 고산동 961-3 1.3 s /
  35 ordinances (8 searches), 역삼동 823-26 1.5 s / 29, 2024-06-01 past date 2.8 s / 38 searches, body 0.3 s (92 조문·
  17 별표). Tests `test_ordinance_discovery_service.py` (21) + `test_ordinance_body.py` (3); inventory regenerated.
  Review fixes (second commit, same day): body cache keeps only records with 자치법규기본정보 (an error body was pinned
  for the TTL); edition ties compare the serial numerically; the snapshot's issuer spelling widens the match
  (`snapshot_issuer`, `issuers_of`) instead of replacing the derived issuer; a level with no current record of its own
  is noted from the data (제주시 같은 행정시); "past date" uses the server's local day; frontend: 60 s timeout + 다시 조회,
  heading count only after verification, excluded list says how many are not shown, history-only ordinance gets a
  notice in the reader; unused `OrdinancePanel.tsx` removed.
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
- 2026-10-09 host: external (compose) entries now fall under the same failure/backoff/give-up policy as managed ones
  (an asked-for compose entry counts as launched+alive until it answers; `gave_up` after `giveUpAfter`), and a down
  compose entry is not launched at all while `docker info` fails — snapshot state `docker_down`, one `[docker-down]`
  /`[docker-up]` event per change, the engine asked again every `dockerRecheckMs` (60 s); `ensure` fails such ids at
  once ("Docker engine is not running"). Reported cause: with `locate()` always alive:false, `compose up -d` re-ran
  every 10 s tick for 4 services while Docker Desktop was off (console windows flashing). Host tests 41. Separate,
  still open: the `editor` entry's `bun run dev --filter editor` spawn fails ENOENT under the daemon (Node cannot
  run the `bun` shim without a shell) — closed the same day: `resolveCommand` asks `where.exe` for any bare command
  on Windows and runs a .cmd/.bat hit through a shell (bun, bunx added to the shim list as the fallback); the
  `editor` entry now starts through turbo with `--webpack --hostname 127.0.0.1 --port {port}` (Turbopack cannot
  resolve the dwg workspace's ./x.js imports; runtime.mjs carries the same args so registry test (f) holds), and the
  local env file's `EDITOR_PUBLIC_URL`/`EDITOR_SCENE_URL` name 3002 so the host-run editor passes the same-origin
  doors. Live: `host:start editor` -> pid 25900 on 3002, /dwg 200, ordinances + body doors 200 via 3002, host +
  dev tests 68. The manual 3003 Next instance is retired.
- 2026-10-10 host (review "확인해"): the host-run editor's `logs/host/editor.{log,err}` stayed empty while the server
  ran. Measured cause: a .cmd shim run through cmd.exe under `detached` (DETACHED_PROCESS, no console) loses every
  child's output — each child console app gets a fresh console whose handles replace the inherited log files
  (`cmd /c bun --version` detached -> 0 bytes; bun.exe spawned directly -> fine; non-detached would land in libuv's
  kill-on-close job and die with the daemon). Fix: `shimTarget` reads an npm-made shim and the host spawns the
  program it names (node + the last .js it references, or the .exe — bun installed through npm) with no shell;
  other .cmd/.bat files still go through one (output lost, documented). Processes tests 4 (shim parse + live
  `npm --version` landing in a log). Also seen: `docker compose up -d` launched the host's way opens no window
  detectable at 300 ms polling (Docker off), and no host-run service owns a window; the 10 s compose relaunch is
  gone (daemon log: one `[docker-down]`, zero compose starts). Unexplained: at 08:01Z backend+orchestrator (python)
  and at ~08:13Z the daemon, editor, dwg and everything node died together, image-wise, while the machine carried
  286 node.exe / 282 cmd.exe (8 copies of every MCP server) — looks like a manual cull, not the host (its detached
  children sit in no job object, measured with IsProcessInJob). Restarted with `host:start`; host + dev tests 70.
- 2026-10-10 host watchdog (user: "근본적인거 해결한거임?" → research → "나머지 해결하고"): nobody kept the daemon alive, so
  `cli.mjs revive` (a daemon only when none runs; the wanted set untouched — `start` would re-add the default set
  and resurrect stopped services) plus a Task Scheduler task `ace-host` (`bun run host:install`, infra/host/task.ps1:
  logon + every 5 min, current user, no admin; S4U and schtasks are denied here). Measured: an interactive task that
  starts node.exe directly opens a Windows Terminal window every tick, hence wscript hidden.vbs in front. Live test:
  daemon killed, task fired, new daemon adopted the running services in 3 s, no window. Same day the Claude Code MCP
  set was cut (user scope 28 → 8, claude-flow trio un-approved) because 7 sessions × ~50 server processes = 293 node /
  10 GB; the editor project's own servers (ACE, pascal) now sit at "pending approval", which is fine — both unused.
- 2026-10-11 address → map (user: "주소 치면 지도 찾아줄 수 있는 거 아님?" → "구현해"): a message that is one address or a
  PNU is claimed by the Site role's deterministic pattern (`routing/roles/site.py`, no place names listed) and answered
  by `ask.locate_site` through the editor's own address door (Vworld geocoding, the map search's) — `answer.kind='site'`
  {query, pnu, address, coordinates, error}, no agent, no span. The conversation (`useAsk(open)`) posts the Site Agent
  line and opens `site-map` with `pnu|address` + `pick=1`; the map locates, picks and saves the parcel (the card's 선택
  pressed for the user) and takes a new site while mounted (the shell re-opens it with new params). Live: 산곡동 684-1
  → PNU + point; 테헤란로 152 → point only (the map reverse-geocodes); bogus → error line. Commit 08b9433f, routing
  tests 22, feed-line tests 28. Caveat: the other session's uncommitted conversation rewiring sends typed messages to
  the Orchestrator's door (`routers/conversation.py`), not `/ask`; that path has to run the same `site_locate` claim
  (or the Orchestrator must) for a typed address to reach the map there.
- 2026-10-12 address → map through the conversation door (user: "ㅇㅇ 해결해"): `POST /projects/{id}/conversation` runs
  the Site role's deterministic claim (`roles/site.locate`, whole message only) before anything else; a hit is
  answered by `ask.locate_site` as 200 `{located}` — no activation, never relayed, so the owner's conversation does
  not record the address. (The door answers without the owner, but the frontend controller only dispatches while the
  conversation's GET succeeds, so with the owner down a typed address waits as 전송 대기 like any message.) A sentence that merely contains an address
  still goes to the owner (202 snapshot). Frontend: `postConversation` returns snapshot | `{located}`; the controller
  drops the pending message and calls `onLocated` (set by `useConversation(…, onLocated)`); `AgentConversation` posts
  the user bubble + Site Agent line to the feed and opens `site-map` with `pnu|address` + `pick=1` (same path as
  `useAsk`). `siteLocatedLine` now takes the site body, not the whole AskAnswer. Live: 산곡동 684-1 → 200 located
  (PNU + point); 없는 주소 → error body; 문장 → 202 working. Tests: conversation 46 (+2), frontend 256.
- 2026-10-12 editor back on port 3003 (user: "네이버가 원래 됐었는데 왜 안 되냐" → "3003으로 하면 되잖아"): the Naver
  Maps app `editor` has Web 서비스 URL 127.0.0.1:3003 · localhost:3003 · 127.0.0.1:3005 (05-decisions 10-07), and the
  10-08 host registry (852dcffe) put the editor on the repo default 3002 and retired the manual 3003 instance without
  checking that list — so Naver's auth answered 503 for every 3002 page and the map showed "인증 실패" tiles (the
  mount-time fallback does not catch it: the auth callback lands after `init`). Proof: JSONP probes of
  oapi.map.naver.com/v3/auth from the page succeed for the three registered URLs and fail for 3002. Changed: registry
  editor port 3003, `.env.defaults`/`.env.example` PORT, `package.json` kill script, pascal_mcp default editor URL,
  infra runtime tests, and the backend's env file (`.superpowers/sdd/editor-law.env`, git-ignored) EDITOR_PUBLIC_URL /
  EDITOR_SCENE_URL → 3003 so the same-origin doors accept the browser. `?engine=openlayers` (VWorld through the tile
  proxy, one tile at a time) is a debugging flag only — the user does not want VWorld. Memory 05-decisions: the Naver
  key's registered URLs are the port's source of truth; a port change needs the NCP console or a key with port-less
  `http://localhost` / `http://127.0.0.1` (Maps troubleshoot guide says register the host without a port).
- 2026-10-12 a sentence that names a site moves the map too, by the model's judgment (user: "산곡동 684-1에 어린이집을
  지으려고 해요 이렇게 해도 지도로 가야 하는 거 아냐?", then "llm이 자동으로 판단해야지 … rules 기반은 옛날 방식"):
  `routing/site_mention.site_named` asks the local Claude login (JSON schema `SiteMention`: names_site, address as
  written) whether the message names an address/PNU; `roles/site.find` (the same shapes, searched) only when the
  model is off or fails. The conversation door locates it (`ask.locate_site`), relays the message to the owner with
  `context.pnu/address` set to the parcel, and returns the owner's 202 snapshot plus `located`; the frontend accepts
  the snapshot and fires `onLocated(located, null)` (no bubble — the owner has the message) so the map opens and
  selects the parcel. Not geocodable → untouched relay. Measured: judge 3.5–4.7 s per message (CLI spawn), catches
  "테헤란로152" without a space, says no for "의정부 쪽에". Live in Chrome: sentence → Requirement Agent working +
  map on 684-1 selected + Site Agent line. Also the Requirement Agent's seven `requirements.*` artifacts are one card
  (`lib/agents/requirement/lib/sheet.ts`: fields in the user's words, n/7 채워짐, "아직 없음" for empty ones,
  structured-brief keys translated) — user: "대화하면서 채워나가야지", "chat gpt claude 처럼 ui ux 가 좋아야지".
  Tests: site_mention 3, conversation 50, frontend 72 (sheet 2, artifacts 4).
- 2026-10-12 Law defect found live (user: "59.92%도 맞아? 60%가 아니고?", "법은 틀리면 안 되는데"): for 684-1 Law weights
  `zone_areas_m2 {제2종일반주거지역: 2499.69, 자연녹지지역: 4.85}` (sum 2,504.54 > parcel 2,499.69 — the green 4.85 ㎡ is
  a zoning/cadastral layer overlap, not a split; 10-07 measured 1.2–1.8 m offset) under 국토계획법 84조① and reports
  59.92 / 249.67 with "national ceiling 59.9225 / 249.7094". Legally 84조① weighting needs a real split; the 획지
  공공1 has the district plan's 60 / 250 → the right caps are 60% / 250%. The editor does not recompute (user 10-08:
  numbers come from the agent); the fix is Law's: clip zone areas to the parcel, drop a zone below ~0.5% when
  another covers the parcel, let a district-plan 획지 cap override zone weighting, and stop calling 과밀억제권역 ·
  공공주택지구 · 지구단위계획구역 · 가축사육제한구역 · 공공청사 "용도지역" (they are 지구·구역·용지). Editor side today:
  the law summary line drops the policy id and tool names ("건폐율 59.92% · 용적률 249.67% · 최고 5층 · 제한 12건",
  확인 필요 on its own line) and `unresolved_zoning:` reads "용도 구분 미확인". Memory: law-zone-sliver-weighting-defect.
- 2026-10-12 zone split fixed in the editor (plan `agile-doodling-emerson`, user: "모든 대지가 잘되게, 모듈화, 메모리"; the
  Law Agent never looked at the land — its `law_parcel_limits` calls the editor's ARR land pipeline, so the defect
  was ours): one pure module `land/reference/services/zone_split.py` (`split_parcel`: per-zone union → exclusive
  partition largest-first, overlaps between zones go to the zone covering more of the parcel → a remaining part
  under 1 % of the parcel, narrower than 1 m and no larger than the 시행령 94조 small part (330 ㎡, read from the
  rules JSON) is boundary tolerance folded into the largest zone; uncovered ground reported, never redistributed;
  every exclusion disclosed in Korean) used by both `zone_geometry` copies (`zone_split(...)`, `zone_areas` =
  `.areas`, `parcel_zone_split` → ZoneSplit). `massv2/legal.load_legal_site` drops a 용도지역 the split left no
  ground to (`exclusive_zone_names`), caches `{pnu}.zoning.json` with `split_version` (old caches ignored and
  rewritten), carries `LegalSite.zone_split`; `/law/agent/parcel-limits` returns `zone_split`; land analysis puts
  it in `zone_info.zone_split` and appends the notes to `restrictions`; `run_results` law parser and the
  conversation's law summary line show the note. Thresholds are module constants with their basis (the rules JSON
  is sha-pinned by tests). Before/after over the 11 cached parcels (cached LT_C_UQ111 features): 684-1 59.9225 /
  249.7094 (84조① on a 4.85 ㎡, 0.089 m strip) → 60 / 250 single zone; 684-3 79.94 / 1298.7 → 80 / 1300 (2.31 ㎡,
  0.051 m); Seoul 1168010600105090002 and 1168010100106770000 caps unchanged, sums now equal the parcel (0.22 ㎡
  and 0.07+0.04 ㎡ folded); the other 7 identical; Σareas + uncovered − parcel = 0 everywhere. Live after restart:
  parcel-limits 684-1 → bcr 60, far 250, zones [제2종일반주거지역], zone_split.excluded_slivers = 자연녹지지역
  0.089 m, both caches rewritten. Tests: zone_split 11 (synthetic boxes: overlap sliver, genuine split, mutual
  overlap, uncovered gap, thin strip, green minor part + 84조①/③ branches, >330 ㎡ strip kept, zero-area pieces,
  tiny parcel, name filter, JSON, both copies agree through the projection), cache 1, parity fixture unchanged;
  backend subset 120. Left as debt: `massv2/parcel_policy._POLICIES` hard-codes 684-1's district caps by PNU; the
  zone facts (official list + measured split + district 획지 caps) belong to the Site Agent and should move there
  with this module.
- 2026-10-12 the rest of 684-1's law summary reviewed against the statutes (user: "나머지도 검토해봐" → "진행해"), using
  the Law Agent's own `law_ordinance` for the 의정부시 건축 조례 text. Right as found: 조경 (조례 제29조 verbatim: 200 ㎡
  이상 대지, 15/10/5 %), 인접대지 0.5 m (민법 242조), 가각전제 (시행령 31조), 과밀억제권역·공공주택지구·지구단위계획구역·
  가축사육제한구역, 도로사선 삭제, 일조 수치 (10 m 이하 1.5 m · 초과 H/2, 2023.9 개정). Fixed (editor): (1) `공공청사`
  was "unresolved zoning" and withheld the ordinance caps ("상한 미확정" beside 60/250 tiles) → new
  `land/reference/services/designations.py` classifies a name by suffix (…지역 = 용도지역 and blocks when unknown;
  …지구·구역·권역·지대·구간 = overlay; anything else = 용지·시설, reported as `unlisted_designation:` and never
  blocking); both calculators use it; 684-1 now `available_snapshot` 60/250. (2) 일조 was asserted "applies": 시행령
  86조① 단서 lifts it inside 지구단위계획구역·경관지구·중점경관관리구역·특별가로구역·건축협정구역 when the parcel fronts
  a road ≥ 20 m → the restriction line and the review item say so and the item is `conditional` (road width is a
  Site fact). (3) 대지 분할 제한 said "최소 60 ㎡" (before the zone fix it said 200 ㎡, the 녹지 value): 건축법 57조
  makes the ordinance's figure the rule within the 시행령 80조 floor → the line now says "시행령 하한 60 ㎡ … 조례로 정함
  — 조례 면적 확인 필요". (4) 접도 "2,000 ㎡ 초과 6 m 도로" is the 시행령 28조② default; 의정부 건축 조례 31조 sets 3,000 ㎡
  → rule text says the ordinance may set the size and the review item is `conditional`. (5) 최고 층수 5층 was annotated
  with the height articles; it is the district plan's 획지 decision (parcel policy) → the tile's note says 지구단위계획
  획지 결정 + source. Not verified: the 5-storey figure itself (시행지침 PDF not opened), the 의정부 조례 article for
  대지 분할 면적 (not in 제30~36조). Tests: designations 4, land review/local analysis/calculator safety/ask 77,
  frontend 72.
- 2026-10-12 the ordinance is read by the model, one generic path (user: "뭐 빨리해 제대로", "법규 MCP로 다 찾아지는 거
  아님?", "하드코딩 아니지 제발 — llm이 자연스럽게 뱉게 해야지, 그렇게 따지면 모든 법규 다 코드 짜야 하는데"): a first
  version with an extractor per article (분할·접도) was thrown away before commit. `land/reference/services/
  ordinance_reading.py`: the jurisdiction's 「…시 건축 조례」 is discovered and fetched as the Law Agent's
  `law_ordinance` does (`modules/law/ordinances` — law.go.kr official text, the edition in force on the date), the
  local model reads the WHOLE text against QUESTIONS (data: key → what to find, unit, breakdown kind; 6 lines today:
  분할 면적·접도 규모·조경·대지 안의 공지·공개공지·일조), and answers each with figure(s), the article and a verbatim
  quote; code only verifies the quote is in the text and the article exists (`verify_quotes`), drops the rest,
  caches per jurisdiction edition for a day, and lands every item on the extended rule of the same key
  (`apply_to_extended`: `ordinance` block + the two figures the restriction lines print — 분할 by the parcel's 시행령
  80조 zone category, 접도 size). No rules fallback: model off → defaults stay flagged "조례 확인". Live 684-1
  (의정부시 건축 조례 2163451, 시행 2026-08-19, 11 s): 분할 주거 60·상업 150·공업 150·녹지 200·그 밖 60 (제41조), 접도
  3,000 ㎡ (제31조), 조경 15/10/5 % (제29조), 공개공지 5/6/7 % (제44조), 일조 1.5 m·H/2 (제43조), 대지 안의 공지 skipped by
  the model itself (제45조 cites 별표 3, no figure in the body), dropped 0. Restriction lines now read "대지 분할 제한:
  최소 60 ㎡ (의정부시 건축 조례 제41조, 주거지역)". CORRECTION (same day, independent review): 시행령 28조②'s 2,000 ㎡
  (공장 3,000 ㎡) rule is statute; what the ordinance sets is the size of 축사·작물재배사 and similar buildings that are
  EXEMPT from the 6 m road (의정부 제31조: under 3,000 ㎡) — my first reading made 3,000 the general threshold, which
  would have told a 2,500 ㎡ building it needs no 6 m road. The question, the field (`exempt_similar_buildings_below_m2`)
  and the lines now say that. Other review fixes: a split that measured nothing (or left ground uncovered) removes no
  zone; the governing zone for the 분할 category is the catalog zone with the most ground; quotes must sit inside the
  article they cite; `kind()` ignores a trailing "(7층이하)"; only 국토계획법 36조 families count as 용도지역 (역사문화환경
  보존지역 is a designation, not a zone); the 정북 exemption names 86조①1 (road ≥ 20 m, 경관지구 by suffix) and ①2
  (건축협정구역) separately; tolerance share 1 % → 5 % (a 0.09 m strip is 1.4 % of a 200 ㎡ parcel); `folded_into` names
  the zone that holds the ground; the conversation door asks the model only when the message has a digit and is not
  a confirmation; the reading cache is per assessment date; legal.py splits only when two catalog zones are listed.
- 2026-10-12 (evening) the six editor leftovers (user: "빨리 해결하셈"): (1) the law artifact's 검토 조항 tab ends with
  `OrdinanceReadings` — every ordinance the model read (name, edition, 시행일, verified items with figure, breakdown,
  article and quote, dropped count) and the zone-split disclosure; (2) `ordinance_reading` reads three kinds side
  by side (`ORDINANCE_KINDS`: 건축·도시계획·주차장 by name pattern + law topic; `QUESTIONS_BY_KIND` for 도시계획
  (용도지역별 건폐율·용적률, 건축 가능 건축물 별표) and 주차장 (설치기준, 설치제한지역); `read_all_kinds` gathers them;
  the analysis carries `ordinance_reading[kind]`; only the 건축 reading feeds the rule table); (3) the split's notes
  are no longer appended to `restrictions` — they live in `zone_info.zone_split.notes` and the UI shows them, so
  "제한 N건" counts restrictions only; (4) 시행령 86조①3: `zone_split.north_neighbour_zone` samples the zone layer
  3 m across every north-facing boundary segment (outward normal within 45° of north, longest run wins) and the
  일조 note says "정북방향 인접 대지가 X(전용·일반주거지역 아님)이라 적용 제외(§86①3) — 레이어로 읽은 값"; SPLIT_VERSION v2;
  (5) the site card: `describe_site` runs the same split for a parcel listed under two zones and drops a boundary
  hair from the card's zone list, with the note under the warnings (`zone_notes`), so card and review agree;
  (6) other owners' artifacts: field names in the user's words (`FIELD_LABELS`), empty fields as "아직 없음", `{value}`
  wrappers unwrapped, titles by id family (프로그램·설계 의도·요구사항). Tests: backend 118, frontend 99.
  Also verified 5층: 의정부고산 지구단위계획 시행지침 제2편 제23조(공공청사용지, p.56) — 공공1 건폐율 60 % 이하·용적률
  250 % 이하·최고층수 5층 이하 (image `agents/MassAgent/docs/reports/legal-sources/gosan-9-guidelines-public-office.png`).
  Tests: ordinance_reading 4. Next: the same reading for 도시계획 조례·주차장 조례 (ORDINANCE_KINDS + QUESTIONS lines), the
  review panel showing the `ordinance` block per item, and the Law Agent reading these items instead of the editor.
