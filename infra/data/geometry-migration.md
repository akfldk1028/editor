# Existing building assets: geometry-only v3 migration

This migrates existing published buildings. It does not sample DEM, add source-only buildings, publish a catalog release, or activate `releases/current.json`.

Operational storage setting (2026-10-24): the parent enabled NTFS compression on the `C:\Data\25_ACE\world-buildings` directory itself using nonrecursive `compact /C`. Newly created region folders/files inherit compression; existing assets were not recursively rewritten or deleted. A Busan probe retained the identical SHA256 while allocated storage fell from 11,365,144 logical bytes to 3,952,640 bytes after flush. This single sample is not a guaranteed national ratio. The full catalog's approximately 56.8 GB logical assets would exceed available storage plus the 20 GB reserve if duplicated uncompressed. Keep watching actual free bytes in each batch status; compression does not waive the reserve or file-hash checks.

Run **after** the current ground candidate is complete and reviewed. The launcher acquires the same byte-zero `national-buildings.lock` as the national ground jobs; an active writer causes an immediate failure before starting Bun.

Configure the existing `DataPaths` environment (`DATA_ROOT`, `NGII_DEM_ROOT`, `WORLD_BUILDINGS_OUTPUT`, `WORLD_BUILDINGS_ASSET_OUTPUT`, `SCENE_TILES_DIR`, and optional `WORLD_BUILDINGS_ARCHIVE`/`BUN_EXE`) to the intended writer catalog and assets. The archive's adjacent `manifest.json` version must match the catalog source URL.

For this workspace, the explicit PowerShell environment is:

```powershell
$env:EDITOR_ROOT = 'D:\Data\25_ACE\editor'
$env:DATA_ROOT = 'C:\Data\25_ACE'
$env:NGII_DEM_ROOT = 'D:\Data\NGII_DEM'
$env:WORLD_BUILDINGS_OUTPUT = 'C:\Data\25_ACE\world-buildings'
$env:WORLD_BUILDINGS_ASSET_OUTPUT = 'C:\Data\25_ACE\world-buildings'
$env:SCENE_TILES_DIR = 'C:\Data\25_ACE\tiles\buildings'
$env:BUN_EXE = Join-Path $env:APPDATA 'npm\node_modules\bun\bin\bun.exe'
Set-Location -LiteralPath $env:EDITOR_ROOT
```

`DATA_ROOT` alone would default the DEM directory to `C:\Data\25_ACE\dem`, which is **not** the existing writer lock location. Preserve the explicit `NGII_DEM_ROOT` above. `WORLD_BUILDINGS_ARCHIVE`, when unset, is derived from the current writer catalog's source version under `SCENE_TILES_DIR`; do not leave a stale inherited override. The launcher does not load `.env` files automatically. All paths above are local configuration, not embedded migration defaults.

Create a JSON array of at most 256 existing z14 coordinate keys, for example `["14/13976/6335"]`. Run from the editor repository:

```powershell
python infra/data/migrate_building_geometry.py --dem-root $env:NGII_DEM_ROOT --regions-file <batch.json> --limit 16 --resume
```

The default free-space reserve is 20,000,000,000 bytes, checked before each region and each file. The process never removes old assets. Keep each batch bounded; select the next batch from catalog rows that still have an older `meshRevision`. Repeating an interrupted batch with `--resume` validates completed v3 assets and continues the remaining selected regions. `--limit` limits newly migrated regions per invocation.

For each component, `reconcilePublishedGeometry` matches the exact source key and entire exterior ring. Published `z`, `h`, `s`, `pnu`, key, and outer coordinates are preserved; only source holes are restored. Missing or ambiguous source components, duplicate published components, and disagreement with already-published holes fail without replacing that region. Resolve failures explicitly instead of relaxing identity matching or dropping buildings.

Each new immutable asset folder contains z14/z15/z16 B3DM, its footprint metadata, byte-identical `ground-source.json` when present, and `geometry-migration.json`. The receipt records before/after identity hashes and the byte count/SHA256 of every output dependency. Coverage and partial-coverage lists and ground provenance remain unchanged. Bounds expand to include coarse rotated corners. Completed files are read back and verified before the writer catalog is atomically replaced. An unexpected outside catalog edit aborts publication.

`last-geometry-migration.json` reports the selected batch, migrated/skipped/remaining counts and immutable replacements. The CLI does **not** update the service release pointer. Parent orchestration must inspect the final candidate, check disk space and reconcile the nationwide remaining revision counts before separately publishing and activating it.

## Sequential rollout handoff

1. Wait for the active c748 ground bake to exit, then finish its existing-height and missing-key validation. Do not run a geometry migration against that writer catalog during validation, even if the byte lock becomes free.
2. Freeze the validated writer catalog hash and fresh revision inventory. The old inventory of 25,582 rows is a checkpoint, not a completion claim. Generate explicit coordinate selections from this validated catalog.
3. Start with `["14/13976/6335", "14/14044/6440", "14/14066/6479"]` (Gosan, Daegu, Busan). Use `--limit 3 --resume`. A region already baked as valid v3 is checked and skipped. Check identity hashes, unchanged ground source bytes, coverage and tile bounds; inspect the corrected courtyard and coarse silhouettes through the parent-controlled candidate/release workflow.
4. Partition the remaining older-revision coordinates into stable, disjoint JSON batches of 16. Run **one launcher at a time**, with `--limit 16 --resume`. Save each batch's report before the next invocation replaces `last-geometry-migration.json`. Stop on the first nonzero exit, low reserve, source identity mismatch, or catalog hash conflict. Never bypass the lock or silently skip a failed component.
5. After each batch, recount candidate rows by `meshRevision` and compare completed region component/ground identity hashes. The CLI reports footprints, not physically deduplicated buildings. Keep original folders and the previous active service release available.
6. Finish only when every targeted existing row is verified v3, unresolved/error rows are zero, and the final candidate passes parent publication validation. New national source acquisition and missing-ground coverage remain separate tasks; this migration cannot create absent building data.

The c748 bake and height gates passed. On 2026-10-24, the first live Gosan/Daegu/Busan batch migrated 3 regions / 19,644 footprint components with unchanged published identity/ground hashes. Its catalog SHA256 is `cc657ce41ad3a65b0ff37933e74fb6c9c13819d76146eb60253dcf5f2590ab0e`. The resulting writer inventory is 25,567 unique regions: 195 v3, 25,372 legacy, zero v2. This replaces the earlier pre-deduplication inventory of 25,582 rows.

`infra/data/queue_building_geometry.py` provides the durable sequential worker. With the environment above, invoke:

```powershell
python infra/data/queue_building_geometry.py --dem-root $env:NGII_DEM_ROOT --work C:\Data\25_ACE\management\geometry-v3-national
```

When launching in the background use `Start-Process -WindowStyle Hidden`, redirect stdout/stderr to files, and retain the PID. The Bun migration child uses Windows `BELOW_NORMAL_PRIORITY_CLASS` alongside `CREATE_NO_WINDOW`, so interactive foreground work takes precedence. There is only one migration child, processing regions sequentially. The work directory contains `plan.json`, `catalog-before.json`, `status.json`, and immutable `batch-000001/...` logs/reports/receipts. Status heartbeat updates every 10 seconds while a child batch runs. Re-running the same command resumes its frozen plan from the current verified v3 rows. A first unresolved error, no-progress batch, changed source/coordinate coverage, or storage reserve breach stops later batches and records the reason. A `STOP` file in the work directory requests a graceful stop between batches.

The first checkpoint `042efc85f60ba3a424c77b876855208967034d829ff119c3b4bbff589f468743` was subsequently activated by the parent and verified over HTTP. After fixing transient Windows `EPERM` rename contention in `migrate-building-geometry.ts` and freeing C: disk space above 38 GB via NTFS compression (`compact /C`) on plain-text archives and legacy `14-*` folders, the sequential national queue worker (`infra/data/queue_building_geometry.py --dem-root D:\Data\NGII_DEM --work C:\Data\25_ACE\management\geometry-v3-national`) completed all 1,570 batches (`25,567 / 25,567` regions migrated to `footprint-holes-obb-v3`, `remaining: 0`, `catalogSHA256: 168c0a4bcb03d994a67f849820125bbec514d730982f092b80a1c790841cab31`). On 2026-10-25, `infra/data/finalize_geometry_queue.py` validated all 25,567 regions (`434,831` files, `59,947,481,917` bytes) and level-20 building/terrain height alignment (`16,989 / 16,989` building datum checks with `0.0m` max error), built the sharded catalog (`catalogs/168c0a4bcb03d994a67f849820125bbec514d730982f092b80a1c790841cab31/index.json`), sealed and atomically activated release `77cc59cd91562f475fcd6f4292308b06ce3c98e7de1f69cd26d4ae20e34f4782` in `C:\Data\25_ACE\releases\current.json`, and verified HTTP 206 health on `http://127.0.0.1:3003` (`C:\Data\25_ACE\management\geometry-v3-national\finalization-status.json`).

## Optional verified finalization supervisor

After the parent activates the first checkpoint, pin that exact release ID and the fixed c748 DEM/native terrain work/verification points. Start `finalize_geometry_queue.py` separately only after review:

```powershell
python infra/data/finalize_geometry_queue.py `
  --data-root $env:DATA_ROOT --dem-root $env:NGII_DEM_ROOT --editor-root $env:EDITOR_ROOT `
  --queue-work C:\Data\25_ACE\management\geometry-v3-national `
  --terrain-work <fixed-native-terrain-work> --dem <fixed-c748-layered.vrt> `
  --points <fixed-publication-detail-points.json> --expected-release <activated-checkpoint-release-id> `
  --base-url http://127.0.0.1:3003
```

This supervisor freezes the DEM and verification-point hashes, waits for queue completion, then holds the existing national writer lock through validation and publication. It reuses `verify-terrain-archive.py` at level 20, `verify-terrain-publication.py`, `catalog_release.build`, `prepare_map_release.prepare`, and `release_store.activate`. Queue errors, changed input hashes, non-v3 rows, changed coordinate coverage/catalog hash, height failures, or a changed active checkpoint prevent activation.

`release_store.activate(expected_current=...)` compares the active release inside its existing publication lock. Both final activation and any rollback use this compare-and-swap guard. If postactivation HTTP health fails, rollback targets the pinned checkpoint only while the active pointer still equals the just-activated release. An intervening release is never overwritten. Such an outcome is recorded as `activated_health_failed`, with the rollback result, rather than as successful completion.

Monitor `finalization-status.json`, `finalization-pins.json`, and `finalization.log` in the queue work directory. No new ground writer may start until this finalization finishes or explicitly fails and is reviewed.

Tests:

```powershell
# From frontend/app/editor
bun test ./tools/migrate-building-geometry.test.ts ./tools/reconcile-building-geometry.test.ts ./tools/building-publication-safety.test.ts
# From infra/data
python -m unittest test_migrate_building_geometry.py
```
