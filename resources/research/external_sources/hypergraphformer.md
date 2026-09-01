# HypergraphFormer External Source

- Paper: https://arxiv.org/abs/2605.18932
- Model: https://huggingface.co/NikitaKlimenko/HypergraphFormer
- Base model: `Qwen/Qwen3-4B-Instruct-2507`
- Model revision: `cdbee75f17c01a7cc42f958dc650907174af0554`
- Adapter revision: `ce9f4765d25e7eac9cb7092dc424c1bcb5d3274f`
- Local base: `clone/models/Qwen3-4B-Instruct-2507`
- Local adapter: `clone/models/HypergraphFormer/qwen_hypergraphformer/checkpoint-8700`
- Tracking policy: model assets are excluded from PLAN Git and PyCharm indexing

The released adapter is a 528,550,256-byte LoRA for a 4B base model. PLAN
verified local NF4 inference on the RTX 5080 Laptop at about 3.05 GB allocated
VRAM. The adapter generated valid BSP JSON in a residential smoke test.

HypergraphFormer is trained for single-apartment residential access graphs. It
is not used as an office or neighborhood-commercial geometry generator. PLAN's
commercial path uses the unadapted local 4B model only to propose ordered
space-topology alternatives; deterministic priors retain areas and mandatory
relationships, and PLAN owns geometry, code screening, validation, and review.
