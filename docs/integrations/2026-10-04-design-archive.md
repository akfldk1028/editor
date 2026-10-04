# Saved design ownership and PLANM handoff

Editor now preserves original design jobs, candidates and revision evidence in `modules/design`, binds archived jobs to existing platform projects, and saves/reopens selected candidates by original result primary key. The existing project page and PLANM route consume these records. Original optimization execution and external image/elevation artifacts are not migrated by this increment.

## Storage and identity

`DesignRepository` stores complete original rows separately from project attachments/selections. The importer reads a consistent SQLite snapshot, validates JSON and job references, retains nullable revision references, and commits all rows and its manifest atomically. Conflicting source rows roll back; identical retries do not duplicate records. Dry-run never initializes destination storage. Source path aliases and hard links to the destination are rejected.

The source has duplicate `(job_id, design_id)` groups. Original result PK, source namespace and job identity are therefore the lookup/selection contract. Original status is retained as `source_status`; all imported jobs/results are `execution_state=archived`, including previously running jobs. No imported process is claimed to be alive.

```powershell
python -m backend.app.modules.design.import_records --source <preserved-source.sqlite> --destination D:/Data/25_ACE/editor/runtime/editor/design
python -m backend.app.modules.design.import_records --source <preserved-source.sqlite> --destination D:/Data/25_ACE/editor/runtime/editor/design --source-id arr-design-main --apply
```

Reuse `arr-design-main` for the same source. The dev launcher supplies `EDITOR_DESIGN_DATA_DIR` with this default local directory. DB files remain outside Git tracking.

## Project and frontend flow

Routes are under `/api/v1/platform/projects/{project_id}/design`: paginated archive/jobs and candidate lists, attached job/result detail, saved selection and prepared PLANM mass. Existing `ProjectService` owns actor/project/scene binding. Attachment and selection mutations validate origin, strict IDs, expected revision and current scene ownership/version. Reads require an existing accessible project; candidate detail requires that job to be attached. Stored revision is a selection snapshot, not a promise that an external scene can never change afterward.

The project page browses archived jobs, displays candidates with distinct original PKs, previews stored geometry as a labeled 2D projection, shows metrics and saved constraints, and restores the saved selection after reload. It does not label footprint preview as a full 3D reconstruction.

The selected-design link opens `/planm?designProject=...`. It fetches a read-only prepared mass, displays its source/geometry, and starts the existing PLANM run endpoint only on explicit action. The original mass form is not used to reconstruct or simplify imported shapes. Existing review, approval and DWG/Pascal flow remains the destination pipeline.

## Loss-checked mass conversion

The source renderer uses WGS84 and UTM52N. Supported single-ring polygon extrusion, explicit stepback and complete floor-plate representations are projected into local metre coordinates using the projected base centroid. Source CRS, projected CRS, origin in both systems, units, original identity, row hash and mass hash are retained in `source_provenance` and the existing PLANM input artifact. Explicit floor counts/heights are required; inconsistent total/lower/bottom heights are rejected.

Raw archived geometry remains unchanged. Holes, multipart geometry, unsupported compound volumes/sections, malformed coordinates and unrepresentable floor plates are explicitly rejected by the bridge; no fallback footprint or invented floor count is substituted. An aggregate read-only probe over 16,964 source masses found 8,162 supported; the remaining reasons are recorded in `mass-probe.json`. This is compatibility evidence, not optimizer parity, survey validation or legal approval.

## Preservation and remaining scope

Actual canonical archive contains 540 jobs, 18,601 results and 2 revision events. Every row/field equals the preserved original SQLite snapshot used for land history. Repeating the import inserted no rows and destination integrity is `ok`. No original DB, agent state or operational service was modified. Canonical archive has no test project attachments; browser verification uses a database copy and fixture scene/owner identity.

The source database does not provide complete external artifact links: single-execution/executed-mass images, passports and elevations still need preservation/catalog/delivery integration. Native source job-spec creation, durable optimizer execution/cancellation, complex mass representations and full scene/parking/floor/elevation parity remain open. Revision rows are archived but their decision workflow is not yet exposed. Full ARR/selected AG integration remains incomplete.

## Verification and execution limits

59 focused design/platform backend tests, 8 runtime tests, production frontend build and 7 mocked browser cases passed. Independent storage, conversion and frontend review found no remaining material issue. Actual HTTP/browser verification uses a copy of the imported database and fixture project/scene identities; it confirms attachment, original-PK selection, reload restoration and prepared mass preview. It does not establish a production owner/scene round trip.

Planning use starts blank and must be explicitly chosen. Office supplies `{office: 1}` for this new planning scenario only; original building type and geometry remain unchanged. Commercial stays unavailable until a verified street frontage can be supplied. Optional regulatory facts default to unknown and reuse the existing checked ruleset date window; no current legal-compliance claim is made.

Actual candidate PK18183 reached real PLANM normalize/analyze successfully. Run `1e648c200a244043ac2f3bec2c6f9c24` first exposed missing use_mix; subsequent explicit office scenario `0fa13c38842848d58272e1a8602b6831` reached alternatives and stopped with `insufficient_accepted_alternatives` (two accepted alternatives required). Missing regulatory facts remain unresolved. Neither run proves successful generation, approval, DWG delivery or scene publication. Raw mass geometry/provenance is retained in the run input. Receipts are local under `.superpowers/sdd/2026-10-04-design-archive/`.

Next: inspect the rejected alternatives and preserve/catalog original external execution artifacts, then add verified frontage/program context and compatible representations. Preserve validation gates; do not make an infeasible candidate pass by inventing facts or flattening its geometry.
