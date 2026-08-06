import assert from "node:assert/strict";
import { copyFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import type { HostDialogProvider } from "@dwg/host-dialogs";

import { createCadGatewayServer } from "../../src/http/gateway.ts";

const MINIMAL_DXF = "tests/fixtures/dxf/minimal-architectural.dxf";
const EXPORT_SAMPLE = resolve(process.cwd(), "tests/fixtures/dwg/export_sample.dwg");

async function listen(server: Awaited<ReturnType<typeof createCadGatewayServer>>) {
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return `http://127.0.0.1:${address.port}`;
}

function dialogs(overrides: Partial<HostDialogProvider> = {}): HostDialogProvider {
  return {
    async openDrawingFile() { return null; },
    async chooseDirectory() { return null; },
    ...overrides
  };
}

test("a gateway boots with its configured drawing as the only session", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: MINIMAL_DXF
  });
  context.after(() => server.close());
  const base = await listen(server);

  const body = await (await fetch(`${base}/api/drawings/sessions`)).json();

  assert.equal(body.sessions.length, 1);
  assert.equal(body.sessions[0].displayName, "minimal-architectural.dxf");
  assert.equal(body.sessions[0].active, true);
  assert.equal(body.activeSessionId, body.sessions[0].id);
});

test("opening without a host dialog reports the dialog as unavailable", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: MINIMAL_DXF
  });
  context.after(() => server.close());
  const base = await listen(server);

  const response = await fetch(`${base}/api/drawings/open`, { method: "POST" });

  assert.equal(response.status, 501);
  assert.equal((await response.json()).error.code, "DIALOG_UNAVAILABLE");
});

test("a dismissed drawing dialog leaves the open sessions untouched", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: MINIMAL_DXF,
    dialogs: dialogs()
  });
  context.after(() => server.close());
  const base = await listen(server);

  const response = await fetch(`${base}/api/drawings/open`, { method: "POST" });

  assert.equal(response.status, 409);
  assert.equal((await response.json()).error.code, "DRAWING_OPEN_CANCELLED");
  assert.equal((await (await fetch(`${base}/api/drawings/sessions`)).json()).sessions.length, 1);
});

test("a chosen drawing becomes a second active session and drives the drawing route", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: MINIMAL_DXF,
    dialogs: dialogs({
      async openDrawingFile() {
        return { canonicalPath: EXPORT_SAMPLE, displayName: "export_sample.dwg" };
      }
    })
  });
  context.after(() => server.close());
  const base = await listen(server);

  const before = await (await fetch(`${base}/api/drawing`)).json();
  assert.equal(before.entities.length, 4);

  const opened = await (await fetch(`${base}/api/drawings/open`, { method: "POST" })).json();
  assert.equal(opened.sessions.length, 2);
  assert.equal(opened.sessions[1].displayName, "export_sample.dwg");
  assert.equal(opened.sessions[1].active, true);
  assert.equal(opened.sessions[0].active, false);

  // The active session drives every read surface, not just the session list.
  const after = await (await fetch(`${base}/api/drawing`)).json();
  assert.equal(after.entities.length, 234);

  const inspection = await fetch(`${base}/api/inspections`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ checks: [{ kind: "layer", value: "0" }] })
  });
  assert.equal(inspection.status, 200);
  assert.equal((await inspection.json()).drawingId, opened.sessions[1].drawingId);

  const restored = await (await fetch(
    `${base}/api/drawings/sessions/${opened.sessions[0].id}/activate`,
    { method: "POST" }
  )).json();
  assert.equal(restored.activeSessionId, opened.sessions[0].id);
  assert.equal((await (await fetch(`${base}/api/drawing`)).json()).entities.length, 4);
});

test("an unknown session cannot be activated and the last one cannot be closed", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: MINIMAL_DXF
  });
  context.after(() => server.close());
  const base = await listen(server);

  const unknown = await fetch(`${base}/api/drawings/sessions/session-404/activate`, {
    method: "POST"
  });
  assert.equal(unknown.status, 404);
  assert.equal((await unknown.json()).error.code, "SESSION_UNKNOWN");

  const sessions = await (await fetch(`${base}/api/drawings/sessions`)).json();
  const last = await fetch(`${base}/api/drawings/sessions/${sessions.activeSessionId}`, {
    method: "DELETE"
  });
  assert.equal(last.status, 409);
  assert.equal((await last.json()).error.code, "SESSION_LAST");
});

test("closing a session removes it and restores an active drawing", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: MINIMAL_DXF,
    dialogs: dialogs({
      async openDrawingFile() {
        return { canonicalPath: EXPORT_SAMPLE, displayName: "export_sample.dwg" };
      }
    })
  });
  context.after(() => server.close());
  const base = await listen(server);

  const opened = await (await fetch(`${base}/api/drawings/open`, { method: "POST" })).json();
  const closed = await (await fetch(
    `${base}/api/drawings/sessions/${opened.activeSessionId}`,
    { method: "DELETE" }
  )).json();

  assert.equal(closed.sessions.length, 1);
  assert.equal(closed.sessions[0].active, true);
  assert.equal((await (await fetch(`${base}/api/drawing`)).json()).entities.length, 4);
});

test("a drawing opened outside the repository can be saved through the repository CAD I/O host", async (context) => {
  const externalRoot = await mkdtemp(join(tmpdir(), "dwg-opened-session-"));
  context.after(() => rm(externalRoot, { recursive: true, force: true }));
  const externalDrawing = join(externalRoot, "export_sample.dwg");
  await copyFile(EXPORT_SAMPLE, externalDrawing);
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: MINIMAL_DXF,
    dialogs: dialogs({
      async openDrawingFile() {
        return { canonicalPath: externalDrawing, displayName: "export_sample.dwg" };
      },
      async chooseDirectory() {
        return { canonicalDirectory: externalRoot, displayDirectory: "Test exports" };
      }
    })
  });
  context.after(() => server.close());
  const base = await listen(server);

  await fetch(`${base}/api/drawings/open`, { method: "POST" });
  const drawing = await (await fetch(`${base}/api/drawing`)).json();
  const grant = await (await fetch(`${base}/api/export/destination-grants`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}"
  })).json();
  const saved = await fetch(`${base}/api/export/drawings`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      documentId: drawing.drawingId,
      expectedRevision: drawing.drawing.revision,
      destinationGrantId: grant.grantId,
      baseFilename: "opened-session-copy",
      format: "dxf",
      version: "AC1032"
    })
  });

  assert.equal(saved.status, 200);
  assert.equal((await saved.json()).status, "passed");
});
