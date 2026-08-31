# @dwg/cad-edit

Produces deterministic, atomic in-memory previews of versioned CAD edit
commands. Its public entrypoint is `@dwg/cad-edit`.

The module depends only on `@dwg/contracts` and `@dwg/cad-document`. It clones
the supplied document snapshot, validates every revision and precondition, and
returns typed public diffs plus the preview snapshot. It does not write CAD
files, access a writer, parser, `cad-runtime`, or a workspace implementation.

Copies have no final CAD handle: their deterministic temporary ID is
`copy:<transactionId>:<commandId>:<entityIndex>` until a future writer assigns
one. A collision with an input or earlier planned copy ID rejects the complete
batch before command application.

Every operation target requires its own scoped precondition. A layer creation
specifically requires `exists:false` for its new layer ID. Multi-target
operations emit one typed resolved-command record per target. Existing warning
evidence from each edited entity is sorted and de-duplicated on that resolved
record; preview warnings are the sorted, de-duplicated union for edited targets
only.

History consumers that need exact undo/redo response metadata use
`undoWithTransaction` and `redoWithTransaction`. Each transition returns the
new defensive document snapshot and the exact defensive committed transaction
from the active/redo lineage, independent of the bounded UI history window.

From the repository root, run:

```powershell
npm run test:edit
npx tsc -p modules/cad-edit/tsconfig.json --noEmit
```
