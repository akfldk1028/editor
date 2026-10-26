# NGII canonical building interface

`NgiiBuildingAdapter` accepts explicitly verified continuous B020 or B021 `N3A_B0010000` geometry in EPSG:5179. The actual product code remains in provenance and identity; B021 is never relabeled B020. Manifests require matching `family`/`productCode`, `productKind=continuous-topographic`, and `productReceiptSHA256`; individual map sheets are rejected. It neither reads GIS building geometry nor publishes a catalog. Nationwide production remains gated on the official complete B001 source receipt and schema validation; regional data is sufficient only for testing this adapter.

The four-feature `ngii-b021-jeju.fixture.json` comes from the officially received 2024 Jeju B021 building ZIP (SHA256 `612b61887b6bd6dad40babc9db8d82718d9eb7fcdb00a16a3fa9de2f9efa3e95`). Its actual PRJ resolves to EPSG:5179 and its schema has NMLY, but no metric height field. The fixture contains no download/session URLs.

Feed `stream()` a lazy iterator of `(source row number, properties, native Shapely geometry)`. Retain every yielded rejection in the ingest receipt. A rejection is not permission to call source coverage complete. The adapter keeps all positive-area polygons, including sub-2m² shapes, all parts and interior rings, and records geometry repair.

Each successful JSON-safe output contains:

- `canonicalBuildingId`: SHA256 of family, original UFID, normalized full native geometry. Ring winding/start and multipart order do not change it. Different geometries under one UFID stay separate.
- `sourceUFID`, `geomWGS84`, `anchorWGS84`: full shape plus an interior point. Assign one owner partition from the anchor; do not clip or replicate the building into all intersected partitions. Expand tile bounds to contain its full shape.
- `h`, `heightSource`: explicit metric-field contract if supplied, otherwise positive NMLY × declared floor height, otherwise declared default. Both defaults are 3.4m. NMLY is a source floor attribute, not claimed to be registry-derived.
- `geometryAudit`, `provenance`: geometry hash, area/parts/repair, source family/layer/edition/manifest SHA/file/row. Pin the complete height policy alongside the source receipt in each build recipe.

Deduplicate only matching canonical IDs with compatible height decisions; retain all source-row provenance. Different heights for the same ID must produce an explicit conflict for reconciliation, not two overlapping output meshes or silently selected heights. Never deduplicate by parcel number alone. One snapshot is selected before ingestion; do not merge different editions automatically.

The parent terrain stage supplies ground from its pinned prebuilt terrain archive and adds ground provenance. The parent HLOD stage consumes this canonical stream, emits the common material/LOD hierarchy, and verifies input/output identity coverage before switching runtime rendering.
