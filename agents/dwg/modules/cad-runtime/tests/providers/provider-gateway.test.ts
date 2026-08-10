import assert from "node:assert/strict";
import test from "node:test";

import { createProviderGateway } from "../../src/http/providerGateway.js";

test("loopback gateway exposes health, provider status, and grounded chat", async (context) => {
  const drawing = {
    schemaVersion: "cad-index/v0.1" as const,
    drawingId: "dwg:test",
    source: {
      kind: "dwg" as const,
      displayName: "fixture.dwg",
      parser: "test"
    },
    summary: {
      entityCount: 1,
      layerCount: 1,
      unsupportedCount: 0,
      modelSpaceCount: 1,
      paperSpaceCount: 0
    },
    layers: [
      { name: "0", entityCount: 1, visible: true, frozen: false }
    ],
    entities: [],
    unsupported: []
  };
  const inspection = {
    status: "completed" as const,
    drawingId: drawing.drawingId,
    events: [
      {
        sequence: 1,
        agentId: "orchestrator" as const,
        action: "complete",
        status: "completed" as const
      }
    ],
    findings: [],
    issues: [],
    warnings: []
  };
  const server = createProviderGateway({
    getDrawing: async () => drawing,
    inspect: async () => inspection,
    getStatuses: async () => [
      {
        id: "codex",
        label: "GPT · Codex",
        installed: true,
        authenticated: true,
        authMethod: "chatgpt",
        detail: "기존 ChatGPT 로그인 세션"
      }
    ],
    chat: async (request) => ({
      provider: request.provider,
      text: "근거 응답 [handle:23D]",
      sessionId: "thread-1"
    })
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const baseUrl = `http://127.0.0.1:${address.port}`;

  const health = await fetch(`${baseUrl}/api/health`).then((response) => response.json());
  assert.deepEqual(health, { ok: true, service: "dwg-provider-gateway" });

  const providers = await fetch(`${baseUrl}/api/providers`).then((response) => response.json());
  assert.equal(providers.providers[0].authMethod, "chatgpt");

  const drawingResponse = await fetch(`${baseUrl}/api/drawing`);
  assert.equal(drawingResponse.status, 200);
  assert.deepEqual(await drawingResponse.json(), drawing);

  const inspectionResponse = await fetch(`${baseUrl}/api/inspections`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      checks: [{ kind: "layer", value: "0" }]
    })
  });
  assert.equal(inspectionResponse.status, 200);
  assert.deepEqual(await inspectionResponse.json(), inspection);

  const chatResponse = await fetch(`${baseUrl}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      provider: "codex",
      drawingPath: "tests/fixtures/dwg/export_sample.dwg",
      message: "이 도형을 설명해줘"
    })
  });
  assert.equal(chatResponse.status, 200);
  assert.equal((await chatResponse.json()).text, "근거 응답 [handle:23D]");
});

test("gateway rejects oversized or malformed requests without invoking chat", async (context) => {
  let calls = 0;
  const server = createProviderGateway({
    getDrawing: async () => {
      throw new Error("should not run");
    },
    inspect: async () => {
      throw new Error("should not run");
    },
    getStatuses: async () => [],
    chat: async () => {
      calls += 1;
      throw new Error("should not run");
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const baseUrl = `http://127.0.0.1:${address.port}`;

  const malformed = await fetch(`${baseUrl}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{"
  });
  assert.equal(malformed.status, 400);
  const invalidSession = await fetch(`${baseUrl}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      provider: "codex",
      drawingPath: "drawing.dwg",
      message: "test",
      sessionId: "--last"
    })
  });
  assert.equal(invalidSession.status, 400);
  const pathInjection = await fetch(`${baseUrl}/api/inspections`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      path: "../../secret.dwg",
      checks: [{ kind: "layer", value: "0" }]
    })
  });
  assert.equal(pathInjection.status, 400);
  assert.equal(calls, 0);
});

test("gateway rejects non-loopback browser origins before dispatching a route", async (context) => {
  let routeCalls = 0;
  const server = createProviderGateway({
    getDrawing: async () => { throw new Error("should not run"); },
    inspect: async () => { throw new Error("should not run"); },
    getStatuses: async () => [],
    chat: async () => { throw new Error("should not run"); },
    additionalRoute: async (_request, response) => {
      routeCalls += 1;
      response.statusCode = 204;
      response.end();
      return true;
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");

  const response = await fetch(`http://127.0.0.1:${address.port}/api/drawings/open`, {
    method: "POST",
    headers: { origin: "https://attacker.example" }
  });

  assert.equal(response.status, 403);
  assert.equal(routeCalls, 0);
});

test("gateway aborts provider work when the browser cancels the request", async (context) => {
  let providerAborted = false;
  let chatStarted!: () => void;
  const started = new Promise<void>((resolve) => {
    chatStarted = resolve;
  });
  const server = createProviderGateway({
    getDrawing: async () => {
      throw new Error("should not run");
    },
    inspect: async () => {
      throw new Error("should not run");
    },
    getStatuses: async () => [],
    chat: async (_request, signal) => new Promise((resolve) => {
      chatStarted();
      signal?.addEventListener("abort", () => {
        providerAborted = true;
        resolve({ provider: "codex", text: "", sessionId: null });
      }, { once: true });
      if (!signal) {
        resolve({ provider: "codex", text: "signal missing", sessionId: null });
      }
    })
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");

  const controller = new AbortController();
  const request = fetch(`http://127.0.0.1:${address.port}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      provider: "codex",
      drawingPath: "drawing.dwg",
      message: "취소 테스트"
    }),
    signal: controller.signal
  });
  await started;
  controller.abort();
  await assert.rejects(request, /abort/i);
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(providerAborted, true);
});
