# Claude handoff — nationwide ordinance coverage (2026-10-09)

## User requirement

Every applicable local ordinance nationwide must be discoverable for a selected parcel and assessment date, with its official source URL and readable provision text. The user asked to save this for Claude to continue. This is an implementation requirement, not a claim that national coverage is already complete. Never hardcode a city, PNU, a finite municipality list, or a default jurisdiction. Never label candidate discovery as confirmed applicability.

## Existing flow and known gap

- Frontend law reader: `frontend/app/editor/features/artifacts/law/ui/ReviewNavigation.tsx`, `ReviewTab.tsx`, `SourceArticle.tsx`; source client/cache: `features/artifacts/law/api/reference.ts` and `reference-cache.ts`.
- Frontend only displays ordinance refs already present in `analysis.review`. A name-only ref is sent through platform `/ask` with exact instrument name and date.
- Backend `/platform/ask` `clause_route` sends a named ordinance to Law Agent `law_ordinance`; this is exact-name law.go.kr DRF retrieval. It does not discover an absent ordinance or list all relevant ordinances.
- Law Agent already exposes MCP/A2A `law_ordinance_candidates(query, assessment_date)` (`D:\Data\25_ACE\agents\Lawagent\mcp\server.py`) and its editor provider `POST /api/v1/law/agent/ordinance-candidates` (`backend/app/api/agent_providers/law.py`). It delegates to `backend/app/modules/law/reference/ordinance_discovery.py` and law.go.kr.
- `discover_ordinances` is nationwide source discovery only. It currently searches two edition sets with `max_pages=5` (up to 500 records per edition set), filters effective dates, returns candidates, and explicitly sets `coverage_complete: false`. Candidates are not body-verified; jurisdiction match, ordinance articles/annexes, and legal applicability remain unresolved. It cannot support “all nationwide ordinances” today.
- `law_ordinance` in `D:\Data\25_ACE\agents\Lawagent\mcp\server.py` fetches exact-name ordinance body for an article/keyword and assessment date. With an empty article it returns dated edition metadata and URL, but no whole body (`matches: []`). Do not tell the user that an entire ordinance body was fetched when only a URL/edition was returned.
- Backend review builder `backend/app/modules/land/review/refs.py` turns a generic `건축조례` into an unidentified ordinance. `backend/app/modules/platform/law_sources.py` now resolves this shorthand only when exactly one named matching ordinance in the same review supplies jurisdiction; it must stay unresolved if none/multiple exist. This is not a general nationwide resolver.

## Next implementation Claude should do

1. Trace the selected PNU through authoritative parcel address/legal-dong and sigungu jurisdiction, assessment date, zoning/designations, and relevant use/program. Build a modular ordinance-discovery owner/service that takes these inputs; do not infer municipality from a display string or hardcode an example city.
2. Connect MCP candidate discovery to parcel analysis/review so local ordinances absent from current calculation receipts can be discovered. Search must account for all pages and both current/historical edition sets as of the requested date, deduplicate by stable ordinance edition identity, and expose pagination/API failures. Do not silently cap pages and then imply completeness. Use bounded pagination, caching, continuation if necessary, and a truthful completeness/coverage status.
3. Verify every candidate's exact ordinance identity and responsible municipality/jurisdiction against authoritative records. Reject similarly named municipalities and stale/wrong editions. Preserve assessment date, ordinance ID, edition/MST, effective date, official URL, retrieval time/source, and matching jurisdiction provenance.
4. Fetch full text per applicable article and annex through exact-name/date law.go.kr `law_ordinance`, retaining the official hierarchy and amendment metadata. Resolve topic-relevant provisions/annexes from parcel regulations and intended design use. “Every ordinance” means all relevant ordinances/provisions for the selected site and design, not rendering every unrelated ordinance in the country.
5. Make frontend show every discovered relevant ordinance/provision, official clickable URL, date/edition and source status. Separate `candidate`, `jurisdiction_verified`, `body_verified`, `relevant`, `applies/conditional/unknown`; unknown evidence stays explicit and never becomes legal absence. No dead retry buttons; a name-only ordinance opens its verified official URL until inline body is actually available.
6. Add regression coverage for multiple municipalities with similar names, zero/multiple jurisdiction matches, multiple pages, current + historical edition selection by date, truncated/error responses, empty article/full ordinance link fallback, annexes, and no coverage-complete claim on partial data. Run focused backend/frontend checks and a browser flow on more than one jurisdiction; keep fixture data distinct from live evidence.

## Relevant contracts / constraints

- Agent-facing provider additions or changes are contracts: record them in `backend/memory/07-decisions.md`; do not edit agent-owned `D:\Data\25_ACE\agents\Lawagent` unless that owner session is explicitly coordinated.
- Read `backend/memory/02-agent-doors.md`, `backend/memory/05-run-and-test.md`, and `backend/app/api/agent_providers/law.py` before changing provider/API shapes.
- Read Law Agent `LAWAGENT.md` and its v4 implementation record before changing MCP contract; agent domain owner is `D:\Data\25_ACE\agents\*`.
- No city/PNU-specific behavior, no generic keyword result presented as exact legal authority, and no certification of complete national coverage without end-to-end evidence.

## Done 2026-10-09 (Claude session, after the handoff)

Steps 1–5 of the list above are implemented end to end; see backend `memory/07-decisions.md` and frontend
`memory/05-decisions.md` (2026-10-09 Claude lines) for the exact shapes.

- Jurisdiction: `backend/app/modules/law/ordinances/jurisdiction.py` — registry address by PNU (Vworld parcel `addr`),
  시·도 + 시·군·자치구 levels, 일반구 noted, cross-check against the PNU code's ordinance snapshot, conflict fails closed.
- Discovery: `search.py` + `service.py` — every page, both edition sets where they matter, dedupe by edition serial (MST),
  per-query pages/total/complete/error, `coverage_complete` always false, `search.complete` truthful.
- Verification: issuer (`지자체기관명`) must equal a level's issuer; similar names of other governments land in `excluded`.
  Edition in force on the date; later editions listed as `future_editions`; history-only ordinances for a past date are
  returned apart (`historical`, in_force unknown — the list does not say when they were repealed).
- Full text: `body.py` + `POST /platform/ordinances/body` — the whole edition (articles, 별표 with file links, 부칙),
  accepted only as the same name/edition/in force. Per-article text still goes through the Law Agent `law_ordinance`.
- Frontend: 관할 조례 list by level with status words, 제외/연혁 details, whole text inline, article buttons, official URL
  always visible. Third pane no longer carries a question form (conversation panel only).
- Tests: backend 24 (fixture governments 갑도·을시; similar names, zero/multiple matches, 3 pages, current+history by
  date, truncated/error, generic-name rules, door 403/422), frontend 64 in the law slice incl. api-surface.

## Still open after 2026-10-09

- Relevance is name-based: a topic word in the name (건축 → 녹색건축물·제설 조례 too). Narrowing needs the parcel's
  regulations/design use to name provisions, not only ordinances; `topics[]` on the door is accepted but no UI sends it.
- Annex (별표) bodies are HWP/HWPX attachments: linked, not parsed (the caps generator reads HWP with the SiteContext venv).
- A past assessment date lists `historical` ordinances with unknown repeal dates; nothing confirms they were in force.
- `body` status is not fed back into the list (no `body_verified` chip after reading).
- The Orchestrator run path (`limits` goal) does not call discovery; only the law artifact does.

## Current reader work already present

- Three-pane law reader at wide widths, collapsible context/navigation at artifact width; original text 13px default, adjustable, 40 CJK glyph measure, hierarchy indentation.
- Official URL always visible. Exact edition URL wins; otherwise law.go.kr name route is labelled current-law fallback.
- Same-source requests are shared/cached in memory for 5 minutes (64 max), timeout 45s. Measured Law Agent exact ordinance lookup was about 4.1s; cache reopen about 25ms. Candidate discovery/full-body batching is not yet built.
- Law summary actions are “검토 조항 보기” and “설계 방향 이야기하기”; latter drafts a use/spaces prompt into the existing design conversation without auto-submitting or selecting a hardcoded agent.
- The backend same-review unique-name resolution and source URL screen check were implemented during this session; do not overwrite these with a fixed 의정부시 mapping.
