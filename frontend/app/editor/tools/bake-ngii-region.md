# NGII canonical candidate mesh batches

This command writes candidate folders only. It does not update a served catalog or release.

Run from `frontend/app/editor`, with explicit pinned paths:

```powershell
bun ./tools/bake-ngii-region.ts --database <completed-buildings.sqlite> --regions <completed-regions.json> --source-plan <plan.json> --source-plan-sha256 <raw-plan-file-sha256> --terrain <terrain.pmtiles> --terrain-sha256 <archive-sha256> --output <new-candidate-root>
```

`--snapshot <completed-canonical-snapshot.json>` accepts the immutable base-plus-delta dataset instead of `--database`. The source gate verifies the completed snapshot before terrain access.

`--snapshot <completed-canonical-snapshot.json>` accepts the immutable base-plus-delta dataset instead of `--database`. The source gate verifies the completed snapshot before terrain access.

`--region 14/x/y` selects one inventoried region; `--limit N` bounds the sorted region list. The existing `--input <sample.ndjson>` mode remains available instead of `--database` and `--regions`. Sample receipts always retain `completeRegion:false`.

Database mode rejects incomplete sources, unresolved source issues, source-plan mismatches and inconsistent region inventories before opening or hashing terrain. One SQLite read transaction streams the selected regions. Each region is streamed once for its input digest/count checks and again for mesh generation; no nationwide NDJSON is created. Only one region's mesh inputs are retained at a time.

The terrain archive is hashed and opened once per invocation. All regions share its height-contract cache. The source plan and terrain file identity are checked during processing. `candidate-inputs.json` pins source-plan file SHA, terrain SHA, inventory SHA and mesh/terrain contract revisions for the output root. Use a new output root when changing these identities.

Existing immutable region folders resume only after receipt identity, expected building/component counts and every listed payload's byte count/SHA are verified. Incomplete work stays under `.staging/<region-id>`, bound to the same source identity. Completed staging files are reused only after size/SHA verification; interrupted `.part` files can be recreated. A full verified receipt precedes the atomic move to the final immutable region folder. Final folders and mismatched staging payloads are never overwritten. The free-space guard reserves 20 GiB before payload writes.

`completeRegion:true` proves complete canonical source coverage for that region, not full terrain support or publication readiness. `supportedGroundBuildings` and `unresolvedGroundBuildings` remain separate. Final national quality, speed and publication validation are still required.

New candidates use `gzip6-mesh-and-metadata-v1`: byte-identical LOD meshes share one `.b3dm.gz` payload, while `footprints.json.gz` and `ground-source.json.gz` retain offline source evidence. Receipts verify both stored and decoded bytes/SHA. Root tilesets and receipts remain plain JSON. These are new versioned candidates; existing v3 outputs are unchanged. Service-ready output must be below `DATA_ROOT/world-buildings/`.

New candidates use `gzip6-mesh-and-metadata-v1`: byte-identical LOD meshes share one `.b3dm.gz` payload, while `footprints.json.gz` and `ground-source.json.gz` retain offline source evidence. Receipts verify both stored and decoded bytes/SHA. Root tilesets and receipts remain plain JSON. Existing v3 outputs are unchanged. Service-ready output must be below `DATA_ROOT/world-buildings/`.
