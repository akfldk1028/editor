import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import type { ExportCapabilitiesResponse } from "@dwg/contracts";
import * as exportHook from "../../src/features/export/useExport.js";

type CommitIfActive = (
  signal: AbortSignal,
  response: ExportCapabilitiesResponse,
  commit: (response: ExportCapabilitiesResponse) => void
) => void;

const response: ExportCapabilitiesResponse = { capabilities: [] };

function lifecycleGuard(): CommitIfActive {
  const candidate = (exportHook as unknown as { commitExportCapabilitiesIfActive?: unknown })
    .commitExportCapabilitiesIfActive;
  assert.equal(typeof candidate, "function");
  return candidate as CommitIfActive;
}

test("commits an export capability response while the effect is active", () => {
  let committed: ExportCapabilitiesResponse | null = null;
  lifecycleGuard()(new AbortController().signal, response, (value) => { committed = value; });
  assert.equal(committed, response);
});

test("does not commit an export capability response after effect cleanup aborts", () => {
  const controller = new AbortController();
  controller.abort();
  let commits = 0;
  lifecycleGuard()(controller.signal, response, () => { commits += 1; });
  assert.equal(commits, 0);
});

test("a new export action aborts in-flight HTTP and blocks its stale commit", async (t) => {
  const lifecycle = exportHook.createExportActionLifecycle();
  let requestStarted!: () => void;
  const started = new Promise<void>((resolve) => { requestStarted = resolve; });
  const server = createServer((_request, response) => {
    requestStarted();
    response.on("close", () => response.end());
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");

  const first = lifecycle.begin();
  const pending = fetch(`http://127.0.0.1:${address.port}/pending`, {
    signal: first.signal
  });
  await started;
  const second = lifecycle.begin();

  await assert.rejects(pending, (error) =>
    error instanceof DOMException && error.name === "AbortError"
  );
  let committed = "";
  exportHook.commitExportActionIfCurrent(
    lifecycle,
    first,
    () => { committed = "stale"; }
  );
  exportHook.commitExportActionIfCurrent(
    lifecycle,
    second,
    () => { committed = "current"; }
  );
  assert.equal(committed, "current");
  assert.equal(lifecycle.finish(first), false);
  assert.equal(lifecycle.finish(second), true);
});

test("export action cleanup aborts the current request", () => {
  const lifecycle = exportHook.createExportActionLifecycle();
  const current = lifecycle.begin();
  lifecycle.abort();
  assert.equal(current.signal.aborted, true);
  assert.equal(lifecycle.isCurrent(current), false);
});
