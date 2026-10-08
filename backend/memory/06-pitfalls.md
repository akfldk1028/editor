# Known traps (2026-10-06)

- **Trailing slash.** Provider ops are `/{domain}/agent/{op}` without a slash (a slash 307s and
  httpx `raise_for_status` fails). The design catch-all normalises, but write clients without it.
- **Identity envelopes.** `masterplan/operations` results are hashed; the catch-all must not
  rewrite URLs inside them (special-cased in `routes_design_runtime.py`).
- **Windows zip names.** `zipfile` silently turns `\` into `/` in `.filename`; check
  `orig_filename` when refusing unsafe members.
- **Paths never cross servers.** Do not add a field that hands an agent a path on this disk;
  give an `href` (relative to `/api/v1`) + sha256 and a token-protected route that serves it.
- **Process not replaced.** A fix is not live until the uvicorn process is replaced (PID start
  time). Two listeners on 18449 happened before.
- **Model keys.** No credits on the stored OpenAI key; placeholder Anthropic key. Local work uses
  `EDITOR_MODEL_AUTH=oauth`. Never let the CLI child inherit `ANTHROPIC_API_KEY`.
- **Tests and the real CLI.** Keep `tests/conftest.py` pinning `api_key`, or tests call Claude.
- **Stale test expectations vs newer decisions.** Check git dates: e.g. design targets without a
  Law count (2026-09-30 decision) and `diagnostics` on rejected plan families — the test was the
  stale side both times.
- **CRLF warnings** on commit are harmless (git normalises).
- **Public IP.** This machine's 163.239.x address is public — never bind `0.0.0.0` for tests;
  use 127.0.0.1 or the host-only adapter 172.27.80.1.
- **Leftover `__pycache__` dirs after a move.** A directory holding only `__pycache__` makes the old
  dotted path import as an empty namespace package (no ModuleNotFoundError). Delete it after `git mv`.
- **Host daemon reads `infra/config/services.json` once** (registry.mjs). A registry change (10-08: Orchestrator
  `--enable-submissions`) is not live until `bun run host:stop` + `host:start <ids>`; the stale daemon spawned the
  Orchestrator read-only and every submission got `Owner unavailable` (503) from `/projects/{id}/context`.
- **`bun run host:start` with no ids starts every editor-owned service** (dwg, pascalMcp, …) and the daemon dies on the
  first spawn error (`spawn bun ENOENT` for pascalMcp: unhandled ChildProcess 'error'), leaving backend/orchestrator
  unsupervised. Always name ids; `runtime/host/wanted.json` keeps the list and must be trimmed by hand afterwards.
- **A limits run needs the Orchestrator *worker*** (`agents/OrchestratorAgent/scripts/services/stack.ps1`:
  `python -X utf8 -m orchestrator --runtime <runtime/orchestrator> worker`, record `runtime/services/orchestrator-worker.json`).
  The editor door (:8791) alone accepts (202) and the run stays `queued` with no communications forever. The host
  registry does not start the worker.
- **A stale project binding gives a bare 409.** `POST /projects/{id}/runs` answers "Request identity or source version
  conflict" when the binding's owner project/branch is no longer in `GET :8791/editor/v1/projects` (the first binding,
  `uijeongbu-r39-own-design`, is such a one); the reason text is swallowed by the router. Use a binding the door lists.
- **`import-linter` lives in `.venv` only.** Running pytest with the system Python skips `test_import_layers`
  (importorskip) — run `.venv/Scripts/python.exe -m pytest …` or the layer contract is not checked.
- **Composer answers vanish on reload and the conversation forgets the site.** After a full reload the site card still says
  선택됨 but `site-context` (in-memory) is empty, so the Orchestrator's situation says "no site" and the thread is empty;
  the feed is in-memory only. Same root as the open "thread empty after reload" (10-08). Re-select the parcel before
  judging a reply that mentions the site.
- **All 16 agents start with one host command** (10-08 23:03): `bun run host:start masterplan program elevation mass kmass
  systems domain-expert interior scene` brought 7 up in 25 s and mass/scene (their `scripts/serve-a2a.sh`: nohup + wait
  for the card) in ~40 s; the Orchestrator catalog then reports 16 up and the conversation's situation changes by itself.
  `--with-agents` selects every agent entry. Caveats: the daemon still dies on a spawn ENOENT (name ids, never bare
  `host:start`), `runtime/host/wanted.json` now lists them all so the daemon restarts any that die, and the three
  compose-served agents (site/revision/requirement/design-intent per ops compose) must not be double-started by hand.
