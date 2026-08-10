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
- `agents/runtimes/gitagent` remains a generic built runtime with no PLAN or DWG imports.
  Its built discovery API is required by every deployed PLANM stage; no user
  activation switch or LLM provider is required.
- `agents/dwg` is built from its complete vendored source. Its public
  gateway starts only for an approved CAD inspection and receives the single run
  handoff directory as `DWG_WORKSPACE`.
- DWG source is never copied into Backend Python packages and Frontend never
  receives an Agent or DWG filesystem path.

The deployable source includes the DWG workspace, runtime, parser, CAD I/O,
contracts, skills, and tests. It also retains the numeric DXF handle
normalization used by the PLAN handoff.

```powershell
docker compose build
docker compose up -d
```

The product is then served at `http://localhost:8080`. Run records and artifacts
are stored in the `planm-runs` named volume, while API contracts retain only
run-relative artifact paths.
