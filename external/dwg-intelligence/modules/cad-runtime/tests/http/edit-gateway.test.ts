import assert from "node:assert/strict";
import type { IncomingMessage, ServerResponse } from "node:http";
import { Readable } from "node:stream";
import test from "node:test";

import { createProviderGateway } from "../../src/http/providerGateway.js";
import { createCadApplication } from "../../src/application/createCadApplication.js";
import { handleEditGatewayRequest } from "../../src/http/editGateway.js";
import { createCadGatewayServer } from "../../src/http/gateway.js";

const documentId = "dwg:edit-test";
const transactionId = "11111111-1111-4111-8111-111111111111";
const commandId = "22222222-2222-4222-8222-222222222222";
const previewId = "33333333-3333-4333-8333-333333333333";

test("edit gateway validates requests, responses, and only returns public edit DTOs", async (context) => {
  const calls: Array<{ name: string; input: unknown }> = [];
  const server = createProviderGateway({
    ...readDependencies(),
    edit: async (name, input) => {
      calls.push({ name, input });
      if (name === "edit.preview") {
        return {
          previewId,
          documentId,
          transactionId,
          baseRevision: 0,
          nextRevision: 1,
          changeCount: 0,
          changesTruncated: false,
          changes: [],
          warningCount: 0,
          warningsTruncated: false,
          warnings: []
        };
      }
      return { documentId, revision: 1, transactionId, changeCount: 0 };
    }
  });
  const baseUrl = await listen(server, context);

  const malformed = await post(baseUrl, "/api/edit/preview", { batch: {} });
  assert.equal(malformed.status, 400);
  assert.deepEqual(await malformed.json(), {
    error: { code: "EDIT_REQUEST_INVALID", message: "Invalid CAD edit request." }
  });

  const preview = await post(baseUrl, "/api/edit/preview", { batch: validBatch() });
  assert.equal(preview.status, 200);
  assert.deepEqual(await preview.json(), {
    previewId,
    documentId,
    transactionId,
    baseRevision: 0,
    nextRevision: 1,
    changeCount: 0,
    changesTruncated: false,
    changes: [],
    warningCount: 0,
    warningsTruncated: false,
    warnings: []
  });
  assert.deepEqual(calls, [{ name: "edit.preview", input: { batch: validBatch() } }]);

  const apply = await post(baseUrl, "/api/edit/apply", {
    previewId,
    documentId,
    expectedRevision: 0,
    approved: true
  });
  assert.equal(apply.status, 200);
  assert.deepEqual(await apply.json(), { documentId, revision: 1, transactionId, changeCount: 0 });
});

test("edit gateway rejects oversized bodies and malformed capability responses", async (context) => {
  let calls = 0;
  const server = createProviderGateway({
    ...readDependencies(),
    edit: async () => {
      calls += 1;
      return { documentId, revision: 1, transactionId, changeCount: 0, snapshot: { secret: true } };
    }
  });
  const baseUrl = await listen(server, context);

  const oversized = await fetch(`${baseUrl}/api/edit/preview`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "x".repeat(1024 * 1024 + 1)
  });
  assert.equal(oversized.status, 413);
  assert.deepEqual(await oversized.json(), {
    error: { code: "EDIT_REQUEST_TOO_LARGE", message: "CAD edit request exceeds the 1 MiB limit." }
  });
  assert.equal(calls, 0);

  const invalidResponse = await post(baseUrl, "/api/edit/undo", {
    documentId,
    expectedRevision: 0,
    approved: true
  });
  assert.equal(invalidResponse.status, 500);
  assert.deepEqual(await invalidResponse.json(), {
    error: { code: "EDIT_RESPONSE_INVALID", message: "CAD edit capability returned an invalid response." }
  });
});

test("edit gateway forwards the request AbortSignal unchanged", async (context) => {
  let started!: () => void;
  let aborted = false;
  const startedPromise = new Promise<void>((resolve) => { started = resolve; });
  const server = createProviderGateway({
    ...readDependencies(),
    edit: async (_name, _input, signal) => new Promise((resolve) => {
      started();
      signal?.addEventListener("abort", () => {
        aborted = true;
        resolve({ documentId, revision: 0, transactionId, changeCount: 0 });
      }, { once: true });
    })
  });
  const baseUrl = await listen(server, context);
  const controller = new AbortController();
  const request = fetch(`${baseUrl}/api/edit/undo`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ documentId, expectedRevision: 0, approved: true }),
    signal: controller.signal
  });
  await startedPromise;
  controller.abort();
  await assert.rejects(request, /abort/i);
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(aborted, true);
});

test("edit gateway drives preview apply reuse stale undo and redo through one paired application", async (context) => {
  const application = await createCadApplication({
    loadInitialIndex: async () => editableIndex(),
    read: {
      open: async () => editableIndex(),
      get: () => editableIndex()
    }
  });
  const server = createProviderGateway({
    ...readDependencies(),
    edit: (name, input, signal) => application.capabilities.execute(name, input, signal)
  });
  const baseUrl = await listen(server, context);

  const firstPreview = await post(baseUrl, "/api/edit/preview", { batch: validBatch() });
  const first = await firstPreview.json() as { previewId: string };
  assert.equal(firstPreview.status, 200, JSON.stringify(first));
  const applied = await post(baseUrl, "/api/edit/apply", {
    previewId: first.previewId, documentId, expectedRevision: 0, approved: true
  });
  assert.equal(applied.status, 200);
  assert.equal((await applied.json() as { revision: number }).revision, 1);

  const reused = await post(baseUrl, "/api/edit/apply", {
    previewId: first.previewId, documentId, expectedRevision: 1, approved: true
  });
  assert.equal(reused.status, 409);
  assert.equal((await reused.json() as { error: { code: string } }).error.code, "EDIT_PREVIEW_REUSED");

  const stalePreview = await post(baseUrl, "/api/edit/preview", { batch: validBatch(1) });
  const stale = await stalePreview.json() as { previewId: string };
  const undo = await post(baseUrl, "/api/edit/undo", {
    documentId, expectedRevision: 1, approved: true
  });
  assert.equal(undo.status, 200);
  assert.equal((await undo.json() as { revision: number }).revision, 2);
  const staleApply = await post(baseUrl, "/api/edit/apply", {
    previewId: stale.previewId, documentId, expectedRevision: 1, approved: true
  });
  assert.equal(staleApply.status, 409);
  assert.deepEqual(await staleApply.json(), {
    error: {
      code: "EDIT_PREVIEW_STALE",
      message: "CAD edit operation could not be completed.",
      currentRevision: 2
    }
  });

  const redo = await post(baseUrl, "/api/edit/redo", {
    documentId, expectedRevision: 2, approved: true
  });
  assert.equal(redo.status, 200);
  assert.equal((await redo.json() as { revision: number }).revision, 3);
});

test("pre-aborted edit gateway apply preserves the preview and transaction lifecycle", async () => {
  const application = await createCadApplication({
    loadInitialIndex: async () => editableIndex(),
    read: {
      open: async () => editableIndex(),
      get: () => editableIndex()
    }
  });
  const proposed = await application.capabilities.execute("edit.preview", {
    batch: validBatch()
  }) as { previewId: string; transactionId: string };
  const controller = new AbortController();
  controller.abort();
  const request = Readable.from([Buffer.from(JSON.stringify({
    previewId: proposed.previewId,
    documentId,
    expectedRevision: 0,
    approved: true
  }))]) as IncomingMessage;
  request.method = "POST";
  request.headers = { "content-type": "application/json" };
  let responseBody = "";
  const response = {
    destroyed: false,
    writableEnded: false,
    statusCode: 0,
    end(value: string) {
      responseBody = value;
    }
  } as unknown as ServerResponse;

  const handled = await handleEditGatewayRequest(
    request,
    response,
    "/api/edit/apply",
    {
      execute: (name, input, signal) => application.capabilities.execute(name, input, signal)
    },
    controller.signal
  );

  assert.equal(handled, true);
  assert.equal(response.statusCode, 409);
  assert.deepEqual(JSON.parse(responseBody), {
    error: {
      code: "EDIT_CANCELLED",
      message: "CAD edit operation could not be completed."
    }
  });
  assert.equal(application.transactions.getCommittedTransaction(transactionId), null);

  assert.equal((await application.capabilities.execute("edit.apply", {
    previewId: proposed.previewId,
    documentId,
    expectedRevision: 0,
    approved: true
  }) as { revision: number }).revision, 1);
});

test("assembled gateway publishes the active edit snapshot through apply undo and redo", async (context) => {
  const application = await createCadApplication({
    loadInitialIndex: async () => movingIndex(),
    read: {
      open: async () => movingIndex(),
      get: () => movingIndex()
    },
    sourceSha256: "a".repeat(64)
  });
  const sourceHash = application.transactions.getSaveState(documentId, 0)?.source.sourceSha256;
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dwg/export_sample.dwg",
    application
  });
  const baseUrl = await listen(server, context);

  const initial = await getDrawing(baseUrl);
  assert.equal(initial.drawing.revision, 0);
  assert.deepEqual(entityBox(initial), { min: [0, 0, 0], max: [1, 1, 0] });

  const preview = await post(baseUrl, "/api/edit/preview", { batch: moveBatch() });
  const previewBody = await preview.json() as { previewId: string };
  assert.equal(preview.status, 200, JSON.stringify(previewBody));
  assert.equal((await post(baseUrl, "/api/edit/apply", {
    previewId: previewBody.previewId, documentId, expectedRevision: 0, approved: true
  })).status, 200);
  const applied = await getDrawing(baseUrl);
  assert.equal(applied.drawing.revision, 1);
  assert.deepEqual(entityBox(applied), { min: [5, 0, 0], max: [6, 1, 0] });

  assert.equal((await post(baseUrl, "/api/edit/undo", {
    documentId, expectedRevision: 1, approved: true
  })).status, 200);
  const undone = await getDrawing(baseUrl);
  assert.equal(undone.drawing.revision, 2);
  assert.deepEqual(entityBox(undone), { min: [0, 0, 0], max: [1, 1, 0] });

  assert.equal((await post(baseUrl, "/api/edit/redo", {
    documentId, expectedRevision: 2, approved: true
  })).status, 200);
  const redone = await getDrawing(baseUrl);
  assert.equal(redone.drawing.revision, 3);
  assert.deepEqual(entityBox(redone), { min: [5, 0, 0], max: [6, 1, 0] });
  assert.equal(application.transactions.getSaveState(documentId, 3)?.source.sourceSha256, sourceHash);
});

function readDependencies() {
  return {
    getDrawing: async () => { throw new Error("not used"); },
    inspect: async () => { throw new Error("not used"); },
    getStatuses: async () => [],
    chat: async () => { throw new Error("not used"); }
  };
}

async function listen(server: ReturnType<typeof createProviderGateway>, context: test.TestContext) {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return `http://127.0.0.1:${address.port}`;
}

function post(baseUrl: string, path: string, body: unknown): Promise<Response> {
  return fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
}

function validBatch(expectedRevision = 0) {
  return {
    schemaVersion: "cad-edit/v1",
    transactionId,
    documentId,
    expectedRevision,
    commands: [{
      commandId,
      expectedRevision,
      origin: { kind: "user", id: "test" },
      preconditions: [{ target: "10", field: "exists", equals: true }],
      operation: { kind: "text.replace", handle: "10", text: "updated" }
    }]
  };
}

function moveBatch(expectedRevision = 0) {
  return {
    schemaVersion: "cad-edit/v1",
    transactionId: "44444444-4444-4444-8444-444444444444",
    documentId,
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

async function getDrawing(baseUrl: string) {
  const response = await fetch(`${baseUrl}/api/drawing`);
  assert.equal(response.status, 200);
  return await response.json() as { drawing: { revision?: number }; entities: Array<{ handle: string | null; bbox: unknown }> };
}

function entityBox(index: Awaited<ReturnType<typeof getDrawing>>) {
  const entity = index.entities.find((candidate) => candidate.handle === "10");
  assert.ok(entity);
  return entity.bbox;
}

function editableIndex() {
  return {
    schemaVersion: "cad-index/v0.2" as const,
    drawingId: documentId,
    source: { kind: "dxf" as const, displayName: "edit-test.dxf", parser: "test" },
    summary: { entityCount: 1, layerCount: 1, unsupportedCount: 0, modelSpaceCount: 1, paperSpaceCount: 0 },
    layers: [{ name: "0", entityCount: 1, visible: true, frozen: false }],
    entities: [{
      id: "h:10", handle: "10", type: "TEXT", layer: "0", space: "model" as const, layout: "Model",
      bbox: { min: [0, 0, 0] as [number, number, number], max: [1, 1, 0] as [number, number, number] },
      text: "original", blockName: null, attributes: {}, warnings: [],
      geometry: {
        kind: "text" as const,
        insertionPoint: [0, 0, 0] as [number, number, number],
        alignmentPoint: null,
        height: 1,
        rotation: 0,
        width: null
      }
    }],
    unsupported: []
  };
}

function movingIndex() {
  const index = editableIndex();
  const entity = index.entities[0]!;
  return {
    ...index,
    entities: [{
      ...entity,
      type: "LWPOLYLINE",
      geometry: {
        kind: "lwpolyline" as const,
        vertices: [
          { point: [0, 0, 0] as [number, number, number], bulge: 0, startWidth: 0, endWidth: 0 },
          { point: [1, 1, 0] as [number, number, number], bulge: 0, startWidth: 0, endWidth: 0 }
        ],
        closed: false,
        elevation: 0,
        normal: [0, 0, 1] as [number, number, number]
      }
    }]
  };
}
