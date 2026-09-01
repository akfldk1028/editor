# @dwg/cad-query

Grounded, deterministic read-only schedule extraction and drawing comparison.

Public entrypoint: `@dwg/cad-query`. It may depend only on `@dwg/contracts`.
It must not import parser, CAD runtime, workspace, HTTP, MCP, or provider internals.

`extractCadSchedule` derives rows only from indexed `TEXT` and `MTEXT` entities
with non-null handles and bounding boxes. It groups deterministic Y bands and
sorts cells by X; it does not infer native table rows, columns, or cells.

`compareCadDrawings` matches non-null handles first, then all unmatched
occurrences by stable ID. Occurrence indices preserve repeated references and
duplicate handle/ID queues use stable evidence order. Its serialized result
exposes only typed evidence with normalized `{ min, max }` bounding boxes.

Comparison accepts at most 4,000 entities per drawing and at most 4,000 entity
occurrences across both inputs. It throws `CAD drawing comparison input exceeds
4000 entities per drawing.` or `CAD drawing comparison work budget exceeds 4000
entity occurrences.` before allocating comparison indexes. Serialized output
remains limited to 2,000 added, removed, and changed entries combined.

The optional comparison `AbortSignal` is checked before validation, between
bounded phases, at periodic loop checkpoints, and before return. The read
capability also checks the same signal before and after execution. Comparison
is synchronous bounded work, so cancellation raised by another event-loop turn
cannot run until the current call yields.

Run focused tests:

```powershell
node --import tsx --test "modules/cad-query/tests/*.test.ts"
```
