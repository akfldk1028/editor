## 2026-10-04 - Latest user correction: lightweight frontend, selective migration

AUTHORITATIVE: Editor is the ONLY target product. User intentionally made `D:/Data/25_ACE/AG-frontend` lightweight; inspect THAT frontend, not AutoGen Studio's own frontend. Inventory actual pages/functions/API calls, then port only selected useful functionality into existing Editor routes/backend. NOT all AG features. All architectural agents connect through Editor, which does not mean importing the entire AG platform. No permanent Studio service, `/agentlab` product or blanket AG backend dependency.

Root acknowledged earlier Studio scope expansion and corrected master design/plan. Temporary isolated Studio PID74668 (launcher62536) was stopped after exact source/command identity check;8081 has no listener. Do not restart it just to satisfy an obsolete target. Legacy run-detail GET500 is evidence only; frontend does not currently call that endpoint, so fixing it is not automatically selected work.

Completed source inventories: `docs/integrations/ag-frontend-feature-inventory.md` and `ag-backend-feature-inventory.md`, grounded in D:/Data/25_ACE/AG-frontend. Verified 9 sidebar pages plus Flow popup; prioritize agent status, task/progress UI and history as selection candidates. Settings uses GET/PUT. Next: settle the selected first slice and its Editor/owner contract before implementation. Preserve its lightweight structure, lazy routes and selected dependencies. Candidate/defer/exclude decisions are not all-feature approval. No original folders have been moved; completed full-history import rehearsal was disposable only. Existing AG file restore validation may finish for preservation, not product adoption.

## 2026-10-04 - Editor integration Task1 in progress (historical progress)

Execution root: D:/Data/25_ACE/editor, branch docs/editor-platform-plan-20261004. User clarified that AG functionality is integrated into Editor and ALL agents connect through Editor; folder relocation alone is insufficient. Existing frontend router must be extended, preserving /dwg, /planm and /editor. Design commits 59e7e646, 7a2a9946, 53b87575; preservation tooling 4a4bebe2.

Read [source map and evidence](../docs/migrations/2026-10-04-source-map.md) and [agent matrix](../docs/integrations/agent-connection-matrix.md). Backups outside source: %LOCALAPPDATA%/CodexMigrationBackups/editor-platform-20261004. Git bundles verified/restored; editor and AG-frontend file restore comparisons passed. Isolated editor runtime copy has dependencies added after comparison and uses its own pascal.db. Migration suite 32 passed; source inventory skips active external Git filters instead of allowing status to mutate LFS storage.

Followup 93f11598: explicit opt-in raw Windows reparse restore and directory-size comparison fix; 42 migration tests passed. AG snapshot v2 failed on four directory allocation-size-only changes; v3 is being created with narrowly corrected comparison. Browser scene reopen now passed with one canvas/no page errors. Actual restored backend OpenAPI/config/schema reads passed, but /health is undefined (404).

Further progress: AG files-v3.zip created429653files/12828462346bytes with293recordedlinks; full opt-in restore is running. Editor5e36616f enables explicit owner path/hidden stage host. PLANM151c59d fixes actual lost stdout through hidden wrappers (19Python+4Node tests). Isolated run858fab437a334726904a2116bde47539 generated and published alternative-c into scene868e0a5e9231/version2/321nodes. Real API reread and browser2D/3D passed; graphhash unchanged. Evidence and non-legal-approval limits in source-map326468e5. Owner remains outside Editor.

Studio isolated environment (restored source) passed health/session/run-create/WS ping; additional run detail GET returned500 due string timestamps receiving .isoformat. Preserve this as legacy source evidence only; Studio is not the target runtime. Model execution was never started. Original venv was untouched.

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
