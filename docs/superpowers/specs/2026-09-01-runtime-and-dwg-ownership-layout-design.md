# Runtime and DWG Ownership Layout Design

## Decision

`agents/` contains executable product agents only. PLAN currently has one such
agent, PLANM. Generic execution infrastructure and the independent DWG service
move to ownership-specific paths:

```text
PLAN/
|-- agents/
|   `-- planm/                    PLAN domain agent
|-- infra/
|   |-- runtimes/
|   |   `-- gitagent/             generic agent runtime
|   `-- services/
|       `-- dwg/                  independent CAD service and workspace
|-- frontend/
|-- backend/
|-- docs/
`-- resources/
```

The previous paths `agents/runtimes/gitagent` and `agents/dwg` cease to be
active source locations. `agents/` must have exactly one direct product child:
`planm/`.

## Rationale

GitAgent executes agents but is not itself a PLAN product agent. Placing it
under `infra/runtimes` states that responsibility directly. DWG is called as an
independent process after Backend approval and includes its own gateway,
workspace, parsers, and CAD I/O. Placing it under `infra/services` preserves
that process boundary without implying that PLANM owns DWG internals.

The full DWG implementation does not move inside `agents/planm`. PLANM owns its
workflow, skills, contracts, and delivery evidence; Backend owns approval and
invokes DWG through the existing adapter. Any PLANM-to-DWG data remains a
versioned public contract rather than a source import.

## Alternatives Rejected

- `agents/gitagent-runtime`: clearer than the current nesting, but still mixes
  infrastructure with actual agents.
- `agents/planm/dwg`: falsely makes the PLANM agent own an independently
  executable CAD service and weakens replacement or extraction boundaries.
- `resources/lib/{gitagent,dwg}`: places production execution code under a
  directory reserved for datasets, research, experiments, and scripts.

## Path and Contract Changes

- Root scripts build GitAgent from `infra/runtimes/gitagent`.
- Backend process configuration resolves the GitAgent export from the new
  runtime path.
- Local development, Docker, Playwright, and frontend file dependencies resolve
  DWG from `infra/services/dwg`.
- Active architecture, integration, deployment, root guidance, and memory files
  use the new paths.
- Completed historical plans and specifications may retain their original paths
  when describing the checkout that existed at that time; current guidance must
  clearly use only the new paths.
- No Python, TypeScript, or JavaScript source may import DWG or GitAgent through
  either retired path.

## Migration Safety

The migration is a history-preserving move, not a delete-and-copy operation.
Ignored dependencies and build outputs are reinstalled or rebuilt at the new
locations. Old ignored directory remnants are moved to a recoverable archive
outside the repository after confirming that Git tracks nothing beneath them.

No validation gate, PLANM workflow, Backend state ownership, or DWG public
contract changes as part of this migration.

## Verification

1. Add a structure test that fails while either retired path exists and requires
   `agents/planm`, `infra/runtimes/gitagent`, and `infra/services/dwg`.
2. Move the tracked trees and update active path references.
3. Run structure tests and stale-path scans.
4. Build and test PLANM/GitAgent, Backend, frontend, and the live product flow.
5. Run DWG `verify:all` from `infra/services/dwg`.
6. Validate Docker Compose configuration and inspect the final Git tree/status.

Success means the repository exposes one actual agent directory, all defined
verification commands pass from the new paths, retired physical source roots
are absent, and Git history records the migration in one implementation commit.
