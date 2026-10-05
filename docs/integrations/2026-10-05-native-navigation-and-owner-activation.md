# Native navigation and actual owner activation

This increment restores navigation and connects the existing user project. It does
not establish completed domain design or retirement of every ARR dependency.

## Product surfaces

The shared header links the native 3D editor, CAD/DWG, PLANM, saved scenes,
Projects, land, VWorld, law, design, design language, agents, dialogue, flow,
builder, gallery, history, deployment and settings. `/projects`, `/projects/[id]`
and `/runs/[id]` reuse the original project/execution components. The run page
requires the native binding and checks owner, branch and request identity.
Original project execution panels retain their additive-only contract; the full
multi-algorithm engine remains at `/design`.

CAD preserves the original drawing/chat/review panels and its gateway contract.
CAD styles are scoped to `.dwg-workspace`; the standalone reset stays in its own
entrypoint. Native API forwarding permits only existing operations. Imported
PLANM views use a build-time product prefix, including API, artifact and scene links.
The live CAD drawing contains 234 fixture entities, not the r39 project drawing.

The dialogue screen accepts an owner-authored read-only specialist request file.
It distinguishes coordinator versions from declared source versions/assets.
Before submission it persists the exact body and idempotency key; an uncertain
response or reload retries that same request. Switching projects aborts local
work and preserves an already uncertain request under its original project.

## Actual execution evidence

The existing project is `uijeongbu-r39-own-design`, branch
`gross-zone-study-20261002`, in the preserved owner root
`runtime/diagnostics/own-program-plan-20261002`. The word diagnostics in this
historical directory name does not make this a synthetic project. Gateway8791
and its worker now use that root with submissions enabled. The separate8793
backup runtime was not substituted. Source snapshots and 81 artifact hashes
were checked before/after activation; dirty/needs_evidence states were preserved.

Docker recovery restored Law, SiteContext, Requirement and DesignIntent; actual
A2A health requests passed. Catalog status now reports 12 available, 2 declared
HTTP providers, 1 local coordinator and 10 without declared endpoints. Local
Mass is implemented despite its missing catalog endpoint. These statuses do not
mean that all 25 roles have complete operational domain implementations.

Native binding `6c92d0cfe54d44cab465c00f6f59d04c` refers to scene
`uijeongbu-r39-source-mass3`. Its reference GLB is an unchanged copy of retained
mass revision3, SHA256
`67fb4ba51ddc01916cf6125234fd848e605506bb6a68cf1079e788de544876d1`.
The backend serves only hash-addressed GLBs from configured scene asset storage
and refuses missing, oversized or hash-mismatched files. This is a source
reference, not an editable reconstruction of accepted rooms. The newly imported
scene's missing schema defaults were repaired through the versioned scene API;
its own binding was advanced from revision1 to2 with an online backup and an
exact compare-and-swap. Existing scenes and source GLB bytes were not rewritten.
The reference was then repaired to the existing site/building/level/scan envelope
at scene revision3, with a matching backed-up binding update. The site container
has an empty property boundary, not an invented parcel. View-only camera bookmarks
were added; original model transforms and GLB coordinates remain unchanged.
The existing auto-frame calculation only sees node positions, not the GLB's
internal offset, so reference framing requires its saved view/tree focus.
The existing SiteRenderer also returned before rendering children when the parcel
boundary was absent. This was reproduced as a missing GLB request and fixed by
keeping the child group while conditionally drawing only the boundary line.
After rebuilding the nodes package and production app, the real GLB returned200
and the entire retained mass was visually verified through Scene -> Camera
snapshot -> View snapshot, with zero page errors. Screenshot:
`.superpowers/sdd/actual-project/source-complete-view.png`. Automatic initial
framing of offset reference assets remains a separate usability improvement.

Browser file import and submission produced actual run
`0c8fd0d96bdc429ca34294e349a77050`. All three recorded A2A request/response pairs
carry locally recorded agent identities:

| Owner | Tool | Actual outcome | Evidence boundary |
| --- | --- | --- | --- |
| Systems | systems_requirements | blocked | Frozen real Program r2 source; coordinator context r3 is not proof of consuming current Program r3. |
| DomainExpert | domain_review | blocked | Current Program r3 bound; domain-use evidence is missing. |
| Interior | interior_review | partial | Current retained mass r3/hash inventoried; generation, UV/material application and design acceptance are pending. |

Earlier failed run `6953eb7e98d948bf8970b8434c5096ea` remains recorded. The draft
Interior request incorrectly added unsupported fields; the corrected request
uses the existing strict owner contract. Historical un-attributed calls were
not relabeled. Dialogue and flow display recorded communication, not fabricated
agent conversation or an approval verdict.

Raw evidence is retained locally in `.superpowers/sdd/actual-project/`,
`.superpowers/sdd/cad-css-isolation.*` and the owner activation checkpoint.
Runtime databases, source assets and private environment files are not committed.

## Verification and running services

- Backend: 41 project, run, specialist, scene-asset and design API tests passed.
- Owner: 30 specialist, dialogue and Systems-flow tests passed; owner commit9d6b447.
- Frontend: 3 proxy/prefix tests passed (28 assertions); 10 dialogue, flow and
  specialist browser cases passed, including frozen retry and project races.
  Final production navigation suite: 6 passed6.2s, including the empty-boundary
  scene regression, actual asset load and saved-camera operation.
- CAD: `npm run verify` passed (435 Node tests, 75 .NET tests, TypeScript and
  standalone Vite build). Both standalone and native CSS isolation were viewed.
- Native production: `next build --webpack` passed compilation, TypeScript and
  route generation. The previous development child consumed about9.5GiB; only
  its verified parent/child tree was stopped. Final production frontend PID60880 now
  serves3003 with the same private endpoint/storage configuration. Build and
  restart receipts are in `.superpowers/sdd/actual-project/production-build*`
  and `site-renderer-production-build*` (the second build includes the renderer fix).
  CAD, PLANM, project/list/detail/run and drawing HTTP probes returned200.

The native product browser suite depends on the local bound project and retained
scene; it is a live integration suite, not a fixture-free CI suite. The specialist
browser suite mocks transport for retry/error coverage; the separate real run above
is the actual owner execution proof. Always check process identity afresh; PIDs
here are observations, not safe stop instructions.

## Remaining owner work

- Systems: bind the current accepted program and actual equipment/use demands;
  frozen generic spaces cannot establish service loads or clearance acceptance.
- DomainExpert: supply explicit domain/use criteria and independently check them.
- Interior: propose separately labeled surfaces/camera, generate source-conditioned
  appearance, compare projection with portable PBR on held-out views, then verify
  geometry and Systems constraints. No image/material was generated by this run.
- Orchestrator: verify a real correction/review/publication cycle before closing
  findings. A read-only blocked review does not authorize source acceptance.
- Platform: finish native provider retirement for remaining ARR consumers, account
  for local adapters in the catalog, and add an explicit scene-revision refresh
  workflow before treating edited scene bindings as automatically current.
