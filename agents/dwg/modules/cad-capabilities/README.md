# @dwg/cad-capabilities

Owns the composable read, reviewed-edit, report-export, and verified Save As
CAD capability API. Its public entrypoint is
`@dwg/cad-capabilities`; consumers must not import `src/**` or use parser and
runtime implementation folders as reusable APIs.

This package consumes only the public `@dwg/contracts`, `@dwg/cad-edit`,
`@dwg/cad-query`, `@dwg/cad-export`, and `@dwg/cad-io-acadsharp` entrypoints.
Parser composition, workspace UI, and persistence remain outside the package.
The injected source resolver owns source paths; capability callers provide only
an opaque one-use destination grant and never a path, transaction, or command
lineage.

Save As writes a server-UUID temporary sibling, closes the writer, independently
reopens the temporary drawing, and verifies version, units, hashes, entity
counts, cumulative changes, copied handles, and unaffected entity evidence.
Before writer launch, the destination is probed for writable no-replace
hard-link support. The temporary SHA-256 is computed once with bounded
64 KiB asynchronous chunks. Source and temporary-output hashing receive the
request `AbortSignal`, check it before opening or reading, between reads, and
after the final read, and close path-owned descriptors in `finally`.
Publication then uses a synchronous composite operation that revalidates
`dev`, inode, size, nanosecond modification/change times, and link count before
creating the final hard link. The temporary inode must have exactly one link
after writer return and throughout verification. Atomic publication must
produce exactly two links for the known temporary and final aliases; temporary
cleanup must then produce exactly one link. Publication never falls back to an
overwriting rename and performs no synchronous full-file hash. A second
synchronous commit validation checks source, destination-directory, final
metadata identity, and the exact final link count of one; the passed
verification is stored immediately afterward without an asynchronous yield.

The verified inode handle remains open through commit. Failed or cancelled
temporary and published aliases are removed or quarantined. If destination
movement makes an original alias unreachable, the open handle is truncated to
zero and flushed before close, `CAD_SAVE_CLEANUP_FAILED` is returned, and no
passed verification is retained. An unexpected external hard link at any
observed phase rejects the save. Cleanup never guesses or deletes its unknown
path: it neutralizes the shared inode through the retained handle, removes only
known temporary/final aliases, and returns `CAD_SAVE_CLEANUP_FAILED` while the
external alias remains with zero CAD bytes. Sanitization failure still proceeds
to descriptor close. This guarantees either disposed aliases or neutralized
residual bytes with an explicit cleanup failure. Source drawings are never
writer destinations or overwritten.

This transaction boundary protects against in-process and JavaScript event-loop
interleavings. It assumes the destination grant names an OS-writable directory
owned by the current user. A separate OS process with sufficient filesystem
privileges, including another process running as that user, can still race
between native filesystem calls. The composite detects mutations observed
before commit but does not claim an indivisible multi-file filesystem
transaction; a native hard-link creation in the final gap after the last link
count observation cannot be prevented by JavaScript. Metadata detection assumes
the filesystem reports inode, link count, `mtime`, and `ctime` changes
faithfully and that an unprivileged racing process cannot restore `ctime`.
External mutation after a successful return is outside the save transaction.

`createEditCapabilityComposition` retains at most 20 active previews per
document. Active previews expire after 10 minutes. Terminal lifecycle evidence
(`applied`, `rejected`, `stale`, `expired`, or `evicted`) is retained in a
per-document FIFO ring of 40 IDs for 10 minutes after retirement; an ID becomes
`EDIT_PREVIEW_UNKNOWN` after either TTL or ring pruning. The optional
composition-local `now()` dependency exists for deterministic tests and defaults
to `Date.now`; production preview IDs always use `node:crypto` `randomUUID()`.

Preview responses return at most 200 typed changes and 100 warnings. Exact
`changeCount`/`warningCount` totals and `changesTruncated`/`warningsTruncated`
flags disclose omitted evidence. Full snapshots and resolved engine records are
never returned.

From the repository root, run the focused parity tests with:

```powershell
node --import tsx --test modules/cad-capabilities/tests/*.test.ts
node --import tsx --test tests/roundtrip/dxf-roundtrip.test.ts
```
