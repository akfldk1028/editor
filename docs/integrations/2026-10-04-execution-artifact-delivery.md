# Archived execution evidence in Editor projects

The existing project page now connects copied execution evidence independently of saved database candidates. The catalog is registered explicitly from preserved Editor blobs; browsing and downloading never call ARR or regenerate images/passports. Source-cache and portfolio identities remain separate, and no candidate association is inferred.

## Ownership and registration

`modules/design/execution_catalog.py` owns `execution-catalog.sqlite` under `EDITOR_DESIGN_DATA_DIR`. Catalog snapshots and execution attachments share one transaction boundary, while existing design candidate tables remain unchanged. This is a refinement of the earlier proposed design-repository migration: the existing ProjectService still owns project/scene identity, and the execution catalog owns its pinned evidence links.

```powershell
python -m backend.app.modules.design.register_artifacts --directory D:/Data/25_ACE/editor/runtime/editor/design --source-id arr-maas-cache
python -m backend.app.modules.design.register_artifacts --directory D:/Data/25_ACE/editor/runtime/editor/design --source-id arr-design-executions
```

The canonical catalog contains 133 cache groups / 1,314 registered artifact roles and 150 portfolio groups / 423 roles. All 6,629 preserved files remain in the archive; only known roles are offered by the product. Temporary and unknown files stay preserved. Groups without recognized evidence or readable metadata remain explicit incomplete entries. Root batch/log files are preserved but are not execution groups.

Catalog IDs pin namespace, source manifest hash and group. Artifact IDs pin that catalog and file identity. Additive source capture creates a new catalog snapshot; existing project attachments and artifact lists remain unchanged. Reads open the index read-only and never register a missing snapshot. An unregistered index is an empty catalog, while a corrupt index/blob is an explicit service error.

## API and project flow

The existing `/api/v1/platform/projects/{project_id}/design` prefix includes archive execution pages, paginated project attachments, explicit attachment POST, attached execution detail, PNG preview and JSON/PNG download. IDs are opaque 64-character hashes; clients cannot supply a filesystem path. Every route requires the current local actor's project. Detail and downloads additionally require an explicit attachment. Mutation shares `DesignAccess` with candidate selection: origin, current scene revision and live owner/scene binding are rechecked.

Each download verifies the pinned content hash. PNGs must decode as PNG and pass a bounded image-size check before inline display. Original JSON is streamed as an attachment, retaining historical bytes and paths as evidence; embedded paths are not followed. Responses use a digest ETag, private immutable caching and `nosniff`. Missing/corrupt files produce errors without a fallback to original roots.

The project child offers separate catalog, attachment and artifact pagination, historical status, available mass/elevation/proposal images and explicit evidence downloads. Reload restores project links. Late requests cannot replace a newer selection. Missing previews/passports and failed storage remain distinct. Source flags describe recorded claims, not current design approval or legal compliance.

## Verification boundary

84 focused catalog, archive, design and platform tests passed. Tests include original source removal, pinned snapshots across additive imports, actor isolation, stale revision/origin rejection, corrupted persisted metadata, invalid PNG content, linked/corrupt blobs, and unchanged index/blob/manifest bytes after repeated GETs. The existing design candidate workflow is included in this regression scope.

Actual isolated HTTP verification uses a copy of the canonical catalog with selected copied blobs and fixture project/scene identities. Portfolio board, run state, exact geometry and summary responses matched their registered hashes; repeated reads did not change the index. This proves archived evidence delivery, not native optimization, artifact regeneration, production scene publication or end-to-end generation.

Local receipts: `.superpowers/sdd/2026-10-04-execution-artifact-ui/`. Original sources, shared agent state and canonical project attachments remain untouched by fixture verification.

Remaining: resolve original lineage with evidence where possible, integrate additional recognized artifact roles, diagnose empty core searches, implement supported native optimizer/program workflows, and verify full DWG/scene publication and reopening. Full ARR/selected AG integration is incomplete.

Actual Chrome verification additionally displayed the copied mass, front and right elevations, compared their HTTP bytes to pinned hashes, downloaded the original passport through the browser and matched its hash, and restored attached execution links after reload. No browser execution/generation POST occurred. Mock interception canceled one download despite a valid response; the mock checks the registered download link/header/bytes, while the actual Chrome test retains the full native download assertion. Both evidence types are kept distinct.

Final frontend checks: production build and two boundary tests passed; five focused mocked browser cases passed (one separate live-gated case skipped), and the actual HTTP/Chrome case passed separately. Disposable ports 18444/5186 were closed after verification. Canonical catalog integrity is ok with two snapshots, 283 groups, 1,737 roles and zero test project attachments.
