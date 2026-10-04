# Additive mass computation: exact migration closure

2026-10-04. Read-only source inventory after native job creation/storage. No optimizer implementation or execution was added by this investigation. Refer to `2026-10-04-native-design-execution-plan.md` for the durable worker and remaining full-MAAS scope.

## Source snapshot read

Files below are under `D:/Data/25_ACE/ARR`. Full `objects.py`, `utils.py`, `mass_evaluator.py`, `repair_operator.py` and `mass_renderer.py` were read, including branches that are not needed for additive. Runner lifecycle was inspected in the preceding plan investigation. SHA256 values identify the files observed, not an immutable Git revision.

| File | Lines | SHA256 |
|---|---:|---|
| `backend/design/engine/objects.py` | 806 | `ebb845253f34a79f76a997fa565743ed557dcb1e1e7fbe0131754bf956d62574` |
| `backend/design/engine/utils.py` | 157 | `fc4c5db9d8d43ef5720c20fef5c244388a823693f423f0e0ebdb578ad1eafdf1` |
| `backend/design/engine/runner.py` | 320 | `36a02624aa244b984ebbc399e887fe5fd37de2b1859174428e1be34dd884637d` |
| `backend/design/services/mass_evaluator.py` | 822 | `691869fc9c21e0deea32b743c26f3207b30dc6ef25a329845e70f67709a04b5d` |
| `backend/design/services/repair_operator.py` | 332 | `c653ed205e6924cac17d621d0c741fe633c98024db4d43d86fcfc90fda5a987f` |
| `backend/design/services/mass_renderer.py` | 289 | `b35064fe5f78707657f545171d5e3043e5abd4e6cf4abd1ce83c2a9161356f3d` |

## Complete additive path and used symbols

The consumer is one native job's prepared specification, original WGS84 Polygon and separately pinned regulation/envelope evidence. Its result is a generation stream plus candidates with the same evaluated geometry used for rendering. No Django, ARR filesystem lookup or remote agent is necessary inside this numerical closure.

| Source → proposed Editor boundary | Used symbols and imports | Explicit exclusions |
|---|---|---|
| `objects.py` → `modules/design/optimization/genome.py` | `Design`: initialization, continuous `generate_random`, BLX/DE `crossover`, continuous `mutate`, input/output access, penalty/feasibility, `get_data`. Uses `remap`, Gaussian/uniform RNG and lists. Inputs are 29 nested scalar lists, not a flat vector. Preserve IDs/generation/rank/elite/parents fields. | Categorical/Series/Sequence are rejected by current native spec validation; do not port their permutation codecs. Legacy duplicate/elites/parents helpers used only by old Job are not required by SSIEA. |
| `objects.py` → `optimization/ssiea.py` | `SSIEAJob.__init__`, `init_designs`, `step`, `_evolve_step`, `_fitness_key`, `_find_worst`, `_should_replace`, `_tournament_select`, `_migrate`, `get_pareto_front`, `get_best`. Dependencies: Design, rank, injected RNG.sample. | `Job` and `NSGA3Job` are not selected by original JobRunner. The latter is itself a rank/crowding fallback, not an actual pymoo NSGA-III implementation. No pymoo dependency is needed. |
| `utils.py` → `optimization/ranking.py` | `remap`, `rank`, `getDominantSet`, recursive `front`; math. Maximize/minimize direction, reverse rank numbering, feasible filtering at caller and tie behavior matter. | `permutation2inversion`, `inversion2permutation`, unused module random import. |
| `mass_evaluator.py` → `optimization/evaluator.py` | Additive constants/layout, `_build_mass_polygon_freeform`, `evaluate_designs`, `_compute_metrics`, `_pick_outputs`, `_METRIC_MAP`, `_build_repair_limits_from_outputs`. Uses math, Shapely Polygon/box/rotate/translate/scale/unary_union and Editor projection. Reuse floor heights from existing `job_defaults.py`. | Nine unrelated shape builders and fallback dispatch for unknown algorithms. Native execution must explicitly require additive even though creation supports other saved specs. |
| `repair_operator.py` → `optimization/repair.py` | `RegulationLimits`, `RepairReport`, `repair_footprint`, `repair_floors`, `clip_to_sunlight_envelope`, `_sunlight_height_cap_m`, `repair_design`. Uses dataclasses/math, Polygon/MultiPolygon/box, centroid scale and WGS84→UTM transform. | Unused translate import. Do not duplicate a projection transformer when Editor's existing helper has identical CRS/axis semantics. |
| `mass_renderer.py` → `optimization/renderer.py` | `design_to_geojson`; same builder, global indices, floor heights, repair limits/repair call; Shapely mapping/scale and both Editor projections. Produces footprint Feature with height, num_floors, floor_height, building_type, mass_shape, footprint_area, BCR/FAR/floor_area and optional step_floor/upper_scale/lower_height/upper_geometry. | `constraint_envelope_geojson` is a separate simplified visualization with invented defaults, not the locked land envelope. `pareto_to_feature_collection` omits repair arguments and must not become the native result path. |
| `runner.py` → native worker boundary | JobRunner event contract: started, generation, complete, error, cancelled; evaluator callable and emitted best/Pareto/scatter. | Source queue/global runner/daemon ownership is not durable storage. MultiAlgoRunner is unnecessary for additive and must remain unsupported at this phase. |

The additive geometry itself unions five independently rotated boxes centered relative to the site centroid, then rotates the union globally. A disconnected union becomes its largest polygon and sets `is_multi`. Geometry below 1 m² returns None. Gene indices 25–28 are floor count, rotation, upper scale and step fraction. Preserve Python `round` behavior for floor/step counts.

Evaluation clips to the site, repairs footprint/floors, then computes stepback floor area, BCR/FAR, height, minimum boundary distance, open-area percentage, compactness and stepback factor. Daylight score is the original open-area/perimeter/stepback proxy, not a physical daylight simulation. Landscaping is open area proxy, not a verified landscape design. Output order follows the specification exactly; current native preparation already rejects unknown metrics.

## State, defaults and determinism that must be pinned

Source `SSIEAJob.step` first evaluates all island members. Subsequent calls evaluate one new child per island, replace worst only when the fitness key improves, and migrate at configured intervals. It checks the generation stop after evaluation: a max-generation N run has the initial evaluation plus N evolution steps. Capture this exact progression in fixtures rather than assuming N total evaluator calls.

Migration creates new IDs and copies inputs/outputs/penalty/rank into destination islands, but does not append those copies to `all_designs`; IDs can therefore have gaps. Pareto uses feasible evaluated history, not only current islands. Its cache key is history length. Best uses that Pareto front, otherwise least-penalized current island members. Parents remain the source values (SSIEA crossover does not populate ancestry); do not invent genealogy.

Global `random` in the source must become a per-execution `random.Random(seed)` passed to Design and SSIEA. Preserve draw order, `sample`, `gauss` and Gaussian cache state in differential tests. If later checkpointing, serialize the RNG state and every optimizer field; saving generation count alone cannot resume the same search. Restarting a stopped attempt is initially acceptable if explicitly labeled restart.

| Omitted option in complete custom spec | Original create-job summary/default validation assumption | Actual SSIEA constructor |
|---|---|---|
| `num_islands` | 7 | 5 |
| `pop_per_island` | 30 | 15 |
| `Number of generations` | 50 | 50 |
| `migration_interval` | generated spec uses 8 | 10 |
| `migrants_count` | generated spec uses 3 | 2 |
| `tournament_size` | 8 | 8 |

Generated default specs explicitly include 120 generations, 7×30 population, migration interval 8 and migrants 3; there is no ambiguity for those. Existing native creation preserves the original complete-spec omission and API summary semantics. Before executing an existing stored job, construct an immutable **effective execution spec** with actual chosen engine defaults and report the resulting population separately. Do not mutate the saved submitted/prepared records. Validate explicit island strategy length against that effective island count; current preparation's fallback count can differ from the engine. Version and hash the execution spec so a later default change cannot alter replay.

## Existing Editor land integration points

- `modules/land/projection.py:wgs84_to_utm,utm_to_wgs84` exactly match source EPSG:4326 ↔ EPSG:32652, always_xy. Preserve longitude/latitude, metres and source area rounding; repair divides by unrounded polygon area whereas evaluator/rendering use saved rounded site_area_m2.
- `modules/land/analysis.py:analyze_land` already assembles parcel geometry, regulatory calculation, roads/neighbors, setbacks and datum. `modules/regulations/setbacks.py:compute_setback_lines` returns `sunlight_envelope` and `datum_result`; the latter explicitly marks unavailable elevation. No fetch occurs from optimization code.
- `modules/regulations/sunlight_envelope.py` owns the existing locked envelope contract. Pin the returned dictionary and its provenance, applicability and errors. Distinguish an exempt/not-applicable envelope from a failed or unavailable one. Never turn absent absolute datum into 0 m; relative geometry and absolute elevation are different evidence.
- `modules/land/repository.py` stores original analysis result JSON. Job creation currently accepts user-supplied constraints and does not pin an analysis reference; that is creation-only behavior. Execution must add an explicit evidence binding or clearly named unverified search mode. Do not call arbitrary user limits municipal clearance.
- `modules/design/native_repository.py` stores created-only immutable jobs. A worker requires separate attempt/event/result state and atomic terminal persistence; do not change `created` to successful merely because a candidate array exists. `mass_bridge.py` is the subsequent selected-mass→PLANM consumer, with exact floor geometry checks and explicit program input.

## Source defects and semantic differences to cover before enabling execution

These are read findings, not fixed code. Preserve source behavior in differential reference fixtures, but do not publish their erroneous success interpretation.

1. **Missing geometry can be feasible numerically.** `_compute_metrics` returns default numbers (floor_area/daylight/height/setback zero, BCR/FAR 100) for missing/empty/failed repair geometry. `Design.set_outputs` decides feasibility only from declared constraints. With no constraints, an empty mass can be feasible/Pareto while renderer returns None. Native result acceptance must require a valid, nonempty rendered/evaluated mass and retain a rejection reason.
2. **Repair defaults are not evidence.** RegulationLimits silently supplies BCR80, FAR1300, height50, adjacent1, road3 and north1.5. `_build_repair_limits_from_outputs` overwrites these by metric name regardless of `Requirement`; `height Greater than` becomes a cap. Execution must explicitly classify supported cap/minimum directions and supplied/derived/default provenance. Do not assert those defaults as law. Negative or zero limits currently accepted as mathematical constraints can also make repair invalid; reject unsupported repair inputs before running.
3. **Repair is not a proof of satisfaction.** Empty inward setback falls back to site; empty north/envelope clips retain the old footprint; BCR scaling stops after three iterations or tiny geometry; FAR/height floors clamp to at least one even where one floor exceeds a cap. Final independent constraint checks are necessary, not just a `repaired` action list.
4. **Envelope coverage is simplified.** Clip uses only `slanted_polygons[0].corners`, constructs an exterior-only polygon, and ignores any other footprint components/holes. Height cap is the minimum positive third coordinate across all slanted corners. Confirm corner heights are the expected relative heights; reject nonfinite values and invalid envelope states. It is not full per-floor sloped-envelope projection and cannot inherit full MAAS compliance wording.
5. **One-floor stepback differs.** Evaluator disables stepback when repaired floor count <2. Renderer does not; it can emit upper geometry/step metadata with zero upper floors. Floor area may coincide, but the geometry description does not. Add a regression and document an explicit native correction so metadata cannot imply a nonexistent upper floor.
6. **Topology affects what survives.** Largest-component extraction appears both before and after repair; evaluator resets `is_multi` after repair while renderer ignores the builder flag. Scaled upper footprint is clipped to site, not to the base footprint, so concave/holed bases can yield upper geometry outside the lower plate. Preserve source component choices as evidence and reject unsupported result topology in downstream consumers; do not flatten holes or quietly fill them.
7. **Numerical and computation boundaries.** Source zip silently ignores short evaluator output batches; source set_outputs accepts nonfinite floats; rank returns infinite crowding distances internally. Require exact vector/batch lengths and finite persisted metrics; do not JSON-serialize infinity. Rank repeatedly processes full feasible history and is not bounded just by population size: benchmark practical history/event budgets before exposing 20000 evaluations. The computation closure must not become an unbounded HTTP handler.

## Differential fixtures and implementation order

1. **RNG and ranking fixtures first.** Load original source files in an isolated test namespace with only their used imports replaced by test-local modules; no Django/config bootstrap and no writes to ARR. Freeze source hashes above. Compare generated 29×1 genes, BLX and source DE interpolation, clipped Gaussian mutation, normalized/binary penalties at/either side of limits, Maximize/Minimize and equal-objective ties, migration ID gaps, history Pareto and best. Test zero migrants, homogeneous/heterogeneous strategies, omitted effective options and a small fixed-seed multi-generation trace. Scalar-only native genes intentionally exclude unrelated Design branches.
2. **Geometry fixtures.** Synthetic WGS84 sites derived from simple UTM boxes/polygons: convex, rotated, concave, a hole and a narrow neck that splits after clipping. Fixed genomes: overlapping boxes, disconnected boxes, wholly off-site, sub-1 m², different global rotations, floors rounding at half values, no stepback, upper-scale threshold, multi-floor stepback and one-floor repaired case. Compare original output vectors and GeoJSON via normalized geometric symmetric-difference/area tolerances, retaining original rounded properties separately. State tolerances explicitly; do not compare geometry only by raw ring order.
3. **Repair fixtures.** Independent BCR scale, FAR floor cap, height cap, max(adjacent,road) setback, north strip, finite valid sunlight polygon/height cap, empty inward/empty clip, missing evidence, malformed envelope and contrary constraint direction. On supported safe inputs, source/new geometry and metrics must agree. Known unsafe source branches get explicit native rejection/difference assertions, not a false blanket parity claim.
4. **One complete computational entrypoint.** Consume saved prepared spec plus effective options/seed and pinned evidence; run bounded SSIEA with evaluator and render each candidate using exactly the same repair settings. Return candidate IDs, metrics, geometry, repair/rejection evidence and generation summaries. This is the first meaningful implementation unit; avoid unused isolated math ports without this consumer.
5. **Then durable worker integration.** Native attempt claim/cancel/event replay/terminal result commit and real HTTP creation→execution→reload tests belong to the next owned lifecycle unit. Disconnect ARR/AG roots for the actual test. Do not enable all-mode, MAAS, agent critique, parking/VLM completion or PLANM interior generation on the strength of additive parity.

No paid/network research was needed for this closure: the authoritative behavior is in the local original source. Full MAAS and external agent contracts remain outside the additive dependency set and require their own source-backed migration units.
