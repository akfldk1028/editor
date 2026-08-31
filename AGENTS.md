# PLAN workspace agent instructions

## First checks

1. Run `git status --short` and verify the current branch.
2. Read `docs/superpowers/specs/2026-08-31-product-first-monorepo-design.md`.
3. Treat historical paths and test totals as stale until verified locally.

## Canonical ownership

- `products/plan`: PLAN frontend, backend, PLANM agent, docs, and resources.
- `products/dwg`: independent DWG product. Its own `AGENTS.md` also applies.
- `platform/agent-runtimes`: product-neutral agent runtimes only.
- `shared/contracts`: versioned DTOs and schemas only.
- Root `infra`: cross-product composition only.
- Root `docs`: workspace-wide decisions only.

Never recreate root `frontend`, `backend`, `resources`, or `agents`. Never merge
another repository by overlaying same-named technical directories; add it under
`products/<product>`.

## Dependency direction

- PLAN Frontend consumes PLAN Backend and supported DWG public packages/routes.
- PLAN Backend owns run, retry, approval, and handoff state.
- PLANM uses declared skills and the deterministic PLAN engine.
- PLAN and DWG never import each other's private modules.
- Platform and shared code never import a product.

## Verification

```powershell
npm run test:architecture
npm run test:dev
npm run test:agent
python -m pytest -q                         # from products/plan
npm --prefix products/plan/frontend run build
npm --prefix products/dwg run verify:all
```

Run DWG Node and .NET suites sequentially on Windows. Inspect retained PNGs after
browser or rendering changes. Do not lower PLAN acceptance or diversity gates.
