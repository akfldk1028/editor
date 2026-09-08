import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createCadApplication } from "../../src/application/createCadApplication.js";
import { createCadGatewayServer } from "../../src/http/gateway.js";
import { defaultProcessRunner } from "../../src/providers/cli/processRunner.js";
import { parseCadExportErrorResponse } from "@dwg/contracts";

test("assembled gateway publishes every available report and drawing export capability", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf"
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");

  const response = await fetch(`http://127.0.0.1:${address.port}/api/export/capabilities`);

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    capabilities: [
      { format: "json", kind: "report", available: true, reason: null },
      { format: "csv", kind: "report", available: true, reason: null },
      { format: "pdf", kind: "report", available: true, reason: null },
      { format: "svg", kind: "report", available: true, reason: null },
      { format: "dxf", kind: "drawing", available: true, reason: null },
      {
        format: "dwg",
        kind: "drawing",
        available: false,
        reason: "DWG drawing export is withheld for a DXF source because the copy cannot be verified against it."
      }
    ]
  });
});

test("assembled gateway issues path-free grants and serves report downloads once", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf"
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");
  const base = `http://127.0.0.1:${address.port}`;

  const rejectedGrant = await fetch(`${base}/api/export/destination-grants`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path: "C:/outside" })
  });
  assert.equal(rejectedGrant.status, 400);

  const report = await fetch(`${base}/api/export/reports`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      documentId: "86be7bbdf2ca52e4",
      revision: 0,
      format: "json"
    })
  });
  assert.equal(report.status, 200);
  const response = await report.json() as { downloadId: string; filename: string };
  assert.match(response.filename, /\.json$/u);
  const first = await fetch(`${base}/api/export/reports/${response.downloadId}`);
  assert.equal(first.status, 200);
  assert.match(first.headers.get("content-type") ?? "", /^application\/json/u);
  assert.equal((await first.text()).includes("canonical"), false);
  const second = await fetch(`${base}/api/export/reports/${response.downloadId}`);
  assert.equal(second.status, 404);
  assert.equal(exportErrorCode(await second.json()), "REPORT_DOWNLOAD_UNKNOWN");

  const malformedDrawing = await fetch(`${base}/api/export/drawings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      documentId: "86be7bbdf2ca52e4",
      expectedRevision: 0,
      destinationGrantId: "not-a-grant",
      baseFilename: "copy",
      format: "dxf",
      version: "AC1032"
    })
  });
  assert.equal(malformedDrawing.status, 400);
  assert.equal(exportErrorCode(await malformedDrawing.json()), "EXPORT_REQUEST_INVALID");

  const malformedVerification = await fetch(`${base}/api/export/verifications/not-a-uuid`);
  assert.equal(malformedVerification.status, 400);
  assert.equal(
    exportErrorCode(await malformedVerification.json()),
    "VERIFICATION_REQUEST_INVALID"
  );
  const unknownVerification = await fetch(
    `${base}/api/export/verifications/11111111-1111-4111-8111-111111111111`
  );
  assert.equal(unknownVerification.status, 404);
  assert.equal(exportErrorCode(await unknownVerification.json()), "VERIFICATION_UNKNOWN");
});

test("destination picker cancellation returns the strict public export error DTO", async (context) => {
  const application = await createCadApplication({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    destinationSelector: {
      async request() {
        return null;
      }
    }
  });
  const server = await createCadGatewayServer({ application });
  const base = await listen(server, context);

  const response = await fetch(`${base}/api/export/destination-grants`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}"
  });

  assert.equal(response.status, 409);
  assert.deepEqual(parseCadExportErrorResponse(await response.json()), {
    error: {
      code: "DESTINATION_SELECTION_CANCELLED",
      message: "Destination selection was cancelled."
    }
  });
});

test("unclaimed report downloads are count bounded and consuming one releases capacity", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf"
  });
  const base = await listen(server, context);
  const body = {
    documentId: "86be7bbdf2ca52e4",
    revision: 0,
    format: "json"
  };
  const downloads: string[] = [];
  for (let index = 0; index < 64; index += 1) {
    const response = await fetch(`${base}/api/export/reports`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    });
    assert.equal(response.status, 200, `report ${index + 1}`);
    downloads.push((await response.json() as { downloadId: string }).downloadId);
  }
  const full = await fetch(`${base}/api/export/reports`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  assert.equal(full.status, 503);
  assert.equal(exportErrorCode(await full.json()), "REPORT_DOWNLOAD_CAPACITY");

  assert.equal((await fetch(`${base}/api/export/reports/${downloads[0]}`)).status, 200);
  const afterConsume = await fetch(`${base}/api/export/reports`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
  assert.equal(afterConsume.status, 200);
});

test("drawing export preserves duplicate grant reuse and stale failure identities", async (context) => {
  const exportRoot = await mkdtemp(join(tmpdir(), "cad-http-export-"));
  context.after(() => rm(exportRoot, { force: true, recursive: true }));
  const application = await createCadApplication({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    exportRoot,
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
  const server = await createCadGatewayServer({ application });
  const base = await listen(server, context);
  const documentId = application.currentIndex().drawingId;
  const issueGrant = async () => {
    const response = await fetch(`${base}/api/export/destination-grants`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}"
    });
    assert.equal(response.status, 200);
    return (await response.json() as { grantId: string }).grantId;
  };
  const save = (grantId: string, baseFilename: string, expectedRevision = 0) =>
    fetch(`${base}/api/export/drawings`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        documentId,
        expectedRevision,
        destinationGrantId: grantId,
        baseFilename,
        format: "dxf",
        version: "AC1032"
      })
    });

  const usedGrant = await issueGrant();
  assert.equal((await save(usedGrant, "duplicate")).status, 200);

  const duplicate = await save(await issueGrant(), "duplicate");
  assert.equal(duplicate.status, 409);
  assert.equal(exportErrorCode(await duplicate.json()), "OUTPUT_ALREADY_EXISTS");

  const reused = await save(usedGrant, "different-name");
  assert.equal(reused.status, 409);
  assert.equal(exportErrorCode(await reused.json()), "DESTINATION_GRANT_REUSED");

  const stale = await save(await issueGrant(), "stale", 1);
  assert.equal(stale.status, 409);
  assert.equal(exportErrorCode(await stale.json()), "REVISION_STALE");
});

async function listen(
  server: Awaited<ReturnType<typeof createCadGatewayServer>>,
  context: test.TestContext
): Promise<string> {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return `http://127.0.0.1:${address.port}`;
}

function exportErrorCode(value: unknown): string {
  assert.ok(value && typeof value === "object" && !Array.isArray(value));
  const outer = value as Record<string, unknown>;
  assert.deepEqual(Object.keys(outer), ["error"]);
  assert.ok(outer.error && typeof outer.error === "object" && !Array.isArray(outer.error));
  const error = outer.error as Record<string, unknown>;
  assert.deepEqual(Object.keys(error).sort(), ["code", "message"]);
  assert.equal(typeof error.code, "string");
  assert.equal(typeof error.message, "string");
  assert.ok(error.message.length > 0 && error.message.length <= 256);
  return error.code;
}
