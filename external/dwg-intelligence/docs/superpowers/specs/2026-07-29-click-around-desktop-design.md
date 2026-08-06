# Click Around Desktop design

Status: approved for implementation planning
Date: 2026-07-29
Product: Click Around
CAD engine: DWG Intelligence

## Goal

Ship a Windows desktop application that lets a user create a local profile,
link a local project folder, inspect DWG/DXF drawings, control layers, and use
an installed Codex or Claude CLI subscription without uploading drawings or
requiring a separate API key.

The current DWG workspace, deterministic CAD evidence, CLI OAuth flows, and
three-panel UI remain the proven baseline. The migration must make those parts
independently reusable by another repository without introducing cross-module
imports or hidden current-working-directory assumptions.

## Release scope

The first release is a Windows 10/11 x64 desktop application built with
Electron Forge. It contains:

- a local display-name profile with no password;
- local project-folder linking;
- local DWG/DXF indexing and inspection;
- drawing-tree and layer visibility controls;
- the existing three-panel conversation and CAD artifact workspace;
- installed Codex and Claude CLI discovery, authentication status, new chat,
  cancellation, and session resume;
- SQLite persistence for profiles, projects, drawing references, sessions,
  messages, inspection results, and preferences;
- a Squirrel.Windows `Setup.exe`;
- deterministic unit, contract, integration, desktop, and visual test gates.

The first release does not contain cloud accounts, Supabase, Kimi or other
hosted model APIs, DWG upload, raw DWG storage in SQLite, automatic updates, or
silent installation of provider CLIs. Release signing is required before
public distribution; unsigned packages are development artifacts only.

## Architectural strategy

The repository uses two levels of modularity.

First, existing trees move as whole modules so history and behavior remain
reviewable:

```text
apps/
  workspace/                 # existing React workspace
modules/
  cad-runtime/               # existing TypeScript agent/CAD runtime
  dwg-parser/                # existing .NET parser
packages/
  contracts/                 # existing stable wire contracts
```

Second, behavior is separated behind domain ports without changing the
external contracts:

```text
apps/
  desktop/
    main/
    preload/
    installer/
  workspace/
    app/
    features/
    shared/bridge/
domains/
  drawings/
    model/
    ports/
    services/
  inspections/
    model/
    ports/
    services/
  conversations/
    model/
    ports/
    services/
  projects/
  profiles/
  settings/
adapters/
  inbound/
    desktop-ipc/
    loopback-http/
    mcp-stdio/
  outbound/
    drawings/
      dwg-acadsharp/
      dxf-parser/
      local-workspace/
    assistants/
      cli-core/
      codex-cli/
      claude-cli/
    persistence/
      sqlite/
packages/
  contracts/
  desktop-bridge/
  test-kit/
composition/
  desktop/
  gateway/
  mcp/
  test/
fixtures/
tests/
docs/
scripts/
```

Only directories backed by working code are added. Future web, cloud API,
Supabase, and hosted-model adapters are documented boundaries, not empty
scaffolding.

## Dependency rules

- Domain modules depend only on their own model and ports, plus
  `@dwg/contracts` where a stable external shape is required.
- Outbound adapters implement domain ports and may depend inward on domains.
- Inbound adapters translate IPC, HTTP, or MCP requests into domain calls.
- UI code imports only `@dwg/contracts` and `@click-around/desktop-bridge`.
- Composition roots are the only code allowed to import both domain services
  and concrete adapters.
- A domain must never import an adapter, Electron, Express, MCP transport,
  SQLite driver, parser implementation, or provider CLI implementation.
- One composition root exists for each execution mode: desktop, loopback
  gateway, MCP stdio, and tests.
- No service creates a concrete adapter as a default. Every parser, provider,
  repository, clock, process runner, and filesystem dependency is injected.
- Cross-module relative imports are forbidden. Public package entry points are
  the only cross-module import surface.
- A boundary checker validates these rules, including aliases and dynamic
  imports.

The `ChatProvider` interface belongs to the conversations domain. Codex and
Claude implement that port. CAD query behavior belongs to drawing services;
parser selection and filesystem access belong to outbound adapters. Provider
registration belongs to composition, not to a domain.

## Desktop runtime

Electron Forge owns packaging and the desktop lifecycle. The renderer remains
the React workspace and is not granted direct Node.js access.

- `contextIsolation` is enabled.
- `nodeIntegration` is disabled.
- renderer sandboxing is enabled.
- the preload exposes a typed, allowlisted bridge only.
- there is no generic `invoke(channel, payload)` renderer API.
- IPC validates request and response contracts at the boundary.
- file and folder selection is initiated through native dialogs in the main
  process.
- navigation, new-window creation, and external URL opening are deny-by-default.
- provider processes and the .NET sidecar run without shell interpolation.
- environment and output logs are redacted before diagnostics are retained.

Development uses the Vite renderer. Packaged loading uses relative assets or a
safe application protocol; it must not depend on a development HTTP server.
The published .NET parser is copied into the application resources and resolved
from `process.resourcesPath`. Packaged code never executes `dotnet run`.

Codex and Claude executables are detected from the current user's `PATH`.
They are never bundled. The application reports missing CLI and unauthenticated
CLI states separately and gives the user an explicit retry action.

## Domain ports

Required stable ports are:

- `DrawingIndexerPort`: index a local source and return deterministic
  `cad-index/v0.2` evidence.
- `DrawingSourcePort`: resolve an allowlisted project-relative source without
  exposing arbitrary filesystem access.
- `AssistantProviderPort`: status, send, resume, cancel, and bounded output.
- `ProfileRepositoryPort`: create, read, and update the local profile.
- `ProjectRepositoryPort`: store project metadata and local root association.
- `ConversationRepositoryPort`: store conversations and ordered messages.
- `InspectionRepositoryPort`: store grounded inspection results.
- `PreferenceRepositoryPort`: store profile-scoped UI and runtime preferences.
- `TransactionPort`: execute repository changes atomically.

Each outbound implementation must pass the same contract suite as its fake
implementation. Tests may not rely on a concrete adapter's private methods.

## Local profile and SQLite

SQLite is the only application database in the first release.
`better-sqlite3` is used through the persistence adapter and rebuilt for the
target Electron runtime by Forge. The native module is unpacked from ASAR when
required.

Identifiers are UUIDs so a future sync adapter can preserve identity. Dates are
UTC ISO-8601 strings. Foreign keys are enabled. Migrations are append-only and
run in a transaction before repositories become available.

Initial logical schema:

```text
schema_migrations(
  version primary key,
  applied_at
)

profiles(
  id primary key,
  display_name not null,
  created_at not null,
  updated_at not null
)

projects(
  id primary key,
  profile_id references profiles,
  name not null,
  local_root not null,
  created_at not null,
  updated_at not null
)

drawings(
  id primary key,
  project_id references projects,
  relative_path not null,
  source_fingerprint not null,
  drawing_id,
  last_seen_at,
  unique(project_id, relative_path)
)

conversations(
  id primary key,
  project_id references projects,
  provider not null,
  provider_session_id,
  title not null,
  created_at not null,
  updated_at not null
)

messages(
  id primary key,
  conversation_id references conversations,
  role not null,
  content not null,
  created_at not null
)

inspection_runs(
  id primary key,
  drawing_id references drawings,
  contract_version not null,
  result_json not null,
  created_at not null
)

preferences(
  profile_id references profiles,
  key not null,
  value_json not null,
  updated_at not null,
  primary key(profile_id, key)
)
```

`local_root` is device-local metadata and is excluded from any future cloud
sync payload. Drawing rows contain only a relative path, fingerprint, and
derived identifiers. Raw DWG/DXF bytes, OAuth tokens, provider credentials,
and environment snapshots are forbidden in SQLite.

## Primary flows

### Create profile and link project

1. The renderer requests profile creation through the typed bridge.
2. The profile service validates a non-empty display name.
3. The desktop main process opens a native folder dialog.
4. The project service records the selected local root through the repository.
5. The drawing source adapter enumerates supported files beneath that root.
6. The renderer receives project and drawing metadata, never unrestricted
   filesystem capabilities.

### Open and inspect a drawing

1. The renderer sends project and drawing identifiers.
2. The drawing service resolves the project-relative path.
3. The source adapter verifies the resolved path remains under the linked root.
4. The selected parser adapter produces deterministic `cad-index/v0.2`.
5. The service verifies the source fingerprint and persists derived metadata.
6. The artifact panel renders geometry, tables, overview content, drawing tree,
   layers, handles, types, bounding boxes, and warnings.
7. Layer visibility changes remain renderer state and do not modify the source.

### Start or resume an assistant session

1. The renderer selects Codex or Claude and submits a prompt.
2. The conversation service calls the injected `AssistantProviderPort`.
3. The CLI adapter supplies bounded, grounded CAD context and starts or resumes
   the provider session.
4. Messages, provider name, and provider session identifier are committed in
   one transaction.
5. Restarting the desktop reloads the same project and conversation from
   SQLite and can explicitly resume the provider session.

## Error behavior

Errors cross boundaries as stable codes with user-safe messages and optional
redacted diagnostics.

- missing provider CLI and unauthenticated provider CLI are distinct;
- invalid, unsupported, or corrupt drawings do not create successful index
  records;
- moved or changed files produce missing-source or fingerprint-mismatch states;
- paths escaping the linked project root are rejected;
- provider timeout, cancellation, non-zero exit, malformed output, and output
  limit are distinct;
- parser sidecar crash returns a bounded failure and leaves the source intact;
- a failed migration rolls back and prevents application data access;
- database corruption never triggers destructive automatic replacement;
- renderer reload and desktop restart do not duplicate profile, project,
  drawing, message, or inspection rows.

Diagnostics may include stack traces, contract versions, fixture identifiers,
source SHA-256, parser summaries, SQLite schema version, and Playwright traces.
They may not include CAD file contents, access tokens, session secrets, full
environment dumps, or unredacted prompts and provider output.

## Verification harness

The harness is organized by responsibility:

```text
tests/
  harness/
    scenarios/
    contracts/
    support/
  fixtures/
    manifest.json
  integration/
    parser/
    process/
    ipc/
    sqlite/
  e2e/
    desktop/
  installer/
    windows/
  live-oauth/
  visual/
packages/
  test-kit/
```

Contract suites cover every domain port. SQLite tests use a fresh temporary
database and cover migrations, reopen, rollback, foreign keys, uniqueness,
fingerprints, busy handling, corruption handling, and the raw-drawing
prohibition. Provider tests place fake executables on a temporary `PATH` and
cover status, JSON, JSONL, malformed data, timeout, abort, output limits, exit
codes, environment filtering, and redaction.

Desktop Playwright tests launch Electron with an isolated user-data directory,
workspace, and database. They run with one worker. Tests cover profile creation,
folder linking, real fixture indexing, three-panel rendering, drawing tree,
layer hide/show, provider selection, fake session resume, restart persistence,
and safe error states.

Visual tests use fake adapters, a fixed 1440x900 viewport, device scale factor
1, bundled fonts, `ko-KR`, `Asia/Seoul`, disabled animation, and
`document.fonts.ready`. Captures are written outside tracked baselines.
Two consecutive captures of the same state must hash identically before a
baseline can be updated. Generated PNGs are inspected, not accepted only from
process exit status.

Live OAuth tests are opt-in, serial, and separated from deterministic gates.
They verify the currently installed Codex and Claude CLI subscriptions without
recording tokens, raw provider sessions, prompts, or responses.

Required commands:

```text
test:unit
test:contracts
test:adapters
test:parser
test:process
test:desktop
test:visual
test:installer
test:live-oauth
verify:fast
verify:desktop
verify:release
```

`verify:fast` runs unit, contracts, boundaries, and type checking.
`verify:desktop` adds adapters, parser, process, IPC, SQLite, and desktop E2E.
`verify:release` adds deterministic visual, packaging, and installer smoke
tests. Live OAuth remains an explicit environment-dependent verification.

A failed scenario retains a redacted diagnostic bundle containing relevant
logs, Playwright trace and screenshots, schema and migration version, parser
summary, and fixture hash. It never copies the user's drawing or credentials.

## Migration sequence and gates

Every phase ends with a green verification gate and its own commit.

1. Record the current test totals, fixture hashes, visual captures, and live
   OAuth evidence.
2. Introduce an npm workspace with one root lockfile and preserve current
   commands through compatibility scripts.
3. Move the React workspace, TypeScript CAD runtime, .NET parser, and contracts
   as whole subtrees with `git mv`.
4. Replace current-working-directory assumptions with explicit repository,
   fixture, application-resource, and user-data path resolvers.
5. Consolidate fixtures and update parser, Playwright, capture, and generator
   paths.
6. Extend the boundary checker for the new module roots, aliases, package
   exports, and dynamic imports.
7. Define domain ports, move one behavior boundary at a time, and remove all
   concrete default construction from services.
8. Add composition roots and shared adapter contract suites.
9. Add the SQLite adapter and migrate existing browser session preferences
   without deleting the compatibility data until verified.
10. Add the Electron main, typed preload bridge, renderer integration, and
    packaged .NET sidecar.
11. Add desktop, visual, package, and Windows installer verification.
12. Run deterministic gates, inspect retained PNGs, run opt-in live OAuth, and
    produce the release candidate.

Electron, SQLite, folder moves, and internal domain extraction are never mixed
in one review commit.

## Failure delegation

When a gate fails, one read-only diagnosis is assigned per ownership boundary:

- module/import failures: module-boundary diagnosis;
- paths, parser publishing, and sidecar failures: packaging diagnosis;
- migrations and repository failures: persistence diagnosis;
- Electron lifecycle, preload, and IPC failures: desktop diagnosis;
- Playwright and PNG differences: visual diagnosis.

Diagnoses do not make overlapping edits. The primary implementation agent owns
the fix, reruns the complete gate, and advances only after it is green.
External research is performed with direct documentation or web tools, not
agent subprocesses.

## Future extension boundaries

A future web product may add `apps/web` and `apps/cloud-api`. Supabase may
implement the repository ports for cloud-safe records, and Kimi or other hosted
providers may implement `AssistantProviderPort`. Those adapters must not change
the desktop domains.

Because a browser cannot directly inherit an arbitrary visitor's local CLI
subscription or filesystem access, the pure web product will require an
explicit desktop companion, BYOK, or hosted provider account. The desktop
release does not claim that local Codex or Claude subscription authentication
can be transparently reused by a deployed website.

## Acceptance criteria

The design is implemented when a clean Windows test environment can:

1. install and launch Click Around Desktop;
2. create and reopen one local profile;
3. link a folder without granting access outside it;
4. index a real DWG fixture while its source SHA-256 remains unchanged;
5. render grounded geometry, overview/table content, drawing tree, and layers;
6. hide and restore layers through the UI;
7. start and resume fake-provider sessions deterministically;
8. start and resume installed Codex and Claude subscription sessions in the
   opt-in live gate;
9. persist project, drawing, conversation, inspection, and preferences across
   desktop restart without duplicates;
10. pass unit, contract, adapter, parser, process, IPC, SQLite, desktop,
    deterministic visual, package, and installer gates;
11. uninstall without deleting user drawings;
12. expose no cloud dependency, bundled credential, raw drawing database blob,
    generic renderer IPC, or forbidden cross-module import.
