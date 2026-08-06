# Host file dialogs and drawing sessions

## Problem

The workspace cannot open a drawing. The active drawing is fixed when the
gateway starts, from `DWG_DRAWING_PATH`, and changing it means restarting the
process. There is no control in the product that selects one.

Export implies a picker that does not exist. `Choose destination` calls
`requestDestinationGrant`, which falls back to `DWG_EXPORT_ROOT` whenever no
`destinationSelector` is supplied, and the gateway never supplies one
(`createCadApplication.ts`). The button reads as a file dialog and is a fixed
folder.

A browser file picker cannot close either gap. The gateway reads drawings from
disk by path; `showOpenFilePicker` yields a handle, not a path. The dialog has
to run in the gateway process, which is what the unused `destinationSelector`
injection point was left for.

## Decisions

Settled before design:

- **Several drawings stay open at once.** Choosing another drawing adds a
  session and switches to it rather than replacing the active document. Each
  session owns its edit history and its grants.
- **A drawing chosen outside `DWG_WORKSPACE` is admitted through a one-use
  read grant** for that exact file, mirroring the existing one-use destination
  grant. The workspace root keeps its meaning for every other path.
- **The dialog adapter is its own module** so tests can substitute it.

## Architecture

The gateway process owns a session registry. One session is one
`CadApplication`, which is one drawing.

The browser never sends a path. `POST /api/drawings/open` carries an empty
body; the gateway opens the dialog, and a human selects the file. No path from
the network surface reaches the reader, so the loopback API gains no new way to
name a file on disk.

```text
UI "Open drawing" ──POST /api/drawings/open (empty body)──▶ gateway
                                                             │ HostDialogProvider.openDrawingFile()
                                                             │ native dialog, human selects
                                                             ▼
                              inside DWG_WORKSPACE? ──yes──▶ resolveWorkspaceCadPath
                                       └──no──▶ source grant issued and consumed
                                                             ▼
                                              session created, becomes active
```

The source grant is a server-side consent record, not a token the client
holds. Issue and consume happen inside the one request. It exists so that
admitting a file from outside the workspace runs through a single checked
place: canonical `realpath`, regular file, `.dwg` or `.dxf`, one use only.

## Modules

| Location | Responsibility | Dependencies |
|---|---|---|
| `modules/host-dialogs` (new, `@dwg/host-dialogs`) | `HostDialogProvider` contract and its Windows implementation | none |
| `modules/cad-capabilities/src/sourceGrants.ts` | one-use read consent for a file outside the workspace | unchanged |
| `modules/cad-runtime/src/application/sessions/` | session registry, active session, limit of eight | owns `CadApplication` |
| `modules/cad-runtime/src/http/drawingSessionGateway.ts` | `/api/drawings/*` | the two above |
| `packages/contracts/src/session.ts` | public DTOs and error codes | `zod` |
| `apps/workspace/src/features/drawing-sessions/` | open control and session list | `shared/api` only |

The dialog adapter is separated because it shells out to the host and cannot
run in CI. Everything above it is tested against a substituted provider. The
session registry stays in `cad-runtime` because it holds `CadApplication`
instances; moving it out would make a module depend on `@dwg/cad-runtime`,
which `scripts/package-dependencies.test.mjs` rejects.

## Contracts

```ts
export interface HostDialogProvider {
  openDrawingFile(signal?: AbortSignal): Promise<{
    canonicalPath: string;
    displayName: string;
  } | null>;
  chooseDirectory(signal?: AbortSignal): Promise<{
    canonicalDirectory: string;
    displayDirectory: string;
  } | null>;
}
```

`null` means the person dismissed the dialog. Dismissal is an outcome rather
than a failure, and it follows the precedent already set by destination
selection: the route answers `409` with `DRAWING_OPEN_CANCELLED`, and the UI
treats that one code as a no-op instead of raising an alert.

The Windows implementation spawns PowerShell through the existing
`CadProcessRunner` seam, filters `*.dwg;*.dxf`, and reads a single path from
stdout. It is the only file in the repository that knows about a host dialog.

Routes:

| Route | Body | Returns |
|---|---|---|
| `POST /api/drawings/open` | empty | the created session, now active |
| `GET /api/drawings/sessions` | — | sessions and the active session id |
| `POST /api/drawings/sessions/:id/activate` | empty | the activated session |
| `DELETE /api/drawings/sessions/:id` | — | the remaining sessions |

Error codes: `DRAWING_OPEN_CANCELLED`, `DRAWING_UNSUPPORTED`,
`DRAWING_NOT_FOUND`, `SESSION_UNKNOWN`, `SESSION_LIMIT`, `DIALOG_UNAVAILABLE`.

## Compatibility

- With `DWG_DRAWING_PATH` set, or with its repository default, that drawing
  boots as the first session. Current behaviour is unchanged.
- `GET /api/drawing` returns the active session's index, so every existing
  route and all sixty browser tests keep working.
- With no dialog provider, which is every headless and test run, export
  destinations keep resolving to `DWG_EXPORT_ROOT` and the open control reports
  `DIALOG_UNAVAILABLE` and stays disabled.
- Drawing export keeps the pairing rule already in place: a session offers the
  format its own source was read as.

## Export destination

`chooseDirectory` is supplied as the `destinationSelector` the gateway never
provided. The change is in gateway assembly, not in the save path, and
`Choose destination` starts opening a real folder dialog.

## Errors

| Condition | Behaviour |
|---|---|
| dialog dismissed | nothing changes, no alert |
| unsupported extension or missing file | bounded message naming neither the path nor the directory |
| dialog provider absent | control disabled, reason in its tooltip |
| eight sessions already open | `SESSION_LIMIT`, the person closes one first |

Messages carry no filesystem paths, matching the existing export errors.

## Testing

- `host-dialogs`: PowerShell argument construction, dismissal, non-zero exit,
  extension filter, all against a substituted process runner.
- `sourceGrants`: expiry, reuse, directory instead of file, unsupported
  extension.
- session registry: limit, activation, and that an edit in one session does not
  reach another.
- gateway: route contracts and error mapping against a substituted provider.
- browser: opening and switching through a test provider; the sixty existing
  tests stay green.

## Out of scope

Cross-format Save As. A session still exports only the format its source was
read as, and the ACadSharp bounding box difference behind that stays open.
