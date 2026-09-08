import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import {
  linkSync,
  mkdirSync,
  renameSync,
  rmSync,
  writeFileSync
} from "node:fs";
import {
  lstat,
  mkdtemp,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  symlink,
  truncate,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import test, { type TestContext } from "node:test";

import type { CadIoClient, CadIoWriteRequest, CadIoWriteResult } from "@dwg/cad-io-acadsharp";
import type { CadReportInput } from "@dwg/cad-export";
import type { CadCommittedTransactionStore, CadSaveState } from "@dwg/cad-edit";
import { createCadEditHistory } from "@dwg/cad-edit";
import type { CadDocumentSnapshot } from "@dwg/cad-document";
import type {
  CadEditBatch,
  CadEditCommand,
  CadEntityIndex,
  ReportFormat
} from "@dwg/contracts";

import {
  CadSaveError,
  createDestinationGrantStore,
  createSaveCapabilityModule,
  createSaveCoordinator,
  type CadParsedDocumentEvidence,
  type CadSaveCoordinator
} from "../src/index.js";
import {
  createNodeCadSaveFileSystem,
  type CadSaveFileSystem
} from "../src/saveCoordinator.js";

const TX1 = "10000000-0000-4000-8000-000000000001";
const TX2 = "10000000-0000-4000-8000-000000000002";
const TX3 = "10000000-0000-4000-8000-000000000003";
const CMD1 = "20000000-0000-4000-8000-000000000001";
const CMD2 = "20000000-0000-4000-8000-000000000002";
const CMD3 = "20000000-0000-4000-8000-000000000003";
const OUTPUT_BYTES = new TextEncoder().encode("independently reopened output");
const LARGE_SOURCE_BYTES = 64 * 1024 * 1024;
const LARGE_ZERO_SHA256 =
  "3B6A07D0D404FAB4E23B6D34BC6696A6A312DD92821332385E5AF7C01C421351";

test("destination grants are canonical, opaque, expiring, and one use", async (t) => {
  const root = await temporaryDirectory(t);
  const destination = join(root, "destination");
  await writeFile(join(root, "anchor"), "");
  await import("node:fs/promises").then(({ mkdir }) => mkdir(destination));
  let now = 1_000;
  const grants = createDestinationGrantStore({ now: () => now });

  const id = await grants.issue(destination, 2_000);
  assert.match(id, /^[0-9a-f-]{36}$/iu);
  const consumed = await grants.consume(id);
  assert.equal(consumed.canonicalDirectory, await realpath(destination));
  assert.equal(consumed.used, true);
  await assert.rejects(grants.consume(id), hasCode("DESTINATION_GRANT_REUSED"));
  await assert.rejects(grants.consume(randomUUID()), hasCode("DESTINATION_GRANT_UNKNOWN"));

  const expiring = await grants.issue(destination, 1_001);
  now = 1_001;
  await assert.rejects(grants.consume(expiring), hasCode("DESTINATION_GRANT_EXPIRED"));
});

test("destination grants canonicalize a directory junction without retaining alias lineage", async (t) => {
  const root = await temporaryDirectory(t);
  const destination = join(root, "destination");
  const alias = join(root, "alias");
  const { mkdir } = await import("node:fs/promises");
  await mkdir(destination);
  await symlink(destination, alias, process.platform === "win32" ? "junction" : "dir");
  const grants = createDestinationGrantStore();

  const id = await grants.issue(alias, Date.now() + 60_000);
  const consumed = await grants.consume(id);

  assert.equal(consumed.canonicalDirectory, await realpath(destination));
  assert.notEqual(consumed.canonicalDirectory, alias);
});

test("large sparse output hashing yields to the event loop and stays bounded", async (t) => {
  const root = await temporaryDirectory(t);
  const path = join(root, "large-sparse.dxf");
  await writeFile(path, "");
  await truncate(path, 128 * 1024 * 1024);
  const fileSystem = createNodeCadSaveFileSystem();
  const handle = await fileSystem.openRead(path);
  let timerFired = false;
  const startedAt = Date.now();
  setTimeout(() => {
    timerFired = true;
  }, 0);

  const pendingHash = handle.sha256();
  const synchronousCallMs = Date.now() - startedAt;
  const hash = await pendingHash;
  handle.close();

  assert.equal(timerFired, true);
  assert.ok(synchronousCallMs < 10);
  assert.match(hash, /^[0-9A-F]{64}$/u);
  assert.ok(Date.now() - startedAt < 5_000);
});

test("path and handle hashing reject a pre-aborted signal without opening or reading", async (t) => {
  const root = await temporaryDirectory(t);
  const path = join(root, "pre-aborted.dxf");
  await writeFile(path, "source");
  const fileSystem = createNodeCadSaveFileSystem();
  const controller = new AbortController();
  controller.abort();

  await assert.rejects(
    fileSystem.sha256(join(root, "missing.dxf"), controller.signal),
    isAbort
  );
  const handle = await fileSystem.openRead(path);
  await assert.rejects(handle.sha256(controller.signal), isAbort);
  handle.close();

  const moved = join(root, "pre-aborted-moved.dxf");
  await rename(path, moved);
  assert.equal(await readFile(moved, "utf8"), "source");
});

test("real 64 MiB path hashing aborts between bounded reads and closes its descriptor", async (t) => {
  const root = await temporaryDirectory(t);
  const path = join(root, "large-source.dxf");
  await writeFile(path, "");
  await truncate(path, LARGE_SOURCE_BYTES);
  const fileSystem = createNodeCadSaveFileSystem();
  const controller = new AbortController();
  const startedAt = Date.now();

  const pending = fileSystem.sha256(path, controller.signal);
  setTimeout(() => controller.abort(), 0);

  await assert.rejects(pending, isAbort);
  assert.ok(Date.now() - startedAt < 1_000);
  const moved = join(root, "large-source-moved.dxf");
  await rename(path, moved);
  assert.equal((await lstat(moved)).size, LARGE_SOURCE_BYTES);
});

test("initial 64 MiB source hash cancellation forwards the signal and never launches writer", async (t) => {
  const base = createNodeCadSaveFileSystem();
  const controller = new AbortController();
  const seenSignals: Array<AbortSignal | undefined> = [];
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async sha256(path, signal) {
      seenSignals.push(signal);
      setTimeout(() => controller.abort(), 0);
      return base.sha256(path, signal);
    }
  };
  const harness = await createHarness(
    t,
    createCadEditHistory(snapshot(LARGE_ZERO_SHA256)),
    {
      fileSystem,
      sourceSizeBytes: LARGE_SOURCE_BYTES,
      sourceSha256: LARGE_ZERO_SHA256
    }
  );

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input, controller.signal),
    isAbort
  );
  assert.deepEqual(seenSignals, [controller.signal]);
  assert.equal(harness.requests.length, 0);
  assert.equal(await exists(harness.finalPath), false);
  const moved = `${harness.sourcePath}.moved`;
  await rename(harness.sourcePath, moved);
  assert.equal((await lstat(moved)).size, LARGE_SOURCE_BYTES);
});

test("successful save uses resolver source and active two-transaction lineage then atomically finalizes", async (t) => {
  const history = createCadEditHistory(snapshot());
  apply(history, textBatch(0, "updated", TX1, CMD1));
  apply(history, copyBatch(1, TX2, CMD2));
  const harness = await createHarness(t, history);

  const verification = await harness.coordinator.saveCopy(harness.input);

  assert.equal(verification.status, "passed");
  assert.equal(verification.intendedChangeCount, 2);
  assert.equal(verification.verifiedChangeCount, 2);
  assert.equal(verification.sourceSha256, harness.sourceSha256);
  assert.equal(verification.outputSha256, sha256(OUTPUT_BYTES));
  assert.deepEqual(Object.keys(verification.copiedHandleMap), [temporaryId(TX2, CMD2)]);
  assert.deepEqual(verification.warnings, ["writer-normalized-header"]);
  assert.deepEqual(harness.requests.map((request) => request.lineage.map((item) => item.transactionId)), [[TX1, TX2]]);
  assert.equal(harness.requests[0]!.sourcePath, harness.sourcePath);
  assert.deepEqual(harness.requests[0]!.lineage.map((item) => [item.beforeRevision, item.afterRevision]), [[0, 1], [1, 2]]);
  assert.deepEqual(Object.keys(harness.requests[0]!).sort(), [
    "format", "lineage", "sourcePath", "temporaryOutputPath", "version"
  ]);
  assert.equal(await readFile(harness.finalPath, "utf8"), new TextDecoder().decode(OUTPUT_BYTES));
  assert.equal(await readFile(harness.sourcePath, "utf8"), harness.sourceText);
  assert.deepEqual(await temporaryOutputs(harness.destination), []);
  assert.deepEqual(await readdir(harness.destination), ["verified-copy.dxf"]);
  assert.ok(harness.events.indexOf("writer:closed") < harness.events.indexOf("parser:opened"));
  assert.ok(harness.events.indexOf("parser:closed") < harness.events.indexOf("final:visible"));
  assert.deepEqual(harness.coordinator.getVerification(verification.id), verification);
  const copy = harness.coordinator.getVerification(verification.id)!;
  copy.warnings.push("outside mutation");
  assert.deepEqual(harness.coordinator.getVerification(verification.id), verification);
});

test("writer-created external hard link is neutralized without deleting the unknown alias", async (t) => {
  let aliasPath = "";
  let verificationId = "";
  const harness = await createHarness(t, createCadEditHistory(snapshot()), {
    afterWriterOutput(path) {
      aliasPath = join(dirname(path), "writer-owned-elsewhere.dxf");
      verificationId = verificationIdFromTemporaryPath(path);
      linkSync(path, aliasPath);
    }
  });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_CLEANUP_FAILED")
  );
  assert.equal(await exists(harness.finalPath), false);
  assert.equal(await exists(aliasPath), true);
  assert.equal((await readFile(aliasPath)).byteLength, 0);
  assert.equal(harness.coordinator.getVerification(verificationId), null);
});

test("external hard link created after output hashing is neutralized before publication", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let aliasPath = "";
  let verificationId = "";
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async openRead(path) {
      const handle = await base.openRead(path);
      return {
        identity: () => handle.identity(),
        async sha256(signal) {
          const result = await handle.sha256(signal);
          aliasPath = join(dirname(path), "post-hash-alias.dxf");
          verificationId = verificationIdFromTemporaryPath(path);
          linkSync(path, aliasPath);
          return result;
        },
        sanitize: () => handle.sanitize(),
        close: () => handle.close()
      };
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_CLEANUP_FAILED")
  );
  assert.equal(await exists(harness.finalPath), false);
  assert.equal(await exists(aliasPath), true);
  assert.equal((await readFile(aliasPath)).byteLength, 0);
  assert.equal(harness.coordinator.getVerification(verificationId), null);
});

test("external hard link created after publication is neutralized before commit", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let aliasPath = "";
  let verificationId = "";
  const fileSystem: CadSaveFileSystem = {
    ...base,
    publishVerifiedNoReplace(input) {
      const result = base.publishVerifiedNoReplace(input);
      aliasPath = join(dirname(input.finalPath), "post-publish-alias.dxf");
      verificationId = verificationIdFromTemporaryPath(input.temporaryPath);
      linkSync(input.finalPath, aliasPath);
      return result;
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_CLEANUP_FAILED")
  );
  assert.equal(await exists(harness.finalPath), false);
  assert.equal(await exists(aliasPath), true);
  assert.equal((await readFile(aliasPath)).byteLength, 0);
  assert.equal(harness.coordinator.getVerification(verificationId), null);
});

test("atomic publication preserves a racing existing destination without overwriting it", async (t) => {
  const base = createNodeCadSaveFileSystem();
  const fileSystem: CadSaveFileSystem = {
    ...base,
    publishVerifiedNoReplace(input) {
      writeFileSync(input.finalPath, "racing owner");
      return base.publishVerifiedNoReplace(input);
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_OUTPUT_EXISTS")
  );
  assert.equal(await readFile(harness.finalPath, "utf8"), "racing owner");
  assert.deepEqual(await temporaryOutputs(harness.destination), []);
});

test("publication rejects a replaced temporary file and removes the linked final", async (t) => {
  const base = createNodeCadSaveFileSystem();
  const fileSystem: CadSaveFileSystem = {
    ...base,
    publishVerifiedNoReplace(input) {
      rmSync(input.temporaryPath, { force: true });
      writeFileSync(input.temporaryPath, "unverified replacement");
      return base.publishVerifiedNoReplace(input);
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_VERIFICATION_FAILED")
  );
  assert.equal(await exists(harness.finalPath), false);
});

test("commit validation retracts a replaced final and stores no passed verification", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let replaced = false;
  let verificationId = "";
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async remove(path) {
      await base.remove(path);
      if (!replaced && path.includes(".click-around.tmp.")) {
        replaced = true;
        verificationId = verificationIdFromTemporaryPath(path);
        const finalPath = join(dirname(path), "verified-copy.dxf");
        rmSync(finalPath);
        writeFileSync(finalPath, "post-link replacement");
      }
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_VERIFICATION_FAILED")
  );
  assert.equal(await exists(harness.finalPath), false);
  assert.equal(harness.coordinator.getVerification(verificationId), null);
});

test("moved destination residue is neutralized and reported as cleanup failure", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let replaced = false;
  let verificationId = "";
  let movedDirectory = "";
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async remove(path) {
      await base.remove(path);
      if (!replaced && path.includes(".click-around.tmp.")) {
        replaced = true;
        verificationId = verificationIdFromTemporaryPath(path);
        const directory = dirname(path);
        movedDirectory = `${directory}-moved`;
        renameSync(directory, movedDirectory);
        mkdirSync(directory);
      }
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_CLEANUP_FAILED")
  );
  assert.equal(await exists(harness.finalPath), false);
  const movedFinal = join(movedDirectory, "verified-copy.dxf");
  assert.equal((await readFile(movedFinal)).byteLength, 0);
  assert.equal(harness.coordinator.getVerification(verificationId), null);
  await rm(movedDirectory, { force: false, recursive: true });
});

test("commit validation retracts final when source mutates after publication", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let mutated = false;
  let sourcePath = "";
  let replacement = "";
  let verificationId = "";
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async remove(path) {
      await base.remove(path);
      if (!mutated && path.includes(".click-around.tmp.")) {
        mutated = true;
        verificationId = verificationIdFromTemporaryPath(path);
        writeFileSync(sourcePath, replacement);
      }
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });
  sourcePath = harness.sourcePath;
  replacement = "X".repeat(Buffer.byteLength(harness.sourceText));

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_SOURCE_MUTATED")
  );
  assert.equal(await exists(harness.finalPath), false);
  assert.equal(harness.coordinator.getVerification(verificationId), null);
});

test("late cancellation during the pre-publication source hash never exposes final output", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let sourceHashes = 0;
  let releaseHash!: () => void;
  let markHashStarted!: () => void;
  const hashStarted = new Promise<void>((resolve) => { markHashStarted = resolve; });
  const hashRelease = new Promise<void>((resolve) => { releaseHash = resolve; });
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async sha256(path, signal) {
      if (basename(path) === "source.dxf" && ++sourceHashes === 2) {
        markHashStarted();
        await hashRelease;
      }
      return base.sha256(path, signal);
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });
  const controller = new AbortController();

  const pending = harness.coordinator.saveCopy(harness.input, controller.signal);
  await hashStarted;
  controller.abort();
  releaseHash();

  await assert.rejects(pending, isAbort);
  assert.equal(await exists(harness.finalPath), false);
});

test("prepublication 64 MiB source hash cancellation closes the descriptor and retracts output", async (t) => {
  const base = createNodeCadSaveFileSystem();
  const controller = new AbortController();
  const seenSignals: Array<AbortSignal | undefined> = [];
  let sourceHashes = 0;
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async sha256(path, signal) {
      seenSignals.push(signal);
      if (basename(path) === "source.dxf" && ++sourceHashes === 2) {
        setTimeout(() => controller.abort(), 0);
      }
      return base.sha256(path, signal);
    }
  };
  const harness = await createHarness(
    t,
    createCadEditHistory(snapshot(LARGE_ZERO_SHA256)),
    {
      fileSystem,
      sourceSizeBytes: LARGE_SOURCE_BYTES,
      sourceSha256: LARGE_ZERO_SHA256
    }
  );

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input, controller.signal),
    isAbort
  );
  assert.deepEqual(seenSignals, [controller.signal, controller.signal]);
  assert.equal(harness.requests.length, 1);
  assert.equal(await exists(harness.finalPath), false);
  assert.deepEqual(await temporaryOutputs(harness.destination), []);
  const moved = `${harness.sourcePath}.moved`;
  await rename(harness.sourcePath, moved);
  assert.equal((await lstat(moved)).size, LARGE_SOURCE_BYTES);
});

test("cancellation immediately after atomic link removes final and never stores passed verification", async (t) => {
  const base = createNodeCadSaveFileSystem();
  const controller = new AbortController();
  const fileSystem: CadSaveFileSystem = {
    ...base,
    publishVerifiedNoReplace(input) {
      const publication = base.publishVerifiedNoReplace(input);
      controller.abort();
      return publication;
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input, controller.signal),
    isAbort
  );
  assert.equal(await exists(harness.finalPath), false);
});

test("unsupported hard-link destination fails before writer launch", async (t) => {
  const base = createNodeCadSaveFileSystem();
  const fileSystem: CadSaveFileSystem = {
    ...base,
    preflightNoReplace() {
      throw new CadSaveError("CAD_SAVE_DESTINATION_UNSUPPORTED");
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_DESTINATION_UNSUPPORTED")
  );
  assert.equal(harness.requests.length, 0);
  assert.equal(await exists(harness.finalPath), false);
});

test("cleanup failure is explicit and never stores a passed verification", async (t) => {
  const base = createNodeCadSaveFileSystem();
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async remove() {
      throw Object.assign(new Error("locked"), { code: "EACCES" });
    },
    async move() {
      throw Object.assign(new Error("still locked"), { code: "EACCES" });
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), {
    fileSystem,
    writerFailure: true
  });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_CLEANUP_FAILED")
  );
  assert.equal(await exists(harness.finalPath), false);
});

test("post-publication temporary cleanup failure retracts final and reports fatal cleanup", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let failedTemporaryRemoval = false;
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async remove(path) {
      if (!failedTemporaryRemoval && path.includes(".click-around.tmp.")) {
        failedTemporaryRemoval = true;
        throw Object.assign(new Error("locked temp"), { code: "EACCES" });
      }
      return base.remove(path);
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_CLEANUP_FAILED")
  );
  assert.equal(await exists(harness.finalPath), false);
  assert.ok((await temporaryOutputs(harness.destination)).every((name) => name.includes(".failed.")));
});

test("sanitize failure still closes the retained handle and reports cleanup failure", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let aliasPath = "";
  let closeAttempts = 0;
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async openRead(path) {
      const handle = await base.openRead(path);
      return {
        identity: () => handle.identity(),
        async sha256(signal) {
          const hash = await handle.sha256(signal);
          aliasPath = join(dirname(path), "sanitize-failure-alias.dxf");
          linkSync(path, aliasPath);
          return hash;
        },
        sanitize() {
          throw new Error("sanitize probe");
        },
        close() {
          closeAttempts += 1;
          handle.close();
        }
      };
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_CLEANUP_FAILED")
  );
  assert.equal(closeAttempts, 1);
  assert.equal(await exists(harness.finalPath), false);
  await rm(aliasPath);
});

test("close failure retracts a would-be verification and reports cleanup failure", async (t) => {
  const base = createNodeCadSaveFileSystem();
  let closeAttempts = 0;
  let verificationId = "";
  const fileSystem: CadSaveFileSystem = {
    ...base,
    async openRead(path) {
      verificationId = verificationIdFromTemporaryPath(path);
      const handle = await base.openRead(path);
      return {
        identity: () => handle.identity(),
        sha256: (signal) => handle.sha256(signal),
        sanitize: () => handle.sanitize(),
        close() {
          closeAttempts += 1;
          if (closeAttempts === 1) {
            handle.close();
          }
          throw new Error("close probe");
        }
      };
    }
  };
  const harness = await createHarness(t, createCadEditHistory(snapshot()), { fileSystem });

  await assert.rejects(
    harness.coordinator.saveCopy(harness.input),
    hasCode("CAD_SAVE_CLEANUP_FAILED")
  );
  assert.ok(closeAttempts >= 1);
  assert.equal(await exists(harness.finalPath), false);
  assert.equal(harness.coordinator.getVerification(verificationId), null);
  await rm(harness.destination, { recursive: true });
});

test("an undone branch exports only the active branch and rebases process revisions without caller lineage", async (t) => {
  const history = createCadEditHistory(snapshot());
  apply(history, textBatch(0, "first", TX1, CMD1));
  apply(history, textBatch(1, "undone", TX2, CMD2));
  history.undo(2);
  apply(history, textBatch(3, "replacement", TX3, CMD3));
  const harness = await createHarness(t, history);

  await harness.coordinator.saveCopy(harness.input);

  assert.deepEqual(harness.requests[0]!.lineage.map((item) => item.transactionId), [TX1, TX3]);
  assert.deepEqual(harness.requests[0]!.lineage.map((item) => [item.beforeRevision, item.afterRevision]), [[0, 1], [1, 2]]);
});

test("layer-only cumulative changes do not alter the verified entity-count delta", async (t) => {
  const history = createCadEditHistory(snapshot());
  apply(history, layerCreateBatch(0, TX1, CMD1));
  const harness = await createHarness(t, history);

  const verification = await harness.coordinator.saveCopy(harness.input);

  assert.equal(verification.intendedChangeCount, 1);
  assert.equal(verification.verifiedChangeCount, 1);
  assert.equal(harness.requests[0]!.lineage[0]!.commands[0]!.kind, "layer.create");
});

test("save rejects stale, incomplete, non-contiguous, and over-limit state before writer launch", async (t) => {
  const history = createCadEditHistory(snapshot());
  apply(history, textBatch(0, "updated", TX1, CMD1));
  const valid = history.getSaveState(snapshot().documentId, 1)!;
  const cases: Array<[string, CadCommittedTransactionStore, string, number?]> = [
    ["stale", { getCommittedTransaction: () => null, getSaveState: () => null }, "CAD_SAVE_STALE"],
    ["incomplete", stateStore({
      ...valid,
      current: { ...valid.current, units: "Feet" }
    }), "CAD_SAVE_LINEAGE_INVALID"],
    ["revision mismatch", stateStore({
      ...valid,
      current: { ...valid.current, revision: valid.current.revision + 1 }
    }), "CAD_SAVE_LINEAGE_INVALID", valid.revision],
    ["non-contiguous", stateStore({
      ...valid,
      lineage: [{
        ...valid.lineage[0]!,
        before: { ...valid.lineage[0]!.before, units: "Feet" }
      }]
    }), "CAD_SAVE_LINEAGE_INVALID"],
    ["over-limit", stateStore({
      ...valid,
      lineage: [{
        ...valid.lineage[0]!,
        batch: {
          ...valid.lineage[0]!.batch,
          commands: Array.from({ length: 10_001 }, () => valid.lineage[0]!.batch.commands[0]!)
        }
      }]
    }), "CAD_SAVE_LINEAGE_LIMIT"]
  ];

  for (const [name, store, code, expectedRevision] of cases) {
    await t.test(name, async (child) => {
      const harness = await createHarness(child, store);
      await assert.rejects(harness.coordinator.saveCopy({
        ...harness.input,
        expectedRevision: expectedRevision ?? harness.input.expectedRevision
      }), hasCode(code));
      assert.equal(harness.requests.length, 0);
      assert.equal(await exists(harness.finalPath), false);
    });
  }
});

test("save rejects resolver hash, version, and units mismatches before writer launch", async (t) => {
  const mismatch = [
    { sourceSha256: "F".repeat(64) },
    { drawingVersion: "AC1027" },
    { units: "Feet" }
  ];
  for (const [index, sourceOverride] of mismatch.entries()) {
    await t.test(String(index), async (child) => {
      const harness = await createHarness(child, createCadEditHistory(snapshot()), { sourceOverride });
      await assert.rejects(harness.coordinator.saveCopy(harness.input), hasCode("CAD_SAVE_SOURCE_MISMATCH"));
      assert.equal(harness.requests.length, 0);
    });
  }
});

test("save rejects traversal, source equality, and an existing destination without overwriting", async (t) => {
  const traversal = await createHarness(t, createCadEditHistory(snapshot()));
  await assert.rejects(
    traversal.coordinator.saveCopy({ ...traversal.input, baseFilename: "../escape" }),
    hasCode("CAD_SAVE_DESTINATION_INVALID")
  );

  const same = await createHarness(t, createCadEditHistory(snapshot()), { destinationIsSourceDirectory: true });
  await assert.rejects(
    same.coordinator.saveCopy({ ...same.input, baseFilename: "source" }),
    hasCode("CAD_SAVE_SOURCE_OUTPUT_EQUAL")
  );

  const existing = await createHarness(t, createCadEditHistory(snapshot()));
  await writeFile(existing.finalPath, "owned");
  await assert.rejects(existing.coordinator.saveCopy(existing.input), hasCode("CAD_SAVE_OUTPUT_EXISTS"));
  assert.equal(await readFile(existing.finalPath, "utf8"), "owned");
  assert.equal(existing.requests.length, 0);
});

test("writer, reopen, and invariant failures never publish final and remove or quarantine temporary output", async (t) => {
  const cases = [
    { name: "writer", options: { writerFailure: true }, code: "CAD_SAVE_WRITE_FAILED" },
    { name: "reopen", options: { reopenFailure: true }, code: "CAD_SAVE_REOPEN_FAILED" },
    { name: "entity invariant", options: { mutateEvidence: deleteUnaffectedEntity }, code: "CAD_SAVE_VERIFICATION_FAILED" },
    { name: "version invariant", options: { evidenceVersion: "AC1027" }, code: "CAD_SAVE_VERIFICATION_FAILED" },
    { name: "units invariant", options: { evidenceUnits: "Feet" }, code: "CAD_SAVE_VERIFICATION_FAILED" },
    { name: "warning invariant", options: { mutateEvidence: addParserWarning }, code: "CAD_SAVE_VERIFICATION_FAILED" },
    { name: "copy map invariant", options: { invalidCopyMap: true }, code: "CAD_SAVE_VERIFICATION_FAILED" }
  ] as const;

  for (const item of cases) {
    await t.test(item.name, async (child) => {
      const history = createCadEditHistory(snapshot());
      apply(history, copyBatch(0, TX1, CMD1));
      const harness = await createHarness(child, history, item.options);
      await assert.rejects(harness.coordinator.saveCopy(harness.input), hasCode(item.code));
      assert.equal(await exists(harness.finalPath), false);
      const remnants = await temporaryOutputs(harness.destination);
      assert.ok(remnants.length === 0 || remnants.every((name) => name.includes(".failed.")));
      assert.equal(await readFile(harness.sourcePath, "utf8"), harness.sourceText);
    });
  }
});

test("verification rejects copied-handle collisions and extra reopened entities", async (t) => {
  await t.test("copy handle collides with an existing identical entity", async (child) => {
    const history = createCadEditHistory(snapshot());
    apply(history, copyBatch(0, TX1, CMD1, [0, 0, 0]));
    const harness = await createHarness(child, history, { copyHandleCollision: true });

    await assert.rejects(
      harness.coordinator.saveCopy(harness.input),
      hasCode("CAD_SAVE_VERIFICATION_FAILED")
    );
    assert.equal(await exists(harness.finalPath), false);
  });

  await t.test("reopened output contains an extra non-null entity", async (child) => {
    const harness = await createHarness(child, createCadEditHistory(snapshot()), {
      mutateEvidence(evidence) {
        evidence.index.entities.push({
          ...structuredClone(evidence.index.entities[0]!),
          id: "h:FE",
          handle: "FE"
        });
        evidence.index.summary.entityCount += 1;
      },
      writerEntityCountDelta: 1
    });

    await assert.rejects(
      harness.coordinator.saveCopy(harness.input),
      hasCode("CAD_SAVE_VERIFICATION_FAILED")
    );
    assert.equal(await exists(harness.finalPath), false);
  });

  await t.test("reopened output contains an arbitrary empty layer", async (child) => {
    const harness = await createHarness(child, createCadEditHistory(snapshot()), {
      mutateEvidence(evidence) {
        evidence.index.layers.push({
          name: "UNEXPECTED",
          entityCount: 0,
          visible: true,
          frozen: false,
          color: 7,
          locked: false
        });
        evidence.index.summary.layerCount += 1;
      }
    });

    await assert.rejects(
      harness.coordinator.saveCopy(harness.input),
      hasCode("CAD_SAVE_VERIFICATION_FAILED")
    );
    assert.equal(await exists(harness.finalPath), false);
  });
});

test("pre-cancel and in-flight cancellation do not publish files and preserve source", async (t) => {
  const before = await createHarness(t, createCadEditHistory(snapshot()));
  const preAborted = new AbortController();
  preAborted.abort();
  await assert.rejects(before.coordinator.saveCopy(before.input, preAborted.signal), isAbort);
  assert.equal(before.requests.length, 0);
  assert.equal(await exists(before.finalPath), false);

  const during = await createHarness(t, createCadEditHistory(snapshot()), { abortInWriter: true });
  const controller = new AbortController();
  const pending = during.coordinator.saveCopy(during.input, controller.signal);
  await during.writerStarted;
  controller.abort();
  await assert.rejects(pending, isAbort);
  assert.equal(await exists(during.finalPath), false);
  assert.equal(await readFile(during.sourcePath, "utf8"), during.sourceText);
});

test("capability module strictly exposes report, drawing, and verification without path or lineage input", async () => {
  const calls: unknown[] = [];
  const verification = verificationFixture();
  const coordinator: CadSaveCoordinator = {
    async saveCopy(input) {
      calls.push(input);
      return verification;
    },
    getVerification(id) {
      return id === verification.id ? verification : null;
    }
  };
  const reports: unknown[] = [];
  const module = createSaveCapabilityModule(coordinator, async (
    input: CadReportInput,
    format: ReportFormat
  ) => {
    reports.push([input, format]);
    return {
      format,
      mediaType: "application/json",
      filename: "report.json",
      bytes: new Uint8Array([123, 125]),
      sha256: "B".repeat(64)
    };
  });

  assert.deepEqual(module.names, ["export.report", "export.drawing", "verification.get"]);
  assert.deepEqual(await module.execute("export.drawing", {
    documentId: "drawing:save",
    expectedRevision: 0,
    destinationGrantId: randomUUID(),
    baseFilename: "copy",
    format: "dxf",
    version: "AC1032"
  }), verification);
  assert.deepEqual(Object.keys(calls[0] as object).sort(), [
    "baseFilename", "destinationGrantId", "documentId", "expectedRevision", "format", "version"
  ]);
  await assert.rejects(module.execute("export.drawing", {
    documentId: "drawing:save",
    expectedRevision: 0,
    destinationGrantId: randomUUID(),
    baseFilename: "copy",
    format: "dxf",
    version: "AC1032",
    sourcePath: "C:\\forbidden.dxf",
    lineage: []
  }), hasCode("CAD_SAVE_INPUT_INVALID"));
  assert.equal(calls.length, 1);
  assert.deepEqual(await module.execute("verification.get", { id: verification.id }), verification);
  assert.equal(await module.execute("verification.get", { id: randomUUID() }), null);

  const reportInput = { document: snapshot(), findings: null, changeSet: null, verification: null };
  const report = await module.execute("export.report", { input: reportInput, format: "json" });
  assert.equal((report as { filename: string }).filename, "report.json");
  assert.deepEqual(reports, [[reportInput, "json"]]);
});

interface HarnessOptions {
  sourceOverride?: Partial<{
    sourceSha256: string;
    drawingVersion: string | null;
    units: string | null;
  }>;
  destinationIsSourceDirectory?: boolean;
  writerFailure?: boolean;
  reopenFailure?: boolean;
  abortInWriter?: boolean;
  invalidCopyMap?: boolean;
  copyHandleCollision?: boolean;
  writerEntityCountDelta?: number;
  evidenceVersion?: string | null;
  evidenceUnits?: string | null;
  mutateEvidence?: (evidence: CadParsedDocumentEvidence) => void;
  fileSystem?: CadSaveFileSystem;
  sourceSizeBytes?: number;
  sourceSha256?: string;
  afterWriterOutput?: (path: string) => void | Promise<void>;
}

async function createHarness(
  t: TestContext,
  transactions: CadCommittedTransactionStore,
  options: HarnessOptions = {}
) {
  const root = await temporaryDirectory(t);
  const sourcePath = join(root, "source.dxf");
  const sourceText = "immutable source drawing";
  if (options.sourceSizeBytes === undefined) {
    await writeFile(sourcePath, sourceText);
  } else {
    await writeFile(sourcePath, "");
    await truncate(sourcePath, options.sourceSizeBytes);
  }
  const sourceSha256 = options.sourceSha256
    ?? sha256(new TextEncoder().encode(sourceText));
  const destination = options.destinationIsSourceDirectory ? root : join(root, "destination");
  if (!options.destinationIsSourceDirectory) {
    await import("node:fs/promises").then(({ mkdir }) => mkdir(destination));
  }
  const grants = createDestinationGrantStore();
  const grantId = await grants.issue(destination, Date.now() + 60_000);
  const saveState = transactions.getSaveState("drawing:save", currentRevision(transactions));
  const current = saveState?.current ?? snapshot();
  const copyIds = current.index.entities.filter((entity) => entity.handle === null).map((entity) => entity.id);
  const copyMap = Object.fromEntries(copyIds.map((id, index) => [id, (0xABC + index).toString(16).toUpperCase()]));
  if (options.copyHandleCollision && copyIds.length > 0) copyMap[copyIds[0]!] = "11";
  if (options.invalidCopyMap && copyIds.length > 0) delete copyMap[copyIds[0]!];
  const requests: CadIoWriteRequest[] = [];
  const events: string[] = [];
  let releaseWriter: (() => void) | undefined;
  let markWriterStarted!: () => void;
  const writerStarted = new Promise<void>((resolve) => { markWriterStarted = resolve; });

  const cadIo: CadIoClient = {
    async writeCopy(request, signal): Promise<CadIoWriteResult> {
      requests.push(structuredClone(request));
      events.push("writer:started");
      if (options.writerFailure) {
        markWriterStarted();
        await writeFile(request.temporaryOutputPath, "partial");
        throw new Error("private writer detail");
      }
      if (options.abortInWriter) {
        await writeFile(request.temporaryOutputPath, "partial");
        markWriterStarted();
        await new Promise<void>((resolve, reject) => {
          releaseWriter = resolve;
          signal?.addEventListener("abort", () => reject(abortError()), { once: true });
        });
      } else {
        markWriterStarted();
      }
      await writeFile(request.temporaryOutputPath, OUTPUT_BYTES);
      await options.afterWriterOutput?.(request.temporaryOutputPath);
      events.push("writer:closed");
      return {
        format: request.format,
        version: request.version,
        entityCount: current.index.entities.length + (options.writerEntityCountDelta ?? 0),
        copiedHandleMap: copyMap,
        warnings: ["writer-normalized-header"]
      };
    }
  };

  const coordinator = createSaveCoordinator({
    cadIo,
    sources: {
      async resolve(documentId) {
        assert.equal(documentId, "drawing:save");
        return {
          documentId,
          canonicalPath: await realpath(sourcePath),
          sourceSha256,
          drawingVersion: "AC1032",
          units: "Millimeters",
          ...options.sourceOverride
        };
      }
    },
    async readDocument(path) {
      events.push("parser:opened");
      if (options.reopenFailure) throw new Error("private parser detail");
      const bytes = await readFile(path);
      const evidence: CadParsedDocumentEvidence = {
        index: materializeIndex(current, copyMap),
        sourceSha256: sha256(bytes),
        drawingVersion: options.evidenceVersion === undefined ? "AC1032" : options.evidenceVersion,
        units: options.evidenceUnits === undefined ? "Millimeters" : options.evidenceUnits
      };
      options.mutateEvidence?.(evidence);
      events.push("parser:closed");
      return evidence;
    },
    transactions,
    grants,
    fileSystem: options.fileSystem
  });
  const finalPath = join(destination, "verified-copy.dxf");
  const input = {
    documentId: "drawing:save",
    expectedRevision: current.revision,
    destinationGrantId: grantId,
    baseFilename: "verified-copy",
    format: "dxf" as const,
    version: "AC1032"
  };

  const originalLstat = lstat;
  async function observeFinal(): Promise<void> {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (await exists(finalPath)) {
        events.push("final:visible");
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1));
    }
  }
  void observeFinal();

  return {
    coordinator,
    input,
    requests,
    events,
    sourcePath: await realpath(sourcePath),
    sourceText,
    sourceSha256,
    destination: await realpath(destination),
    finalPath,
    writerStarted,
    releaseWriter,
    originalLstat
  };
}

function snapshot(
  sourceSha256 = sha256(new TextEncoder().encode("immutable source drawing"))
): CadDocumentSnapshot {
  return {
    documentId: "drawing:save",
    revision: 0,
    sourceSha256,
    drawingVersion: "AC1032",
    units: "Millimeters",
    index: {
      schemaVersion: "cad-index/v0.2",
      drawingId: "drawing:save",
      source: { kind: "dxf", displayName: "source.dxf", parser: "fixture" },
      drawing: { fileVersion: "AC1032", units: "Millimeters" },
      summary: {
        entityCount: 2, layerCount: 1, unsupportedCount: 0, modelSpaceCount: 2, paperSpaceCount: 0
      },
      layers: [{ name: "0", entityCount: 2, visible: true, frozen: false, color: 7, locked: false }],
      unsupported: [],
      entities: [{
        id: "h:10", handle: "10", type: "TEXT", layer: "0", space: "model", layout: "Model",
        bbox: { min: [0, 0, 0], max: [0, 0, 0] }, text: "original", blockName: null,
        attributes: {}, warnings: [],
        geometry: {
          kind: "text", insertionPoint: [0, 0, 0], alignmentPoint: null,
          height: 1, rotation: 0, width: null
        }
      }, {
        id: "h:11", handle: "11", type: "LINE", layer: "0", space: "model", layout: "Model",
        bbox: { min: [1, 0, 0], max: [2, 0, 0] }, text: null, blockName: null,
        attributes: {}, warnings: [],
        geometry: { kind: "line", start: [1, 0, 0], end: [2, 0, 0] }
      }]
    },
    layers: [{
      id: "layer:imported:MA", name: "0", color: 7, visible: true, frozen: false, locked: false
    }]
  };
}

function textBatch(
  expectedRevision: number,
  text: string,
  transactionId: string,
  commandId: string
): CadEditBatch {
  return batch(expectedRevision, transactionId, commandId, {
    kind: "text.replace",
    handle: "10",
    text
  });
}

function copyBatch(
  expectedRevision: number,
  transactionId: string,
  commandId: string,
  delta: [number, number, number] = [10, 0, 0]
): CadEditBatch {
  return batch(expectedRevision, transactionId, commandId, {
    kind: "entity.copy",
    handles: ["11"],
    delta
  });
}

function layerCreateBatch(
  expectedRevision: number,
  transactionId: string,
  commandId: string
): CadEditBatch {
  const layerId = "layer:created:verified";
  return {
    schemaVersion: "cad-edit/v1",
    transactionId,
    documentId: "drawing:save",
    expectedRevision,
    commands: [{
      commandId,
      expectedRevision,
      origin: { kind: "user", id: "test" },
      preconditions: [{ target: layerId, field: "exists", equals: false }],
      operation: {
        kind: "layer.create",
        layerId,
        name: "VERIFIED",
        color: 4
      }
    }]
  };
}

function batch(
  expectedRevision: number,
  transactionId: string,
  commandId: string,
  operation: CadEditCommand
): CadEditBatch {
  const target = "handle" in operation ? operation.handle
    : "handles" in operation ? operation.handles[0]!
    : operation.layerId;
  return {
    schemaVersion: "cad-edit/v1",
    transactionId,
    documentId: "drawing:save",
    expectedRevision,
    commands: [{
      commandId,
      expectedRevision,
      origin: { kind: "user", id: "test" },
      preconditions: [{ target, field: "exists", equals: true }],
      operation
    }]
  };
}

function apply(history: ReturnType<typeof createCadEditHistory>, batchValue: CadEditBatch): void {
  history.apply(history.preview(batchValue));
}

function materializeIndex(
  current: CadDocumentSnapshot,
  copiedHandleMap: Record<string, string>
): CadEntityIndex {
  const index = structuredClone(current.index);
  index.drawingId = "reopened-output";
  index.source.displayName = "verified-copy.dxf";
  for (const entity of index.entities) {
    if (entity.handle === null && copiedHandleMap[entity.id]) {
      entity.handle = copiedHandleMap[entity.id]!;
      entity.id = `h:${entity.handle}`;
    }
  }
  return index;
}

function deleteUnaffectedEntity(evidence: CadParsedDocumentEvidence): void {
  evidence.index.entities = evidence.index.entities.filter((entity) => entity.handle !== "10");
  evidence.index.summary.entityCount = evidence.index.entities.length;
}

function addParserWarning(evidence: CadParsedDocumentEvidence): void {
  evidence.index.entities[0]!.warnings.push("new-parser-warning");
}

function stateStore(state: CadSaveState): CadCommittedTransactionStore {
  return {
    getCommittedTransaction: () => null,
    getSaveState: (documentId, expectedRevision) =>
      documentId === state.documentId && expectedRevision === state.revision
        ? structuredClone(state)
        : null
  };
}

function currentRevision(store: CadCommittedTransactionStore): number {
  for (let revision = 20; revision >= 0; revision -= 1) {
    const state = store.getSaveState("drawing:save", revision);
    if (state) return revision;
  }
  return 0;
}

function temporaryId(transactionId: string, commandId: string): string {
  return `copy:${transactionId}:${commandId}:0`;
}

function verificationIdFromTemporaryPath(path: string): string {
  const match = basename(path).match(
    /[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/iu
  );
  assert.ok(match);
  return match[0]!;
}

function verificationFixture() {
  return {
    id: randomUUID(),
    status: "passed" as const,
    format: "dxf" as const,
    version: "AC1032",
    sourceSha256: "A".repeat(64),
    outputSha256: "B".repeat(64),
    intendedChangeCount: 0,
    verifiedChangeCount: 0,
    copiedHandleMap: {},
    warnings: []
  };
}

async function temporaryDirectory(t: TestContext): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "cad-save-test-"));
  t.after(() => rm(directory, { force: true, recursive: true }));
  return directory;
}

async function temporaryOutputs(directory: string): Promise<string[]> {
  const { readdir } = await import("node:fs/promises");
  return (await readdir(directory)).filter((name) =>
    name.includes(".click-around.tmp.") || name.includes(".failed.")
  );
}

async function exists(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ENOENT"
      ? Promise.reject(error)
      : false;
  }
}

function sha256(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex").toUpperCase();
}

function hasCode(code: string) {
  return (error: unknown) => error instanceof CadSaveError && error.code === code;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}
