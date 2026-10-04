# Editor law search and advisory integration

The default land analysis path, including include_law=true, now executes inside Editor. Only ENABLE_DATUM_ELEVATION=true still delegates analyze to ARR. Default historical statistics remain legacy; Editor-owned statistics use scope=editor. This increment does not complete ARR/selected AG integration.

## Implementation

adapters/law_search.py owns asynchronous primary search and connection-failure fallback. It preserves original base/extended/building-type query composition, deduplicates queries, filters similarity below0.25 and the source noise-law list, and normalizes fallback IDs. Primary and fallback citation metadata are retained, including article, effective dates and nested source references. Invalid/nonfinite response data fails explicitly. Errors do not expose provider URLs or credentials.

A loop-scoped semaphore limits concurrent queries to5 across batches. A real overall deadline cancels unfinished work while retaining completed results, replacing the original thread-pool timeout that could continue waiting. Results follow query order rather than nondeterministic completion order. Fallback occurs only after connection errors/timeouts, not HTTP errors, read timeouts or malformed success responses. No configured URLs means an explicit partial result with no network attempt; there is no implicit external fallback destination.

adapters/regulation_extraction.py owns explicit optional extraction using the migrated prompt configuration in modules/regulations/extraction_prompts.py. LLM_EXTRACTION_ENABLED=true and OPENAI_API_KEY are both required. The model is server configured; default retains gpt-4o-mini. Unlike original default-enabled extraction, an unset flag disables this optional external call. Search for extraction keeps the original unfiltered evidence behavior, deduplicates content and uses the first5 texts. Completion has a bounded cancellation deadline; invalid booleans, negative/nonfinite numbers and malformed lists are rejected. There is no zone-only cache that could reuse stale evidence/model settings.

modules/land/evidence.py composes search and extraction, cancels and awaits sibling work on failure, and reuses the existing article flatten/dedup helper. The analysis service feeds proposals through the calculator's existing advisory seam; numeric rules and permit-compliance status are unchanged. Proposals are exposed separately as advisory.status=unverified_proposal; no usable proposal returns unavailable. Existing /land displays these in a separate review region with an explicit exclusion from calculated limits. HTML-like provider/model text remains text.

LAW_BACKEND_URL and optional AG_LIGHT_URL configure search providers. These are server-side values, never request-supplied URLs. .env.example describes configuration. Search/advisory failures remain visible while computed/reference results and local persistence remain available. Ineligible evidence is not promoted to approval.

## Verification

- 367 targeted backend tests and41 subtests passed, one existing Starlette/httpx deprecation warning.
- Source AST fixtures verify filtering, preserved metadata and extended/building query composition. Timeout, partial completion, cancellation, connection-only fallback and malformed-response tests pass.
- Review found semaphore reuse across event loops and dropped article/source metadata; both reproduced RED and fixed GREEN. A separate sibling-cancellation regression verifies reference failure cannot orphan ongoing searches.
- Actual Editor HTTP18440 with HTTP and completion fixtures verifies default law analysis, duplicate-article collapse, partial search errors, saved local results and999m advisory values that do not replace calculated setbacks.
- Chrome20 passed,11 unrelated opt-in tests skipped. Includes hostile-markup text rendering and explicit unavailable advisory display. Frontend build and2 module-boundary checks pass.
- Existing parcel/source calculation parity remains passing. Actual law/Vworld/OpenAI providers and legal currency were not reverified.

Evidence: .superpowers/sdd/2026-10-04-law-analysis/{backend.xml,browser.json,server.log}. Isolated18440 was stopped after validation; no operational/shared service or original source database changed.

Next: absorb datum elevation with explicit provider provenance, failure states and preserved relative geometry; migrate historical analysis/cache records; then continue design/jobs/artifacts and selected AG workflows. Full regulation-line/3D UX and production restart/cutover remain unproven.
