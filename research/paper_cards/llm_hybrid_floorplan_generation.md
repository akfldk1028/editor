# LLM Hybrid Floorplan Generation

## Decision

OpenAI supplies structured floor-use assignments only. Deterministic profiles,
geometry, and validators own room creation and acceptance. PLAN uses the LLM
as a constrained program planner, not as the geometry authority. The model
proposes strict JSON floor assignments and, later, program graphs.
Deterministic geometry code produces polygons, and the exact validator rejects
boundary, overlap, area, circulation, and room-form failures.

This division keeps natural-language and use-mix reasoning flexible while
making geometric acceptance reproducible.

## Public Paper-Code Evidence

### Graph2Plan

Graph2Plan conditions a learned raster/box generator on both a layout graph and
the building boundary. Its public implementation also documents geometric
post-processing because predicted room boxes can remain misaligned or overlap.

- Paper: https://arxiv.org/abs/2004.13204
- Code: https://github.com/HanHan55/Graph2plan
- PLAN adoption: explicit program graph plus boundary-conditioned geometry
  contract and independent post-generation validation.
- Not adopted yet: RPLAN retrieval/training and learned raster-to-box geometry.

### HouseDiffusion

HouseDiffusion directly generates vector room and door loops. Its discrete and
continuous denoising objectives target both corner coordinates and geometric
incidence such as parallelism, orthogonality, and shared corners.

- Paper: https://arxiv.org/abs/2211.13287
- Project: https://aminshabani.github.io/housediffusion/
- PLAN adoption: vector-first room/opening contracts and explicit incidence
  validation rather than accepting an image as geometry.
- Not adopted yet: learned graph-conditioned diffusion geometry.

### LayoutGPT

LayoutGPT uses an LLM as a visual planner that converts text and spatial
constraints into a structured layout consumed by a downstream generator.

- Paper: https://arxiv.org/abs/2305.15393
- PLAN adoption: the hosted LLM is a high-level program planner behind a strict
  structured contract, not the final geometric authority.

### ChatHouseDiffusion

The public implementation converts a language prompt into structured JSON and
then conditions a Graphormer/diffusion floorplan generator. Its configuration
supports OpenAI-compatible endpoints, including hosted models and local Ollama.

- Paper/code: https://github.com/ChatHouseDiffusion/chathousediffusion
- PLAN adoption: strict prompt-to-JSON boundary before geometry generation.
- Not adopted yet: learned diffusion geometry and its residential training
  pipeline.

### Floor-plan RLVR

The public implementation trains structured JSON-to-JSON generation with SFT
and then reinforcement learning from verifiable rewards. The 2026 paper and
code use executable rewards for valid JSON, non-overlapping room polygons,
connectivity agreement, and total-area agreement.

- Paper: https://arxiv.org/abs/2605.14117
- Paper/code: https://github.com/ludolara/floor-plan-rlvr
- PLAN adoption: exact machine checks remain authoritative after LLM output.
- Future experiment: use PLAN validation codes as verifiable reward signals.

### MANSION

MANSION targets multi-floor indoor scene generation and explicitly models
vertical structures across floors. It covers non-residential categories such
as offices, hospitals, schools, and supermarkets.

- Paper: https://arxiv.org/abs/2603.11554
- Project: https://agibotgeneral.github.io/mansion-site/
- PLAN adoption: one building-level pass, complete floor assignment, and one
  shared core polygon across every generated floor.
- Not adopted yet: learned multi-floor scene generation and detailed objects.

## Current Runtime

The OpenAI Responses API adapter requests a strict JSON Schema. The application
then independently verifies project identity, supported use types, and exact
coverage of floors `1..N` before calling deterministic building generation.
There is no silent fallback when the model or contract fails.

```powershell
python -m backend.app.cli building-review `
  --input datasets/manifests/sample_mass_office_commercial.json `
  --output-dir logs/runs/sample_building_review_llm `
  --planner openai
```

Set `PLAN_LLM_MODEL` or pass `--llm-model` to override the default model.
`OPENAI_API_KEY` is read by the official OpenAI Python SDK.

## Generator Adapter Status

PLAN now has a request-bound generator adapter contract. Requests and responses
carry a canonical SHA-256 digest, immutable program and geometry records,
backend provenance, and explicit `executed`, `failed`, or `unavailable`
status. An `executed` response must include a normalized candidate that can be
reconstructed and run through the same concept-basic validator.

Current execution status:

| Backend | Status | Current evidence |
|---|---|---|
| deterministic | executed | Exact program contract, normalized concept-basic geometry, and revalidation are tested |
| Graph2Plan | partial: raw forward executed | The official repository checkpoint and RPLAN retrieval record execute in a bounded CPU worker. The run retains exact consumed tensors, derived raster/box outputs, preview PNG, repository revision/remote/source hash, checkpoint and dataset hashes, and overlap observations. MATLAB `align`/`decorate`, PLAN normalization, and PLAN validation have not run, so no candidate is emitted |
| HouseDiffusion | unavailable | The local checkpoint strictly loads on CPU with 186/186 state keys and 26,541,330 parameters. No usable RPLAN JSON or processed NPZ dataset is present; required runtime packages are missing, official sampling assumes CUDA, the standalone checkpoint lacks download provenance metadata, and the repository prohibits commercial use of its code and weights |
| floor-plan RLVR | unavailable | Model/runtime are not configured; there is no deterministic fallback presented as RLVR |
| MANSION | unavailable | Enforced as downstream multi-floor/3D evaluation only, not a 2D plan generator |

The adapter harness is integration infrastructure. It is not evidence that the
learned paper implementations have run. The local-only preflight records exact
repository revisions, artifact hashes, strict CPU load results, data schemas,
licenses, and runtime blockers in
[the ignored paper-backend preflight report](../../logs/runs/paper_backends/preflight-2026-07-28.json).
Graph2Plan's checkpoint is a tracked blob in the official repository clone, not
a member of the separately downloaded data archive. Its repository documents
RPLAN80K residential training, raster and room-box output, and MATLAB-based
post-processing for overlap/alignment; those domain, runtime, placement, and
license limits must remain attached to any future benchmark result.

The preflight itself did not generate a learned output. A later isolated
Graph2Plan benchmark executed the official lower-level `generate=True,
refine=True` forward path for RPLAN test record 0 and retained the result under
`docs/paper-conformance/graph2plan-record-0000`. The raw seven-box output has
seven intersecting pairs in both `predBox` and `refineBox`; it remains labeled
`RAW_OUTPUT_NOT_VALIDATED`. This is residential RPLAN evidence, not evidence
that Graph2Plan generates PLAN's commercial or office layouts. HouseDiffusion
still has no executed sampling result.

## Limits

- Whole-building generation currently accepts only axis-aligned rectangular
  floor plates.
- LLM output currently controls floor use assignment, not room polygons.
- The deterministic concept-basic output includes role-specific rooms,
  room-to-corridor doors, core subdivision, two stair references, elevator,
  shaft, lobby, schematic corridor-routed egress, structural grid/columns,
  windows/entrance, representative furniture/fixtures, dimensions, north,
  scale, and street evidence.
- Numerical defaults and furniture density are `concept-basic-v1` research
  policies. They are not jurisdictional compliance values.
- Statutory applicability, maximum travel distance, fire resistance, detailed
  accessibility, elevator traffic, MEP sizing, and construction assemblies are
  explicitly not checked.
- `internal concept validation: pass` means internally consistent under the
  current concept-basic contract. `regulatory screening` is reported
  separately and remains `not_checked` while two-stair applicability is
  unresolved. Neither status means permit-ready or architect-quality.
