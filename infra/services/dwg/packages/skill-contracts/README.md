# @dwg/skill-contracts

Owns strict validation for versioned CAD skill manifests. Its only public
entrypoint is `@dwg/skill-contracts`; import serialized permissions from
`@dwg/contracts` through that entrypoint when needed.

Its runtime dependencies are `@dwg/contracts` and Zod. `@dwg/contracts` is its
only internal `@dwg/*` dependency. Browser code must not import this package.

Manifest text is deliberately bounded:

- ID: 64 characters; semantic version and each capability/entity type: 128
  characters.
- Purpose: 2,048 characters; each failure or limitation code: 64 characters.
- Capabilities and codes: 64 unique items each; entity types: 128 unique items.
- Permissions and formats are unique and cannot exceed their fixed public
  enums.

Workflow values, runner inputs, and capability outputs must be data-only JSON.
Only finite primitives, dense ordinary arrays, and enumerable data properties
on plain objects are accepted. Accessors, symbols, hidden properties, sparse or
extended arrays, altered prototypes, cycles, and prototype-related keys are
rejected without reading getter values.

From the repository root, run:

```powershell
node --import tsx --test packages/skill-contracts/tests/manifest.test.ts
npx tsc -p packages/skill-contracts/tsconfig.json --noEmit
```
