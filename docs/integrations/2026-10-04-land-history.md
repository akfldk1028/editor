# Editor land history and cache ownership

Editor now owns every land analysis/statistics route. The obsolete ARR land HTTP adapter and its injection point are removed. Other ARR design, job and artifact dependencies remain; this does not complete product integration.

## Storage and import

SQLite schema 3 preserves existing analyses and provider caches, adding separate historical queries, results, sources and import manifests. Historical rows retain every original column and JSON string. They are not presented as complete new analyses: the old database did not store the full request, geometry or assessment. Result-less queries and unlinked results remain preserved.

The offline importer takes a consistent read-only SQLite snapshot, validates integrity, required schema, identities, JSON, finite latency and references, and imports one transaction. The stable namespace `arr-land-main` identifies this source. Repeating the same source rows does not duplicate them; changed rows conflict and roll back. Do not assign a new source ID to the same database for a routine retry. Source/destination aliases, including hard links, are rejected. Dry runs do not initialize or migrate destination storage.

```powershell
python -m backend.app.modules.land.import_records history --source <preserved-source.sqlite> --source-id arr-land-main --destination D:/Data/25_ACE/editor/runtime/editor/land
python -m backend.app.modules.land.import_records history --source <preserved-source.sqlite> --source-id arr-land-main --destination D:/Data/25_ACE/editor/runtime/editor/land --apply
python -m backend.app.modules.land.import_records cache --land-dir D:/Data/25_ACE/ARR/backend/runtime/vworld_land_use --zone-dir D:/Data/25_ACE/ARR/backend/runtime/vworld_zone_features --destination D:/Data/25_ACE/editor/runtime/editor/land --apply
```

Omit `--apply` for validation only. History and cache commands are separate transactions. Cache import validates all selected files before writing, preserves original retrieval timestamps and raw features, recomputes Editor zone cache keys from layer/bounds, and keeps equal/newer destination records. Provider zone self-intersections are preserved as in the existing intersection pipeline; no silent geometry repair occurs. Live source cache files are not a cross-file atomic snapshot.

The dev launcher now supplies `EDITOR_LAND_DATA_DIR`, defaulting to `runtime/editor/land`. Local DB files are ignored by Git. The backend receives no ARR land URL. The remaining ARR service probe stays until other domain ownership is migrated.

## Statistics and UI

`GET /api/v1/land/stats` defaults to `scope=all`. `editor`, `imported` and `all` read only the Editor database. Imported totals count original query rows, including unsuccessful/result-less requests; they do not count result rows. Average latency is computed over combined observations, not an average of averages.

The existing `/land` page offers an independent selector for all stored records, new Editor records and imported history. Changing analysis input does not change the selected statistics scope. Aborted/outdated requests cannot overwrite a later selection. Only records actually imported are claimed as historical coverage.

## Actual preservation and verification

- Original ARR database was read through a SQLite backup into `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/land-history-20261004/source-before-import.sqlite`; original database and services were not modified.
- Imported into `D:/Data/25_ACE/editor/runtime/editor/land/land.sqlite`: 466 queries, 364 results, 37 land caches and 17 zone caches. Every archived row and field equals the preserved source snapshot. Destination integrity check is `ok`.
- Repeat application inserted zero historical rows; cache repeat kept existing records. Historical statistics: 466 queries, 85 errors, average 21057.31 ms; input breakdown PNU345/address116/raw5. Canonical storage contains no browser test analysis.
- 434 targeted backend tests plus 41 subtests passed; 27 platform regressions passed. Frontend build, 2 boundaries and 8 runtime tests passed. One existing Starlette/httpx warning remains.
- Chrome mock suite: 21 passed, 15 unrelated opt-in cases skipped. Additional actual HTTP18442 browser test passed using a copy of imported storage: imported totals stayed fixed while a new analysis increased native/all totals. Isolated server stopped; ports18442/5186 are free.
- Independent reviews covered both importers, transactions, source preservation, schema migration and weighted statistics. An old test incorrectly simulated schema1 while leaving new schema3 tables; its fixture now removes those tables before testing the historical upgrade.

Evidence: `.superpowers/sdd/2026-10-04-land-history/` contains backend XML, browser reports, actual import hashes/counts, server log and cleanup record. The logical source snapshot SHA256 is `082be52e7b8138efe53f9eaf3270a6ccb4405c0964cebdb89ef03734d038efe9`.

Next gates: design/jobs/artifacts and selected AG workflows; regulation-line/parking/floor/elevation/3D UI parity; shared-agent path contracts; operational restart/cutover proving original ARR/AG roots unnecessary. This snapshot does not capture future writes to the still-running original service; final cutover must reconcile a fresh snapshot and resolve changed-row conflicts explicitly.
