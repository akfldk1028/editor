# Editor-owned additive computation

This unit consumes an immutable saved native job and computes additive mass candidates in Editor. It is the numerical closure preceding durable worker/API/UI execution. A computed result is not a legal approval, a complete MAAS portfolio, or a published 3D scene.

## Implemented ownership

`modules/design/optimization/` contains scalar continuous genomes, SSIEA with a per-execution Random instance, source ranking, the five-box additive builder, repair, metrics and a renderer sharing the evaluated geometry. `service.compute` pins effective options, emits numbered boundary events, supports cooperative cancellation and returns finite JSON. Missing engine options resolve to the actual source engine defaults (5×15), separately from the unchanged creation summary (7×30).

`modules/design/cli/execute_native.py` is a real consumer. It reads the scoped, checksummed native job, computes its frozen prepared specification without re-preparation, and writes a separate exclusive attempt directory. Result bytes are flushed before a manifest is atomically published last. A missing manifest means the attempt was not published. Existing attempt IDs cannot overwrite an earlier or interrupted attempt. Native jobs remain immutable and retain created/execution_supported=false; this CLI does not claim durable worker ownership.

Invocation:

```powershell
python -m backend.app.modules.design.cli.execute_native --storage-directory ABSOLUTE_STORAGE --actor local --project-id PROJECT --job-id JOB --seed 42 --output-root ABSOLUTE_RESULTS --attempt-id ATTEMPT --unverified-search
```

The explicit mode labels original default repair limits as search settings, never municipal evidence. The CLI currently supplies no envelope; the compute boundary supports validated explicit envelopes. Its seed is an unsigned 64-bit integer. Result serialization permits at most 32 MiB and two million JSON nodes; public job input keeps its existing one MiB/100000-node limit.

## Preserved and corrected behavior

- Safe source traces retain BLX/DE, Gaussian mutation, normalized/binary penalties, ring migration, migration ID gaps, initial population evaluation plus N evolution steps, history Pareto and objective ordering. Global random state is untouched.
- Valid geometry that violates an output constraint keeps finite measured outputs and its fitness penalty. Structurally rejected geometry has explicit rejection codes, no fabricated metrics and cannot enter Pareto results.
- Empty setback/envelope intersections fail instead of restoring the original footprint. Unsupported cap directions and invalid context fail before enumeration. Repairs are rechecked against search limits.
- Evaluator and renderer use the same footprint/floor count. A one-floor mass emits no phantom upper plate. Unsupported scaled upper topology is rejected. Polygon holes are preserved. Source largest-component reduction is recorded in repair actions.
- North setback clips even when the change is below the source's one-percent threshold; the prior threshold could leave a small violation. A failing regression demonstrated this correction.
- Source default limits remain explicitly labelled; daylight and landscaping are source mathematical proxies. This does not establish physical daylight, actual landscaping, or permit compliance.

## Evidence

337 focused backend tests passed, including 102 new computation/geometry/CLI tests and 235 existing native/design/archive/platform regressions. Source SSIEA/genome/ranking/penalty fixtures are committed with source hashes. Seven committed original geometry fixtures run without ARR; seven additional live-source comparisons passed locally. Geometry comparisons use output tolerance 1e-8 and footprint symmetric-difference area below 1e-14 in WGS84 coordinates.

Actual evidence is under `.superpowers/sdd/2026-10-05-additive-computation`. An isolated process audit denied file opens below the original ARR/AG/AG-frontend roots. The saved synthetic-site job `3a478d3f858043a9981732bb9d2f46dd` ran the default 120 generations, seven islands and 30 initial members per island: 1050 evaluated records, 480 Pareto records, 315 rejected records. Pareto records are not claimed to be distinct architectural alternatives. Two executions took approximately 3.59 and 4.60 seconds and produced byte-identical 1241683-byte result files with SHA256 `517c2fcd6617c69122850bc66e2b50edbf004563b9714f84d55b25ff458f360a`. Manifest hashes/readback and unchanged native DB bytes were verified.

The first default-budget execution exposed the inappropriate 100000-node input limit on result serialization. It failed without publishing a manifest; that attempt is preserved. The separate bounded result budget and actual-default regression fixed it. No original source, canonical archive, operating service or shared-agent state was changed.

Parallel implementers stopped due to tool-reported usage limits. Root completed the remaining regression fixes and reviewed the assembled code; a final independent whole-change review was unavailable. No frontend files changed in this unit, and no browser execution or 3D rendering is claimed.

## Next required unit

Implement durable attempts and persisted events/results around this same compute function, not another optimizer. Record queued intent, atomically claim with attempt ownership, persist event sequence and cancellation intent, and commit terminal state only with the verified result. A process lost without an optimizer checkpoint becomes interrupted; an explicit new attempt restarts from the pinned seed. Read/poll/SSE never starts work. Wire existing project routes/UI to create/run/progress/cancel/restart and inspect actual saved geometry, with project/scene guards and source-root-denied HTTP verification.

Remaining algorithms, all-mode, MAAS/LLM/VLM/parking, agent task operations and full DWG/PLANM/3D scene publication/reopen remain separate obligations. ARR/AG removal and overall completion remain unproven.
