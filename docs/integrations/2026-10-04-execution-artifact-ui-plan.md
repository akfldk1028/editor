# Saved execution artifacts: bounded project UI plan

Status: implementation tracked in [execution artifact delivery](2026-10-04-execution-artifact-delivery.md), 2026-10-04. Catalog/attachments use a separate execution-catalog.sqlite within the existing design storage root; ProjectService remains the identity authority. Source-filter controls remain a follow-up; bounded combined-source pagination is implemented. Inspected `design-artifact-inventory.md`, `design/artifacts.py`, `routes_design.py`, `ProjectService`, and the existing ProjectPage/SavedDesigns workflow.

## Scope and identity

Add **보관된 실행 자료** to the existing project page, alongside **저장된 설계**. It browses copied execution evidence and explicitly attaches it to the current project. It does not select a database design candidate, generate a design, or start/resume an execution.

Keep the service-cache and portfolio corpora in distinct source namespaces. Their declared execution/run IDs and source references are historical evidence; no proven join to `(source_id, job_id, result_pk)` exists. Do not join by filename similarity, geometry hash, mass index, or visual appearance. Existing saved-candidate selection and PLANM handoff remain independent.

Use an opaque `catalog_id` for an execution group within a pinned `(source_namespace, snapshot_sha256)` and an opaque `artifact_id` for each registered file. A declared execution ID is optional display metadata, not a filesystem locator. Groups without a manifest remain listed as incomplete; preserve their available files without inventing an execution identity.

## Catalog and project ownership

1. After each explicit preservation operation, register a catalog snapshot from its validated manifest. Store the immutable entry set and snapshot hash, execution groups, artifact roles, sizes, digests, and a small sanitized metadata projection in an Editor-owned catalog index. Index registration is an explicit maintenance/import step; GET must never rebuild it.
2. `ArtifactArchive` currently holds content-addressed blobs and a current manifest per source ID; additive imports change that manifest. Therefore attachments must pin catalog snapshots, not a mutable “latest” source manifest. Preserve the pinned entry set and resolve its registered digest. Reuse archive containment/link checks and digest verification; do not expose `file(source_id, relative)` as a public path endpoint.
3. Add an explicit schema migration for a separate `execution_attachments` table in the local design repository: actor, project ID, scene ID/revision, catalog ID, and attached timestamp. Enforce uniqueness by actor/project/catalog. Validate catalog membership before inserting; retries are idempotent. The copied blobs and catalog snapshot are independent of project links, so attachment does not duplicate or alter files.
4. Resolve project ownership through the existing ProjectService repository and actor context (`local` in the current single-user profile). On attachment, retain existing same-origin checks, require `scene_revision`, and revalidate owner project/branch and accessible live scene through `ProjectService.create`. Reject stale bindings with 409 and unavailable verification with 503. Reads require project membership; artifact detail/download additionally requires that execution to be attached to that actor/project. No client-supplied actor, storage directory, relative path, or digest authorizes access.

## Minimal API extension

Keep `/api/v1/platform/projects/{project_id}/design` as the prefix; add these routes without changing saved-candidate endpoints:

| Method and suffix | Behavior |
|---|---|
| `GET /archive/executions?source_namespace=…&limit=20&offset=0` | Bounded catalog page; stable ordering, maximum 100, no raw source paths. |
| `GET /executions` | This project's explicit execution attachments. |
| `POST /executions` | `{catalog_id, scene_revision}`; validate ownership and pinned catalog, return attachment (201). |
| `GET /executions/{catalog_id}` | Sanitized historical metadata and bounded artifact list with availability and pagination. |
| `GET /executions/{catalog_id}/artifacts/{artifact_id}` | Registered PNG bytes only, for preview or elevation display. |
| `GET /executions/{catalog_id}/artifacts/{artifact_id}/download` | Explicit download of a registered PNG or original JSON; no arbitrary path argument. |

Catalog summaries contain source namespace, snapshot hash, declared execution/run ID if present, `execution_state: archived`, recorded source status, and observed preview/passport availability. Detail exposes allowlisted historical scalar flags and unresolved replay references. Do not return the preservation manifest's path map or blindly return arbitrary manifest/passport objects as API metadata.

Register roles from known copied layouts: mass preview, front/right/back/left/top/axon elevation, proposal image, execution manifest, program, and passport; include portfolio board and exact-geometry/summary evidence as separate roles. An absent artifact is `missing`, an unreadable or oversized metadata projection is `metadata_unavailable`, and a broken explicit replay reference is `unresolved`. TMP/unknown files remain preserved but are not offered as completed preview/evidence roles.

Only validated PNG content is inline-renderable (`image/png`, `nosniff`); a `.png` suffix alone is insufficient. Original JSON, including embedded historical local paths, is an explicit attachment download with a safe generated filename. Those strings never become links or lookup instructions. Serve immutable bytes with a digest ETag and private immutable caching after project authorization. Stream large portfolio JSON downloads; bound metadata parsing and list responses rather than parsing whole archives per request. Missing/corrupt registered blobs fail explicitly; no fallback to the original source tree.

## Existing-page interaction

Add a small ProjectPage child and its typed API module; do not expand SavedDesigns into a combined execution/candidate state machine. Load attached executions on open, and load the paginated source catalog only when **실행 자료 찾아보기** is expanded. **프로젝트에 연결** is the sole attachment action. Reopening the project restores links from the repository.

Selecting an attached execution shows **보관됨**, **원본 상태**, namespace/snapshot, available PNG preview and elevation tabs, and explicit **원본 패스포트 다운로드** / manifest/program/evidence download links. Label source geometry/gate/VLM flags **원본 기록의 판정**. Missing views and passports show unavailable states instead of generated substitutes. State plainly that attachment provides project reference material and does not establish a relationship with a selected database candidate.

Abort catalog/detail requests on pagination or selection changes; ignore late responses. Loading, empty, missing-artifact, and service-failure states stay distinct. No HTML from imported evidence, no raw filesystem links, and no generation, crop, compilation, provider call, or source access on GET.

## Verification and completion evidence

- Catalog/storage: both namespaces, identical IDs across snapshots, incomplete groups, missing manifest/PNG/passport, unresolved references, idempotent attachment, and reload persistence. Preserve candidate selection unchanged after execution attachment.
- API: actor/project isolation, unbound catalog/artifact denial, stale revision and origin rejection, invalid/encoded traversal IDs, linked/tampered/missing blobs, PNG signature/MIME, JSON attachment disposition, matching content hash, ETag, pagination bounds, and streamed large evidence.
- Read-only guarantee: repeated catalog/preview/download GETs leave archive/index bytes unchanged and never call source render/compiler/provider functions, including when an image or passport is missing. Test with original corpus inaccessible.
- Browser: explicit attach, historical status, preview/elevation switching, passport download, unavailable states, late-response suppression, and project reload. Verify no execution POST or candidate-selection mutation occurs from browsing or downloading.
- Run focused backend tests, frontend build/boundaries, mock Chrome tests, then a real HTTP/Chrome fixture backed by copied records from both corpora. Compare downloaded bytes to pinned archive digests. Report preserved/available/missing separately; neither preservation nor viewing proves current generation or regulatory success.
