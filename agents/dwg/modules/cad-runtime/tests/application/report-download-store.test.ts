import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { MAX_REPORT_BYTES } from "@dwg/cad-export";

import {
  CadReportDownloadStoreError,
  createCadReportDownloadStore
} from "../../src/application/reportDownloadStore.js";

test("report download storage enforces total bytes and prunes expired entries before capacity checks", async () => {
  let now = 1_000;
  const bytes = new Uint8Array(MAX_REPORT_BYTES);
  const store = createCadReportDownloadStore({
    clock: () => now,
    async generate() {
      return {
        format: "json" as const,
        mediaType: "application/json",
        filename: "bounded.json",
        bytes,
        sha256: createHash("sha256").update(bytes).digest("hex").toUpperCase()
      };
    }
  });
  const request = { documentId: "drawing:bounded", revision: 0, format: "json" };

  for (let index = 0; index < 16; index += 1) {
    await store.create(request);
  }
  await assert.rejects(
    store.create(request),
    (error) => error instanceof CadReportDownloadStoreError &&
      error.code === "REPORT_DOWNLOAD_CAPACITY"
  );

  now += 10 * 60 * 1_000;
  assert.match((await store.create(request)).filename, /\.json$/u);
});
