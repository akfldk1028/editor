# Agent-facing doors — a contract with the agents (2026-10-06)

Agents run on **separate servers** with no shared disk. Everything below is called over HTTP by
agents; changing a path, field or status is a contract change: record it in `07-decisions.md`
and tell the Orchestrator session. Base URL the agents use: `EDITOR_DOMAIN_URL`
(default `http://127.0.0.1:18449/api/v1`, no trailing slash).

## Authentication
`A2A_TOKEN` (the agent network's one shared bearer token; owner `app/core/agent_network.py`,
`token_accepted()` / `network_headers()`). Unset on a single machine → no check. Set → these
doors answer **401** without `Authorization: Bearer <token>`:
- `POST /api/v1/{domain}/agent/{op}` (routes_agent_providers.py)
- `/api/v1/design/masterplan/operations` (routes_design_runtime.py)
- everything under `/api/v1/design/maas/delivered-mass-export/` except the original GET/POST door
The editor **sends** the same header to planm (`adapters/planm_agent.py`) and the Orchestrator
(`adapters/orchestrator.py`). UI routes keep their origin checks and need no token.

## Provider ops `POST /api/v1/{domain}/agent/{op}` (no trailing slash; 2 MiB body, research-bundle 20 MiB)
- law: review-design-state, review-program, review-facilities, facility-criteria, building-uses,
  fire-requirements, use-research-routes, ordinance-candidates, parking-design-rules,
  **parking-count** (regulation_calculator.calculate_all verbatim — Lawagent golden set), parcel-limits, audit
- land: parcel-geometry, roads, datum, basement-storey
- design: research-bundle (KMass)

## Planning operations `POST /api/v1/design/masterplan/operations/`
`{operation, arguments}` → envelope `arr.masterplan.operations.v1` with `request_hash` /
`result_hash` (sha256 canonical JSON, sort_keys, ensure_ascii=False, separators=(',',':')).
URL rewriting is skipped for this path (it would break `result_hash`). Ops include plan_site,
validate_plan, footprint_inside, ramp_overhead (Systems via MasterPlan), bind_delivered_*.

## Delivered mass export (Mass → editor → Orchestrator/Elevation)
- `POST .../maas/delivered-mass-export/bundle` (zip, token): `request.json` = {request
  (canonical: completion_sha256, source_run_id, source_identity, source_versions[, include_plan] —
  never a path), round, origins{workspace, sources}}, `workspace/...`, `sources/<i>/...`. Staged
  under `<EDITOR_DELIVERED_MASS_EXPORT_ROOT>/.incoming/<uuid>`, Mass-host paths remapped
  (`remap_origin`), unchanged export runs; `request_hash = digest(canonical request)`.
  Module `modules/design/generation/maas/delivered/mass_bundle.py`.
- Results carry **hrefs relative to `/api/v1`**: `artifacts[].href`,
  `elevation_handoff.request.package_href|selected_glb_href`, `plan_handoff.artifact.href`.
- `GET .../<hash>/files/<member>` and `GET .../<hash>/package.zip?candidate=<id>` (token, confined).
- The original path-based POST `.../delivered-mass-export/` stays for same-host callers.

## Calls this backend makes to agents
- planm: `POST /planm/stage-bundle` (planm-stage-bundle/v1: run dir zipped both ways;
  `adapters/planm_agent.py run_planm_stage`), `POST /planm/generate`. Never send host paths.
- Orchestrator editor API (`EDITOR_ORCHESTRATOR_URL`, :8791): `/editor/v1/...`.

## Guards
`backend/route-inventory.json` + `tests/test_route_inventory.py` (regenerate with
`python -m backend.app.route_inventory --write`), frontend `lib/api-surface.test.ts`.
