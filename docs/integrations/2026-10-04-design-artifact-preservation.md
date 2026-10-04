# Execution artifact preservation

`modules/design/artifacts.py` owns a byte-preserving file archive. It imports explicit source trees into content-addressed blobs and publishes a manifest only after a second complete source content scan agrees with the initial capture. Reads need only Editor storage. The importer never imports ARR, calls an original HTTP endpoint, compiles geometry, or regenerates a preview.

The source namespaces remain separate: `arr-maas-cache` for the service cache, `arr-design-executions` for the actual portfolio corpus. Neither implies an association with a database design candidate. The original JSON bytes, including recorded statuses and obsolete absolute paths, are preserved. Embedded paths are never followed.

## Run

```powershell
python -m backend.app.modules.design.import_artifacts --source D:/Data/25_ACE/docs/ai-session-memory/maas-service-cache --destination D:/Data/25_ACE/editor/runtime/editor/design/artifacts --source-id arr-maas-cache
python -m backend.app.modules.design.import_artifacts --source D:/Data/25_ACE/docs/ai-session-memory/maas-service-cache --destination D:/Data/25_ACE/editor/runtime/editor/design/artifacts --source-id arr-maas-cache --apply
python -m backend.app.modules.design.import_artifacts --source D:/Data/25_ACE/ARR/docs/playwright/design-route-live-verify --destination D:/Data/25_ACE/editor/runtime/editor/design/artifacts --source-id arr-design-executions --apply
```

Dry-run creates no destination files. Identical imports add no entries. Additions are allowed; changing or removing a previously recorded file rejects publication. Capture changed source bytes under a new explicit snapshot namespace to retain the older manifest. Each entry records relative path, size and SHA-256; equal content shares one blob. File lookup verifies bytes before returning a path. This archive preserves file contents and relative paths, including incomplete `.tmp` evidence, not empty directories, ACLs or modification timestamps.

Import uses one exclusive destination lock and atomically replaces the manifest. A failure may leave unreferenced verified blobs, but cannot expose a partial manifest. A crashed importer can leave `import.lock`; confirm the specific importer process is terminal before operator recovery. There is no automatic lock deletion or source cleanup. Source/destination overlap, symlinks/junctions, path traversal, missing/corrupt stored blobs and unreadable source directories fail closed.

This is a stable-interval capture with repeated content scans, not an atomic snapshot of an actively changing filesystem. Final cutover still requires reconciling source writes. The original roots and their backups remain untouched.

## Verification and remaining integration

Seven preservation tests exercise offline reads after the original source is renamed, byte preservation, repeated/additive imports, duplicate content, conflicts/removals, corrupt blobs, path boundaries, source changes during capture and concurrent-import locking. Combined design archive/API/bridge tests: 39 passed. Independent preservation review found no blocking issue; its source-change and lock regression requests are included.

Local capture receipts are under `.superpowers/sdd/2026-10-04-design-artifacts/`. The inventory documents the authoritative corpus and unresolved links. Product catalog, explicit project attachment, bounded artifact-serving routes, historical status display and PNG/elevation/passport UI are the next integration step. No artifact UI or full generation/3D parity is claimed by this preservation increment.

Actual canonical capture completed: service cache 1,735 files / 64,941,515 bytes; portfolio corpus 4,894 files / 2,877,613,459 bytes. Combined: 6,629 files / 2,942,554,974 bytes. A repeat full source-and-stored-blob hash check found zero added entries and identical snapshot hashes. Source snapshots: cache `d0b9f3f8fb9f63ce7eb45c4c3c2fc5cad14f1fc84a5aa595d25f556a763de27a`; portfolio `982f0ba6ae3a201b6ae648495e2590e0c802dee535639943226500693c2d8fab`. Manifests and blobs live under ignored `runtime/editor/design/artifacts`; no original files were moved or deleted.
