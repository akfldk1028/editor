# Native design specification creation

The first unit of `2026-10-04-native-design-execution-plan.md` now has an Editor-owned API, durable storage and a consumer in the existing project route. This unit saves specifications; it does not execute optimization or establish building compliance.

## Ownership and contract

- `modules/design/job_defaults.py` contains the used source default gene/objective builders; `job_spec.py` validates and prepares specifications for ten algorithms and ten building types. Runtime imports do not require ARR.
- `native_repository.py` and `native_service.py` store immutable original input, prepared specification, project/scene binding and checksums in a separate `native-jobs.sqlite` under `EDITOR_DESIGN_DATA_DIR`. Imported archives are unchanged.
- `/api/v1/platform/projects/{project_id}/design/native-jobs` supports POST and paginated GET; `/{job_id}` retrieves a saved record. Existing DesignAccess checks project ownership, mutation origin and live scene binding. Identical request identity/input/binding returns the same job; conflicting reuse returns 409.
- Existing ProjectPage contains NativeDesignJobs. It accepts an explicit WGS84 site Polygon, building type and algorithm, optional constraints and advanced specification. It displays the original parcel and complete saved specification after reload. The UI labels the record as saved with execution unconnected and exposes no Run action.

Storage uses transactional creation and a unique actor/project/request key. Reads neither create a database nor start work. Corrupt records, unsupported schema and linked storage paths fail explicitly. Public input is bounded to one MiB, depth 32, supported geometry and bounded search budgets. Invalid numeric values return 422. Missing/unavailable storage returns 503.

## Deliberate differences from source

Unsupported algorithms (including all/maas at this stage), fields, metrics, gene layouts and invalid ranges are rejected instead of silently replaced. Multipart sites are rejected; Polygon holes remain intact. Complete specifications merge constraints by `(name,type)` so an objective cannot silently erase a same-named constraint. Conflicting constraints fail. Incomplete custom specifications with outputs fail instead of losing supplied outputs. Small sites whose source defaults produce reversed gene bounds fail explicitly.

Original complete specifications may omit options: the source creation API summarizes population as 7 × 30, but the source SSIEA constructor defaults to 5 × 15. Current created-only records preserve the API behavior. Before execution, the worker must resolve and pin effective options and prevent a summary from misrepresenting actual computation. This discrepancy is not a verified execution configuration.

## Verification and limits

Backend verification: 235 focused native/design/archive/platform tests passed, including 100 complete canonical source fixtures, transactional duplicate requests, concurrent creation, reopen, actor/project isolation, corruption, readonly retrieval and invalid input. The fixture records source hashes; tests require no ARR runtime import. Review also found and fixed Python 3.11 compatibility in shared linked-path checks: lstat symlink/reparse evidence replaces the Python 3.12-only Path.is_junction API, with simulated API-absence regression tests. Independent API/spec/storage review found no additional blocking issue.

Browser evidence is recorded under `.superpowers/sdd/2026-10-04-native-design-jobs`: 39 mock browser tests passed (19 separately gated tests skipped), and one separate actual HTTP browser test passed. Frontend build and two boundary checks passed. The live fixture uses real Editor routes/storage with synthetic project identities and an explicitly synthetic site; it verifies persistence, not cadastral accuracy or optimizer execution. Saved job `d8a9c4796df54f78aa63441f6fe5c51d` retains the exact input and prepared grid/office specification, 12 generations and 2×20 population, status created and execution_supported=false. Reload retrieval equals the creation response; the only mutation was specification creation. Owned fixture port 18446 and test frontend 5186 were closed afterwards; operational services and canonical archives were unchanged.

Next: complete additive SSIEA computation, evaluator/repair/renderer agreement and durable worker/event/cancel/restart behavior. Remaining algorithms' execution, full MAAS, shared-agent task paths, 3D scene publication/reopen and source-unavailable cutover remain open. ARR and AG are not yet removable.
