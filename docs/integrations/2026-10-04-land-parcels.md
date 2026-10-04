# Land parcel API integration

Editor now owns `POST /api/v1/land/reverse` and `POST /api/v1/land/parcel-geometry`.
Source: ARR `land/services/pnu_resolver.py:reverse_geocode,fetch_parcel_geometry`,
`land/views.py:reverse`, and `land/views_agent.py:parcel_geometry`.
The API lives in `app/api/routes_land.py`; provider access lives in
`app/adapters/vworld.py`; geometry validation/selection lives in
`app/modules/land/parcel_geometry.py`. No ARR import or ARR HTTP request is used
by these two operations. Shared agent endpoints and execution state are unchanged.

## Contract and compatibility

- Reverse input is numeric `{x,y}` within the original Korea bounding box
  (124–133 longitude, 33–44 latitude). Output retains all parcel polygons,
  PNU, coordinates and address. Failed address enrichment retains the boundary
  and cadastral address. Missing/invalid provider PNU becomes null.
- Parcel input is `{pnu}` with the shared ASCII 19-digit/hyphen normalizer.
  MultiPolygon selection uses largest **exterior** area, retaining its holes,
  matching the source policy rather than ranking area after hole subtraction.
- Server-owned `VWORLD_API_KEY` is required. Missing configuration and provider
  failures return `success:false`, null geometry and a safe error. Provider URLs,
  keys and arbitrary exception text are never echoed.
- Intentional tightening: malformed, unclosed, non-finite, out-of-range,
  non-2D or topologically invalid geometry is rejected. Provider status must be
  OK for both routes. Invalid API input returns 422; cross-origin requests 403.
- WGS84 boundary coordinates are not surveyed dimensions or projected areas.

## Verification and remaining work

New tests first failed (15 expected missing-method/route failures). After
implementation and additional review cases, 42 targeted land/resolution/catalog
tests pass, with one existing Starlette TestClient deprecation warning.
Fixtures exercise provider request parameters, full/fallback addresses, polygon
holes, exterior-vs-net-area selection, HTTP/malformed/empty/missing-key failures,
geometry rejection and successful API calls with no legacy URL configured.
`git diff --check` passes.

The follow-up UI slice connects the existing `/land` page to these endpoints.
`ParcelLookup.tsx` owns inputs/request cancellation/status, `parcel-api.ts` owns
response validation, and `ParcelPreview.tsx` owns SVG rendering. Existing HTTP
transport is reused. No new dependency, route shell or map engine was added.
Holes use even-odd fill; MultiPolygon parts stay separate. Input changes cancel
pending requests and clear old results. The preview labels its coordinate-based
scope explicitly and does not write to a project or scene.

Actual Chrome: 9 passed, 5 unrelated opt-in cases skipped. This includes four
parcel UI response-fixture cases and one browser-to-real-Editor-HTTP case with
only the upstream Vworld transport replaced by a fixture. The original three UI
tests first failed on missing controls, then passed after implementation.
Frontend build and both module-boundary tests pass; all 42 targeted backend
tests pass again. A separate read-only reviewer found no blocker and recommended
the added in-flight cancellation test. Screenshot inspected at
`test-results/editor-parcel-preview.png`. Browser log is under
`.superpowers/sdd/2026-10-04-land-parcel-ui/browser.log`.

The isolated test server used port18436 and the expected frontend origin5186.
It was stopped after verification. The Python wrapper's final console print
hit Windows cp949 encoding; the saved UTF-8 Playwright log confirms 9 passing
tests and server cleanup was verified. This was a reporting-tool issue.

Real Vworld calls and production services were not exercised. Next verify
owner-managed provider configuration and address-result-to-boundary flow.
Analysis/stats still depend on the legacy adapter. Project persistence and scene
application, remaining ARR/AG features and specialist completion remain separate
gates.

Rollback: revert this slice; original sources, databases and services were not
modified. No dependency or lockfile changes; existing Shapely is reused.
