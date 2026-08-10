# PLAN/DWG Dual-Agent Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate PLANM, generic GitAgent runtime, and DWG Agent ownership, then connect Backend and Frontend through versioned process and HTTP contracts.

**Architecture:** PLAN and DWG remain independent product agents. The PLAN Backend owns orchestration and communicates with each process through dedicated adapters; the Frontend knows only Backend HTTP DTOs.

**Tech Stack:** Python, TypeScript, GitAgent, JSON Schema, FastAPI-compatible HTTP layer, Playwright, DWG loopback API/MCP

## Global Constraints

- Work only inside `C:\DK\PLAN` and its declared submodules.
- Preserve existing uncommitted files and do not commit without explicit approval.
- Folder ownership and dependency direction are the primary acceptance criteria.
- Do not copy DWG internals into PLAN Backend, Frontend, or PLAN Agent.
- Use repository-root-relative paths; do not persist personal absolute paths.

---

### Task 1: Extract PLANM Product Agent

**Files:**
- Move: `agent/gitagent/agents/planm/**` -> `agents/planm/**`
- Move: `agent/gitagent/test/planm-*.test.ts` -> `agents/planm/tests/*.test.ts`
- Modify: `backend/tests/test_planm_bridge.py`
- Modify: `backend/tests/test_planm_skill_install.py`
- Modify: `backend/tests/test_planm_agent_e2e.py`
- Modify: `docs/superpowers/specs/2026-08-05-planm-gitagent-skill-runtime-design.md`
- Modify: `docs/superpowers/plans/2026-08-05-planm-gitagent-skill-runtime.md`

**Produces:** A PLAN-owned `agents/planm` package with no product files inside the generic runtime.

- [ ] Record all old path references.
- [ ] Move only PLANM-owned files and remove generated `__pycache__` from the migration set.
- [ ] Update tests, installer source resolution, and documentation to `agents/planm`.
- [ ] Reinstall local Codex Skills from the new single source.
- [ ] Run PLANM contract and Python E2E checks.

### Task 2: Normalize Generic GitAgent Runtime

**Files:**
- Create/Register: `agents/runtimes/gitagent`
- Modify: `.gitmodules` or root runtime package configuration
- Create: `docs/integrations/gitagent-runtime.md`

**Produces:** A clean pinned runtime with no PLANM product files and no dirty nested Git ambiguity.

- [ ] Choose a reviewed forked submodule commit or released npm package.
- [ ] Preserve the audited dependency versions without an uncommitted runtime overlay.
- [ ] Update Agent runtime discovery to receive `agents/planm` as configuration.
- [ ] Add a boundary test rejecting imports from runtime to PLAN code.

### Task 3: Add Backend Agent and DWG Adapters

**Files:**
- Create: `backend/app/adapters/planm_agent.py`
- Create: `backend/app/adapters/dwg_client.py`
- Create: `backend/app/schemas/planm_run.py`
- Create: `backend/tests/test_planm_agent_adapter.py`
- Create: `backend/tests/test_dwg_client.py`
- Modify: `agents/planm/adapters/planm_bridge.py`

**Produces:** Versioned JSON boundaries; PLAN Agent no longer imports `backend.app.modules` directly.

- [ ] Define request/result/run-state JSON contracts and adapter mappings.
- [ ] Move PLAN engine invocation behind the Backend-owned process boundary.
- [ ] Add timeouts, exit-code mapping, artifact-root validation, and cancellation.
- [ ] Implement DWG loopback/MCP client without deep imports.

### Task 4: Add Backend Run API and Frontend Flow

**Files:**
- Create: `backend/app/api/routes_planm_runs.py`
- Modify/Create: `backend/app/main.py`
- Create: `frontend` application files after selecting the existing product stack
- Create: Backend run API tests and Frontend/Playwright flow tests

**Produces:** Input -> run -> status -> alternatives -> review -> approval -> download, plus optional post-approval DWG action.

- [ ] Implement repository-owned run/project/artifact persistence.
- [ ] Expose versioned Backend HTTP DTOs.
- [ ] Build Frontend against Backend only.
- [ ] Add optional approved-result DWG inspection/export action.
- [ ] Verify Backend, Agent, Frontend, Playwright, and retained PNG artifacts.
