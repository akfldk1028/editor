import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const contract = await readFile(
  "docs/architecture/integration-contract.md",
  "utf8"
);

test("public loopback contract lists every CAD edit route and shared DTO", () => {
  const routes = [
    ["/api/edit/preview", "CadEditPreviewRequest", "CadEditPreviewResponse"],
    ["/api/edit/apply", "CadEditApplyRequest", "CadEditApplyResponse"],
    ["/api/edit/undo", "CadEditHistoryRequest", "CadEditApplyResponse"],
    ["/api/edit/redo", "CadEditHistoryRequest", "CadEditApplyResponse"]
  ];

  for (const [route, request, response] of routes) {
    assert.match(contract, new RegExp(
      String.raw`\|\s*\x60POST\x60\s*\|\s*\x60${route.replaceAll("/", String.raw`\/`)}\x60\s*\|[^\n]*\x60${request}\x60[^\n]*\x60${response}\x60`
    ));
  }
  assert.match(contract, /strict shared `@dwg\/contracts` validators/i);
});

test("public loopback contract fixes edit lifecycle privacy and trust guarantees", () => {
  for (const pattern of [
    /1 MiB/,
    /`approved: true`/,
    /`expectedRevision`/,
    /server-owned `previewId`/,
    /single use/i,
    /ten minutes/i,
    /20 active previews/i,
    /`changesTruncated`/,
    /`warningsTruncated`/,
    /same `AbortSignal`/,
    /before-state/i,
    /provider content/i,
    /bounded, redacted/i,
    /single loopback trust boundary/i,
    /does\s+not\s+write DWG or DXF files/i,
    /MCP\s+remains\s+read-only/i
  ]) {
    assert.match(contract, pattern);
  }
});
