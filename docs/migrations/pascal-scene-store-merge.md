# Pascal scene-store merge

`infra/migration/merge_scene_store.py` adds scene records from a designated SQLite source to an existing destination. It uses Python's standard library and never replaces a database file.

Run a read-only preflight first:

```powershell
python infra/migration/merge_scene_store.py --source C:/path/baseline/pascal.db --destination C:/path/active/pascal.db --output runtime/editor/workspace/scene-merge-unique-run
```

Repeat with `--apply` to merge. The output directory must not already exist; it holds a private `destination-before.db` backup and `receipt.json`. This workspace's `runtime/editor/workspace/` is ignored by Git.

The source is opened with SQLite `mode=ro` and a stable read transaction. Applying acquires a destination `BEGIN IMMEDIATE` writer reservation, checks schemas/integrity/foreign keys, and rejects differing records with the same scene ID, revision key, or event ID. Identical records are skipped. Event IDs are preserved, including their AUTOINCREMENT behavior; collisions are never renumbered automatically. A repeat merge is a no-op as long as the overlapping records remain identical. Later edits to overlapping records produce a conflict requiring explicit reconciliation.

The utility backs up the entire destination through SQLite's backup API, including committed WAL content, before inserting. A separate backup reader operates while the writer reservation prevents competing writes. Inserts, preservation checks, and foreign-key checks run inside one transaction. Unrelated destination tables remain untouched. Destination triggers on merged tables are rejected for manual review. Constraint failures roll back all inserted rows. Services can keep their existing connections and readers; another active writer can cause the command to time out after ten seconds and should be retried later.

Receipt table hashes cover ordered columns and complete ordered rows using compact UTF-8 JSON and SHA-256. They describe transaction snapshots, including WAL content, rather than an unreliable hash of only the active database's main file. The receipt also includes the physical backup's SHA-256. The receipt is written atomically before and after commit. An interrupted process can leave a `prepared` receipt: inspect the live database with read-only preflight to determine whether commit completed. Do not restore a whole backup over a live database with newer edits.

## Applied integration: 2026-10-05

Source: `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/editor/runtime-baseline/pascal.db`.

Destination: `%APPDATA%/Pascal/data/pascal.db`, the existing shared Editor/MCP default. No service restart or environment change was used.

| Table | Before | Added | After |
|---|---:|---:|---:|
| scenes | 1 | 6 | 7 |
| scene_revisions | 3 | 7 | 10 |
| scene_events | 0 | 2 | 2 |

The preflight found no conflicting IDs. The merge preserved the current scene and all baseline scenes, their exact metadata, serialized graphs, revisions, and event records. A subsequent read-only preflight found zero pending rows in every table.

Local evidence is in `runtime/editor/workspace/scene-store-merge-20261005/receipt.json` and the adjacent `destination-before.db`. Backup SHA-256: `890a55924df471b7a0ec99dcd22e0c6f0a4e5f60ea22397c7e36ad107d1ee3e7`.

Validation: `python -m pytest infra/migration -q` passed 62 tests, including nine merge cases covering history preservation, idempotence, all three identifier conflict types, read-only preflight, late failure rollback, live WAL backup, orphan rejection, and evidence-directory protection.
