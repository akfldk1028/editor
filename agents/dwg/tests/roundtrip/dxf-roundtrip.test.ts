import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { createAcadSharpCadIoClient, type CadProcessRunner } from "@dwg/cad-io-acadsharp";
import { createDocumentSnapshot } from "@dwg/cad-document";
import { createCadEditHistory } from "@dwg/cad-edit";
import type { CadEditBatch } from "@dwg/contracts";

import { createDestinationGrantStore, createSaveCoordinator } from "../../modules/cad-capabilities/src/index.js";
import { buildIndexFromDxfFileName } from "../../modules/cad-runtime/src/parsers/dxf/dxfIndexer.js";

const repositoryRoot = resolve(import.meta.dirname, "../..");
const hostProject = join(
  repositoryRoot,
  "modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgIntelligence.CadIo.Host.csproj"
);

test("real ACadSharp DXF write is independently reopened and source remains immutable", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "cad-save-roundtrip-"));
  t.after(() => rm(root, { force: true, recursive: true }));
  const destination = join(root, "destination");
  await mkdir(destination, { recursive: true });
  const sourcePath = join(root, "source.dxf");
  await writeFile(sourcePath, twoLineDxf(), "utf8");
  const sourceBytes = await readFile(sourcePath);
  const sourceHash = sha256(sourceBytes);
  const sourceIndex = buildIndexFromDxfFileName(sourceBytes.toString("utf8"), sourcePath);
  const snapshot = createDocumentSnapshot(sourceIndex, sourceHash);
  snapshot.drawingVersion = "AC1027";
  snapshot.units = null;
  snapshot.index.drawing = { fileVersion: "AC1027", units: null };
  const sourceLine = snapshot.index.entities.find((entity) => entity.handle === "10");
  assert.ok(sourceLine?.bbox);
  sourceLine.geometry = {
    kind: "line",
    start: [...sourceLine.bbox.min],
    end: [...sourceLine.bbox.max]
  };
  const history = createCadEditHistory(snapshot);
  const batch: CadEditBatch = {
    schemaVersion: "cad-edit/v1",
    transactionId: "50000000-0000-4000-8000-000000000001",
    documentId: snapshot.documentId,
    expectedRevision: 0,
    commands: [{
      commandId: "60000000-0000-4000-8000-000000000001",
      expectedRevision: 0,
      origin: { kind: "user", id: "roundtrip" },
      preconditions: [{ target: "10", field: "exists", equals: true }],
      operation: { kind: "entity.move", handles: ["10"], delta: [5, 10, 0] }
    }]
  };
  history.apply(history.preview(batch));
  const grants = createDestinationGrantStore();
  const grantId = await grants.issue(destination, Date.now() + 60_000);
  const coordinator = createSaveCoordinator({
    cadIo: createAcadSharpCadIoClient({
      projectPath: hostProject,
      processRunner: new SpawnRunner()
    }),
    sources: {
      async resolve(documentId) {
        return {
          documentId,
          canonicalPath: await realpath(sourcePath),
          sourceSha256: sourceHash,
          drawingVersion: "AC1027",
          units: null
        };
      }
    },
    async readDocument(path) {
      const bytes = await readFile(path);
      const text = bytes.toString("utf8");
      const index = buildIndexFromDxfFileName(text, path);
      const version = dxfHeader(text, "$ACADVER");
      const unitsCode = dxfHeader(text, "$INSUNITS");
      return {
        index,
        sourceSha256: sha256(bytes),
        drawingVersion: version,
        units: unitsCode === null || unitsCode === "0" ? null : unitsCode
      };
    },
    transactions: history,
    grants
  });

  const verification = await coordinator.saveCopy({
    documentId: snapshot.documentId,
    expectedRevision: 1,
    destinationGrantId: grantId,
    baseFilename: "roundtrip",
    format: "dxf",
    version: "AC1027"
  });
  const finalPath = join(destination, "roundtrip.dxf");
  const reopened = buildIndexFromDxfFileName(await readFile(finalPath, "utf8"), finalPath);

  assert.equal(verification.status, "passed");
  assert.deepEqual(reopened.entities.find((entity) => entity.handle === "10")?.bbox, {
    min: [5, 10, 0],
    max: [105, 10, 0]
  });
  assert.equal(await shaFile(sourcePath), sourceHash);
  assert.equal(await shaFile(finalPath), verification.outputSha256);
});

class SpawnRunner implements CadProcessRunner {
  async run(spec: Parameters<CadProcessRunner["run"]>[0], signal?: AbortSignal) {
    return new Promise<{ exitCode: number; stdout: string; stderr: string }>((resolveRun, reject) => {
      const child = spawn(spec.command, spec.args, {
        cwd: spec.cwd,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
        signal
      });
      const stdout: Buffer[] = [];
      const stderr: Buffer[] = [];
      let bytes = 0;
      const collect = (target: Buffer[]) => (chunk: Buffer) => {
        bytes += chunk.byteLength;
        if (bytes > spec.maxOutputBytes) {
          child.kill();
          reject(new Error("process output limit"));
          return;
        }
        target.push(chunk);
      };
      child.stdout.on("data", collect(stdout));
      child.stderr.on("data", collect(stderr));
      child.once("error", reject);
      child.once("close", (code) => resolveRun({
        exitCode: code ?? -1,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8")
      }));
      child.stdin.end(spec.stdin);
    });
  }
}

function dxfHeader(text: string, variable: string): string | null {
  const lines = text.replaceAll("\r", "").split("\n");
  const index = lines.findIndex((line) => line.trim() === variable);
  return index >= 0 ? lines[index + 2]?.trim() ?? null : null;
}

function twoLineDxf(): string {
  return [
    "0", "SECTION", "2", "HEADER",
    "9", "$ACADVER", "1", "AC1027",
    "0", "ENDSEC",
    "0", "SECTION", "2", "TABLES",
    "0", "TABLE", "2", "LAYER", "70", "1",
    "0", "LAYER", "2", "A-WALL", "70", "0", "62", "7", "6", "CONTINUOUS",
    "0", "ENDTAB", "0", "ENDSEC",
    "0", "SECTION", "2", "ENTITIES",
    "0", "LINE", "5", "10", "8", "A-WALL",
    "10", "0", "20", "0", "30", "0", "11", "100", "21", "0", "31", "0",
    "0", "LINE", "5", "11", "8", "A-WALL",
    "10", "0", "20", "20", "30", "0", "11", "100", "21", "20", "31", "0",
    "0", "ENDSEC", "0", "EOF", ""
  ].join("\n");
}

async function shaFile(path: string): Promise<string> {
  return sha256(await readFile(path));
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex").toUpperCase();
}
