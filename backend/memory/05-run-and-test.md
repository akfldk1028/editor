# Run and test (2026-10-06)

## Interpreter
`D:\Data\25_ACE\editor\.venv\Scripts\python.exe` (run from the editor root; imports are
`backend.app...`).

## Start the backend (port 18449)
```
.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 18449 \
  --env-file D:/Data/25_ACE/editor/.superpowers/sdd/editor-law.env --log-level warning
```
or the whole stack with `bun run plan:dev` (`infra/dev/runtime.mjs`). A code change is live only
after the process is replaced — check the listener PID's start time, not just the port.
For other servers: `--host` / env as in `agents/docs/AGENT_MODULE_CONVENTIONS.md` §5; set
`A2A_TOKEN` to the network's value.

## Tests
- Whole: `.venv/Scripts/python.exe -X utf8 -m pytest backend/tests -q` (long; the engine
  folder alone is ~11 min).
- Focused sets used most:
  - engine: `backend/tests/masterplan_engine`
  - agent doors: `test_agent_domain_providers.py test_masterplan_operations_identity.py
    test_masterplan_operations_ramp_overhead.py test_delivered_mass_bundle.py test_route_inventory.py`
  - workspace/AG: `test_workspace_*.py test_land_agent_analysis.py test_model_auth_oauth.py`
  - planm client: `test_planm_adapter.py test_planm_transport_boundary.py test_planm_run_*.py`
- Live planm test runs only with `PLANM_AGENT_URL` set and planm up:
  `PLANM_AGENT_URL=http://127.0.0.1:8309 ... test_planm_run_api.py::test_live_plan_agent...`
- Layer guard: `.venv/Scripts/lint-imports` (dev extra `import-linter`), also in `test_import_layers.py`.
- Route guard: after adding a route, `python -m backend.app.route_inventory --write`.

## Commit
The editor checkout is on branch `docs/editor-platform-plan-20261004` (Codex also edits it).
Stage only your files; never sweep other sessions' changes. `git rev-parse --show-toplevel`
before committing (repos overlap under D:\Data\25_ACE).
