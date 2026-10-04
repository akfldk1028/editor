# Land analysis absorption dependency brief

Reviewed 2026-10-04 against `D:/Data/25_ACE/ARR/backend`. This is a source inspection and migration brief, not a claim that analyze has been absorbed or that statutory content has been independently revalidated. The architecture in `docs/architecture/2026-10-04-backend-domain-integration.md` applies: no `backend/arr` tree, and shared agents remain outside Editor.

## Smallest useful cut and full endpoint cut

The smallest useful vertical cut is the existing `POST /api/v1/land/analyze` with `input_type=raw`, explicit zones, `include_law=false`, and no geometry. It needs the core and extended calculators, overlay matching, program normalization, source snapshots, response formatting, and a local analysis/audit repository consumed by statistics. Wire these to the real endpoint in the same increment; do not merge standalone calculation files with no product consumer. Other request modes can remain explicitly delegated through the existing adapter while their providers are moved. That is partial ownership, not analyze completion.

Full analyze absorption also needs address/PNU resolution, land attributes, parcel geometry, zone-area splitting, law search, optional advisory extraction, neighboring roads/parcels, setback geometry, and optional datum elevation. Removing only `LandClient.analyze` while dropping these branches would lose existing behavior. The legacy streaming/AutoGen endpoint is a separate consumer of `_core_analysis`; it is not required to import AutoGen into the new product endpoint.

## Source call graph

`land/views.py:analyze` normalizes the program; resolves PNU/address; fetches land attributes; obtains parcel geometry; returns a warning when zones cannot be resolved; otherwise calls `_core_analysis` and records a query. `_core_analysis`:

1. Normalizes program/date again and derives the five-digit jurisdiction from PNU `sido + sigungu`.
2. For multiple recognized zones plus geometry, invokes `zone_geometry.parcel_zone_split` with `design.services.site_geometry` conversion/projection functions. Failure leaves limits unresolved and adds an error.
3. Calls `regulation_calculator.calculate_all`, `regulation_calculator_ext.calculate_extended`, and overlay resolution.
4. Optionally searches law articles, saves the analysis, builds restrictions, and reconciles `zone_info` caps with municipal calculation results.
5. With parcel geometry, fetches neighboring roads and parcels and computes setback lines, optionally including datum elevation.
6. Formats the response with `assessment.status=needs_evidence`, `permit_compliance_verified=false`, and scope `regulation_lookup_and_partial_calculation`.

## Responsibility and source-to-target map

All source paths below are relative to ARR `backend/`. Destinations are Editor paths relative to `backend/app/` and are proposed filenames, not instructions to create empty modules.

| Source | Responsibility | Destination and seam |
|---|---|---|
| `land/services/regulation_calculator.py` | Core rules plus currently mixed file loading and optional LLM calls | `modules/regulations/calculator.py`; explicit snapshot inputs/reader; advisory extraction outside numeric rules |
| Core calculator parking helpers | Legal parking count, mixed-use rounding and accessible applicability | Initially preserve as a coherent tested part of calculator; extract `modules/regulations/parking_requirements.py` when wired to calculator, avoiding confusion with geometric parking layout in `modules/parking/` |
| `land/services/regulation_calculator_ext.py` | 31 references/provisional applicability, not 31 compliance decisions | `modules/regulations/extended.py`; packaged data reader, pure classification/evidence dependencies |
| `land/services/legal_use.py` | Conservative identity classification | `modules/regulations/legal_use.py` |
| `land/services/ordinance_evidence.py` | Date/jurisdiction/source eligibility | `modules/regulations/ordinance_evidence.py` |
| `land/services/zoning_use_evidence.py` | Caller-supplied rule evaluation with unverified provenance | `modules/regulations/zoning_use_evidence.py` |
| `land/services/zoning_mapper.py` | Lookup and overlap arithmetic | Existing catalog plus planned `modules/regulations/zoning_limits.py`; coordinate with zoning slice rather than duplicate its implementation |
| `land/services/overlay_resolver.py` | Regex matching, captures and information-only recognition | `modules/regulations/overlays.py` with packaged `overlay_zones.json` |
| `land/services/program_contract.py` | Program fields, dates, finite positive area validation | `modules/land/analysis_request.py` or API request contract; preserve normalization semantics |
| `land/formatters.py` and `views._flatten_law_articles` | Pure response construction and article deduplication | `modules/land/analysis_response.py` |
| `views.analyze` and `_core_analysis` | Request-independent application flow | `modules/land/analysis.py`, composed by `api/routes_land.py`; domain modules must not import Django views |
| `land/persistence.py`, relevant `land/models.py` models | Analysis records, query logs, statistics | `modules/land/repository.py`; runtime data under `runtime/editor/land`; explicit import of preserved historical data, not ORM tree copying |
| `land/services/land_api.py` | Three Vworld NED endpoints, normalization, partial success | `adapters/vworld_land.py` or extend existing Vworld adapter; cache owned by land repository, separate from provider parsing |
| `land/services/law_enricher.py` | Law HTTP search, fallback, concurrency, optional OpenAI calls | `adapters/law_search.py` and explicit advisory extraction boundary; query selection/response normalization can remain regulations functions |
| `land/data/regulation_prompts.py` | Optional extraction templates | Regulations-owned resources consumed only by configured extraction adapter |
| `land/services/zone_geometry.py` | Vworld zone features, disk cache, geometric intersection | Split provider/cache from `modules/land/zone_geometry.py` arithmetic; reuse projection primitives without importing whole design app |
| `land/services/road_frontage.py` | Neighbor retrieval and metric frontage computation | Provider retrieval in adapter; shared-edge/width geometry in `modules/land/frontage.py` |
| `land/services/setback_geometry.py`, `envelopes/sunlight.py` | Setback lines and envelope geometry | `modules/regulations/setbacks.py` and `sunlight_envelope.py`; preserve output schema consumed by design/UI |
| `land/services/datum/{cases,calculator,elevation_api}.py` | Datum calculation and optional external/local raster provider | Geometry in land terrain/datum responsibility; HTTP/raster I/O in adapters; preserve explicit enable flag |

`land/config.py` is not portable as a unit: importing it creates six synchronous HTTP clients and registers cleanup. Compose configured clients at the Editor service boundary, keep secrets server-side, and pass booleans/settings explicitly. `LLM_EXTRACTION_ENABLED` defaults true in source; `include_law=false` does **not** by itself prevent calculator extraction attempts. Offline parity fixtures must explicitly disable extraction on both sides.

## Calculation and evidence invariants

- `calculate_all` depends on full zone rows, not the reduced catalog response. It recognizes overlay names separately when deciding unresolved zoning.
- Multi-zone caps require area allocation. Do not restore the obsolete strictest-zone shortcut described in the calculator's top-level docstring.
- Municipal source eligibility is checked on each call, including cached documents. Layer two-digit province/city then five-digit jurisdiction. Example, future, expired, incorrectly identified, or unsupported provenance snapshots cannot establish caps.
- Preserve national ceilings and municipal snapshots as distinct values. Missing ordinance edition identity leaves public BCR/FAR unresolved even where numeric snapshot caps exist.
- Parking keeps use exclusions/ambiguous umbrellas, national-reference versus municipal basis, per-use intermediate values, mixed-use first-decimal rounding, under-one-car handling, restricted-boundary uncertainty, and accessible-space applicability/ceiling rules. A numeric national floor must not become a binding municipal requirement.
- Extended output preserves `evaluated=false`, `needs_evidence`, caller-supplied source status and explicit missing inputs. Classification is not permission; provisional daylight applicability is not geometric compliance.
- LLM sunlight/adjacent-setback/designation outputs are `unverified_proposal`; they must never replace numeric rule values. Current public formatter does not expose every internal proposal field; preserve the API contract and decide any exposure separately.
- Formatter output contains ten core presentation groups despite the calculator describing eleven rules; building designation is retained internally and affects downstream geometry. Do not infer completeness from a group count.
- The legacy land-attribute cache reads only after all live requests fail, writes when zoning lookup succeeds, and currently returns cached data without adding cache-age metadata. Preserve source artifacts; explicitly record any deliberate stale-data reporting improvement.
- Address geocoding can succeed with coordinates and no PNU. The new analysis orchestrator must handle that as unresolved parcel identity rather than indexing/parsing `None` as a full PNU.

## Efficient execution sequence

1. Commit the zoning overlap module only with its active product consumer and parity tests; reuse it in the next cut.
2. Implement the raw-zone analysis cut together: packaged snapshots/readers, conservative calculator and helpers, extended references, overlays, formatter, local repository/statistics and route dispatch. Existing `/land` UI consumes the same response; expose an intentional zone-only action if it otherwise cannot reach raw mode. Freeze assessment dates in parity fixtures. Keep other modes delegated and visible in migration status.
3. Move land attribute retrieval/cache and compose existing Editor PNU/address/parcel providers. Enable PNU/address cases on the same analysis service. Avoid network I/O on the FastAPI event loop through synchronous copied functions.
4. Move zone allocation plus road/neighbor/setback geometry together for requests carrying or resolving geometry. Add datum only through its explicit flag and configured providers; no silent omission on default paths. Split deployment work for optional local DEM resources from mathematical parity.
5. Move law search/fallback and optional extraction; validate configured real providers separately from fixture parity. Preserve article deduplication and partial failures.
6. Migrate historical query/analysis rows from the preserved DB copy with IDs/counts/relationships verified, test local stats, then remove analyze/stats delegation once every supported branch passes without ARR source/server. Coordinate remaining streaming and specialist consumers separately before retiring ARR.

Do not copy all geometry/provider dependencies ahead of the endpoint branch that will consume them. If intermediate hybrid routing is used, define the exact supported request predicate; unsupported fields must not be silently ignored.

## Verification gates

Use fixed-date differential responses from the source with providers replaced by deterministic fixtures. Cover empty/unrecognized/single/multiple zones; missing and available jurisdiction sources; future/expired/example snapshots; mixed-use and same-use parking boundaries; excluded use subtypes; restricted-zone candidates; accessible threshold and ceiling; unknown and source-bound extended-use evidence; duplicate law articles; no-zone warning; partial provider failure; coordinate-only address success; geometry split failure; hole/multipolygon behavior; optional datum on/off; and audit/statistics failure policy.

Existing source tests worth preserving include `land/test_program_contract.py`, `land/test_zoning_area_contract.py`, `land/test_zoning_use_evidence.py`, `law/test_program_parking.py`, and `law/test_program_parking_scenario.py`. Test ported calculator directly and through the actual Editor endpoint. Browser fixtures validate rendering only; add an isolated real Editor HTTP test with provider fixtures. Separately verify original source and DB artifacts unchanged. Passing these checks demonstrates behavioral migration, not fresh verification of every legal statement.

## Source data SHA-256

Observed bytes on 2026-10-04; hash equality is provenance evidence, not legal currency. Paths relative to `ARR/backend/land/data/`.

| Data file | SHA-256 |
|---|---|
| `zoning_limits.json` | `3c65baaba1d8e7af8809be644fb3a0091fbf9e141acf22748668a4466c2f2584` |
| `zone_overlap_rules.json` | `089c4175f13c8698406668dcb542b3b8569cb68a2d6901d117996c6a3e9809e7` |
| `zoning_limits_extended.json` | `027210efc6ee737be988bc10855fa120e27e1768d875a993aac19accf2b84d3f` |
| `overlay_zones.json` | `7dae3e9c276d321efb748b9e973c4a2c11f5fd37bacf2a85f513cc5791cf7bb3` |
| `parking_national.json` | `659488f6cc75d0acc0f171400cfdca2af3a30f3ec7ff45f34cd37015ccfcc25d` |
| `accessible_parking_applicability.json` | `eb35c4570d6025d28a669a2e87a9adc9e9b53998f157ed4126c91f45da53578b` |
| `ordinance_overrides/11.json` | `f50410e815269111d28d13a91dbc440b89054bf7c9e3a45a7be2b82d0c77e669` |
| `ordinance_overrides/11680.json` | `969cf4886c59d16327ed907319b7bb354f38c4699489394f30fe5486abdfe31b` |
| `ordinance_overrides/41150.json` | `7cf3d9ddc84326a21f1817cf8e0fc192ed3d02d8ac335b09b48f069f50e62015` |

Read fully: core calculator, extended calculator, formatter, config, legal-use classifier, ordinance evidence, zoning-use evidence and persistence helpers. Read analysis entry/core flow and inspected imports/config/data references of provider and geometry dependencies. Full geometry implementation audits and live-provider verification remain implementation prerequisites for their respective slices.

## Implemented first vertical cut

Editor now executes existing POST /api/v1/land/analyze locally only for input_type=raw and include_law=false. Current public request model accepts input/zones/include_law only; geometry/program/provider requests are not silently routed through this narrow branch. PNU/address and raw requests with law search remain delegated. Optional advisory extraction is explicitly disabled on this branch; no hidden HTTP/LLM client is imported.

Local modules own core/extended calculations, overlays, program normalization and response formatting. Seven newly bundled data files match preserved source bytes. Mandatory reference loss/corruption fails closed with503; missing/ineligible optional municipal snapshots remain missing evidence. The national reference is not promoted to a municipal limit: raw zones without jurisdiction retain null permit-facing BCR/FAR and show national ceilings separately.

LandRepository atomically saves full request/result and audit fields with UUID/UTC timestamp in EDITOR_LAND_DATA_DIR/land.sqlite. Configure an absolute directory, normally runtime/editor/land; no data is created on app import. Storage failures retain the calculation but return storage.saved=false. Successful records survive repository reopening. This does not import original Django history. GET /api/v1/land/stats?scope=editor counts these local records with legacy_history_included=false; default statistics still query legacy records. No mixed-history totals are fabricated.

Existing /land route now offers zone-only analysis, hides parcel-only inputs in that mode, and displays saved status and correctly scoped statistics. In-flight responses are cancelled when inputs/scope change. No new frontend root or router was created.

Verification:261 backend tests and41 subtests passed (one existing Starlette/httpx deprecation warning);43 fixed-date calculator differential cases plus24 complete assembled response comparisons. Fresh wheel contains9 byte-identical JSON resources including3 municipal snapshots; isolated extracted wheel runs analysis outside the source checkout. Frontend build and2 boundary checks pass. Chrome17 passed,7 unrelated opt-in checks skipped, including actual Editor HTTP18438 with original ARR service unconfigured, local save and count increment. Independent reviewer found no blocker. Evidence: .superpowers/sdd/2026-10-04-local-analysis/{browser.json,wheel-verification.json}. Source providers and current legal accuracy were not reverified.

Next cut: Vworld land attributes and local cache, then PNU/address orchestration, zone allocation/neighbor roads/setbacks, law search/advisory provider, historical row migration. Existing operational services and source databases were not changed. Whole ARR/selected AG integration remains incomplete.
