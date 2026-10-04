# Editor parcel analysis ownership

Editor now owns POST /api/v1/land/analyze for raw, PNU and address requests when include_law=false and ENABLE_DATUM_ELEVATION is not true. The existing /land screen consumes these results. Law-enabled and datum-enabled requests still use the legacy adapter. Full ARR integration is not complete.

## Responsibilities

- adapters/vworld_land.py: independent land-use, area/category and current/prior-year price HTTP requests; adapters/vworld_geometry.py: zone and neighboring cadastral feature retrieval.
- modules/land/attributes.py: live-result authority and cached fallback policy. repository.py upgrades its SQLite schema from1 to2 atomically, preserves analysis rows, and stores land/zone cache snapshots with UTC timestamps. Original Django/file caches have not been imported.
- modules/land/{projection,zone_geometry,frontage,geometry_queries}.py: coordinate projection, area union/intersection, road/frontage computation and cached geometry query composition.
- modules/regulations/{setbacks,sunlight_envelope}.py: original default relative-height geometry algorithms and outputs. Datum=true is explicitly unsupported here and is routed to legacy by API before local computation.
- modules/land/analysis.py: resolution, land attributes, parcel boundaries, zone split, regulation calculation, neighbors, setbacks and atomic local persistence. API accepts validated geometry and program/date fields; invalid geometry or nonfinite areas are rejected.

pyproj>=3.7,<4 is now an explicit runtime dependency. The isolated verification environment used3.8.0. Operational services were not restarted or modified.

## Preserved behavior and deliberate corrections

Source files land_api.py,zone_geometry.py,road_frontage.py matched protected backup bytes. Core/regulation snapshots retain their existing evidence limitations; no current-law validation was performed. Unknown jurisdiction does not invent municipal caps. Failed multi-zone split leaves limits unresolved. Neighbor-provider failure remains distinguishable from a valid empty result; inherited road-edge heuristics remain approximations.

MultiPolygon selection is intentionally branch-specific: zone query and setback select the largest net polygon; neighbor lookup uses the first part, and existing PNU boundary lookup ranks exterior area. A new RED/GREEN regression caught and fixed overly broad query bounds rather than merging these different semantics.

Missing credentials no longer produce the original success=true stub. Provider malformed data, negative/nonfinite values and error messages containing keys/URLs are rejected/sanitized. Independent attribute requests run asynchronously. A coordinate-only address returns an unresolved-identity warning rather than parsing a missing PNU. Attribute errors are visible in the response and audit log.

Cache fallback occurs only after all attribute requests fail; a partial live result remains authoritative. Only successful zoning-bearing data is cached. Zone feature fallback preserves the source transport/HTTP/JSON-failure policy and does not mask provider ERROR/status/schema failures. Cache hits expose their timestamp and stale status (zone split uses an explicit warning). Empty/synthetic answers are not substituted. Feature cache keys use exact bounds, avoiding rounded-box collisions. Cache failures do not invalidate live results. Historical cache import remains outstanding.

The API identifies execution_owner=editor or legacy. The existing frontend selects statistics from that actual owner and shows cached-land timestamps even when success=true. Default statistics remain legacy history; scope=editor includes local saved analyses only. Storage failures explicitly show unsaved results. Old rows/artifacts remain untouched.

## Verification

- 320 focused backend tests and41 subtests passed, with one existing Starlette/httpx deprecation warning.
- Source-generated geometry fixtures cover rectangle, holes, MultiPolygon, concavity, road/neighbors, disabled sunlight and invalid geometry; area intersections deduplicate overlapping same-zone features.
- Five assembled original-response cases cover municipal roads/neighbors, Seoul municipal rules, multi-zone split, geometry-provider failure and missing zones. Numeric/geometry/evidence outputs match exactly after the original request normalization; sanitized error/warning text compares presence. Parity also passed with two hash seeds.
- Cache tests cover live versus partial/failure, explicit stale metadata, SQLite schema upgrade preserving old analyses, unavailable storage and zone fallback policy.
- Frontend build and2 module boundaries pass. Chrome20 passed,8 unrelated opt-in checks skipped. The isolated actual Editor HTTP server18439 used httpx provider fixtures, including PNU/address geometry, persistent cache outage and saved-result statistics. This is not a live Vworld verification.
- Extracted wheel runs default geometry outside the Editor source directory. No ARR source imports or server are required for these local branches.

Evidence: .superpowers/sdd/2026-10-04-parcel-analysis/{backend.xml,browser.json,wheel.log,generate_parcel_parity.py}. Disposable HTTP server18439 was stopped after verification. Existing shared processes, source checkouts and original data were preserved.

## Next cut

Move law search/fallback/article deduplication and explicitly configured advisory extraction. Preserve bounded concurrency/partial errors while replacing the source ineffective overall timeout with an actual async deadline. Then migrate datum with explicit elevation-provider provenance and failures (the original double-failure0m fallback must not claim surveyed data), historical analysis/cache import, remaining design/job/artifact ownership and selected AG workflows. UI regulation-line/3D parity and full operational cutover remain separate required gates.
