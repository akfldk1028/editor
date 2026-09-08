# @dwg/cad-export

Deterministic, local report serialization for a `CadDocumentSnapshot`. This module
owns report-only application input and does not publish it through
`@dwg/contracts`; the public serialized DTOs remain in `@dwg/contracts`.

Dependencies point only to public package entrypoints: `@dwg/cad-document` for
the in-memory snapshot and `@dwg/contracts` for serialized evidence. It never
imports the workspace, runtime, parser, browser APIs, or native exporters.

`exportCadReport` produces UTF-8 JSON/CSV/SVG or text-first PDF 1.7 bytes with
stable ordering and SHA-256. CSV protects formula-leading cells, filenames are
sanitized, and every report is limited to 1 MiB. A bounded iterative preflight
rejects excessive depth, collection counts, strings, and estimated input bytes
before serialization. It also rejects malformed UTF-16 and active-ancestor
cycles while permitting shared data aliases, counted once per occurrence. Every
serializer uses an exact UTF-8 byte-accounting writer. SVG/PDF render only known
line geometry; all other geometry is explicitly reported as unsupported.

The preflight accepts only dense arrays with index data properties and the exact
standard `Array.prototype`, plus plain objects with enumerable own data
properties. Array prototypes and lengths are validated before index or property
inspection; object fields are counted incrementally with `for...in`. Report
serialization uses indexed array traversal or captured intrinsics instead of
caller-overridable array methods. Proxies are rejected through Node's proxy
detector before any user trap, and non-enumerable or symbol metadata is outside
the serialized input contract and is never inspected.

Run focused tests with:

```powershell
node --import tsx --test modules/cad-export/tests/report-export.test.ts
```
