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
Production/matched experiment still running at this entry; passing tests do not prove
better architecture. This is UCB1 parameter search, not full MCTS.

Detailed user-requested algorithm and experiment memory:
[MassAgent record](../../../agents/MassAgent/memory/2026-10-17-delivery-guided-search.md).
The local absolute canonical record is
`D:/Data/25_ACE/agents/MassAgent/memory/2026-10-17-delivery-guided-search.md`.
