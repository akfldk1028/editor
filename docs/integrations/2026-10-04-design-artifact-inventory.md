# Design artifact ownership inventory — 2026-10-04

Read-only filesystem and source-code inspection. No ARR imports, HTTP calls, rendering, compilation, file moves, or source writes were performed. Counts are an observed snapshot, not a complete migration claim.

## Observed artifact roots

Root: `D:/Data/25_ACE/docs/ai-session-memory/maas-service-cache`.

| Subdirectory | Immediate directories | Files | Bytes | File types |
|---|---:|---:|---:|---|
| `single-executions` | 114 | 1,355 | 49,867,133 | 541 JSON, 814 PNG |
| `executed-masses` | 19 | 338 | 10,424,929 | 106 JSON, 208 PNG, 24 TMP |
| `geometry-language` | 0 | 37 | 870,541 | 18 JSON, 19 PNG |

Including five files directly under the root: **1,735 files, 64,941,515 bytes**. No symlinks were observed. All 665 JSON files in the three subdirectories parsed successfully. Temporary files must be preserved as opaque evidence, not exposed as completed render artifacts.

`single-executions` contains 112 `execution.json`, 112 `program.json`, 112 `mass.png.passport.json`, and 111 `mass.png`. Two directories have no execution manifest. Of the 112 manifests, 111 declare `geometry_ready=true`; every declared `execution_id` matches its containing directory. These are recorded claims, not newly rerun validation.

## Original endpoint and identity contracts

`ARR/backend/design/views.py` exposes:

- `maas/single-executions/{execution_id}/preview/`: existing `mass.png`.
- `.../manifest/`: `execution.json`; `.../passport/`: `mass.png.passport.json`.
- `.../elevation/{view}/`: `elevation/views/{front,right,back,left,top,axon}.png`.
- `.../elevation-proposals/alt-01/`: `elevation/proposals/alt-01/proposal.png`.
- Multiview proposal images: `elevation/proposals/multi-view-alt-01/{front,right,back,left,critic-montage}.png`; evidence JSON: `proposal.json`, `critic.json`.

`design/maas/single_execution/catalog.py` names execution runs `single-execution:{execution_id}`. Its catalog selects geometry-ready manifests, reads existing passports, and exposes program/geometry/visual/floor-capacity hashes. A new preservation catalog should also retain incomplete directories and failed manifests rather than silently omit them.

`execution.json` artifact keys include directory, manifest, passport, preview, and program paths. Other JSON documents contain local/source/condition-pack/critic paths and downstream evidence. Preserve original bytes, but treat embedded paths as untrusted provenance strings, never as authorization to open files.

Eleven execution manifests contain explicit `source_run_id` and `source_mass_index`: two refer to single executions, nine to portfolio runs. None of the nine portfolio directory names exists under the inspected ARR portfolio root. Recursive inspection of cache JSON found **no** `job_id`, `optimization_job_id`, `source_job_id`, `result_pk`, or `design_id` fields. There is therefore no demonstrated mapping from these files to the imported SQLite design job/result records. Equal hashes or visually similar masses are not sufficient to invent that mapping.

## Derived cache versus authoritative portfolio evidence

`design/maas/geometry_language/executed_archive.py` reads run artifacts named:

- `maas-book-exact-geometry-artifacts.json`
- `maas-book-programs-summary.json`
- `maas-run-state.json`
- Referenced board PNG, commonly `maas-book-neighborhood-20.png`.

Its `workspace_root()` currently resolves to `D:/Data/25_ACE`, then searches `docs/playwright/design-route-live-verify/book-program-portfolios-*`. That expected location has no matching run directories. Actual run evidence exists under **`D:/Data/25_ACE/ARR/docs/playwright/design-route-live-verify`**, and most directory names use `legal-mass-*`, not the helper's `book-program-portfolios-*` filter.

Across immediate run directories in the actual root, inspection found 124 exact-geometry archives (312,581,701 bytes), 124 summaries (2,167,424,724 bytes), 143 run-state files (217,951 bytes), and 32 standard board PNGs (4,487,927 bytes). Only three directories match the helper's `book-program-portfolios-*` prefix, each containing a state file and no exact archive/summary. Thus correcting only the root still would not discover the actual run corpus. The large portfolio corpus is a separate explicit preservation scope; copying the 65 MB cache does not preserve all authoritative source data.

The **entire actual portfolio root contains 4,894 files, 2,877,613,459 bytes**. Selecting only its 143 immediate directories containing an exact archive or run-state file yields **4,862 files, 2,876,413,221 bytes** including their descendants. None of the 19 executed-mass cache directory names matches an immediate directory of this actual portfolio root. Preserve both corpora separately; do not associate a cached PNG to one of these source runs by index or hash prefix alone. The three cache subdirectories total 61,162,603 bytes; the larger root total includes one root JSON and four log files.

The original executed-mass preview GET can crop a board and write a new cache PNG. Its passport GET invokes archived compilation, writes a passport, and assembles evidence. The single-execution thumbnail GET can also materialize an image. These handlers must not be reused as read-only artifact serving, and historical files must not be regenerated silently.

## Recommended Editor preservation and serving contract

Use `backend/app/modules/design/artifacts.py` with an explicit source root and source namespace. Preserve files into immutable content-addressed blobs, then atomically publish a manifest containing relative path, byte size, SHA-256, artifact family, recorded execution identity, and observed availability. Keep the source untouched. Reject traversal, symlink escapes, and source/destination aliases; verify destination bytes before publishing. Repeating an identical snapshot is idempotent; changed snapshots retain prior versions.

Use separate execution identities `(source_namespace, execution_id, snapshot_hash)`. Keep imported database candidates `(source_id, job_id, result_pk)` distinct. Project attachment may be explicit, but should not imply a proven candidate association. Preserve explicit replay links as unresolved references where their target is absent.

Expose a bounded catalog and artifact lookup by catalog ID/role, not arbitrary filesystem paths. For example, list executions, read a sanitized manifest, and retrieve a registered artifact by ID. Serve copied PNG bytes with a fixed MIME type, `nosniff`, content-hash ETag, and immutable caching; serve original JSON as an explicit download if it contains historical local paths. A sanitized JSON projection may expose selected provenance fields separately. TMP and unknown files remain preserved but not inline-renderable.

Missing preview, manifest, source replay target, or passport should be explicit unavailable states. Catalog reads must not compile, render, call providers, or generate evidence. Keep original `geometry_ready`, gate, VLM, and lifecycle flags labeled as historical claims. Add a separate task later for authoritative portfolio preservation and explicit dependency reconciliation; do not mark it complete after preserving only service caches.
