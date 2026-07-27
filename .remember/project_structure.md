# PLAN Memory Structure

## Current Modules
- `backend/app/schemas`: dataclass contracts for mass, program, precedent, layout, metrics, result, visual artifacts.
- `backend/app/modules`: mass analyzer, program prior, precedent retriever, baseline layout generator, validator, generation loop, visual review.
- `engine`: reusable geometry and PNG IO primitives.
- `datasets`: raw/processed/annotations/manifests; sample mass JSON exists.
- `research`: paper buckets for generation, retrieval, shape grammar, chip floorplanning, RLVR.
- `docs`: architecture, research loop, schema contracts, dataset policy, decisions.

## Commands
- Test: `pytest -q`
- Generate JSON: `python -m backend.app.cli generate --input datasets/manifests/sample_mass_office_commercial.json --floor 1 --use-type neighborhood_commercial`
- Visual loop: `python -m backend.app.cli loop-review --input datasets/manifests/sample_mass_office_commercial.json --floor 1 --use-type neighborhood_commercial --output-dir logs/runs/sample_review --max-iterations 3`

## Commits
- `e4e9b26` scaffold loop
- `f4ffdd1` visual artifacts
- `85e169e` browser review page
- `3fdae5d` iterative visual review loop
- `36c7098` docs for visual review loop
