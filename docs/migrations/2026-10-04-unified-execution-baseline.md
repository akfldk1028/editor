# Unified Editor migration execution baseline

Implementation root: `D:/Data/25_ACE/editor`. Shared owners remain in `D:/Data/25_ACE/agents`. No ARR/AG source or operational endpoint has been moved in this increment.

## Implemented and checked

- Persistent ARR and shared orchestrator are probe-only in Editor startup. ARR probes before the owner and product sessions. Source relocation status is explicitly pending.
- 21 development tests pass, including real isolated HTTP process survival on session shutdown and startup failure. Shared production processes were untouched.
- 48 migration tests pass. The coverage command checks all observed mounted ARR/AG routes against the curated matrix and detects source hash drift.
- Matrix: 249 entries: 127 ARR URL declarations including the root admin route, 24 ARR/AG feature page groups, 40 AG HTTP/WebSocket operations, 29 ARR management commands, 25 shared phase/provider roles, four AG CLI commands. A row is evidence of inventory, not implementation.
- 79 active ARR application routes have statically resolved handlers and declared HTTP methods. The admin route is a mounted group whose generated model operations require separate review. 120 mounted ARR/AG declarations are accounted for in the CLI check. WebSocket message operations and individual UI action mapping remain incomplete.
- Source map records 63 files with commit and working-tree SHA256. It is not the full transitive import/asset closure. Seven explicit shared source/config/HTTP dependencies are recorded separately.

## Original checkout regression

Restored Gitagent using `npm ci --ignore-scripts --no-audit --no-fund` in `infra/runtimes/gitagent`, then `bun run plan:build:agent-runtime`. Existing lockfile unchanged. The previous missing `dist/exports.js` blocker is resolved.

Full run: `python -m pytest backend/tests -q --tb=short` using the preserved dedicated backend environment. **1016 passed, 2 skipped, 1 failed**, 55 warnings, 691.86 seconds. The suite is not green.

Failure: `backend/tests/test_orthogonal_layout_generator.py::test_legacy_layout_preserves_literal_room_geometry_and_unbounded_subdivision`. A separate single-test run reproduced the failure. `restroom` and `it_storage` polygons exchange their literal expected positions; the other six match. Read-only tracing finds target areas `26.400000000000002` and `26.399999999999977`. `program_prior._nodes_from_profile` assigns the final room the residual area; `layout_generator.orthogonal` sorts raw target areas before the ID tie-break. This tiny numeric difference changes assignment order. No domain geometry code or expected output was changed to hide the failure. Deterministic area priority needs a separate regression fix and bounded geometry verification.

## Live observations

ARR18320 `/law/health/` reports Django reachable and law dependency ready. This does not prove all land/design operations. Default owner8791 `/editor/v1/health` returned404 and is incompatible with the Editor gateway contract. The launcher now reports this without spawning/restarting shared services. Full product degraded UI behavior remains unverified.

## Preservation

Protected artifacts: `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/ARR/`.

- `history-20261004.bundle`: verified full history; all source refs restored into `restored-history.git`.
- `metadata-20261004.json`: 296744 entries, metadata scan completed with no errors. Metadata alone is not a backup.
- `working-tree-20261004.zip` and `restored-working-tree`: archive/restore of 127815 tracked or non-ignored regular files, 10541365900 bytes. Consult `working-tree-receipt.json` and independent disk verification receipt before treating restoration as verified. Ignored files are outside this selection.
- `sqlite-online-20261004/receipt.json`: ten read-only-source SQLite online backups; all destination `PRAGMA integrity_check` results are `ok`, with per-table counts and hashes. These are individually consistent database backups, not an atomic cross-database/artifact project snapshot.
- `ignored-required-assets-receipt.json`: 210 additional ignored data/reproducibility files, 1898727354 bytes, copied and independently re-read with matching hashes. Includes law relationship embeddings, law data, elevation data/OpenTopoData sources and the frontend lockfile. These are preservation copies outside Git; no production asset paths changed. Remaining ignored files include generated Electron builds/logs, private environment/account configuration, research models and supplemental lockfiles; classification remains explicit work.

## Next required gates

Finish independent restored-file hash verification; inventory ignored required assets, active UI actions, WebSocket messages, transitive imports/configuration and all affected owner preservation. Resolve or explicitly retain the known geometry baseline failure. Then copy the verified ARR closure to `backend/arr`, run it with isolated data and ports, compare domain responses/artifacts, and add product UI functions through the existing router. No old source removal or runtime cutover is authorized by a static inventory result.
