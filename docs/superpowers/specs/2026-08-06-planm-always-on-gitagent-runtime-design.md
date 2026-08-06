# PLANM Always-On GitAgent Runtime Design

## Purpose

Every deployed PLANM run must pass through the PLANM Agent package and the
generic GitAgent runtime. Users do not select or activate an Agent mode. The
product must continue to generate, review, approve, and deliver plans when no
LLM provider is configured.

## Non-Negotiable Boundaries

- Frontend calls only the Backend HTTP API.
- Backend owns run state, project ownership, artifacts, approval, and optional
  post-approval DWG orchestration.
- `agents/planm` owns identity, contracts, skills, workflow, memory, and its
  deployment runtime host.
- `external/gitagent-runtime` remains generic and imports no PLANM, Backend, or
  DWG product code.
- PLANM Agent imports no Backend modules and contains no Backend filesystem
  path.
- DWG remains an independent submodule and process.
- No user-facing runtime mode or activation flag is introduced.

## Runtime Architecture

```text
Frontend
  -> Backend run API
     -> Backend PLANM process adapter
        -> agents/planm/runtime/gitagent_host.mjs
           -> generic GitAgent workflow and skill discovery
              -> selected PLANM skill script
                 -> agents/planm/runtime/planm_bridge.py
                    -> Backend-injected deterministic execution command
```

The Backend adapter always invokes `gitagent_host.mjs`. It no longer invokes
the Python bridge directly. The host loads the checked-in PLANM workflow and
skills through public generic-runtime exports, verifies that the requested
stage maps to the declared workflow step, then executes only that skill's
checked-in script.

## Deterministic Continuity

GitAgent runtime participation does not require an LLM call. Identity,
workflow, skill discovery, bounded stage dispatch, and provenance are runtime
responsibilities that work without provider credentials. The deterministic
PLAN engine remains authoritative for geometry and validation.

An LLM provider may later add advisory reasoning through the same Agent
package, but it cannot replace hard gates, mutate geometry directly, or become
a prerequisite for the deployed run path. This change does not add provider
selection or model fallback behavior.

## Process Contract

Backend launches the host with:

- repository-relative PLANM Agent directory;
- one stage name;
- input, state, and output paths already constrained to the Backend-owned run;
- `PLANM_ENGINE_COMMAND_JSON` and `PLANM_ENGINE_CWD` injected by Backend;
- bounded outer and inner timeouts.

The host must:

1. reject unknown stages and unknown workflow or skill identities;
2. load workflow and skill metadata through generic-runtime public exports;
3. resolve scripts only beneath the canonical PLANM Agent directory;
4. use `spawn` without a shell;
5. forward stdout, stderr, exit code, cancellation, and timeout;
6. emit no secrets or absolute paths in the product result;
7. preserve the existing `skill-result/v1` response unchanged.

## Failure Semantics

- Missing runtime build, malformed workflow, missing skill, escaped script, or
  invalid runtime metadata blocks the run with an explicit infrastructure
  violation. It must not silently bypass the Agent path.
- Missing LLM credentials is not an error because the required path is
  deterministic.
- Skill timeout and engine timeout retain their existing bounded result codes.
- Backend remains the only component that translates process failure into run
  status.

## Deployment

The Backend image already builds `external/gitagent-runtime/dist`. The image
must also include the PLANM host and invoke Node from the copied runtime. No
additional service, port, API key, or user configuration is required.

## Verification

- Unit test: every PLANM stage maps to exactly one declared workflow skill.
- Boundary test: Backend adapter invokes only the Node host.
- Boundary test: host imports generic runtime but no Backend or DWG code.
- Boundary test: generic runtime imports no PLANM product code.
- Failure tests: unknown stage, missing skill, escaped script, timeout, and
  malformed result are explicit and bounded.
- E2E: normalize through deliver succeeds through the host without model keys.
- Product API: create, alternatives, approval, download, and optional DWG remain
  unchanged.
- Compose: a fresh deployed run proves the complete path.

## Out of Scope

- User-selectable Agent modes.
- Making an LLM provider mandatory.
- Moving PLAN domain geometry into GitAgent runtime.
- Direct PLANM-to-DWG calls.
- Frontend awareness of Agent or runtime locations.
