# Native design runtime and preserved project data

Editor now serves the original design execution endpoints from its own FastAPI
process. The absorbed algorithms live under `modules/design/generation`; Django
models and execution persistence live under `adapters/design_storage`; HTTP
compatibility contracts live under `api/design_runtime`. The Next application
uses its own `/api/v1/design` boundary. No running ARR web server is required by
these execution routes. Shared domain agents remain in their separate owner roots.

## Implemented and verified boundaries

- All ten original mass algorithms execute through the native HTTP boundary.
  Job creation, start, journaled SSE, event-cursor replay, persisted geometry,
  cancellation, duplicate process claims and expired worker leases are tested.
  Subscriber disconnects release streams without owning or cancelling computation.
  A failed result write cannot publish successful completion.
- Original floor-plan algorithms are retained. Graph2Plan runs its installed
  original model in an isolated child, without modifying the server import path.
  Geographic building geometry is converted to local metres before floor planning;
  the API retains geographic results and supplies local geometry to the canvas.
- The browser test uses a real VWorld parcel, original ten-algorithm execution,
  displayed results, a generated metric floor plan and cancellation of a second
  job. Rendering-only fixture tests remain distinct from this live execution test.
- Fresh single-execution archives and the eighteen preserved MASS run groups share
  one native read boundary. Existing identity, source hashes and original evidence
  remain preserved; generated asset URLs use Editor's public API namespace.
- Design components now have separate geometry, renderer helpers, interaction
  hooks and named views. Original JSX/behavior was retained during extraction.
- The Pascal scene merge retained the current four-node scene and added historical
  scenes without overwriting collisions: seven scenes, ten revisions and two events.
  The 321-node historical building was reopened and visibly rendered in 3D.

## Data preservation

Verified implementation commits: `34ca1086` (scene merge), `5ff543fb` (component
boundaries), `f229a275` (webpack metadata access), `7e1f19fe` (execution engine and
persistence), `cbcf56b6` (native UI/BFF and evaluation navigation). Local commits;
no upstream push or deletion of original product roots.

The active creative catalog contains 54 source-validated runs / 1,405 candidates.
The evaluation archive contains 124 runs / 670 candidate records. A further 23
creative runs / 792 candidates failed original geometry-hash replay and are
preserved separately in quarantine with their exact failures, never promoted to
validated output. Copied file hashes and timestamps are recorded in the ignored
runtime receipts; see [archive import details](design-portfolio-archives.md).

The scene import has its own preflight, SQLite backup, receipt and idempotent
collision checks. Runtime databases, model weights, secrets and generated
artifacts are excluded from Git. Original ARR/AG sources were not deleted.

## Verification record

- Final backend integration: 93 passed in 126.13s (HTTP adapter, real geometry, floor coordinates,
  lifecycle, collaboration binding, archives, asset URL boundary, parking sources,
  explicit law-search configuration, active/quarantine migration, MAAS parity and
  generation, reference-asset closure and evaluation run navigation).
- Frontend/BFF and registry checks: 52 passed / 322 assertions. Core and editor
  workspace TypeScript builds passed.
- Production Next webpack build passed with type checking. Seventeen native page
  routes are present. Direct `import.meta` access warnings were removed while
  retaining development HMR and production duplicate-registration behavior.
- Actual creative and populated evaluation catalog responses returned HTTP 200;
  representative PNGs returned 200 (15,982 and 33,021 bytes). Candidate identifiers
  containing `:` and `+` remain addressable through the BFF.
- Follow-up archive review corrected default/relative data-root resolution and
  URL normalization in imported passport responses. Two referenced images were
  found in the original parent corpus, copied into Editor, and served with hashes
  identical to their sources; [receipt details](../migrations/reference-asset-closure.md).
- Parking optimization and original-algorithm integration: 11 passed in 47.20s.
  Indexed conflict rows and selected-candidate bitsets retain original order,
  scoring and ties. Nine parity cases include captured production-shaped geometry,
  accessibility, partial layouts, equal dictionaries and tiny polygons.
- Fresh complete browser suite: 22 passed in 3.4 minutes, including live VWorld,
  live design execution/floor planning/cancellation, original route controls,
  archive rendering and saved-scene error/retry behavior.
- Added evaluation archive navigation: two additional live browser tests passed
  in 15.8 seconds. The latest empty run remains empty; older runs preserve their
  original cards/status, `evaluation_run` URL and reload behavior. The selected
  twenty-candidate archive displayed all 41 image elements successfully. These
  recorded statuses are historical evidence, not a new legal review.
- Final production webpack/type build passed again after the selector changes.

Local runtime: Next `http://127.0.0.1:3003`; Editor FastAPI
`http://127.0.0.1:18449`. The backend was restarted hidden with its existing private
environment file. Check process identity and live endpoints before future restarts;
stored PIDs are observations, not authority.

## Remaining acceptance work

MAAS is not silently replaced by legacy algorithms: empty/rejected generation is
an explicit failed job with the original reason. The synthetic 1,600-square-metre
office case with explicit operator preference and two variants completed in
31.72 seconds (49.35 seconds in an earlier loaded run). Its review pool recorded
two parking passes and one architecture-order pass. The original caps, geometry
checks and acceptance gates were retained. This verifies the targeted execution
path, not acceptance of every returned variant, unrestricted eighteen-variant
feasibility, or verified law for the live parcel. Ordinary algorithm results are
not substituted as MAAS success.

The design collaboration UI can inspect project/run-bound owner records and actual
health. The current owner gateway has no free-form design-review submission
contract; that action returns an explicit unsupported response. Systems,
DomainExpert and InteriorDesign remain incomplete domain capabilities, regardless
of service connectivity.

This increment does not close every row in the
[original route ledger](native-editor-route-ledger.md). AG Playground execution,
popup/channel/session behavior, generic MCP workbench, deployment/auth/settings
parity, populated live law retrieval, and a real-project correction-to-acceptance
loop still need their own original-screen and owner-contract verification. Legacy
roots must not be retired solely on the basis of these design-runtime checks.
