# Host File Dialogs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the gateway a real host file dialog and use it for the export destination, so `Choose destination` stops silently resolving `DWG_EXPORT_ROOT`.

**Architecture:** A new zero-dependency workspace module, `@dwg/host-dialogs`, owns the only code that knows about a native dialog. It spawns PowerShell through an injected process runner and returns a canonical path or `null` for dismissal. The gateway supplies it as the `destinationSelector` the save path already leaves room for, and falls back to the current behaviour when no provider is available.

**Tech Stack:** TypeScript with NodeNext modules, `node:test` with `tsx`, npm workspaces, PowerShell `System.Windows.Forms` dialogs on Windows.

## Global Constraints

- Node 24+, npm workspaces; every workspace package is `"type": "module"` and `"private": true`.
- A reusable workspace must expose `src/index.ts` as its package-root export, enforced by `scripts/package-entrypoints.test.mjs`.
- Every workspace package needs an entry in `allowedDependencies` in `scripts/package-dependencies.test.mjs`, listing exactly its `@dwg/*` dependencies. A missing entry fails the suite.
- A `packages/**` surface must declare every external import it makes; `modules/**` is not covered by that guard but still must not rely on hoisting for anything it imports directly.
- Every text file is checked out LF (`.gitattributes` pins `* text=auto eol=lf`). Do not introduce CRLF.
- Error messages crossing a process or network boundary must not contain filesystem paths.
- Dismissing a dialog is an outcome, not a failure: it returns `null`, never throws.
- Run Node and .NET suites sequentially on Windows: `npm test`, then `npm run test:dotnet`, then `npm run build:frontend`.
- Browser tests need free ports; use `DWG_FRONTEND_PORT` and `DWG_GATEWAY_PORT` overrides rather than assuming 4173/4317 are free.

---

### Task 1: `@dwg/host-dialogs` module with a folder dialog

**Files:**
- Create: `modules/host-dialogs/package.json`
- Create: `modules/host-dialogs/src/contracts.ts`
- Create: `modules/host-dialogs/src/windowsDialogs.ts`
- Create: `modules/host-dialogs/src/index.ts`
- Create: `modules/host-dialogs/tests/windows-dialogs.test.ts`
- Modify: `package.json` (root `dependencies`)
- Modify: `scripts/package-dependencies.test.mjs:13-35` (`allowedDependencies`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `HostDialogProcessRunner.run(spec: { command: string; args: string[]; cwd: string; env: NodeJS.ProcessEnv; signal?: AbortSignal }): Promise<{ exitCode: number | null; stdout: string; stderr: string }>`
  - `HostDirectorySelection { canonicalDirectory: string; displayDirectory: string }`
  - `HostDialogProvider.chooseDirectory(signal?: AbortSignal): Promise<HostDirectorySelection | null>` — Task 2 adds `openDrawingFile` to this same interface
  - `class HostDialogError extends Error { readonly code: "HOST_DIALOG_FAILED" }`
  - `createWindowsHostDialogProvider(options: { runner: HostDialogProcessRunner; cwd?: string }): HostDialogProvider`

- [ ] **Step 1: Register the workspace so the policy suites see it**

`modules/host-dialogs/package.json`:

```json
{
  "name": "@dwg/host-dialogs",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "exports": {
    ".": "./src/index.ts"
  }
}
```

Add to the root `package.json` `dependencies`, keeping the keys alphabetically sorted:

```json
    "@dwg/host-dialogs": "file:modules/host-dialogs",
```

Add to `allowedDependencies` in `scripts/package-dependencies.test.mjs`, beside the other module entries:

```js
  "modules/host-dialogs": [],
```

- [ ] **Step 2: Write the failing test**

`modules/host-dialogs/tests/windows-dialogs.test.ts`:

```ts
import assert from "node:assert/strict";
import { mkdtemp, realpath } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  createWindowsHostDialogProvider,
  HostDialogError,
  type HostDialogProcessRunner
} from "../src/index.ts";

function recordingRunner(result: {
  exitCode: number | null;
  stdout: string;
  stderr: string;
}) {
  const calls: Parameters<HostDialogProcessRunner["run"]>[0][] = [];
  const runner: HostDialogProcessRunner = {
    async run(spec) {
      calls.push(spec);
      return result;
    }
  };
  return { runner, calls };
}

test("a chosen directory is returned canonically with a bare display name", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "dwg-dialog-"));
  const canonical = await realpath(directory);
  const { runner, calls } = recordingRunner({
    exitCode: 0,
    stdout: `${directory}\r\n`,
    stderr: ""
  });

  const selection = await createWindowsHostDialogProvider({ runner }).chooseDirectory();

  assert.deepEqual(selection, {
    canonicalDirectory: canonical,
    displayDirectory: canonical.split(/[\\/]/u).filter(Boolean).at(-1)
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, "powershell");
  assert.ok(calls[0].args.includes("-NoProfile"));
  assert.ok(calls[0].args.includes("-STA"));
  assert.ok(calls[0].args.at(-1)?.includes("FolderBrowserDialog"));
});

test("a dismissed dialog reports no selection rather than failing", async () => {
  const { runner } = recordingRunner({ exitCode: 0, stdout: "", stderr: "" });

  assert.equal(await createWindowsHostDialogProvider({ runner }).chooseDirectory(), null);
});

test("a failed dialog process raises a bounded error carrying no path", async () => {
  const { runner } = recordingRunner({
    exitCode: 1,
    stdout: "",
    stderr: "C:\\Users\\secret\\failed"
  });

  await assert.rejects(
    () => createWindowsHostDialogProvider({ runner }).chooseDirectory(),
    (error: unknown) => {
      assert.ok(error instanceof HostDialogError);
      assert.equal(error.code, "HOST_DIALOG_FAILED");
      assert.doesNotMatch(error.message, /secret/u);
      return true;
    }
  );
});

test("a selection that is not an existing directory reports no selection", async () => {
  const { runner } = recordingRunner({
    exitCode: 0,
    stdout: "C:\\definitely\\missing\\directory",
    stderr: ""
  });

  assert.equal(await createWindowsHostDialogProvider({ runner }).chooseDirectory(), null);
});

test("an aborted signal is refused before the dialog is spawned", async () => {
  const { runner, calls } = recordingRunner({ exitCode: 0, stdout: "", stderr: "" });
  const controller = new AbortController();
  controller.abort();

  await assert.rejects(
    () => createWindowsHostDialogProvider({ runner }).chooseDirectory(controller.signal)
  );
  assert.equal(calls.length, 0);
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `node --import tsx --test modules/host-dialogs/tests/windows-dialogs.test.ts`
Expected: FAIL — cannot resolve `../src/index.ts`.

- [ ] **Step 4: Write the contracts**

`modules/host-dialogs/src/contracts.ts`:

```ts
export interface HostDialogProcessRunner {
  run(spec: {
    command: string;
    args: string[];
    cwd: string;
    env: NodeJS.ProcessEnv;
    signal?: AbortSignal;
  }): Promise<{ exitCode: number | null; stdout: string; stderr: string }>;
}

export interface HostDirectorySelection {
  canonicalDirectory: string;
  displayDirectory: string;
}

export interface HostDialogProvider {
  chooseDirectory(signal?: AbortSignal): Promise<HostDirectorySelection | null>;
}

export class HostDialogError extends Error {
  readonly code = "HOST_DIALOG_FAILED";

  constructor() {
    // The host dialog reports the operator's filesystem in stderr; it is never
    // carried into a message that crosses a process or network boundary.
    super("The host file dialog did not complete.");
    this.name = "HostDialogError";
  }
}
```

- [ ] **Step 5: Write the Windows provider**

`modules/host-dialogs/src/windowsDialogs.ts`:

```ts
import { realpath, stat } from "node:fs/promises";
import { basename } from "node:path";

import {
  HostDialogError,
  type HostDialogProcessRunner,
  type HostDialogProvider,
  type HostDirectorySelection
} from "./contracts.js";

const FOLDER_SCRIPT = [
  "Add-Type -AssemblyName System.Windows.Forms;",
  "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;",
  "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)",
  "{ [Console]::Out.Write($dialog.SelectedPath) }"
].join(" ");

export function createWindowsHostDialogProvider(options: {
  runner: HostDialogProcessRunner;
  cwd?: string;
}): HostDialogProvider {
  const cwd = options.cwd ?? process.cwd();

  async function selectPath(script: string, signal?: AbortSignal): Promise<string | null> {
    if (signal?.aborted) throw signal.reason;
    const result = await options.runner.run({
      command: "powershell",
      args: ["-NoProfile", "-NonInteractive", "-STA", "-Command", script],
      cwd,
      env: process.env,
      signal
    });
    if (result.exitCode !== 0) throw new HostDialogError();
    const selected = result.stdout.trim();
    return selected.length === 0 ? null : selected;
  }

  return {
    async chooseDirectory(signal): Promise<HostDirectorySelection | null> {
      const selected = await selectPath(FOLDER_SCRIPT, signal);
      if (selected === null) return null;
      const canonicalDirectory = await canonicalize(selected, "directory");
      if (canonicalDirectory === null) return null;
      return {
        canonicalDirectory,
        displayDirectory: basename(canonicalDirectory)
      };
    }
  };
}

async function canonicalize(
  selected: string,
  kind: "file" | "directory"
): Promise<string | null> {
  try {
    const canonical = await realpath(selected);
    const entry = await stat(canonical);
    const matches = kind === "directory" ? entry.isDirectory() : entry.isFile();
    return matches ? canonical : null;
  } catch {
    return null;
  }
}
```

`modules/host-dialogs/src/index.ts`:

```ts
export {
  HostDialogError,
  type HostDialogProcessRunner,
  type HostDialogProvider,
  type HostDirectorySelection
} from "./contracts.js";
export { createWindowsHostDialogProvider } from "./windowsDialogs.js";
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `node --import tsx --test modules/host-dialogs/tests/windows-dialogs.test.ts`
Expected: PASS, 5 tests.

- [ ] **Step 7: Link the workspace and run the policy suites**

Run: `npm install`
Then: `npm test`
Expected: PASS. `package-dependencies`, `package-entrypoints`, and `package-external-dependencies` all accept the new workspace; total count rises by 5.

- [ ] **Step 8: Commit**

```bash
git add modules/host-dialogs package.json package-lock.json scripts/package-dependencies.test.mjs
git commit -m "feat: add a host folder dialog module"
```

---

### Task 2: Drawing file dialog

**Files:**
- Modify: `modules/host-dialogs/tests/windows-dialogs.test.ts` (append)
- Modify: `modules/host-dialogs/src/contracts.ts`
- Modify: `modules/host-dialogs/src/windowsDialogs.ts`
- Modify: `modules/host-dialogs/src/index.ts`

**Interfaces:**
- Consumes: `createWindowsHostDialogProvider`, `HostDialogProvider`, `HostDialogProcessRunner` from Task 1.
- Produces:
  - `HostDrawingSelection { canonicalPath: string; displayName: string }`
  - `HostDialogProvider.openDrawingFile(signal?: AbortSignal): Promise<HostDrawingSelection | null>` — Task 3 consumes the provider but only calls `chooseDirectory`; the second plan calls this.

- [ ] **Step 1: Write the failing tests**

Append to `modules/host-dialogs/tests/windows-dialogs.test.ts`:

```ts
test("a chosen drawing is returned canonically with its filename", async () => {
  const directory = await mkdtemp(join(tmpdir(), "dwg-dialog-file-"));
  const file = join(directory, "plan.dwg");
  await writeFile(file, "not a real drawing");
  const canonical = await realpath(file);
  const { runner, calls } = recordingRunner({ exitCode: 0, stdout: file, stderr: "" });

  const selection = await createWindowsHostDialogProvider({ runner }).openDrawingFile();

  assert.deepEqual(selection, { canonicalPath: canonical, displayName: "plan.dwg" });
  assert.ok(calls[0].args.at(-1)?.includes("OpenFileDialog"));
  assert.ok(calls[0].args.at(-1)?.includes("*.dwg;*.dxf"));
});

test("a chosen file that is not a drawing reports no selection", async () => {
  const directory = await mkdtemp(join(tmpdir(), "dwg-dialog-other-"));
  const file = join(directory, "notes.txt");
  await writeFile(file, "text");
  const { runner } = recordingRunner({ exitCode: 0, stdout: file, stderr: "" });

  assert.equal(await createWindowsHostDialogProvider({ runner }).openDrawingFile(), null);
});

test("a directory chosen where a drawing is expected reports no selection", async () => {
  const directory = await mkdtemp(join(tmpdir(), "dwg-dialog-dir-"));
  const { runner } = recordingRunner({ exitCode: 0, stdout: directory, stderr: "" });

  assert.equal(await createWindowsHostDialogProvider({ runner }).openDrawingFile(), null);
});
```

Extend the existing import so `writeFile` is available:

```ts
import { mkdtemp, realpath, writeFile } from "node:fs/promises";
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --import tsx --test modules/host-dialogs/tests/windows-dialogs.test.ts`
Expected: FAIL — `openDrawingFile` is not a function on the provider.

- [ ] **Step 3: Extend the contract**

In `modules/host-dialogs/src/contracts.ts`, add the selection type above `HostDialogProvider` and the method to the interface:

```ts
export interface HostDrawingSelection {
  canonicalPath: string;
  displayName: string;
}

export interface HostDialogProvider {
  openDrawingFile(signal?: AbortSignal): Promise<HostDrawingSelection | null>;
  chooseDirectory(signal?: AbortSignal): Promise<HostDirectorySelection | null>;
}
```

- [ ] **Step 4: Implement the drawing dialog**

In `modules/host-dialogs/src/windowsDialogs.ts`, extend the contracts import with `type HostDrawingSelection`, add the script constant beside `FOLDER_SCRIPT`:

```ts
const FILE_SCRIPT = [
  "Add-Type -AssemblyName System.Windows.Forms;",
  "$dialog = New-Object System.Windows.Forms.OpenFileDialog;",
  "$dialog.Filter = 'CAD drawings|*.dwg;*.dxf';",
  "$dialog.Multiselect = $false;",
  "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)",
  "{ [Console]::Out.Write($dialog.FileName) }"
].join(" ");
```

and add the method to the returned object, before `chooseDirectory`:

```ts
    async openDrawingFile(signal): Promise<HostDrawingSelection | null> {
      const selected = await selectPath(FILE_SCRIPT, signal);
      if (selected === null) return null;
      const canonicalPath = await canonicalize(selected, "file");
      if (canonicalPath === null) return null;
      const extension = extname(canonicalPath).toLowerCase();
      if (extension !== ".dwg" && extension !== ".dxf") return null;
      return { canonicalPath, displayName: basename(canonicalPath) };
    },
```

Extend the `node:path` import to `import { basename, extname } from "node:path";`.

In `modules/host-dialogs/src/index.ts`, add `type HostDrawingSelection` to the contracts re-export.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `node --import tsx --test modules/host-dialogs/tests/windows-dialogs.test.ts`
Expected: PASS, 8 tests.

- [ ] **Step 6: Commit**

```bash
git add modules/host-dialogs
git commit -m "feat: add a host drawing file dialog"
```

---

### Task 3: Serve the export destination from the host dialog

**Files:**
- Modify: `modules/cad-runtime/src/http/gateway.ts:28-60`
- Create: `modules/cad-runtime/tests/http/destination-selector.test.ts`
- Modify: `docs/architecture/integration-contract.md` (the `DWG_EXPORT_ROOT` note)

**Interfaces:**
- Consumes: `createWindowsHostDialogProvider`, `HostDialogProvider` from Task 1.
- Produces: `CadGatewayServerOptions.dialogs?: HostDialogProvider` — browser and integration tests pass a substituted provider through this field.

- [ ] **Step 1: Write the failing test**

`modules/cad-runtime/tests/http/destination-selector.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";

import type { HostDialogProvider } from "@dwg/host-dialogs";

import { createCadGatewayServer } from "../../src/http/gateway.ts";

async function listen(server: Awaited<ReturnType<typeof createCadGatewayServer>>) {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return `http://127.0.0.1:${address.port}`;
}

test("a granted destination comes from the host dialog when one is available", async (context) => {
  const chosen: string[] = [];
  const dialogs: HostDialogProvider = {
    async openDrawingFile() { return null; },
    async chooseDirectory() {
      chosen.push("asked");
      return { canonicalDirectory: process.cwd(), displayDirectory: "chosen-folder" };
    }
  };
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    dialogs
  });
  context.after(() => server.close());
  const base = await listen(server);

  const response = await fetch(`${base}/api/export/destination-grants`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}"
  });

  assert.equal(response.status, 200);
  assert.equal((await response.json()).displayDirectory, "chosen-folder");
  assert.deepEqual(chosen, ["asked"]);
});

test("a dismissed dialog answers the documented cancellation error", async (context) => {
  const dialogs: HostDialogProvider = {
    async openDrawingFile() { return null; },
    async chooseDirectory() { return null; }
  };
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    dialogs
  });
  context.after(() => server.close());
  const base = await listen(server);

  const response = await fetch(`${base}/api/export/destination-grants`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}"
  });

  assert.equal(response.status, 409);
  assert.equal((await response.json()).error.code, "DESTINATION_SELECTION_CANCELLED");
});

test("without a dialog the export root keeps serving destinations", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf"
  });
  context.after(() => server.close());
  const base = await listen(server);

  const response = await fetch(`${base}/api/export/destination-grants`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}"
  });

  assert.equal(response.status, 200);
  assert.equal((await response.json()).displayDirectory, "Exports");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --import tsx --test modules/cad-runtime/tests/http/destination-selector.test.ts`
Expected: FAIL — `dialogs` is not a known option, and the first test reports `Exports` instead of `chosen-folder`.

- [ ] **Step 3: Accept a dialog provider in the gateway**

In `modules/cad-runtime/src/http/gateway.ts`, add the import beside the other module imports:

```ts
import type { HostDialogProvider } from "@dwg/host-dialogs";
```

Add the field to `CadGatewayServerOptions`:

```ts
  /** Supplies host dialogs. Omitted in headless runs, where the export root serves destinations. */
  dialogs?: HostDialogProvider;
```

Pass a selector into `createCadApplication`, immediately after `dwgVersionManifestPath`:

```ts
    destinationSelector: options.dialogs
      ? { request: (signal) => options.dialogs!.chooseDirectory(signal) }
      : undefined,
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --import tsx --test modules/cad-runtime/tests/http/destination-selector.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 5: Record the behaviour**

`modules/cad-runtime` has no `package.json`; it is owned by the repository root and is not a workspace package, so `allowedDependencies` needs no entry and `scripts/package-dependencies.test.mjs` is not touched by this task. The root manifest already lists `@dwg/host-dialogs` from Task 1, which is what makes the import resolve.

In `docs/architecture/integration-contract.md`, replace the sentence beginning "A host repository must set `DWG_EXPORT_ROOT`" with:

```markdown
A host repository must set `DWG_EXPORT_ROOT`. The default resolves inside this
repository's local test-results directory, which is gitignored and per-process.
It is the destination whenever no host dialog is supplied, which is every
headless and test run; with a dialog the operator chooses the directory and
`DWG_EXPORT_ROOT` is unused.
```

- [ ] **Step 6: Run the full suite**

Run: `npm test`
Then: `npm run test:dotnet`
Then: `npm run build:frontend`
Then: `DWG_FRONTEND_PORT=4193 DWG_GATEWAY_PORT=4337 npm run test:e2e`
Expected: Node passes with 3 more tests than Task 2 left, .NET 11/11 and 61/61, frontend build succeeds, browser suite 60 passed and none skipped. The browser suite supplies no dialog, so `Choose destination` keeps resolving the export root.

- [ ] **Step 7: Commit**

```bash
git add modules/cad-runtime/src/http/gateway.ts modules/cad-runtime/tests/http/destination-selector.test.ts docs/architecture/integration-contract.md
git commit -m "feat: choose the export destination through a host dialog"
```

---

## What this plan does not cover

Opening a drawing needs the session registry, the one-use source grant, the four `/api/drawings/*` routes, and the workspace UI feature described in `docs/superpowers/specs/2026-08-03-host-file-dialogs-design.md`. That is a second plan, written after this one lands, and it consumes `HostDialogProvider.openDrawingFile` which Tasks 1 and 2 deliver and test here.
