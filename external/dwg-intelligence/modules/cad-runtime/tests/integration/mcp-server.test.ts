import assert from "node:assert/strict";
import { test } from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { ElicitRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import {
  parseCadDrawingExportResponse,
  parseCadReportExportResponse
} from "@dwg/contracts";

import { createCadMcpServer } from "../../src/mcp/createServer.js";
import { createCadApplication } from "../../src/application/createCadApplication.js";
import { CAD_TOOL_NAMES } from "../../src/mcp/toolDefinitions.js";
import type { CadCapabilityRuntime } from "@dwg/cad-capabilities";

test("lists the complete deterministic CAD tool surface", async (t) => {
  const application = await createCadApplication();
  const server = createCadMcpServer(application.capabilities);
  const client = new Client({ name: "cad-test-client", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();

  await Promise.all([
    client.connect(clientTransport),
    server.connect(serverTransport)
  ]);

  t.after(async () => {
    await client.close();
    await server.close();
  });

  const result = await client.listTools();

  assert.deepEqual(
    result.tools.map((tool) => tool.name).sort(),
    [...CAD_TOOL_NAMES].sort()
  );
});

test("runs the complete indexed DXF query loop through MCP", async (t) => {
  const application = await createCadApplication();
  const server = createCadMcpServer(application.capabilities);
  const client = new Client({ name: "cad-loop-client", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();

  await Promise.all([
    client.connect(clientTransport),
    server.connect(serverTransport)
  ]);

  t.after(async () => {
    await client.close();
    await server.close();
  });

  const opened = await client.callTool({
    name: "cad.open_drawing",
    arguments: { path: "tests/fixtures/dxf/minimal-architectural.dxf" }
  });
  const drawingId = (
    opened.structuredContent as { drawingId: string }
  ).drawingId;

  const built = await client.callTool({
    name: "cad.build_index",
    arguments: { drawingId }
  });
  assert.equal(
    (built.structuredContent as { drawingId: string }).drawingId,
    drawingId
  );

  const layers = await client.callTool({
    name: "cad.get_layers",
    arguments: { drawingId }
  });
  assert.ok(
    (layers.structuredContent as { layers: Array<{ name: string }> }).layers
      .some((layer) => layer.name === "A-WALL")
  );

  const byLayer = await client.callTool({
    name: "cad.find_entities_by_layer",
    arguments: { drawingId, layer: "A-WALL" }
  });
  const layerMatches = (
    byLayer.structuredContent as { matches: Array<Record<string, unknown>> }
  ).matches;
  assert.equal(layerMatches.length, 2);
  for (const match of layerMatches) {
    for (const field of ["id", "handle", "type", "layer", "bbox"]) {
      assert.ok(match[field], `missing ${field}`);
    }
  }

  const byType = await client.callTool({
    name: "cad.find_entities_by_type",
    arguments: { drawingId, type: "line" }
  });
  assert.equal(
    (byType.structuredContent as { matches: unknown[] }).matches.length,
    1
  );

  const byText = await client.callTool({
    name: "cad.find_text",
    arguments: { drawingId, query: "ROOM" }
  });
  assert.equal(
    (
      byText.structuredContent as {
        matches: Array<{ text: string }>;
      }
    ).matches[0].text,
    "ROOM 101"
  );

  const entity = await client.callTool({
    name: "cad.get_entity",
    arguments: { drawingId, entityIdOrHandle: "10" }
  });
  assert.equal(
    (entity.structuredContent as { entity: { handle: string } }).entity.handle,
    "10"
  );

  const unsupported = await client.callTool({
    name: "cad.list_unsupported",
    arguments: { drawingId }
  });
  assert.ok(
    Array.isArray(
      (unsupported.structuredContent as { unsupported: unknown[] }).unsupported
    )
  );
});

test("official DXF capability results preserve MCP drawing IDs and read summaries", async (t) => {
  const application = await createCadApplication();
  const runtime = application.capabilities;
  const server = createCadMcpServer(runtime);
  const client = new Client({ name: "capability-parity-client", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  t.after(async () => {
    await client.close();
    await server.close();
  });

  const capabilityOpen = await runtime.execute("document.open", {
    path: "tests/fixtures/dxf/minimal-architectural.dxf"
  }) as { drawingId: string };
  const mcpOpen = await client.callTool({
    name: "cad.open_drawing",
    arguments: { path: "tests/fixtures/dxf/minimal-architectural.dxf" }
  });
  const drawingId = (mcpOpen.structuredContent as { drawingId: string }).drawingId;
  assert.equal(capabilityOpen.drawingId, drawingId);

  const capabilityLayers = await runtime.execute("query.layers", {
    drawingId: capabilityOpen.drawingId
  }) as { layers: unknown[] };
  const mcpLayers = await client.callTool({
    name: "cad.get_layers",
    arguments: { drawingId }
  });
  assert.equal(
    capabilityLayers.layers.length,
    (mcpLayers.structuredContent as { layers: unknown[] }).layers.length
  );

  const capabilityText = await runtime.execute("query.text", {
    drawingId: capabilityOpen.drawingId,
    query: "ROOM"
  }) as { matches: Array<{ handle: string | null }> };
  const mcpText = await client.callTool({
    name: "cad.find_text",
    arguments: { drawingId, query: "ROOM" }
  });
  assert.deepEqual(
    capabilityText.matches.map((match) => match.handle),
    (mcpText.structuredContent as { matches: Array<{ handle: string | null }> })
      .matches.map((match) => match.handle)
  );

  const capabilityDescription = await runtime.execute("document.describe", {
    drawingId: capabilityOpen.drawingId
  }) as { unsupported: unknown[] };
  const mcpUnsupported = await client.callTool({
    name: "cad.list_unsupported",
    arguments: { drawingId }
  });
  assert.deepEqual(
    capabilityDescription.unsupported,
    (mcpUnsupported.structuredContent as { unsupported: unknown[] }).unsupported
  );
});

test("returns a stable structured MCP error for an unknown drawing", async (t) => {
  const application = await createCadApplication();
  const server = createCadMcpServer(application.capabilities);
  const client = new Client({ name: "cad-error-client", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();

  await Promise.all([
    client.connect(clientTransport),
    server.connect(serverTransport)
  ]);

  t.after(async () => {
    await client.close();
    await server.close();
  });

  const result = await client.callTool({
    name: "cad.get_layers",
    arguments: { drawingId: "missing-drawing" }
  });

  assert.equal(result.isError, true);
  assert.deepEqual(result.structuredContent, {
    error: {
      code: "CAD_TOOL_ERROR",
      message: "Drawing not opened: missing-drawing"
    }
  });
});

test("registers grant report drawing and verification MCP tools", () => {
  assert.ok((CAD_TOOL_NAMES as readonly string[]).includes("cad_request_export_destination"));
  assert.ok((CAD_TOOL_NAMES as readonly string[]).includes("cad_export_report"));
  assert.ok((CAD_TOOL_NAMES as readonly string[]).includes("cad_export_drawing"));
  assert.ok((CAD_TOOL_NAMES as readonly string[]).includes("cad_get_export_verification"));
});

test("forwards MCP request cancellation to capability execution", async (t) => {
  let receivedSignal: AbortSignal | undefined;
  let entered!: () => void;
  const started = new Promise<void>((resolve) => { entered = resolve; });
  const runtime: CadCapabilityRuntime = {
    async execute(_name, _input, signal) {
      receivedSignal = signal;
      entered();
      await new Promise<void>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    }
  };
  const server = createCadMcpServer(runtime);
  const client = new Client({ name: "cad-cancel-client", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  t.after(async () => {
    await client.close();
    await server.close();
  });
  const controller = new AbortController();

  const pending = client.callTool(
    { name: "cad.get_layers", arguments: { drawingId: "drawing:cancel" } },
    undefined,
    { signal: controller.signal }
  );
  await started;
  controller.abort();

  await assert.rejects(pending);
  assert.ok(receivedSignal);
  assert.equal(receivedSignal.aborted, true);
});

test("export destination elicitation uses a closed boolean form and exact confirmation", async (t) => {
  let grantRequests = 0;
  let rawRequestedSchema: Record<string, unknown> | undefined;
  const application = await createCadApplication();
  const server = createCadMcpServer(application.capabilities, {
    async requestDestinationGrant() {
      grantRequests += 1;
      return {
        grantId: "11111111-1111-4111-8111-111111111111",
        displayDirectory: "Exports",
        expiresAt: 1
      };
    }
  });
  const client = new Client(
    { name: "cad-elicitation-client", version: "0.1.0" },
    { capabilities: { elicitation: { form: {} } } }
  );
  client.setRequestHandler(ElicitRequestSchema, async () => ({
    action: "accept",
    content: { confirm: true, unexpected: true }
  }));
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  const send = serverTransport.send.bind(serverTransport);
  serverTransport.send = async (message, options) => {
    if ("method" in message && message.method === "elicitation/create") {
      rawRequestedSchema = (message.params as { requestedSchema: Record<string, unknown> })
        .requestedSchema;
    }
    return send(message, options);
  };
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  t.after(async () => {
    await client.close();
    await server.close();
  });

  const result = await client.callTool({
    name: "cad_request_export_destination",
    arguments: {}
  });

  assert.equal(rawRequestedSchema?.additionalProperties, false);
  assert.equal(result.isError, true);
  assert.equal(grantRequests, 0);
});

test("forwards MCP cancellation to destination grant selection", async (t) => {
  let receivedSignal: AbortSignal | undefined;
  let entered!: () => void;
  const started = new Promise<void>((resolve) => { entered = resolve; });
  const application = await createCadApplication();
  const server = createCadMcpServer(application.capabilities, {
    async requestDestinationGrant(signal) {
      receivedSignal = signal;
      entered();
      await new Promise<void>((_resolve, reject) => {
        signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    }
  });
  const client = new Client(
    { name: "cad-destination-cancel-client", version: "0.1.0" },
    { capabilities: { elicitation: { form: {} } } }
  );
  client.setRequestHandler(ElicitRequestSchema, async () => ({
    action: "accept",
    content: { confirm: true }
  }));
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  t.after(async () => {
    await client.close();
    await server.close();
  });
  const controller = new AbortController();

  const pending = client.callTool(
    { name: "cad_request_export_destination", arguments: {} },
    undefined,
    { signal: controller.signal }
  );
  await started;
  controller.abort();

  await assert.rejects(pending);
  assert.ok(receivedSignal);
  assert.equal(receivedSignal.aborted, true);
});

test("MCP report export links one single-use application-local resource", async (t) => {
  const application = await createCadApplication({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf"
  });
  const server = createCadMcpServer(application.capabilities, {
    createReportDownload: (input, signal) => application.createReportDownload(input, signal),
    consumeReportDownload: (downloadId) => application.consumeReportDownload(downloadId)
  });
  const client = new Client({ name: "cad-report-client", version: "0.1.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  t.after(async () => {
    await client.close();
    await server.close();
  });

  const result = await client.callTool({
    name: "cad_export_report",
    arguments: {
      documentId: application.currentIndex().drawingId,
      revision: 0,
      format: "json"
    }
  });
  const response = parseCadReportExportResponse(result.structuredContent);

  assert.match(response.filename, /\.json$/u);
  assert.equal(Object.hasOwn(result.structuredContent as object, "bytes"), false);
  assert.ok(Buffer.byteLength(JSON.stringify(result), "utf8") < 2_048);
  const link = (result.content as Array<{
    type: string;
    uri?: string;
    mimeType?: string;
    name?: string;
  }>).find((item) => item.type === "resource_link");
  assert.ok(link && link.type === "resource_link");
  assert.equal(link.mimeType, response.mediaType);
  assert.equal(link.name, response.filename);
  assert.equal(link.uri, `cad-report://reports/${response.downloadId}`);

  const resource = await client.readResource({ uri: link.uri });
  assert.equal(resource.contents.length, 1);
  const content = resource.contents[0]!;
  assert.equal(content.uri, link.uri);
  assert.equal(content.mimeType, response.mediaType);
  assert.ok("text" in content);
  assert.equal(
    JSON.parse(content.text).document.documentId,
    application.currentIndex().drawingId
  );
  await assert.rejects(client.readResource({ uri: link.uri }));
});

test("MCP obtains a real one-use grant and saves a verified drawing copy", async (t) => {
  const { mkdtemp, rm } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const exportRoot = await mkdtemp(join(tmpdir(), "cad-mcp-export-"));
  t.after(() => rm(exportRoot, { force: true, recursive: true }));
  const application = await createCadApplication({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    exportRoot,
    processRunner: {
      async run(spec, signal) {
        const { defaultProcessRunner } = await import("../../src/providers/cli/processRunner.js");
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
  const server = createCadMcpServer(application.capabilities, {
    requestDestinationGrant: (signal) => application.requestDestinationGrant(signal),
    createReportDownload: (input, signal) => application.createReportDownload(input, signal)
  });
  const client = new Client(
    { name: "cad-real-export-client", version: "0.1.0" },
    { capabilities: { elicitation: { form: {} } } }
  );
  client.setRequestHandler(ElicitRequestSchema, async () => ({
    action: "accept",
    content: { confirm: true }
  }));
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
  t.after(async () => {
    await client.close();
    await server.close();
  });

  const granted = await client.callTool({
    name: "cad_request_export_destination",
    arguments: {}
  });
  const grantId = (granted.structuredContent as { grantId: string }).grantId;
  const saved = await client.callTool({
    name: "cad_export_drawing",
    arguments: {
      documentId: application.currentIndex().drawingId,
      expectedRevision: 0,
      destinationGrantId: grantId,
      baseFilename: "mcp-verified",
      format: "dxf",
      version: "AC1032"
    }
  });

  assert.deepEqual(
    parseCadDrawingExportResponse(saved.structuredContent),
    {
      verificationId: (saved.structuredContent as { verificationId: string }).verificationId,
      status: "passed"
    }
  );
});
