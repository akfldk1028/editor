# Unified Editor migration execution baseline

Implementation root: `D:/Data/25_ACE/editor`. Shared owners remain in `D:/Data/25_ACE/agents`. No ARR/AG source or operational endpoint has been moved in this increment.

## Implemented and checked

- Persistent ARR and shared orchestrator are probe-only in Editor startup. ARR probes before the owner and product sessions. Source relocation status is explicitly pending.
- 21 development tests pass, including real isolated HTTP process survival on session shutdown and startup failure. Shared production processes were untouched.
- 52 migration tests pass, including the new AST-only import extractor. Review-driven missing-app and builtin-fromlist regressions failed first and now pass. The coverage command checks all observed mounted ARR/AG routes against the curated matrix and detects source hash drift. Inventory increment: `3b27f173`.
- Matrix: 303 entries: 127 ARR URL declarations including the root admin route, 24 ARR/AG feature page groups, 40 AG HTTP/WebSocket operations, 29 ARR management commands, 25 shared phase/provider roles, four AG CLI commands and 54 curated ARR UI actions. A row is evidence of inventory, not implementation.
- 79 active ARR application routes have statically resolved handlers and declared HTTP methods. The admin route is a mounted group whose generated model operations require separate review. 120 mounted ARR/AG declarations are accounted for in the CLI check. WebSocket message operations and individual UI action mapping remain incomplete.
- Source map records 63 files with commit and working-tree SHA256. It is not the full transitive import/asset closure. Eleven explicit shared source/config/HTTP/launcher/workspace dependencies are recorded separately.
- `arr-ui-action-inventory.json` adds 54 curated actions, 40 API-client functions and 213 transport/event call sites. Independently checked 381 file/line references and supplied source snippets. Runtime parity remains unverified; desktop-only calls, proxy routing and history replay require explicit adaptation.
- `arr-import-closure.json` records 604 conservative local source candidates, including package initializers and lazy aliases. Independently re-read all source bytes and matched their hashes; reproduced the exact source/hash set with `arr_import_inventory.py`, with no missing seeds or parse errors. No source copied. HTTP/WSGI, ASGI and management scopes overlap. Disabled HTTP apps can still be imported by ASGI; Neo4j helpers are also HTTP-reachable, and seven tools under `tmp_mass_check` are management-command source dependencies. Two optional local modules (`graph_db.services.indexes` and `.stats`) are absent. Dynamic imports/assets and isolated execution still gate source relocation.

## Original checkout regression

Restored Gitagent using `npm ci --ignore-scripts --no-audit --no-fund` in `infra/runtimes/gitagent`, then `bun run plan:build:agent-runtime`. Existing lockfile unchanged. The previous missing `dist/exports.js` blocker is resolved.

Restored the original checkout's lightweight frontend using the same frozen-install command in `frontend/app/planm` (30 packages). `npm run build` passes TypeScript and Vite production build. Headless Chrome from this checkout passes four mocked API regression cases (partial land evidence, retry identity, routing and unavailable/recovery). A separate two-test live run against existing isolated backend18434 passes ARR PNU analysis and owner catalog25. The first browser run skipped four live fixtures; only land/catalog were subsequently run live. Live project creation and worker execution were not reverified in this increment. Playwright was provided through the preserved external tool installation; no new root lockfile or production service restart.

Initial run: `python -m pytest backend/tests -q --tb=short` using the preserved dedicated backend environment. **1016 passed, 2 skipped, 1 failed**, 55 warnings, 691.86 seconds. This initial run was not green.

Failure: `backend/tests/test_orthogonal_layout_generator.py::test_legacy_layout_preserves_literal_room_geometry_and_unbounded_subdivision`. A separate single-test run reproduced the failure. `restroom` and `it_storage` polygons exchange their literal expected positions; the other six match. Read-only tracing finds target areas `26.400000000000002` and `26.399999999999977`. `program_prior._nodes_from_profile` assigned the final room the residual area; `layout_generator.orthogonal` sorts raw target areas before the ID tie-break. This tiny numeric difference changes assignment order.

The correction assigns the conservation residual to the largest space, keeping equal small-room ratios tied. Existing geometry implementation and literal expected output remain unchanged. Three regression inputs cover integer, fractional and tiny positive floor areas; the program/orthogonal suites passed 61 tests. Independent review found no concrete issue in this two-file change. The interrupted full rerun left neither a live test process nor a JUnit result; it is not a pass. The replacement full run completed with **1020 passed, 2 skipped, 55 warnings in 629.81 seconds**, exit0. JUnit: `.superpowers/sdd/2026-10-04-unified-editor-arr-ag/backend-after.xml`. Warnings concern existing TestClient and reserved-path deprecations; no dependency upgrade was performed.

## Live observations

Baseline correction commit: `cdd79e69`. The two skipped tests are POSIX publication-lock hardlink/symlink cases on Windows; they are not counted as verified here.

ARR18320 `/law/health/` reports Django reachable and law dependency ready. This does not prove all land/design operations. Default owner8791 `/editor/v1/health` returned404 and is incompatible with the Editor gateway contract. The launcher now reports this without spawning/restarting shared services. Full product degraded UI behavior remains unverified.

## Preservation

Protected artifacts: `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/ARR/`.

- `history-20261004.bundle`: verified full history; all source refs restored into `restored-history.git`.
- `metadata-20261004.json`: 296744 entries, metadata scan completed with no errors. Metadata alone is not a backup.
- `working-tree-20261004.zip` and `restored-working-tree`: archive/restore of 127815 tracked or non-ignored regular files, 10541365900 bytes. Independent disk re-read matched every SHA256 in638.48seconds; `restored-disk-verification.json` reports zero missing files or uncopied links. Ignored files are outside this selection.
- `sqlite-online-20261004/receipt.json`: ten read-only-source SQLite online backups; all destination `PRAGMA integrity_check` results are `ok`, with per-table counts and hashes. These are individually consistent database backups, not an atomic cross-database/artifact project snapshot.
- `ignored-required-assets-receipt.json`: 210 additional ignored data/reproducibility files, 1898727354 bytes, copied and independently re-read with matching hashes. Includes law relationship embeddings, law data, elevation data/OpenTopoData sources and the frontend lockfile. These are preservation copies outside Git; no production asset paths changed. Remaining ignored files include generated Electron builds/logs, private environment/account configuration, research models and supplemental lockfiles; classification remains explicit work.
- `ignored-file-classification.json`: 1804 ignored non-environment files classified by inspected paths: runtime1046, research9, required_asset103, source110, generated536; no unclassified paths in this candidate set. `supplemental-source-research-receipt.json` verifies 12 further source/research files, 4722486 bytes, copied and independently hashed. Path classification does not prove transitive runtime consumption or an atomic project backup; private running configuration and generated distributions remain in their original locations.

## Shared source and workspace boundary

Lawagent MCP/A2A uses `ARR_BASE_URL` before `ARR_BACKEND_URL`, with an optional Host header; its audit shell separately changes into `ARR_BACKEND` and executes a management command. Standalone verification scripts also infer the old sibling checkout. Updating only the service URL would leave these dependencies behind.

MassAgent provisioning copies tools and selected corpus inputs into `ARR_BACKEND/tmp_mass_check/<scope>` because tools infer the backend from their parent depth. A source-only relocation cannot preserve this rule while keeping shared agent execution state external. Explicit source-root configuration and two-scope isolation checks are required before changing these paths. No owner state or configuration has been relocated.

## Domain host environment

See `arr-runtime-baseline.json`. Live ARR18320 is launched through the external MasterPlan runtime wrapper, not directly by Editor. Preserve hidden-child-process behavior and BLAS thread caps when building the new persistent domain entry. Same executable metadata reports Python3.13.7, Django6.0.2 and Torch2.8.0+cu126; source requirements specify Torch2.12.0+cpu. The isolated environment must resolve this discrepancy against the observed baseline rather than blindly changing production packages.

## Next required gates

Finish active UI action/WebSocket coverage, dynamic imports/asset consumption, isolated dependency constraints and affected-owner preservation; resolve MassAgent source/data path coupling. The original-checkout geometry baseline is now green. Then copy the verified ARR closure to `backend/arr`, run it with isolated data and ports, compare domain responses/artifacts, and add product UI functions through the existing router. Full Next/DWG/product startup and end-to-end drawing/parking/3D gates remain separate. No old source removal or runtime cutover is authorized by a static inventory result.
