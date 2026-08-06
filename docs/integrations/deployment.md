# PLANM deployment boundary

`compose.yml` preserves the same ownership used in development:

```text
Browser -> Frontend nginx -> Backend HTTP
                            |-> GitAgent host -> PLANM skill subprocess
                            `-> optional DWG gateway subprocess
```

- Frontend contains only the built Vite application and reverse proxy.
- Backend owns run state, orchestration, adapters, and the persistent run volume.
- `agents/planm` remains a separate process boundary from Backend domain code.
- `external/gitagent-runtime` remains a generic built runtime with no PLAN or DWG imports.
  Its built discovery API is required by every deployed PLANM stage; no user
  activation switch or LLM provider is required.
- `external/dwg-intelligence` is built from its pinned submodule source. Its public
  gateway starts only for an approved CAD inspection and receives the single run
  handoff directory as `DWG_WORKSPACE`.
- DWG source is never copied into Backend Python packages and Frontend never
  receives an Agent or DWG filesystem path.

Initialize submodules before building. The deployable source must include a DWG
submodule commit containing the numeric DXF handle normalization used by the
PLAN handoff; an uncommitted submodule worktree is not reproducible deployment
evidence.

```powershell
git submodule update --init --recursive
docker compose build
docker compose up -d
```

The product is then served at `http://localhost:8080`. Run records and artifacts
are stored in the `planm-runs` named volume, while API contracts retain only
run-relative artifact paths.
