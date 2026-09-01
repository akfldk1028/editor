# PLAN repository guidance

Use the flat standalone-repository boundaries documented in `README.md`:

- `frontend/` owns the web UI and calls Backend HTTP only.
- `backend/` owns deterministic PLAN domain behavior, run state, approval, and artifacts.
- `agents/planm/` owns PLANM identity, contracts, skills, workflows, and memory.
- `agents/runtimes/gitagent/` is the generic agent runtime.
- `agents/dwg/` is the independently testable vendored DWG integration.
- `infra/`, `docs/`, and `resources/` remain top-level siblings.

Do not introduce a `products/plan` wrapper inside this standalone repository.
If several repositories are later combined, add the wrapper only in the parent
integration repository.

Run the current checkout and inspect retained artifacts before claiming success.
