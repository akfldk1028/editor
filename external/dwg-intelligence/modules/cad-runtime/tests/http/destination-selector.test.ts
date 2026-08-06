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
