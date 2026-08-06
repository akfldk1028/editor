import { createHash } from "node:crypto";
import { open, readFile } from "node:fs/promises";
import { extname } from "node:path";

import type { CadParsedDocumentEvidence } from "@dwg/cad-capabilities";
import type { CadEntityIndex } from "@dwg/contracts";

import { buildIndexFromDwgFile } from "../../parsers/dwg/acadSharpIndexer.js";
import { buildIndexFromDxfFileName } from "../../parsers/dxf/dxfIndexer.js";

export async function readSourceSha256(path: string, signal?: AbortSignal): Promise<string> {
  if (signal?.aborted) throw signal.reason;
  const handle = await open(path, "r");
  try {
    const hash = createHash("sha256");
    const buffer = Buffer.allocUnsafe(64 * 1024);
    let offset = 0;
    while (true) {
      if (signal?.aborted) throw signal.reason;
      const { bytesRead } = await handle.read(buffer, 0, buffer.byteLength, offset);
      if (bytesRead === 0) break;
      hash.update(buffer.subarray(0, bytesRead));
      offset += bytesRead;
    }
    return hash.digest("hex").toUpperCase();
  } finally {
    await handle.close();
  }
}

export async function readParsedDocumentEvidence(
  path: string,
  signal?: AbortSignal
): Promise<CadParsedDocumentEvidence> {
  const [index, sourceSha256] = await Promise.all([
    buildIndexForPath(path, signal),
    readSourceSha256(path, signal)
  ]);
  return {
    index,
    sourceSha256,
    drawingVersion: index.drawing?.fileVersion ?? null,
    units: index.drawing?.units ?? null
  };
}

export async function buildIndexForPath(
  path: string,
  signal?: AbortSignal
): Promise<CadEntityIndex> {
  if (signal?.aborted) throw signal.reason;
  switch (extname(path).toLowerCase()) {
    case ".dwg": return buildIndexFromDwgFile(path);
    case ".dxf": return buildIndexFromDxfFileName(await readFile(path, "utf8"), path);
    default: throw new Error(`Unsupported drawing format: ${extname(path).toLowerCase() || "(none)"}`);
  }
}

// Save verification compares a written copy against the active document, so
// both sides must come from the same parser and entity model. The active index
// is produced by whichever parser buildIndexForPath selects for the source
// format: ACadSharp emits cad-index/v0.2 for DWG, and the legacy indexer emits
// cad-index/v0.1 for DXF. Reading the copy with the other parser produces a
// different entity model that verification can never match, so the reader is
// bound to the source format rather than to the output format.
export function createVerificationDocumentReader(
  sourcePath: string
): (path: string, signal?: AbortSignal) => Promise<CadParsedDocumentEvidence> {
  const readsThroughAcadSharp = extname(sourcePath).toLowerCase() === ".dwg";
  return async (path, signal) => {
    if (!readsThroughAcadSharp) return readParsedDocumentEvidence(path, signal);
    const extension = extname(path).toLowerCase();
    if (extension !== ".dwg" && extension !== ".dxf") {
      throw new Error(`Unsupported drawing format: ${extension || "(none)"}`);
    }
    const [index, sourceSha256] = await Promise.all([
      buildIndexFromDwgFile(path),
      readSourceSha256(path, signal)
    ]);
    return {
      index,
      sourceSha256,
      drawingVersion: index.drawing?.fileVersion ?? null,
      units: index.drawing?.units ?? null
    };
  };
}
