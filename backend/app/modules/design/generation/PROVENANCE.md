The generation runtime preserves the original design engine, services and MAAS
implementation in Editor-owned Python namespaces. The original source checkout
is an import-time input only. Runtime imports never add it to `sys.path`, and
the imported code does not require the original design HTTP server.

`source-manifest.json` records every source filename, original SHA-256, imported
SHA-256, destination and namespace/path transformation. Its imported hashes are
the reproducible import baseline, not a claim that later integration edits are
byte-identical to that baseline. Editor's API views and storage models and
persistence have intentional post-import lifecycle and scene-ownership changes.
The Graph2Plan service additionally routes model inference through an isolated
worker and preserves the empty-edge tensor shape for one-room plans.
Land reference law search and MAAS law evidence route through Editor's bounded
law-search adapter. `LAW_BACKEND_URL` and `AG_LIGHT_URL` must be configured
explicitly; missing settings return unavailable evidence without network calls.
Display filtering, unfiltered extraction citations and structured LLM extraction
retain their respective contracts.
Their baseline hashes remain unchanged so reviewers can distinguish import
transformations from integration edits. Bootstrap, lifecycle, HTTP routing and
the `paths.py` ownership helper are authored integration code.

The importer at `backend/scripts/import_design_runtime.py` refuses to overwrite
any tracked destination whose bytes differ from its imported baseline. It also
refuses untracked collisions. Use `--output-dir` to produce a separate review
tree; the tool has no force-overwrite option. `--only` restricts source Python
files, while required static reference assets remain included and protected.

All runtime design Python modules are retained except development-only tests,
management commands, scripts, research experiments and archived reference
implementations. The external dependency closure consists of selected land
services and regulation data, the parking-rule helper and the Neo4j adapter.
The manifest also records the 56 original MassAgent word dictionaries and four
authored BOOK reference documents. These are packaged under the language owner;
the catalog verifies all 134 entries and all four source documents.

`EDITOR_DESIGN_DATA_DIR` selects mutable design data (default `runtime/editor/design`
inside Editor). Runtime artifacts use its `runtime` directory; no new ARR or AG
directory is created. Historical ARR names in schemas, evidence and provenance
remain intact because consumers rely on those contracts.

Graph2Plan's original model source and weights are installed locally with:

```text
python -m backend.app.modules.design.generation.services.graph2plan_runtime --install <Graph2Plan/Interface>
```

The exact seven-file inference closure is copied into the already ignored
`runtime/editor/design/reference-models/graph2plan` directory. An installation
manifest records original file sizes and SHA-256 values; existing modified
model files are protected. `EDITOR_GRAPH2PLAN_MODEL_DIR` overrides this location.
The worker requires Torch, torchvision, NumPy and OpenCV. Its `PYTHONPATH` is
scoped to the child process; the HTTP server neither changes `sys.path` nor
registers a top-level `model` alias. Missing dependencies produce the existing
error/zero-results contract. The original weight file is 30,613,537 bytes with
SHA-256 `08046c64b993d1c3382f5dbb37755095c372fff540f5c7502262b1abf7584140`.
Neither its source files nor its weights are added to Git. MAAS and D4Descent
reference packages remain optional installed integrations. Private configuration,
databases, caches and generated project evidence were not copied by the source
import.

Verification includes compilation of the 536 imported Python modules, original
migrations against an in-memory database, successful import of all 48 original
URL patterns, completion of all ten mass algorithms with small budgets, and
HTTP geometry tests for all five floor-plan algorithms, explicit Graph2Plan
unavailability, interactive preview and floor-stack trimming. Real Graph2Plan
inference is exercised for both a one-room graph and an adjacent two-room graph,
including assertions that the server's import path and module names are unchanged.
The HTTP tests use
an isolated temporary database and do not restart or modify a running service.

Parking selector integration computes immutable GEOS overlap and centroid-distance
rows with Shapely vector operations and uses per-seed candidate bitsets, without
pruning seeds/candidates or changing score/tie order. Broad-phase intersections
still use the original exact intersection-area threshold of 1e-6; duplicate
dictionary membership and partial-layout results retain original semantics.
`test_design_parking_cache.py` compares exact selected candidate identities with
the preserved pre-cache selector in `tests/fixtures/parking_selector_before_cache.py`,
including unmet requests, accessible stalls, duplicate dictionaries, tiny-area
stalls and subsets spanning the captured 452-candidate synthetic capacity-anchor
fixture. A representative case reduced scalar overlap calls from 6,969 to 42
and measured 0.315s to 0.075s locally. Capacity-anchor parking completed in
40.4s after previously exceeding 232s; each of its three 452-candidate selectors
completed in about 13s. The real 1,600 m² WGS84 office MAAS integration completed
in 31.72s in the final combined run (49.35s in the initial run), returning two
variants with two review-pool parking passes and one architecture-order pass.
It uses supplied BCR 60/FAR 200/height 30/setback 0.5, max_variants=2 and
the explicit grammar_overlap_shift_terrace operator preference. It asserts
nonempty output, both ordinary parking/architecture gate passes, valid geometry
and bounded design metrics with outbound sockets blocked. These synthetic caps
are test parameters, not verified parcel regulations. It is a default test with
a 90s subprocess limit allowing machine-load variance; the measured duration is
not a runtime guarantee. All ten original mass algorithms are also tested through
HTTP. No parking or architecture acceptance gate was relaxed.
Final combined verification: 11 tests passed in 47.20s. The explicit operator
preference exercises the original targeted-variant path; this result does not
establish feasibility of an unrestricted 18-variant diversity request or certify
every returned variant's legal/design acceptance.
