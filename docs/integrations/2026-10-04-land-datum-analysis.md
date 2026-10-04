# Editor ground datum integration

Editor owns the land analysis path with optional ground datum enabled. The API no longer delegates analysis to ARR. Historical statistics still use the legacy adapter; the complete ARR/selected AG migration remains unfinished.

## Responsibilities and behavior

`adapters/elevation.py` handles Open-Meteo, configured OpenTopoData datasets and optional local GeoTIFF sampling. `modules/land/datum` owns the preserved parcel, road, neighbor and three-meter profile calculations plus context selection. API composition reads server configuration and creates a provider per request. Analysis performs blocking geometry and elevation work in its existing worker thread, then persists the result through the Editor repository.

`ENABLE_DATUM_ELEVATION` defaults to false. `.env.example` lists the provider and sampling settings. Local GeoTIFF support is an optional `terrain` dependency. No original deployment, database or shared agent is moved by this increment.

Successful source calculations retain the original thresholds, sampling, median filter, weighted datum, neighbor average and road half-raise. Three-meter bands remain profile metadata, not completed contour polygon clipping. Datum metadata does not change relative sunlight wall/slanted geometry.

Missing or invalid elevation never becomes a fabricated zero. Mandatory failure yields null absolute elevation and an explicit failed source while reference geometry remains available. Optional road/neighbor failures retain valid parcel results with notes. Invalid or excessive datum geometry is reported explicitly without discarding the relative envelope.

Provider provenance distinguishes configured and actual sources, including mixed fallback. The request-scoped cache includes source identity; local dataset identity includes path, modification time and size. Remote requests retain five-decimal sampling, but local DEM sampling preserves full coordinate precision at pixel boundaries. Local DEM errors never silently switch providers. OpenTopoData fallback is limited to missing/failed samples, and double failure remains a failure.

## Verification scope

- 415 targeted backend tests and 41 subtests passed; one existing Starlette/httpx deprecation warning.
- Six original successful datum fixtures match exactly, excluding newly added provenance metadata. Actual GeoTIFF tests pass without skips.
- Three Chrome tests passed, including real isolated Editor HTTP18441 with provider transports and saved SQLite results for both success and failure. Markup-like notes remain text.
- Frontend production build and two module-boundary checks passed. Independent review confirmed fixes for zero-length roads, excessive sampling, non-advancing band generation and lost provenance.
- The verification server was stopped. Operational services and original data remain unchanged.

Backend evidence: `.superpowers/sdd/2026-10-04-datum-analysis/backend.xml`.

Source fixtures cover flat ground, small/large slopes, road half-raise, neighbor average and metadata-only road use. Integration checks preserve relative envelope coordinates/heights and null failed elevations. Real GeoTIFF fixtures exercise CRS, nodata, bounds, file replacement and submeter coordinate precision in the isolated test environment.

Live terrain-provider accuracy, survey validity, regulatory currency and rendered 3D parity are not established by these fixtures. Historical record import, design/jobs/artifacts, remaining AG workflows and operational cutover remain separate integration gates.
