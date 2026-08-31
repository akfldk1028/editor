# @dwg/skill-runtime

Discovers local CAD skill data packages through the public
`@dwg/skill-contracts` manifest parser. Its public entrypoint is
`@dwg/skill-runtime`.

Skill roots must remain canonically contained below the supplied discovery
directory and contain both `SKILL.md` and `manifest.json`. Instructions are
limited to 64 KiB. Both required files must be strict UTF-8: malformed or
truncated byte sequences and an initial UTF-8 BOM are rejected before parsing,
and replacement-character decoding is never used. Discovery uses the public
`@dwg/skill-contracts` and `@dwg/cad-capabilities` package entrypoints only; it
must never import CAD runtime, parser, HTTP, MCP, workspace, or provider
internals.

Incompatible capability contracts remain visible with the stable
`CAPABILITY_CONTRACT_MISMATCH` reason and are not executable by a later runtime
stage.

## Declarative workflows

`runCadSkillWorkflow` executes at most 32 ordered data-only steps through the
public `@dwg/cad-capabilities` runtime. A step may reference the initial input
with `$input` or `$input.field`, and only an earlier passed step with
`$steps.<step-id>.output` or `$steps.<step-id>.output.field`. Property segments
are own safe JSON object keys; array, prototype, constructor, and forward
references are rejected. Resolved values are deeply copied before a capability
receives them.

Read capabilities require `read`; `edit.preview` requires `propose-edit`; apply,
undo, and redo are never workflow-executable. A capability must be listed in the
compatible skill manifest and its required permission must be both declared and
granted. The same supplied `AbortSignal` is forwarded to every capability call.
Runs return only bounded error codes, validate the final output against the
manifest output JSON Schema, and never exceed one MiB of UTF-8 JSON. If the
ordinary result cannot fit, the runner replaces it with a fixed
`bounded-skill-result` identifier and bounded status-specific error. Invalid
manifest or input data also returns only fixed error codes; capability
exceptions and rejected data are never copied into failures.

From the repository root, run focused tests with:

```powershell
node --import tsx --test modules/skill-runtime/tests/discovery.test.ts
node --import tsx --test modules/skill-runtime/tests/workflow-runner.test.ts
npx tsc -p modules/skill-runtime/tsconfig.json --noEmit
```
