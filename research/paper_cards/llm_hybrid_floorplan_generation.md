# LLM Hybrid Floorplan Generation

## Decision

PLAN uses the LLM as a constrained program planner, not as the geometry
authority. The model proposes strict JSON floor assignments and, later, program
graphs. Deterministic geometry code produces polygons, and the exact validator
rejects boundary, overlap, area, and circulation failures.

This division keeps natural-language and use-mix reasoning flexible while
making geometric acceptance reproducible.

## Public Paper-Code Evidence

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
and then reinforcement learning from verifiable rewards. Its reward components
include valid JSON, no overlap, connectivity, and total area.

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
- The output is schematic zoning. Doors, dimensions, code-compliant corridor
  widths, egress, structure, MEP, and detailed room subdivision remain pending.
- Passing hard validation means geometrically consistent under the current
  contract; it does not mean permit-ready or architect-quality.
