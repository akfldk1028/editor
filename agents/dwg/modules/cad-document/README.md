# @dwg/cad-document

Owns engine-neutral, editable document snapshots. It accepts only the public
`CadEntityIndex` contract from `@dwg/contracts`; it never imports a CAD parser
or `modules/cad-runtime` implementation.

The package upgrades legacy `cad-index/v0.1` records to explicit v0.2 geometry
evidence. Unknown drawing metadata remains `null`; the package does not invent
CAD defaults. Imported layers have deterministic IDs based on their UTF-8 name.

Public entrypoint: `@dwg/cad-document`.

From the repository root, run:

```powershell
node --import tsx --test modules/cad-document/tests/snapshot.test.ts
npx tsc -p modules/cad-document/tsconfig.json --noEmit
```
