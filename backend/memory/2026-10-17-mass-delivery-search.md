# 2026-10-17 — Mass delivery-guided parameter search

General payload/llm BOOK generation now passes BookDeliveryProbe into the portfolio
builder. Failed source/slot proposals regenerate actual canonical BOOK parameters;
DeliveryVariantSearch selects alternatives by shared UCB1 binary delivery reward.
The old middle variant is always evaluated first. Additional-retry budget does not
charge baseline evaluations; exhausted search preserves partial supply explicitly.

Canonical implementation: `app/modules/design/generation/maas/book_language/delivery_search.py`.
The probe shares `book_import.candidate_record`, `_compile_record` and `_refused` with
final import. Its cache keys the complete delivery record, including facing metadata
not included in program_hash. Exact authored development bypasses this search.
No gate relaxation, parking algorithm changes or aesthetic reward were added.

65 relevant tests passed, including the user-required three provider-parity suites.
Independent review found and resolved a total-budget cap and incomplete cache identity.
Implementation commit: `bbc65941`. Matched six-source/site/salt replay recovered
delivery-checked explorations from 1 to 3; all six original geometry hashes stayed
identical. Final fresh probes accepted all nine records. It remains partial (3/6
explorations), with 131 attempts/96 extra retries and 308.49 seconds. Retained
variant indices 8,5,5 show both regeneration and delivery-aware reassignment;
do not attribute the entire gain to UCB1. No UCB-versus-linear ablation was run.
New-source production round has 6 originals + 5 explorations actually staged,
with 7 historical/anchor tiles. Canonical cycle completed all12 steps. Exact
development r1 failed host fit; preserved r2 delivered both children without clipping.
Fresh pair votes BBB/AAA selected child1. This is a single authored-development
comparison, not proof of UCB aesthetic benefit. Breadth sheet has6 originals,
30 browser images loaded;212 receipt hash references match.
Passing gates does not prove better architecture. This is not full MCTS.

Detailed user-requested algorithm and experiment memory:
[MassAgent record](../../../agents/MassAgent/memory/2026-10-17-delivery-guided-search.md).
The local absolute canonical record is
`D:/Data/25_ACE/agents/MassAgent/memory/2026-10-17-delivery-guided-search.md`.
