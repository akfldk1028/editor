import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import {
  CAD_APPLICATION_CAPABILITY_NAMES,
  createCadApplication
} from "../../src/application/createCadApplication.js";
import { createCadToolRuntime } from "../../src/application/cad-tools/runtime.js";
import { createCadMcpServer } from "../../src/mcp/createServer.js";
import { CAD_TOOL_NAMES } from "../../src/mcp/toolDefinitions.js";
import { defaultProcessRunner } from "../../src/providers/cli/processRunner.js";

test("first open establishes one document lineage for inspect edit report and verified Save As", async (t) => {
  const exportRoot = await mkdtemp(join(tmpdir(), "cad-application-lineage-"));
  t.after(() => rm(exportRoot, { force: true, recursive: true }));
  const application = await createCadApplication({
    workspaceRoot: process.cwd(),
    exportRoot,
    dwgVersionManifestPath: resolve(
      "tests/fixtures/dwg/roundtrip-manifest.json"
    ),
    processRunner: {
      async run(spec, signal) {
        const result = await defaultProcessRunner.run({
          command: spec.command,
          args: spec.args,
          cwd: spec.cwd,
          env: process.env,
          stdin: spec.stdin,
          signal
        });
        return {
          exitCode: result.exitCode ?? -1,
          stdout: result.stdout,
          stderr: result.stderr
        };
      }
    }
  });

  const opened = await application.capabilities.execute("document.open", {
    path: "tests/fixtures/dxf/minimal-architectural.dxf"
  }) as { drawingId: string };
  const described = await application.capabilities.execute("document.describe", {
    drawingId: opened.drawingId
  }) as { drawingId: string };
  assert.equal(described.drawingId, opened.drawingId);

  const preview = await application.capabilities.execute("edit.preview", {
    batch: {
      schemaVersion: "cad-edit/v1",
      transactionId: "66666666-6666-4666-8666-666666666666",
      documentId: opened.drawingId,
      expectedRevision: 0,
      commands: [{
        commandId: "77777777-7777-4777-8777-777777777777",
        expectedRevision: 0,
        origin: { kind: "user", id: "lineage-test" },
        preconditions: [{ target: "10", field: "exists", equals: true }],
        operation: { kind: "entity.move", handles: ["10"], delta: [1, 0, 0] }
      }]
    }
  }) as { previewId: string; documentId: string };
  assert.equal(preview.documentId, opened.drawingId);
  await application.capabilities.execute("edit.apply", {
    previewId: preview.previewId,
    documentId: opened.drawingId,
    expectedRevision: 0,
    approved: true
  });
  const secondPreview = await application.capabilities.execute("edit.preview", {
    batch: {
      schemaVersion: "cad-edit/v1",
      transactionId: "88888888-8888-4888-8888-888888888888",
      documentId: opened.drawingId,
      expectedRevision: 1,
      commands: [{
        commandId: "99999999-9999-4999-8999-999999999999",
        expectedRevision: 1,
        origin: { kind: "user", id: "lineage-test" },
        preconditions: [{ target: "10", field: "exists", equals: true }],
        operation: { kind: "entity.move", handles: ["10"], delta: [0, 1, 0] }
      }]
    }
  }) as { previewId: string };
  await application.capabilities.execute("edit.apply", {
    previewId: secondPreview.previewId,
    documentId: opened.drawingId,
    expectedRevision: 1,
    approved: true
  });

  const report = await application.capabilities.execute("export.report", {
    documentId: opened.drawingId,
    revision: 2,
    format: "json"
  }) as { bytes: Uint8Array };
  assert.ok(report.bytes.byteLength > 0);

  const grant = await application.requestDestinationGrant();
  assert.ok(grant);
  const saved = await application.capabilities.execute("export.drawing", {
    documentId: opened.drawingId,
    expectedRevision: 2,
    destinationGrantId: grant.grantId,
    baseFilename: "same-lineage",
    format: "dxf",
    version: "AC1032"
  }) as { status: string; id: string };
  assert.equal(saved.status, "passed");
  assert.equal((saved as { intendedChangeCount: number }).intendedChangeCount, 2);
  assert.equal(
    (await application.capabilities.execute("verification.get", { id: saved.id }) as { status: string }).status,
    "passed"
  );

  const rejectedGrant = await application.requestDestinationGrant();
  assert.ok(rejectedGrant);
  await assert.rejects(
    application.capabilities.execute("export.drawing", {
      documentId: opened.drawingId,
      expectedRevision: 2,
      destinationGrantId: rejectedGrant.grantId,
      baseFilename: "disallowed-version",
      format: "dxf",
      version: "AC9999"
    }),
    (error) => (
      error instanceof Error &&
      "code" in error &&
      (error as { code: unknown }).code === "CAD_SAVE_WRITE_FAILED"
    )
  );

  // A copy can only be proven against the active document when both come from
  // one parser, so a DXF source cannot be exported as DWG.
  const mismatchedGrant = await application.requestDestinationGrant();
  assert.ok(mismatchedGrant);
  await assert.rejects(
    application.capabilities.execute("export.drawing", {
      documentId: opened.drawingId,
      expectedRevision: 2,
      destinationGrantId: mismatchedGrant.grantId,
      baseFilename: "mismatched-format",
      format: "dwg",
      version: "AC1032"
    }),
    (error) => (
      error instanceof Error &&
      "code" in error &&
      (error as { code: unknown }).code === "CAD_SAVE_DESTINATION_UNSUPPORTED"
    )
  );
});

test("active document rejects a different open while comparison reads remain available", async () => {
  const before = editableIndex();
  const after = {
    ...editableIndex(),
    drawingId: "dwg:comparison",
    entities: editableIndex().entities.map((entity) => ({
      ...entity,
      bbox: {
        min: [10, 0, 0] as [number, number, number],
        max: [11, 1, 0] as [number, number, number]
      },
      geometry: {
        kind: "line" as const,
        start: [10, 0, 0] as [number, number, number],
        end: [11, 1, 0] as [number, number, number]
      }
    }))
  };
  const opened = new Map<string, typeof before>();
  const application = await createCadApplication({
    read: {
      async open(path) {
        const index = path === "active.dxf" ? before : after;
        opened.set(index.drawingId, index);
        return index;
      },
      get: (drawingId) => opened.get(drawingId) ?? null
    },
    sourceSha256: "a".repeat(64)
  });

  const first = await application.capabilities.execute("document.open", {
    path: "active.dxf"
  }) as { drawingId: string };
  const same = await application.capabilities.execute("document.open", {
    path: "active.dxf"
  }) as { drawingId: string };
  assert.equal(first.drawingId, before.drawingId);
  assert.equal(same.drawingId, before.drawingId);
  await assert.rejects(
    application.capabilities.execute("document.open", {
      path: "comparison.dxf"
    }),
    (error) => (
      error instanceof Error &&
      "code" in error &&
      (error as { code: unknown }).code === "ACTIVE_DOCUMENT_CONFLICT" &&
      error.message === "Another CAD document is already active."
    )
  );

  const comparison = await application.readIndex("comparison.dxf");
  assert.equal(comparison.drawingId, after.drawingId);
  const result = await application.capabilities.execute("query.compare", {
    beforeDrawingId: before.drawingId,
    afterDrawingId: after.drawingId
  }) as { changed: unknown[] };
  assert.equal(result.changed.length, 1);
  assert.equal(application.currentIndex().drawingId, before.drawingId);
});

test("root CAD application composes one named capability set for adapters and forwards cancellation", async (context) => {
  let receivedSignal: AbortSignal | undefined;
  const index = fakeIndex();
  const application = await createCadApplication({
    loadInitialIndex: async () => index,
    read: {
      open: async (_path, signal) => {
        receivedSignal = signal;
        return index;
      },
      get: () => index
    }
  });

  assert.deepEqual(application.capabilityNames, CAD_APPLICATION_CAPABILITY_NAMES);

  const controller = new AbortController();
  await application.capabilities.execute("document.open", { path: "fixture.dxf" }, controller.signal);
  assert.equal(receivedSignal, controller.signal);

  const cadTools = createCadToolRuntime(application.capabilities);
  assert.deepEqual(await cadTools.call("cad.get_layers", {
    drawingId: index.drawingId
  }), { layers: index.layers });

  assert.equal(
    createCadMcpServer.length,
    1,
    "MCP server must require the root-composed capability runtime"
  );
  const server = createCadMcpServer(application.capabilities);
  const client = new Client({ name: "cad-application-composition", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  context.after(async () => {
    await client.close();
    await server.close();
  });
  const mcpTools = await client.listTools();
  assert.deepEqual(mcpTools.tools.map((tool) => tool.name).sort(), [...CAD_TOOL_NAMES].sort());
});

test("read capabilities resolve the active edit snapshot after apply undo and redo", async () => {
  const index = editableIndex();
  const application = await createCadApplication({
    loadInitialIndex: async () => index,
    read: {
      open: async () => index,
      get: () => index
    },
    sourceSha256: "a".repeat(64)
  });

  const preview = await application.capabilities.execute("edit.preview", {
    batch: moveBatch(0)
  }) as { previewId: string };
  await application.capabilities.execute("edit.apply", {
    previewId: preview.previewId,
    documentId: index.drawingId,
    expectedRevision: 0,
    approved: true
  });
  await application.capabilities.execute("document.open", { path: "fixture.dxf" });
  assert.deepEqual(await queriedBox(application, index.drawingId), {
    min: [5, 0, 0],
    max: [6, 1, 0]
  });
  assert.deepEqual(
    (await application.readIndex("fixture.dxf")).entities[0]?.bbox,
    { min: [5, 0, 0], max: [6, 1, 0] }
  );
  assert.equal(application.currentIndex().drawing?.revision, 1);

  await application.capabilities.execute("edit.undo", {
    documentId: index.drawingId,
    expectedRevision: 1,
    approved: true
  });
  assert.deepEqual(await queriedBox(application, index.drawingId), {
    min: [0, 0, 0],
    max: [1, 1, 0]
  });
  assert.equal(application.currentIndex().drawing?.revision, 2);

  await application.capabilities.execute("edit.redo", {
    documentId: index.drawingId,
    expectedRevision: 2,
    approved: true
  });
  assert.deepEqual(await queriedBox(application, index.drawingId), {
    min: [5, 0, 0],
    max: [6, 1, 0]
  });
  assert.equal(application.currentIndex().drawing?.revision, 3);
});

test("application read port serves its configured drawing without reopening the source", async () => {
  let sourceOpenCount = 0;
  const application = await createCadApplication({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dwg/export_sample.dwg",
    loadInitialIndex: async () => editableIndex(),
    read: {
      async open() {
        sourceOpenCount += 1;
        throw new Error("configured source must not be reopened");
      },
      get: () => null
    },
    sourceSha256: "a".repeat(64)
  });

  const current = await application.readIndex("tests/fixtures/dwg/export_sample.dwg");
  assert.equal(current.drawingId, "dwg:composition");
  assert.equal(current.drawing?.revision, 0);
  assert.equal(sourceOpenCount, 0);
});

async function queriedBox(
  application: Awaited<ReturnType<typeof createCadApplication>>,
  drawingId: string
) {
  const result = await application.capabilities.execute("query.entities", {
    drawingId,
    entityIdOrHandle: "10"
  }) as { entity: { bbox: unknown } };
  return result.entity.bbox;
}

function moveBatch(expectedRevision: number) {
  return {
    schemaVersion: "cad-edit/v1",
    transactionId: "44444444-4444-4444-8444-444444444444",
    documentId: "dwg:composition",
    expectedRevision,
    commands: [{
      commandId: "55555555-5555-4555-8555-555555555555",
      expectedRevision,
      origin: { kind: "user", id: "test" },
      preconditions: [{ target: "10", field: "exists", equals: true }],
      operation: { kind: "entity.move", handles: ["10"], delta: [5, 0, 0] }
    }]
  };
}

function editableIndex() {
  return {
    ...fakeIndex(),
    schemaVersion: "cad-index/v0.2" as const,
    summary: {
      entityCount: 1,
      layerCount: 1,
      unsupportedCount: 0,
      modelSpaceCount: 1,
      paperSpaceCount: 0
    },
    layers: [{ name: "0", entityCount: 1, visible: true, frozen: false }],
    entities: [{
      id: "h:10",
      handle: "10",
      type: "LINE",
      layer: "0",
      space: "model" as const,
      layout: "Model",
      bbox: { min: [0, 0, 0] as [number, number, number], max: [1, 1, 0] as [number, number, number] },
      text: null,
      blockName: null,
      attributes: {},
      geometry: {
        kind: "line" as const,
        start: [0, 0, 0] as [number, number, number],
        end: [1, 1, 0] as [number, number, number]
      },
      warnings: []
    }]
  };
}

function fakeIndex() {
  return {
    schemaVersion: "cad-index/v0.1" as const,
    drawingId: "dwg:composition",
    source: { kind: "dxf" as const, displayName: "fixture.dxf", parser: "test" },
    summary: {
      entityCount: 0,
      layerCount: 0,
      unsupportedCount: 0,
      modelSpaceCount: 0,
      paperSpaceCount: 0
    },
    layers: [],
    entities: [],
    unsupported: []
  };
}

test("application composes export capabilities into the transaction owner", async () => {
  const application = await createCadApplication();
  assert.deepEqual(application.capabilityNames.slice(-3), [
    "export.report",
    "export.drawing",
    "verification.get"
  ]);
});

test("gateway MCP stdio and CLI stay thin over the same application factory", async () => {
  for (const path of [
    "modules/cad-runtime/src/http/gateway.ts",
    "modules/cad-runtime/src/mcp/stdio.ts",
    "modules/cad-runtime/harness/run-skill.ts"
  ]) {
    const source = await readFile(path, "utf8");
    assert.match(source, /createCadApplication\s*\(/u, path);
    assert.doesNotMatch(source, /createCadToolRuntime\s*\(/u, path);
  }
});
