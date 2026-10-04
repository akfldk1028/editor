## 2026-10-04 - Editor integration Task1 in progress

Execution root: D:/Data/25_ACE/editor, branch docs/editor-platform-plan-20261004. User clarified that AG functionality is integrated into Editor and ALL agents connect through Editor; folder relocation alone is insufficient. Existing frontend router must be extended, preserving /dwg, /planm and /editor. Design commits 59e7e646, 7a2a9946, 53b87575; preservation tooling 4a4bebe2.

Read [source map and evidence](../docs/migrations/2026-10-04-source-map.md) and [agent matrix](../docs/integrations/agent-connection-matrix.md). Backups outside source: %LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004. Git bundles verified/restored; editor and AG-frontend file restore comparisons passed. Isolated editor runtime copy has dependencies added after comparison and uses its own pascal.db. Migration suite 32 passed; source inventory skips active external Git filters instead of allowing status to mutate LFS storage.

Followup 93f11598: explicit opt-in raw Windows reparse restore and directory-size comparison fix; 42 migration tests passed. AG snapshot v2 failed on four directory allocation-size-only changes; v3 is being created with narrowly corrected comparison. Browser scene reopen now passed with one canvas/no page errors. Actual restored backend OpenAPI/config/schema reads passed, but /health is undefined (404).

Further progress: AG files-v3.zip created429653files/12828462346bytes with293recordedlinks; full opt-in restore is running. Editor5e36616f enables explicit owner path/hidden stage host. PLANM151c59d fixes actual lost stdout through hidden wrappers (19Python+4Node tests). Isolated run858fab437a334726904a2116bde47539 generated and published alternative-c into scene868e0a5e9231/version2/321nodes. Real API reread and browser2D/3D passed; graphhash unchanged. Evidence and non-legal-approval limits in source-map326468e5. Owner remains outside Editor.

Studio isolated environment (restored source) now passed health/session/run-create/WS ping; additional run detail GET returned500 due string timestamps receiving .isoformat. Preserve this known defect for actual Studio integration; model execution was never started. Source declared dependencies required separate compatible MCP1.25.0 after MCP2.3.0 import failure; original venv was untouched.

Task1 NOT complete: AG full restore/hash/link validation and source inventory are still running; remaining Studio evidence and storage strategy must be recorded. No source folders moved, no product routes/API integration implemented. Agent matrix is declared inventory, not proof of live connections. Systems/DomainExpert/Interior remain partial. Continue preservation gates before Task2, without resetting dirty AG research or deleting originals. Detailed receipts remain outside Git; do not commit private source snapshots.

## 2026-10-04 - Editor platform integration planning

User designated D:/Data/25_ACE/editor as the main frontend/backend product root and requested a plan+commit before implementation. Read [design](../docs/architecture/2026-10-04-editor-platform-design.md) and [execution plan](../docs/superpowers/plans/2026-10-04-editor-platform-integration.md).

Planning only: no source relocation, dependency installation, service restart or product changes. editor began clean at bdc6ed38. AG-frontend belongs to parent Git (233 tracked paths); AG has dirty/untracked research that must be preserved separately from history. Next execution is Task1 inventory/restore rehearsal; source directories stay intact until copy/hash/runtime verification.

Current product already contains Vite PLANM/DWG shell and Next editor, plus FastAPI, scene/MCP storage and external PLANM binding. Existing scene placeholders are not a durable product registry. Preserve core/viewer boundaries, owner execution authority and explicit API namespaces. Prior dated handoff below is retained as history.

# Handoff

## State

I kept PLAN as a flat standalone repository on `master` and updated
`resources/scripts/sweep_alternatives.py` so invalid CLI options cannot create
outputs or start a sweep. The current measured baseline remains 48/48 cases and
102 accepted alternatives with all quality gates intact.

## Next

I left no active implementation work. Configure a Git remote before pushing;
run a fresh 48-case sweep whenever generator logic changes.

## Context
I retained older 40/48 analysis in `docs/architecture/input_envelope.md` only as
dated historical evidence; its 2026-09-01 section is authoritative.
