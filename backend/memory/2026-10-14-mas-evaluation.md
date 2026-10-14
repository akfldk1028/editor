# MAS routing evaluation — 2026-10-14

Canonical plan/decisions live in D:/Data/25_ACE/agents/OrchestratorAgent:
`docs/superpowers/plans/2026-10-14-mas-evaluation.md` and
`memory/decisions/2026-10-14-mas-evaluation.md`.

Editor routing/workspace execution30 regression tests passed. Existing golden
fixture rules scored53/54, zero wrong assignments, three asks (two expected).
Plan's `실 배치랑 피난 동선 잡아` was the one unexpected ask. Small development
fixture, not a held-out benchmark. All16 registered role modules represented.

Live/static-roster pilot attempted4 cases: one pattern and three rule fallbacks,
zero LLM decisions. Model-only score is null. Direct adapter probe returned
RuntimeError containing `limit`; exact quota category unresolved. No silent model
substitution, production code change or owner writes. Preserve CAD/layer modules.

Raw outputs: `runtime/mas-evaluation-20261014/`. Durable copy:
`C:/Users/SOGANG1/orca/workspaces/25_ACE/Thesis/agents/OrchestratorAgent/thesis/results/mas-evaluation-20261014/`.
Next: reproducible metrics harness, held-out labels, availability repair, then live
matched-budget experiments. Debate/reflection UI aliases are not proof of execution.
