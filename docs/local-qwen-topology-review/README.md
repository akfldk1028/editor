# Local Qwen Topology Review

## Reproduction

```powershell
python -m backend.app.cli local-topology-review `
  --input resources/datasets/manifests/sample_mass_polygon_setback_office.json `
  --floor 1 `
  --use-type office `
  --output-dir logs/runs/local_qwen_polygon_office_v3 `
  --candidate-count 4
```

Runtime:

- Local `Qwen3-4B-Instruct-2507`, NF4 4-bit
- Isolated Python: `C:\Users\User\anaconda3\envs\maas-qwen\python.exe`
- API calls and API cost: none
- Base weights: about 8.1 GB on disk
- Measured base-model allocation: about 2.55 GB VRAM
- Measured HypergraphFormer LoRA allocation: about 3.05 GB VRAM

## Verified Result

- Four strict topology JSON candidates
- Four distinct PNG SHA-256 values
- Four of four internal validation passes
- Four of four render validation passes
- Hard violations: zero for every candidate
- Scores: 0.8202 to 0.8293
- Full run: `logs/runs/local_qwen_polygon_office_v3/index.html`

## Scope

The LLM changes ordering and optional functional/service adjacency only. For
geometric safety, ordering is applied within primary, support, and remaining
room-role groups rather than as an unrestricted global permutation. It cannot
change the fixed room set, area prior, core count, required prior edges, floor
boundary, geometry rules, or validation policy. Invalid JSON, duplicate
sequences, out-of-domain topology, and duplicate resulting geometry are
rejected.

The current paper-backed HypergraphFormer LoRA is residential and
single-apartment only. Office and neighborhood-commercial topology therefore
use the local 4B base model, while PLAN's deterministic generator creates the
actual geometry.

## Remaining Limits

- Regulatory screening is `not_checked` because the sample has no typed
  jurisdiction, effective date, floor occupancy facts, or verified travel
  distance.
- The diagonal upper part of the hexagonal mass remains structural/free area;
  the current orthogonal room generator does not tile that non-orthogonal
  fringe.
- Some dense dimension and core labels still overlap visually.
- Furniture is schematic review geometry, not manufacturer or CTB output.
