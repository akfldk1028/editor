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
