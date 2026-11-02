# Preparing regional and national 3D coverage

Run from `frontend/app/editor`. The runtime selects regions from the catalog by camera bounds; it has no Gosan-only coordinate condition. Unbaked regions continue using the national PMTiles archive. A national footprint archive is not evidence of complete elevation or road coverage.

## Buildings

```powershell
$env:WORLD_BUILDINGS_SOURCE = 'https://YOUR-TILE-HOST/version/buildings.pmtiles'
$env:WORLD_BUILDINGS_OUTPUT = 'public/world-buildings'
bun tools/bake-world-buildings.ts --bounds 126.76 37.42 127.18 37.70 --resume
```

Use the existing catalog's `source` when extending a snapshot. For production, publish the archive at a reachable HTTPS URL with Range requests and appropriate CORS, then generate a separate output snapshot against that URL. A localhost archive URL only works on this development machine. Serve `world-buildings/` at the same origin as the application (or reverse proxy it to object storage). Do not deploy the development catalog unchanged to remote users.

Split national bounds into regional jobs. Run one writer per output catalog; concurrent writers are not supported. Each completed region atomically updates the catalog, and `--resume` skips completely published regions but retries partial ones. A different source snapshot requires another output directory. `last-bake-report.json` lists regions with missing ground datums; exit code 2 means incomplete coverage. Complete z16 leaves are published even when a neighbour lacks data. The runtime uses explicit leaf coverage to preserve unbaked neighbours. No zero-height substitution is performed.

Set `WORLD_DEM_PATH=D:/Data/NGII_DEM/ngii_dem.vrt` to enrich missing building datums from the installed local raster before baking. `WORLD_PYTHON` optionally selects Python with rasterio and pyproj. The sampler preserves existing archive datums, returns null for NoData and writes raster provenance beside generated geometry. It uses the footprint's first coordinate, matching the current runtime datum lookup. Raster-derived elevations are not a new survey and must retain their source accuracy limitations.

After a DEM snapshot is finalized, use `--resume --refresh-ground` with `WORLD_DEM_PATH` pointing to that stable snapshot to refresh previously derived building datums. The publisher records `groundPolicy`, `groundRevision` and a `groundSource` receipt URL per region. It skips archive-only regions and same-revision complete regions; legacy unversioned regions are inspected once. Existing finite archive datums and building height/status are preserved, because the archive does not identify their derivation. Only datums previously added to missing archive values are recomputed, in batches of at most 1,024 buildings. This does not repair stale finite datums already embedded in the archive; that requires an upstream provenance-aware archive rebuild.

The sampler checks referenced raster size/mtime identities before and after each batch; the publisher rechecks before changing the catalog. Source mutation aborts publication. A refresh with reduced valid coverage retains the previous region rather than removing its buildings. Do not run this refresh against the evolving national VRT or schedule it for every DEM update. Choose a finalized snapshot, keep its referenced rasters stable, and refresh explicitly. No refresh job is launched by the viewer.

The coarse and detailed meshes retain every decoded z16 footprint. Counts are footprint records, not deduplicated national building counts. Completeness also depends on what the upstream PMTiles generation retained.

## Terrain

```powershell
$env:WORLD_API_ORIGIN = 'http://127.0.0.1:3003'
bun tools/bake-world-terrain.ts 126.977 37.565 126.980 37.568 17 17 measured-20261023
```

Arguments: west, south, east, north, minimum level, maximum level, immutable snapshot version. The reader uses Cesium geographic tiles, distinct from the building archive's Web Mercator grid. It tries memory/disk cache, then published measured grids, then the existing computation API. Missing/corrupt grids never become measured zero elevations. Generation reuses validated files and reports missing grids. Use a separate output directory (`WORLD_TERRAIN_OUTPUT`) for another snapshot version.

Generate dense level 17 grids around served destinations first; generating every level 17 tile across Korea is a very large offline job. The current flat catalog is suitable for regional publication; national high-resolution terrain needs a hierarchical availability index or a standard terrain tile service before publishing millions of grids.

For bulk publication from the installed local DEM, use SiteContext's exact bilinear sampler without HTTP:

```powershell
python -X utf8 tools/bake-world-terrain-local.py --bounds 126.76 37.42 127.18 37.79 --levels 11 17 --dem D:/Data/NGII_DEM/ngii_dem-display-20261023.vrt --site-root D:/Data/25_ACE/agents/SiteContextAgent --version prepared-20261023
```

The display VRT is a frozen copy beside the original so relative source paths still resolve. The local publisher pins its VRT hash and referenced-file receipts in the version directory's `local-source.json`. A changed source requires a new version/output directory. It excludes incomplete grids and checkpoints every100 tiles. `local-bake-progress.json` reports running counts; `local-bake-report.json` records final missing keys. Existing HTTP tiles without receipts are explicitly legacy rather than attributed to the current raster.

The runtime refreshes its catalog every60 seconds. During a snapshot transition, an optional `fallback: {version, tiles}` preserves the previous version's coverage; primary tiles win where both exist. Keep both directories while that fallback is referenced. The `prepared-20261023` run finished with109,692 published grids and1,138 NoData gaps across110,830 candidates at levels11–17. A recheck against the newer live mosaic recovered none of those gaps; they remain excluded.

Use `--display-ttl-hours 24` to explicitly activate a stable display snapshot. Its catalog policy pins the VRT hash, sampling method and absolute expiry; each tile must match the version's manifest and policy. This lets an audited regional snapshot survive unrelated national mosaic expansion. It does not relabel old data as current live analysis. Snapshot heights are not written into the live-revision browser cache, and the map displays a snapshot notice. Without this policy, tiles must match the live VRT; absent/expired coverage falls back to the live API. The active regional snapshot has a24-hour policy. SiteContext bilinear and backend nearest-cell samplers are distinct methods.

## Roads, parcels and land cover

```powershell
$env:WORLD_API_ORIGIN = 'http://127.0.0.1:18449'
bun tools/bake-world-ground.ts 127.095 37.722 127.151 37.750
```

Arguments are west, south, east, north. The exporter prepares the same320 m context cells used by the viewer. Successful responses are published; narrowly recognized installed-road coverage gaps may preserve available parcels/cover only when both layer receipts are valid. Gaps remain in the payload and map status. Transport failures and other source gaps are not published. Content-addressed files and the catalog are published atomically; use one writer per output catalog. Re-running verifies hashes before reusing fresh files. Legacy snapshots refresh just their roads from the installed backend source, preserving the original ground expiry; unavailable roads trigger a fresh full read. `WORLD_GROUND_OUTPUT` selects another output directory; the default is `public/world-ground`.

The broader active job uses `126.76 37.42 127.18 37.79` (7,905 cells). `bake-progress.json` records progress. Temporary connection failures,429 and5xx retry the same cell with backoff; sustained unavailability halts dispatch instead of consuming the entire remaining queue. Re-run the same command to resume verified published cells. `last-bake-report.json` distinguishes failed and unvisited cells.

The viewer shares one prepared response between road preview and full ground detail. Snapshots expire after 24 hours, including in memory and browser caches. Missing, expired or invalid snapshots fall back to live context requests. Schedule regeneration for a running service; these display snapshots do not replace fresh analytical evidence. Serve the directory at the application origin.

## Verified coverage on 2026-10-23

- Building catalog expanded from 48 to 390 z14 regions, including Seoul and the existing Gosan area. 1,104,304 footprint records across these regions.
- In the Seoul expansion bounds above, tile `14/13960/6337` was refused: 61 of 3,632 footprint records lack ground datum.
- Point-region checks: Busan `14/14066/6479`: 3,928/10,611 missing; Daejeon `14/13989/6414`: 6,387/6,387; Daegu `14/14044/6440`: 8,096/8,096; Gwangju `14/13965/6480`: 3,221/3,221; Jeju `14/13950/6572`: 9,013/9,013. These are sampled tiles, not city-wide completeness estimates.
- Local `D:/Data/NGII_DEM/ngii_dem.vrt` center samples: Seoul 29.487 m, Busan 15 m; Daejeon, Daegu, Gwangju, Jeju returned NoData. Existing raw contour archives require their own inventory and regional DEM preparation; do not infer national completeness from archive names.
- Published terrain: 18 level 17 grids near Gosan and Seoul City Hall. This is not national terrain coverage.
- Published ground: 96 cells within the Gosan-area bounds above, zero export failures, and all 96 hashes verified on a second run. This is regional road/parcel/land-cover preparation, not national road coverage.

National release remains dependent on filling and auditing ground elevations, road data, source coverage, deployment URLs and cold-browser performance. These changes are regional preparation infrastructure, not certification that nationwide service is ready.
