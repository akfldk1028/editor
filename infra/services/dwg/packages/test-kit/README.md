# @dwg/test-kit

Owns reusable fixture integrity and deterministic CAD-index invariant helpers
for repository tests. Its sole public entrypoint is `@dwg/test-kit`; consumers
must not deep-import `src` files.

The package depends only on `@dwg/contracts`. Install all workspace
dependencies from the repository root, then run:

```powershell
node --import tsx --test packages/test-kit/tests/fixtures.test.ts
npx tsc -p packages/test-kit/tsconfig.json --noEmit
```
