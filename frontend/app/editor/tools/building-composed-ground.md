# Candidate composed ground reconciliation

`bake-world-buildings.ts` retains its default ground policy. The explicit
`WORLD_COMPOSED_DEM_PATH` mode instead samples the already ordered, cell-composed
VRT once at each footprint's first ring coordinate. A finite sample replaces
unverified inherited building elevation. It does not sample the precision VRT
separately, which would produce a different interpolation at mosaic boundaries.

This mode requires `WORLD_BUILDINGS_REGIONS_FILE`, an isolated
`WORLD_BUILDINGS_ASSET_OUTPUT`, and `WORLD_GROUND_FALLBACK_FILE`. The fallback JSON
pins an archive SHA256, the `resolved-ancestor-grid-v1` contract, and explicit
key/coordinate/height/source-level records. Only native NoData at the identical
anchor may use that evidence. Ellipsoid-zero or unsupported records fail.
Other unsupported features remain unsupported; old finite z is not evidence.

Use a separate candidate catalog/output root. The mode preserves mesh revision,
source polygons, holes, heights and statuses, and retains previously published
keys before reconciliation. Publication still rejects lost published keys or
coverage. Resume requires the composed policy and exact source/fallback revision.
The candidate mode enforces 20GiB free storage.

Before release, verify all selected anchors against both the composed source and
the actual displayed terrain contract, including explicit ancestor provenance
for native NoData. The default legacy browser reader is not equivalent to the
resolved contract at NoData boundaries. A passing offline contract comparison
alone does not prove that an unwired legacy viewer uses the same values.
