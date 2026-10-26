# Offline landcover candidate

`bake_landcover_archive.py` collects only the official `EGIS:lv3_2025y`
WMS at `https://api.mcee.go.kr/geoserver/wms`. The seven diagram colors match
the detailed cover renderer. Built classes, text, strokes and building footprint
layers are excluded by an inline SLD. This is coarse surface appearance, never
elevation, parcel evidence or a claim of 1 m imagery resolution at every zoom.

Create a versioned plan (no tile requests):

```powershell
C:/Python313/python.exe -X utf8 infra/data/bake_landcover_archive.py plan --work-root C:/Data/25_ACE/management/landcover-candidates
```

Use the reported immutable version directory for subsequent commands:

```powershell
C:/Python313/python.exe -X utf8 infra/data/bake_landcover_archive.py fetch --work VERSION_DIRECTORY --limit 10 --sample-point 127.1084379 37.7300025
# After the full-country run is separately authorized, omit --limit/--sample-point.
C:/Python313/python.exe -X utf8 infra/data/bake_landcover_archive.py pack --work VERSION_DIRECTORY
```

Only z12 tiles are requested from WMS. World-sized low-zoom WMS renders timed out
and are forbidden. Zooms 0..11 are derived bottom-up from four child tiles using
RGBA premultiplied-alpha BOX filtering. Children outside the exact provider
coverage are transparent; a missing/failed child within coverage blocks its
parent. Derived receipts bind all four child keys, hashes and outside-coverage
status. Source, derived algorithm and Pillow version are distinct manifest pins.
Valid alpha-zero PNGs count as successful transparent tiles, never download
failure or inferred missing evidence.

Every PNG is retained with a SHA256 receipt; resume rechecks bytes and exact
source/style/builder pins. One writer lock protects each version. Default one
worker, at most two; globally spaced requests (default 1 second, minimum .5),
25-second HTTP timeout, three attempts, bounded Retry-After/backoff. A partial
batch reports `complete:false`. Packing requires every intersecting XYZ tile at
z0..12 within the provider's exact advertised bounds, then rereads every packed
tile and compares its SHA. All-transparent tiles are retained. No live pointer is
written. Disk checks retain 20 GiB plus margin; PMTiles temporary spool stays on
the checked candidate volume. Only the temporary spool is automatically closed.

Source checks compare capabilities layer metadata before/after,
every five minutes, and repeat a previously received tile as a sentinel. WMS
does not provide a transactionally frozen dataset; undetectable changes outside
the sentinel are not ruled out. Source changes stop the candidate. Sentinels also
use z12 only; no ancestor ever invokes the WMS API.
The global capabilities updateSequence is not the layer revision: two requests
returned 5462 and 5444 while this layer's XML was identical. It is excluded from
the layer pin to avoid treating unrelated catalog/replica changes as source edits.

Official evidence inspected 2026-10-26:

- https://egis.mcee.go.kr/api/land.do lists the 2025 nationwide layer and recommends
  the provider's GeoWebCache for display performance. It does not explicitly
  license an independently redistributed offline archive.
- https://egis.mcee.go.kr/intro/land.do describes the 2025 product based on 2024
  imagery, 41 classes, nominal 1 m source level and 1:5,000 sheets.
- https://egis.mcee.go.kr/bbs/copyright.do allows attribution-based free reuse for
  KOGL type-1-marked works, and requires consultation for unmarked works. A
  layer-specific KOGL marker was not found in the inspected API/intro/capabilities.

An archive receipt therefore records that redistribution authorization is not
established by the receipt. Full collection and public deployment remain the
parent task's decision; this tool itself never publishes.
