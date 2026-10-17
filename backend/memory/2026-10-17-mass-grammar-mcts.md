# Executable Mass grammar MCTS

User correction: fixed finished-form menus and merely naming a selector MCTS are
insufficient. Mass owns geometric operations; KMass owns residential floor organization.

`book_language/grammar_mcts.py` independently adapts Finch's recovered `dAe`/`ND`
selection, expansion, simulation and ancestor backpropagation. The local source is
`D:/Data/25_ACE/AL/rea-mono/streams/archi/finch/key_excerpts/mcts_core.js`.
UCB1 is observed for segmentation; this is not the FixedCore PUCT implementation.
Mass actions use existing executable BOOK append/prepend/retune productions, not
Finch's floorplan cuts or a list of completed building shapes.

The real `creative_floor_portfolio.py` compiler/delivery callback evaluates every
proposal. Reward is 95% normalized gate progress and 5% measured morphological
distance. Acceptance still requires the actual hard gates; reward cannot certify a
failed solid. A baseline succeeds immediately; otherwise up to ten other numeric
states precede structural search. A one-step rollout and progressive widening leave
room for adaptive revisits within a small compiler budget. Rollout nodes remain in
the tree, and terminal rewards propagate through their ancestors. Cache identities,
seed, parent paths, actual hashes, visits, rewards and refusals are persisted.

The first source round evaluates different source/slot pairs before augmenting
assignment paths. Per-pair allocation divides the shared retry budget by the smaller
of target count and eligible source count. Independent review caught an earlier
minimum11 allocation starving later sources. The production regression with two
sources and eight retries changed from [8,0] to [4,4]. With six sources and96 retries,
each failed initial pair has16 retries: ten retunes plus three two-probe simulations,
including a UCB revisit. A smaller per-pair budget may not cover all numeric states
or run structural MCTS. More sources than retries necessarily leave some with only
a baseline. Baselines are outside the shared retry budget; this is not a bound on
all compiler work.

Seven focused tests verify delayed rewards, preferential revisits, deterministic
seeding, reusable rollout nodes, hard refusal, all11 numeric states with sufficient
budget, shared caps, original geometry preservation, real compiler integration and
low-budget source allocation. Independent review found no remaining established
high/medium MCTS defect after the fairness correction.

Final matched decision: retain beam as the production default. Same six sources,
salt, capacity and96 retries yield beam4 explorations versus MCTS3; original hashes
match and fresh independent probes accept10/10 and9/9 final candidates respectively.
MCTS actually executes14 simulations and4 UCB selections, but its retained results
are one numeric retune and two baselines, so this cohort does not establish a
structural-search benefit. Beam retains two structural derivations. Both are partial
against target6. Single concurrent timings282.17s/217.76s are not a speed benchmark.
MCTS remains available through explicit `delivery_search_algorithm='mcts'` in the
real portfolio API; the canonical command continues to use beam. Do not claim
production MCTS default adoption or aesthetic improvement. Root combined101 tests
pass, including required owner regressions. Runtime comparisons are recorded under
`D:/Data/25_ACE/agents/MassAgent/docs/reports/rea-mass-kmass-algorithms-20261017/`.
Maximum depth, finite action vocabulary and compiler budget limit completeness.
One accepted winner per pair enters the existing assignment/diversity selection;
this does not optimize aesthetic quality or retain every passing sibling.
