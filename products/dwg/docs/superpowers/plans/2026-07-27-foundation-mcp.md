# DWG Intelligence Foundation And MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize the existing CAD index code into explicit domain, parser, application, and MCP boundaries while preserving behavior and exposing all eight `cad.*` tools through a tested local stdio MCP server.

**Architecture:** The deterministic CAD runtime remains independent of MCP. A thin MCP adapter registers typed Zod schemas and converts runtime values into MCP text plus `structuredContent`. Tests use the SDK linked in-memory transport, while a separate spawned-process smoke test verifies stdio framing.

**Tech Stack:** Node.js 24, TypeScript 5.8, `dxf-parser`, `@modelcontextprotocol/sdk` v1, Zod 3, Node test runner, `tsx`.

## Global Constraints

- Source DXF/DWG files are read-only.
- All drawing facts come from CAD parser and runtime results.
- Entity results retain `id`, `handle`, `type`, `layer`, and `bbox`.
- Unsupported entities and partial parsing are surfaced, never hidden.
- `clone/` remains research-only and is not a product dependency.
- Each production behavior is preceded by a failing test.
- The existing four tests and two deterministic harness cases must remain green.

---

### Task 1: Normalize CAD Core Folders Without Behavior Changes

**Files:**
- Move: `agent/src/cad-index/types.ts` to `agent/src/domain/cad-index/types.ts`
- Move: `agent/src/cad-index/dxfIndexer.ts` to `agent/src/parsers/dxf/dxfIndexer.ts`
- Move: `agent/src/cad-tools/runtime.ts` to `agent/src/application/cad-tools/runtime.ts`
- Modify: `agent/harness/harness.test.ts`
- Modify: `agent/harness/run-case.ts`

**Interfaces:**
- Produces: `buildIndexFromDxfText(text, options): CadEntityIndex`
- Produces: `buildIndexFromDxfFileName(text, fileName): CadEntityIndex`
- Produces: `createCadToolRuntime(): { call(name, args): Promise<unknown> }`

- [ ] **Step 1: Move files with Git-aware commands**

```powershell
New-Item -ItemType Directory -Force agent/src/domain/cad-index
New-Item -ItemType Directory -Force agent/src/parsers/dxf
New-Item -ItemType Directory -Force agent/src/application/cad-tools
git mv agent/src/cad-index/types.ts agent/src/domain/cad-index/types.ts
git mv agent/src/cad-index/dxfIndexer.ts agent/src/parsers/dxf/dxfIndexer.ts
git mv agent/src/cad-tools/runtime.ts agent/src/application/cad-tools/runtime.ts
```

- [ ] **Step 2: Update imports only**

`dxfIndexer.ts` imports:

```ts
import type {
  CadEntityIndex,
  CadEntityIndexItem,
  CadPointBox
} from "../../domain/cad-index/types.js";
```

`runtime.ts` imports:

```ts
import { buildIndexFromDxfFileName } from "../../parsers/dxf/dxfIndexer.js";
import type {
  CadEntityIndex,
  CadEntityIndexItem,
  CadToolMatch
} from "../../domain/cad-index/types.js";
```

- [ ] **Step 3: Run the full existing verification**

Run:

```powershell
npm test
npm run harness -- agent/harness/cases/find-layer-a-wall.json
npm run harness -- agent/harness/cases/find-text-room.json
npx tsc --noEmit
```

Expected: 4 tests pass, layer case returns 2 matches, text case returns 1 match, TypeScript exits 0.

- [ ] **Step 4: Commit the structural boundary**

```powershell
git add agent
git commit -m "refactor: separate CAD domain parser and runtime"
```

### Task 2: Register Eight CAD Tools On An In-Memory MCP Server

**Files:**
- Create: `agent/src/mcp/toolDefinitions.ts`
- Create: `agent/src/mcp/createServer.ts`
- Create: `agent/tests/integration/mcp-server.test.ts`
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `tsconfig.json`

**Interfaces:**
- Consumes: `createCadToolRuntime()`
- Produces: `CAD_TOOL_NAMES: readonly string[]`
- Produces: `createCadMcpServer(runtime?): McpServer`

- [ ] **Step 1: Install exact MCP dependencies**

Run:

```powershell
npm install @modelcontextprotocol/sdk@^1.29.0 zod@^3.25.0
```

- [ ] **Step 2: Write a failing MCP tool-list test**

```ts
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createCadMcpServer } from "../../src/mcp/createServer.js";
import { CAD_TOOL_NAMES } from "../../src/mcp/toolDefinitions.js";

test("lists the complete deterministic CAD tool surface", async (t) => {
  const server = createCadMcpServer();
  const client = new Client({ name: "cad-test-client", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  t.after(async () => {
    await client.close();
    await server.close();
  });

  const result = await client.listTools();
  assert.deepEqual(result.tools.map((tool) => tool.name).sort(), [...CAD_TOOL_NAMES].sort());
});
```

- [ ] **Step 3: Run the test and verify RED**

Run:

```powershell
node --import tsx --test agent/tests/integration/mcp-server.test.ts
```

Expected: FAIL because `agent/src/mcp/createServer.ts` does not exist.

- [ ] **Step 4: Define the tool names and Zod input schemas**

`toolDefinitions.ts` exports definitions for:

```ts
export const CAD_TOOL_NAMES = [
  "cad.open_drawing",
  "cad.build_index",
  "cad.get_layers",
  "cad.find_entities_by_layer",
  "cad.find_entities_by_type",
  "cad.find_text",
  "cad.get_entity",
  "cad.list_unsupported"
] as const;
```

Use `z.object()` schemas with required `path`, `drawingId`, `layer`, `type`,
`query`, and `entityIdOrHandle` fields. `regex` is optional and defaults to
`false`.

- [ ] **Step 5: Implement the minimal MCP adapter**

`createServer.ts` constructs:

```ts
const server = new McpServer({
  name: "dwg-intelligence",
  version: "0.1.0"
});
```

Each `registerTool()` handler calls `runtime.call(name, args)` and returns:

```ts
{
  content: [{ type: "text", text: JSON.stringify(result) }],
  structuredContent: result as Record<string, unknown>
}
```

Caught runtime errors return:

```ts
{
  content: [{ type: "text", text: errorMessage }],
  isError: true
}
```

- [ ] **Step 6: Run the tool-list test and verify GREEN**

Run:

```powershell
node --import tsx --test agent/tests/integration/mcp-server.test.ts
```

Expected: 1 test passes.

- [ ] **Step 7: Add a failing full MCP drawing loop test**

The test must:

```ts
const opened = await client.callTool({
  name: "cad.open_drawing",
  arguments: { path: "agent/fixtures/minimal-architectural.dxf" }
});
const drawingId = (opened.structuredContent as { drawingId: string }).drawingId;

await client.callTool({
  name: "cad.build_index",
  arguments: { drawingId }
});

const found = await client.callTool({
  name: "cad.find_entities_by_layer",
  arguments: { drawingId, layer: "A-WALL" }
});
```

Assert two matches and require `id`, `handle`, `type`, `layer`, and `bbox` on
each match. Add an invalid-drawing test and assert `isError === true`.

- [ ] **Step 8: Verify RED then GREEN**

Run the focused test before completing error conversion, confirm the expected
failure, implement only the missing conversion, then rerun:

```powershell
node --import tsx --test agent/tests/integration/mcp-server.test.ts
```

Expected: all MCP integration tests pass.

- [ ] **Step 9: Commit MCP registration**

```powershell
git add package.json package-lock.json tsconfig.json agent/src/mcp agent/tests
git commit -m "feat: expose deterministic CAD tools over MCP"
```

### Task 3: Add And Verify The Stdio Entrypoint

**Files:**
- Create: `agent/src/mcp/stdio.ts`
- Create: `agent/tests/integration/mcp-stdio.test.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: `createCadMcpServer()`
- Produces: `npm run mcp`

- [ ] **Step 1: Write a failing spawned-client smoke test**

Use `StdioClientTransport`:

```ts
const transport = new StdioClientTransport({
  command: process.execPath,
  args: ["--import", "tsx", "agent/src/mcp/stdio.ts"],
  stderr: "pipe"
});
const client = new Client({ name: "stdio-smoke", version: "0.1.0" });
await client.connect(transport);
const tools = await client.listTools();
assert.equal(tools.tools.length, 8);
```

- [ ] **Step 2: Run the smoke test and verify RED**

Run:

```powershell
node --import tsx --test agent/tests/integration/mcp-stdio.test.ts
```

Expected: FAIL because `stdio.ts` does not exist.

- [ ] **Step 3: Implement the stdio process**

```ts
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createCadMcpServer } from "./createServer.js";

const server = createCadMcpServer();
await server.connect(new StdioServerTransport());
```

Do not write logs to stdout.

- [ ] **Step 4: Add the package script**

```json
"mcp": "tsx agent/src/mcp/stdio.ts"
```

- [ ] **Step 5: Run focused and full verification**

Run:

```powershell
node --import tsx --test agent/tests/integration/mcp-stdio.test.ts
npm test
npm run harness -- agent/harness/cases/find-layer-a-wall.json
npm run harness -- agent/harness/cases/find-text-room.json
npx tsc --noEmit
```

Expected: stdio smoke passes, all tests pass, both harness cases pass, TypeScript exits 0.

- [ ] **Step 6: Commit the stdio boundary**

```powershell
git add package.json agent/src/mcp/stdio.ts agent/tests/integration/mcp-stdio.test.ts
git commit -m "feat: add local stdio MCP entrypoint"
```
