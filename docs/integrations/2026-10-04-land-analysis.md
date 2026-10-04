# ARR land analysis inside Editor

## Design and ownership

User requires useful existing AG functions to work through Editor's frontend and backend. The original reference is AG-frontend `features/land`, not Studio's UI. Existing PLANM planning components have no address/PNU form; retain their behavior and add the requested route to the same product shell.

- UI: `frontend/app/planm/src/features/land-analysis/`; lazy `/land`, scoped CSS, no new dependencies.
- API: `backend/app/api/routes_land.py`, `/api/v1/land/{analyze,zones,stats}`.
- Adapter: `backend/app/adapters/land.py`; configured `EDITOR_ARR_URL`. Dev defaults to recorded ARR18320, not Editor backend8000. Browser cannot choose a server URL.
- ARR retains calculations, source retrieval and its existing query persistence. Editor does not calculate regulations or create duplicate geometry. Product project association remains a separate pending step.
- Original input detection, zone override, core/extended regulations, restrictions, law articles and statistics have Editor equivalents. Original API descriptions expected grouped law articles; current ARR emits flat articles. Adapter validates and flattens both forms.
- Preserve ARR assessment, missing evidence and permit-compliance qualification, even though original AG UI did not display them. Absent assessment stays absent, never verified. Partial errors are displayed independently of result data.
- Metadata timeout8s; analysis timeout180s (configurable150–600 via `EDITOR_ARR_ANALYSIS_TIMEOUT`) allows ARR's120s law-enrichment budget. No automatic analysis retry. Cross-origin POST rejected; PNU normalized/validated, input bounds enforced.

## Verification, 2026-10-04

Isolated Editor backend18434 (`platform-live/serve_land.py`) calls existing ARR18320; Chrome Vite5186 displays the real result. Original AG/AG-frontend servers are not used.

Live browser entered PNU `1168011200101280003`, manually selected the first listed zone, disabled law retrieval, and submitted via Editor API. Returned200 and matching PNU; regulations, owner `needs_evidence` assessment and `permit_compliance_verified:false` were visible. Source error `ParcelGeometry: no features` was retained. Manual zone choice is a test input, not a verified zoning assignment for that parcel.

Screenshot outside Git: `%LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004/editor/restored-files-v2/test-results/editor-live-land.png`.

- Adapter/API7 tests pass, including flat/grouped laws, invalid contracts, malformed stats, rejected input/origin, owner assessment retention and timeout budget. Platform regressions27 also pass (34 combined).
- Frontend build, module boundaries2, route2, dev12 pass. Land JS7.64kB/gzip3.10kB after qualification UI. No dependency/lockfile additions.
- Chrome live PNU1 and mocked law/partial/error1 pass. Existing mocked request-reload and routing regressions3 pass.
- Independent review identified dropped assessment and too-short timeout. Both reproduced by failing tests then fixed; no architectural layer violation reported. Core/viewer/scene code untouched.

Not verified: live address resolution, live law retrieval, project result binding/reload, applying land geometry to scene, full normal launcher, all existing DWG/PLANM/scene regressions. The original checkout's missing Gitagent build artifact still prevents reporting the whole backend suite green (see execution-slice evidence). The current module is a verified PNU lookup/display increment, not full ARR or full AG integration.

## Continuation

1. Restore the original checkout's locked build prerequisites and rerun existing-function regression gates.
2. Verify live address/law paths with bounded inputs and keep incomplete source outcomes visible.
3. Bind an analysis reference to the selected product project with source identity; specify owner reference/version before adding persistence. Do not copy the scene graph into another database.
4. Continue general task input, messages/results, pending input, comparison/export. Use the coverage table to keep deferred menus distinguishable from finished product features.
