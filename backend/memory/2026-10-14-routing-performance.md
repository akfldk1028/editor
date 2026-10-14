# Router speed and accuracy - 2026-10-14

User scope correction: this session owns ROUTER speed and accuracy, then Chrome verification of editor frontend/backend. Domain agents own design generation, geometry correction and design quality judgments. Do not resume design-owner implementation under this task.

Changes:
- Keyword spans contained in more specific phrases no longer cast duplicate votes. Preserve genuine multi-owner ambiguity.
- Default Claude model failures open a short local cooldown (quota/auth 60s; other failures 15s); subsequent requests use transparent rules fallback. Cooldown expires automatically. Explicit test/model clients are isolated. No model answer caching.
- Load the live agent situation/catalog only when model inference actually needs it. Explicit role, pattern, rules and circuit-open routes skip it. Model prompts still receive the current context.
- Routing prompt separates unknown execution parameters from unknown responsibility. Missing parcel alone is not a reason to refuse routing to a known owner.

Measured evidence (development fixtures, not held-out accuracy):
- Existing 54-case rule set: 53/54 -> 54/54. Wrong assignments 0 before and after; formerly unnecessary clarification now Plan. Rule-only p50 0.033 -> 0.047 ms and p95 0.052 -> 0.078 ms; accuracy fix adds tiny CPU cost, not a speed gain.
- Actual Claude weekly quota confirmed. Before, warm failures cost 2212-2264ms each. After initial failure, six-case diagnostic subsequent route-only fallbacks 0.110-0.179ms. Initial model failure still takes seconds.
- Chrome -> Next proxy -> actual backend /ask: before lazy catalog, two circuit-open calls 2451/2472ms. After, 20 circuit-open calls all HTTP200/Plan, p50 49.95ms, nearest-rank p95 121.60ms, max443.20ms. Single text repeated, local hot service, no domain generation; not cold model latency or broad production distribution.
- Exploratory Codex model injection, 8 existing development cases: 6/8 -> 7/8; p50 13.54 ->12.17s; p95 18.45 ->17.36s. One pass each, no statistical performance claim. Baseline did not capture exact full live prompt, so it is diagnostic only. After captures prompt/hash and ledger. Remaining core/layout case labelled MasterPlan was assigned Plan; requires independent label/context review, not forced score fitting. Production editor routing provider remains Claude; central conversation Codex is separate.
- 39 routing/evaluation/API regression tests pass. Independent scoped review found no P1/P2. Real backend restarted through host supervisor; Chrome verifies current code.

Future evaluation: independently label held-out questions including context, owner ambiguity and paraphrases; report per-owner precision/recall, clarification and wrong-assignment rates, and model/roster/total latency separately. Full design scores are outside router accuracy.
