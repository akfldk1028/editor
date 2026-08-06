---
name: normalize-plan-request
description: Normalize and validate a PLANM mass request before any planning skill executes. Use for new PLANM projects or changed source requirements.
---

# Normalize PLAN Request

1. Read the source mass JSON and current `planm-state.json` if it exists.
2. Run `python skills/normalize-plan-request/scripts/run.py` with the input, state, and output paths.
3. Continue only when the returned `skill-result/v1` status is `success`.
4. Ask for the listed fields when status is `needs_input`.
5. Preserve unresolved regulatory facts without inventing values.
