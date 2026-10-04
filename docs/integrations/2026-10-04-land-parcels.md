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

These are in-process API/provider contract tests, not live Vworld evidence.
No browser or production service was exercised in this slice. Next connect the
existing land-page coordinate/PNU controls and boundary preview, then verify
the browser flow and real owner-managed provider configuration. Analysis/stats
still depend on the legacy adapter. Project persistence and scene application,
remaining ARR/AG features and specialist completion remain separate gates.

Rollback: revert this slice; original sources, databases and services were not
modified. No dependency or lockfile changes; existing Shapely is reused.
