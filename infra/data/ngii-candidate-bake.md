# NGII regional mesh candidate

`frontend/app/editor/tools/bake-ngii-region.ts` bridges the canonical NGII B001 stream to the existing `footprint-holes-obb-v3` mesh generator. It creates a separate immutable candidate directory and never writes the served building catalog or release pointer.

Export one z14 owner region with `ingest_ngii_buildings.py export-region`. Pass the NDJSON file, its pinned canonical source plan, and a prebuilt terrain archive with its full SHA256:

```powershell
bun tools/bake-ngii-region.ts --input <region.ndjson> --source-plan <plan.json> --terrain <terrain.pmtiles> --terrain-sha256 <sha256> --output <DATA_ROOT>/ngii-mesh-candidates
```

The command verifies the archive hash, source-plan membership, immutable input bytes, terrain metadata and source provenance. It preserves all polygon components and interior rings. Every building gets one ground decision at its canonical interior anchor through `resolved-ancestor-grid-v1`; its components retain distinct stable keys. Confirmed terrain NoData stays visible at the contract's explicit ellipsoid fallback and is counted as unresolved, never as recovered ground. Read failures abort the candidate.

Output includes z14/z15/z16 B3DM, the regional tileset, footprint metadata, ground provenance and a file-size/SHA256 receipt. The 20GB free-space reserve applies throughout writes. Existing candidates are not overwritten. `completeRegion` remains false: source-region completeness and national coverage must be independently proven from the completed canonical ingest before publication. A sample produced with the currently served terrain is an integration check, not authorization to switch the renderer to the new terrain contract.

The first real Seoul sample preserved 100 buildings and verified eight output files. Its evidence is `DATA_ROOT/management/continuous-ground-audit/ngii-mesh-sample-proof.json`.
