# Receipt-bound NGII canonical ingest

The candidate is separate from served buildings and terrain. No command in this tool writes the active catalog or release pointer.

`ingest_ngii_buildings.py plan --orders <official-continuous-orders> --output <plan.json>` selects only B001 building layers from the verified nationwide B021/5000/2024/SHP inventory. Each source binds its existing receipt hash, archive SHA, size and mtime. Previously completed whole-archive CRC/PRJ validation is not repeated. Provider-12 identical-content display-name aliases are coalesced by all ZIP-part SHA values plus the SHP member name; both aliases remain in the plan. Different multipart SHP members remain separate.

`run --plan <plan.json> --output <candidate-directory> [--max-rows N]` uses one writer and commits 2,000 rows and their cursor in one SQLite transaction. The same command resumes. `--max-rows` limits work in that invocation, not source coverage. Plan changes reject resume. A 20 GiB free-space reserve is checked before every batch and split-member extraction. Only derived `candidate-directory/stage/<source-id>` files are removed after their source completes; downloaded archives remain untouched.

Standalone ZIPs use GDAL's ZIP reader. Split ZIPs use the auditor's verified multi-disk offsets, bounded decompression and extracted-member CRC/size checks, staging only the current SHP/SHX/DBF/PRJ members. Neither complete archives nor the national dataset are held in memory. Arrow batches are limited to 2,000 rows; SQLite cache is 32 MiB.

Optional `run ... --geometry-batch` vectorizes normalization and coordinate projection within each existing 2,000-row batch. Nonstandard or invalid geometries retain the scalar adapter. The single SQLite writer, ordered source cursor, source plan, schema, IDs, height policy and provenance are unchanged. Omitting the flag resumes scalar processing from the same committed cursor. Progress and status files use atomic replacement; SQLite remains the authoritative cursor after interruption.

Optional `--wal-pages 16384` raises SQLite's checkpoint threshold to approximately 64 MiB (default remains 1,000 pages). This is a threshold, not an instantaneous WAL allocation limit: an in-flight transaction can overshoot it and long-lived readers can prevent recycling. Retained WAL size is limited to 256 MiB after a reset, and the ingest stops before another batch if the WAL has grown beyond 256 MiB. Keep consumer read snapshots short while ingestion is active. SQLite retains `synchronous=FULL` and its 32 MiB page cache. Values outside 1–16,384 are rejected. This setting changes neither canonical records nor the committed cursor.

The active candidate main DB was NTFS-compressed to recover space, without changing logical bytes. This caused a measured ingestion regression: ordinary batches became fast with the larger WAL threshold, but checkpoints still took roughly 29–33 seconds; the initial sustained sample improved only from about 254 to 277 rows/second. Do not present NTFS compression or this checkpoint setting as a throughput improvement over the original uncompressed database. Source data and served artifacts were not compressed by this operation.

On a real 4,000-row source fixture, three end-to-end trials (source reading, normalization, projection, compression and SQLite writes) measured 2.26–3.65 times faster with the flag. Serialized canonical payloads and observations had identical hashes, cursors and database sizes. This is a bounded fixture measurement, not a nationwide completion-time guarantee. Reports are under `management/uniform-source-audit/canonical-sqlite-benchmark.json`.

SQLite schema:

- `sources`: pinned source ID, expected row count, committed next row, status and full source manifest.
- `buildings`: unique canonical ID, z14 and z16 owner, UFID, BJCD, height decision and compressed JSON payload.
- `observations`: every source row, canonical ID, BJCD and decision (`inserted`, `duplicate`, `conflict`, `rejected`). Exact duplicates retain observation provenance instead of becoming additional meshes.
- `issues`: full rejected/conflicting record and source row. A conflicting height never overwrites the existing building, and prevents `complete=true`.

Payloads use zlib compression and reference `sources.manifest` to avoid repeating long manifests millions of times. Consumers should use `export-region --database <buildings.sqlite> --region 14/x/y`; it emits ordinary NDJSON with expanded original canonical provenance. Output geometry is never clipped to its owner tile; tileset bounds must contain the entire shape.

`progress.json` records inexpensive current-source progress. `status.json` is written at invocation boundaries and includes source completeness, insertion/duplicate/conflict/rejection counts and actual BJCD-prefix counts. While running, the SQLite source cursors are authoritative. A candidate with any conflict, rejection, unfinished source, changed source receipt/file or missing province evidence is not a completed nationwide publication.

Current source plan v2: `C:/Data/25_ACE/ngii-canonical/source-plan-v2.json`, SHA `3cde8dc9444747b7ba4e59cd1c5232fe936b9aad6378946aa439ce4aab22977f`; 19 distinct SHP sources and 22,328,809 input rows after coalescing 2,771,027 byte-identical provider-12 alias rows. Candidate directory: `C:/Data/25_ACE/ngii-canonical/3cde8dc9444747b7`. These are input-row counts, not assertions of unique physical buildings.

## Completed input for the bulk baker

Run `regions --database <buildings.sqlite> --plan <source-plan-v2.json> --output <regions.json>` once after ingestion. It opens a read transaction and refuses unfinished sources, unresolved issues, a different source set/manifest, a different database plan, an invalid plan-content hash, changed archive size/mtime or changed receipt bytes/hash binding. It streams compressed payloads once to count buildings and full Polygon components by z14 owner. Output is atomic and small (one row per region); no nationwide NDJSON copy is created. It deliberately refuses the current unfinished snapshot. `sourceComplete` describes input ingestion, not completed meshes or nationwide terrain coverage. Reported raw BJCD prefixes must separately demonstrate all 17 administrative areas before publication (historical 42/45 codes correspond to current 51/52).

The existing official ZIP CRC/PRJ validation is not repeated by this gate. Its trust boundary is the pinned public receipt plus archive size/mtime; the canonical row manifest retains the receipt and inventory hashes. Preserve the bound archives and receipts throughout the bake. The final release should pin plan SHA, completed region-inventory SHA, terrain archive SHA, and geometry revision; also verify all listed regions and their feature/component counts were emitted. Do not publish a mesh set from an unfinished SQLite snapshot.

Bun direct-read contract (read-only database; hold `BEGIN` for one consistent snapshot):

1. `SELECT id,manifest FROM sources` gives the small source manifest map, where `manifest` is JSON text.
2. `SELECT id,region14,region16,payload FROM buildings WHERE region14=? ORDER BY region16,id` uses the existing region index. `payload` is a zlib stream, decoded with `inflateSync` from `node:zlib`, then UTF-8 JSON. It is not raw DEFLATE or gzip.
3. Restore `value.provenance = {...sourceManifests[value.provenance.sourceId], row:value.provenance.row}` before handing the row to the existing NGII mesh adapter. Missing source IDs must fail. Preserve canonical IDs, height decisions, full multipolygon coordinates and holes.
4. Stream one region at a time; do not load all national payloads into memory. `export-region` performs the same restoration for Python CLI consumers, but intentionally remains available for diagnostic samples before national completion. Only the completed `regions` gate authorizes the bulk production input.

One Bun process should verify the pinned terrain archive once and reuse the opened reader for all regions. Do not hash the multi-gigabyte archive separately per region. Keep ingest and bake outputs separate from the currently served catalog until the complete candidate is verified.

## Frozen base plus writable delta

`ngii_canonical_snapshot.py run --plan <same-plan.json> --base <existing-buildings.sqlite> --output <new-delta-directory>` retains the original database unchanged and writes only new observations/buildings into an uncompressed delta. It holds the original directory's `ingest.lock` as well as the delta writer lock. Base size/mtime and absence of a nonempty base WAL are checked before every batch. An existing base/delta conflict is an issue, never an overwrite. Exact IDs already in the base produce duplicate observations in the delta. The original source cursor is copied into the delta and advances atomically with each new batch; completed base source rows are not ingested again.

`canonical-snapshot.json` uses schema `ngii-canonical-snapshot-v1`, pins the same plan SHA and frozen base identity/cursors, and names the delta database. Its `complete` remains false until **all original source cursors** finish, combined source issues are zero, per-source observation ranges have no gaps/overlap, and canonical IDs are disjoint. A completed delta also receives its file identity. This is one logical nationwide NGII dataset, not a mixture of separate providers or partial regions labeled complete.

Consumers open an in-memory SQLite connection with URI support, attach base and delta with `mode=ro`, and create TEMP views: `metadata` and `sources` select delta tables; `buildings`, `observations`, `issues` each use `base.table UNION ALL delta.table`. Then `PRAGMA query_only=ON; BEGIN` provides one read snapshot. `open_snapshot()` implements this contract. The same region queries, compressed payloads and provenance expansion apply. Do not open the base alone and expect final coverage, or concatenate copies into another nationwide file.

After completion, use `ngii_canonical_snapshot.py regions --snapshot <canonical-snapshot.json> --plan <same-plan.json> --output <regions.json>`. This invokes the existing complete-source/receipt gate through the union and emits the unchanged region-inventory schema. Diagnostic region export is `ngii_canonical_snapshot.py export-region --snapshot <canonical-snapshot.json> --region 14/x/y`. Runtime/bake consumers must explicitly support the snapshot manifest before final publication; no current service is switched by these commands.

A bounded live comparison of the 192 MiB threshold measured 54,000 new rows across two checkpoints in 209.71 seconds (257.5 rows/second); checkpoint-containing batches took 71.78 and 81.04 seconds, and observed WAL peaked at 211,838,072 bytes. This did not materially improve the approximately 244 rows/second sustained 64 MiB result. The worker was returned to the 64 MiB setting to avoid longer concentrated I/O periods. Evidence: `management/uniform-source-audit/wal192-comparison.json`.


Completed snapshot consumers now accept `--snapshot <canonical-snapshot.json>` as an alternative to `--database`:

- `bun tools/bake-ngii-region.ts --snapshot <manifest> --regions <regions.json> --source-plan <source-plan-v2.json> --terrain <archive.pmtiles> --terrain-sha256 <sha> --output <new-candidate-folder> [--limit 16]`
- `python infra/data/prepare_ngii_national_release.py --snapshot <manifest> --data-root <root> --plan <plan> --regions <inventory> --hlod-input <input> --hlod-folder <folder> --terrain-pointer <pointer> --terrain-work <work>`

The baker runs the Python `verify` command before terrain work; set `NGII_PYTHON` if `python` is not the environment with the ingest dependencies. This reuses exact integer source-file timestamps and receipt/content-plan checks without rehashing downloaded archives. Bun opens both attached databases with SQLite URI `mode=ro` (the URI open flag is required on Windows), then applies query-only mode. The publisher uses the same logical connection and checks all 17 province observations and complete region coverage. Neither command accepts `complete:false` as nationwide input; neither activates a release.


Current candidate storage contract is `gzip6-mesh-and-metadata-v1`. Regional B3DMs are deduplicated by decoded SHA256 and stored as deterministic gzip6 `.b3dm.gz`; both `footprints.json.gz` and `ground-source.json.gz` are also losslessly compressed. `tileset.json` and candidate receipts stay plain. Every compressed receipt records encoded `bytes`/`sha256` plus `contentEncoding: gzip`, `decodedBytes` and `decodedSHA256`. Resume, HLOD input and publisher must agree on this revision; the publisher verifies both identities before parsing offline metadata. Metadata gzip is not a public serving requirement. New identity digests prevent overwriting previous packing candidates. The existing 100-building sample measured 130,547 payload bytes plus 2,935 receipt bytes; this is not a national capacity bound.
