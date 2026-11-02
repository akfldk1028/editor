# Static terrain delivery

`bake-terrain-archive.py` materializes the installed NGII raster into immutable heightmap PMTiles. The browser reads byte ranges; it does not calculate 33×33 grids through the terrain API when an archive covers the requested tile. Building terrain-refresh code is unchanged.

The archive contains custom opaque tiles, **not Web Mercator terrain RGB**. Geographic Cesium level L is stored at PMTiles zoom L+1, with the same x/y indices. A gzip tile decodes to `HTM1`, uint16 little-endian width 33, uint16 reserved flags, and 1089 little-endian Float32 samples in north-to-south row order. NaN is NoData; zero is a valid height.

## Build and publish

Requires Python with rasterio, numpy and pmtiles 3.7.0. Run from the editor app directory:

```powershell
C:/Python313/python.exe tools/bake-terrain-archive.py --dem D:/Data/NGII_DEM/ngii_dem.vrt --work C:/Data/25_ACE/terrain-archive-national --output public/world-terrain --detail-points C:/Data/25_ACE/terrain-archive-national/detail-points.json --detail-max-level 20 --workers 2
```

Default coverage is 124.6–132°E, 33.1–38.65°N, levels 11–15. This is the geographic processing extent, **not a claim that every cell has source measurements**. Levels 16–20 cover small neighbourhoods of the supplied detail points. The extra levels reduce resampling error around narrow peaks and source boundaries; they do not improve the original survey resolution. Empty tiles are omitted and partial NoData is retained.

Work is checkpointed into SQLite; re-running the identical arguments resumes completed jobs. `progress.json` tracks the process and completed jobs for that invocation. Completion produces `archive-receipt.json` and a content-addressed PMTiles file. The builder preserves a VRT snapshot and rejects source-file changes during a run. Keep a single builder per work directory. It reserves 15 GB on the destination drive.

Publication is a separate final step: verify the receipt and archive before atomically copying its URL/hash fields into `public/world-terrain/archive.json`. `--publish` enables publication directly after the builder's source-integrity checks. Never publish a partly written archive.

```powershell
C:/Python313/python.exe tools/verify-terrain-archive.py --work C:/Data/25_ACE/terrain-archive-national --dem D:/Data/NGII_DEM/archive-snapshot-9e3532bb1bc98a30.vrt --points C:/Data/25_ACE/terrain-archive-national/detail-points.json --level 20
```

The verifier compares display-grid interpolation against the original projected DEM sampler. It does not measure survey accuracy. Valid bilinear contributors are renormalized at NoData edges; a completely unsupported point is rejected. Rendering-only fallback heights are never returned as measured terrain.

## R2 deployment

Upload the content-addressed archive and set `NEXT_PUBLIC_TERRAIN_ARCHIVE_URL` to its HTTPS URL at frontend build time. Alternatively replace `archive.json` with the remote URL and matching `vrt_sha256`; the binary and provider code need no change. Local files are served through `/api/map-data/world-terrain/...` with 206 range responses, ETag, Content-Range and immutable caching.

R2 must permit GET/HEAD and browser Range requests, expose Content-Range, Content-Length, ETag and Accept-Ranges, and allow the application origin. Preserve the archive bytes; do not apply whole-file content encoding. Raw NGII originals are separate archival data and are not needed by the static tile server.

## Measurements

`benchmark-terrain-browser.js` runs in the connected Playwright browser with an existing 684-1 `/dwg` tab. It opens a temporary tab, disables the HTTP and terrain CacheStorage caches, observes long tasks, and records the first rendered focus terrain at level 12 or higher. Viewer-relative timing and navigation-relative timing are reported separately. The first 20 seconds after viewer construction form the long-task window. Do not run a CPU/IO-intensive national bake concurrently with a comparison benchmark. Save raw results and include all comparable repetitions instead of selecting the fastest run.

The local development server may compile routes on first access. A manifest timeout is retryable and must not permanently switch the viewer to computation APIs. Missing configuration (404) retains the older delivery path; a configured archive's missing source coverage uses display fallback without fetching missing NGII data during interaction.
