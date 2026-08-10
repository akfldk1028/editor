# Handoff

## State
I scaffolded `C:/DK/PLAN` as a git repo for mass-conditioned 근생/오피스 floor-plan research. Core loop exists: `MassInput -> ProgramGraph -> LayoutCandidate -> ValidationReport`, plus CLI `generate`, `review`, and `loop-review`.

## Next
1. Replace `backend/app/modules/layout_generator/service.py` baseline slicing with a real adjacency-aware generator.
2. Add data ingestion/vectorization under `scripts/ingest` and `resources/datasets/processed/*`.
3. Expand validator with circulation, core/access, evacuation, frontage, and rentable-efficiency checks.

## Context
User wants practical 실무용 automation, not hardcoded ratios or pretty image generation. Always create visual artifacts and inspect PNG/HTML during loops; current sample output is under `logs/runs/sample_review/iteration_001`.
