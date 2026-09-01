import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolve } from "node:path";
import { test } from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { ElicitRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import {
  parseCadDrawingExportResponse,
  parseCadReportExportResponse
} from "@dwg/contracts";

import { CAD_TOOL_NAMES } from "../../src/mcp/toolDefinitions.js";

test("serves the CAD tool surface over a spawned stdio process", async (t) => {
  const exportRoot = await mkdtemp(join(tmpdir(), "cad-mcp-stdio-export-"));
  t.after(() => rm(exportRoot, { force: true, recursive: true }));
  const transport = new StdioClientTransport({
    command: process.platform === "win32" ? "npm.cmd" : "npm",
    args: ["run", "mcp", "--silent"],
    cwd: process.cwd(),
    env: {
      ...definedEnvironment(),
      DWG_WORKSPACE: resolve("."),
      DWG_DRAWING_PATH: "tests/fixtures/dxf/minimal-architectural.dxf",
      DWG_EXPORT_ROOT: exportRoot
    },
    stderr: "pipe"
  });
  const client = new Client(
    { name: "stdio-smoke", version: "0.1.0" },
    { capabilities: { elicitation: { form: {} } } }
  );
  client.setRequestHandler(ElicitRequestSchema, async () => ({
    action: "accept",
    content: { confirm: true }
  }));

  t.after(async () => {
    await client.close();
  });

  await client.connect(transport);
  assert.deepEqual(client.getServerCapabilities()?.resources, {
    listChanged: true
  });
  const result = await client.listTools();

  assert.deepEqual(
    result.tools.map((tool) => tool.name).sort(),
    [...CAD_TOOL_NAMES].sort()
  );

  const opened = await client.callTool({
    name: "cad.open_drawing",
    arguments: { path: "tests/fixtures/dxf/minimal-architectural.dxf" }
  });
  assert.equal(opened.isError, undefined);
  const drawingId = (opened.structuredContent as { drawingId?: unknown }).drawingId;
  assert.equal(typeof drawingId, "string");

  const report = await client.callTool({
    name: "cad_export_report",
    arguments: { documentId: drawingId, revision: 0, format: "json" }
  });
  const reportResponse = parseCadReportExportResponse(report.structuredContent);
  assert.equal(Object.hasOwn(report.structuredContent as object, "bytes"), false);
  const reportLink = (report.content as Array<{
    type: string;
    uri?: string;
  }>).find((item) => item.type === "resource_link");
  assert.ok(reportLink && reportLink.type === "resource_link");
  assert.equal(
    reportLink.uri,
    `cad-report://reports/${reportResponse.downloadId}`
  );
  const reportResource = await client.readResource({ uri: reportLink.uri });
  assert.equal(reportResource.contents.length, 1);
  const reportContent = reportResource.contents[0]!;
  assert.ok("text" in reportContent);
  assert.equal(JSON.parse(reportContent.text).document.documentId, drawingId);
  await assert.rejects(client.readResource({ uri: reportLink.uri }));

  const grant = await client.callTool({
    name: "cad_request_export_destination",
    arguments: {}
  });
  const saved = await client.callTool({
    name: "cad_export_drawing",
    arguments: {
      documentId: drawingId,
      expectedRevision: 0,
      destinationGrantId: (grant.structuredContent as { grantId: string }).grantId,
      baseFilename: "stdio-verified",
      format: "dxf",
      version: "AC1032"
    }
  });
  assert.equal(parseCadDrawingExportResponse(saved.structuredContent).status, "passed");
  assert.equal(
    await readFile(join(exportRoot, "stdio-verified.dxf")).then(() => true, () => false),
    true
  );
});

function definedEnvironment(): Record<string, string> {
  return Object.fromEntries(
    Object.entries(process.env).filter(
      (entry): entry is [string, string] => entry[1] !== undefined
    )
  );
}
