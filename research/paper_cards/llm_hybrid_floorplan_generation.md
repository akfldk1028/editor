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
- Passing hard validation means internally consistent under the current
  concept-basic contract; it does not mean permit-ready or architect-quality.
