import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  fstatSync,
  fsyncSync,
  ftruncateSync,
  linkSync,
  lstatSync,
  openSync,
  read,
  rmSync
} from "node:fs";
import {
  lstat,
  open,
  realpath,
  rename,
  rm,
  stat
} from "node:fs/promises";
import { basename, dirname, extname, join, normalize, resolve } from "node:path";

import {
  mapCadSaveLineage,
  type CadIoWriteTransaction
} from "@dwg/cad-io-acadsharp";
import type {
  CadCommittedTransaction,
  CadSaveState
} from "@dwg/cad-edit";
import type { CadOutputVerification } from "@dwg/contracts";

import {
  CadSaveError,
  type CadSaveCoordinator,
  type CadSaveDependencies,
  type CadSaveFileIdentity,
  type CadSaveFileSystem,
  type CadSaveInput,
  type CadSavePublicationInput
} from "./contracts.js";
import { verifySavedOutput } from "./outputVerification.js";

const MAX_LINEAGE_COMMANDS = 10_000;
const MAX_LINEAGE_TRANSACTIONS = 10_000;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const VERSION_PATTERN = /^AC[0-9]{4}$/u;

export function createSaveCoordinator(
  dependencies: CadSaveDependencies
): CadSaveCoordinator {
  const verifications = new Map<string, CadOutputVerification>();
  const fileSystem = dependencies.fileSystem ?? createNodeCadSaveFileSystem();

  return {
    async saveCopy(input, signal) {
      const request = parseInput(input);
      throwIfAborted(signal);
      const saveState = dependencies.transactions.getSaveState(
        request.documentId,
        request.expectedRevision
      );
      if (!saveState) throw new CadSaveError("CAD_SAVE_STALE");
      validateSaveState(saveState, request);
      throwIfAborted(signal);

      const source = await dependencies.sources.resolve(
        saveState.documentId,
        signal
      );
      throwIfAborted(signal);
      if (
        source.documentId !== saveState.documentId
        || upperHash(source.sourceSha256) !== upperHash(saveState.source.sourceSha256)
        || source.drawingVersion !== saveState.source.drawingVersion
        || source.units !== saveState.source.units
      ) {
        throw new CadSaveError("CAD_SAVE_SOURCE_MISMATCH");
      }

      let canonicalSource: string;
      let sourceIdentity: CadSaveFileIdentity;
      try {
        canonicalSource = await fileSystem.canonicalize(source.canonicalPath);
        sourceIdentity = await fileSystem.statIdentity(canonicalSource);
        if (sourceIdentity.kind !== "file") throw new Error("not file");
      } catch {
        throw new CadSaveError("CAD_SAVE_SOURCE_MISMATCH");
      }
      if (pathKey(canonicalSource) !== pathKey(source.canonicalPath)) {
        throw new CadSaveError("CAD_SAVE_SOURCE_MISMATCH");
      }
      throwIfAborted(signal);
      const sourceHashBefore = await fileSystem.sha256(canonicalSource, signal);
      throwIfAborted(signal);
      if (sourceHashBefore !== upperHash(source.sourceSha256)) {
        throw new CadSaveError("CAD_SAVE_SOURCE_MISMATCH");
      }

      const grant = await dependencies.grants.consume(
        request.destinationGrantId
      );
      throwIfAborted(signal);
      let canonicalDirectory: string;
      let directoryIdentity: CadSaveFileIdentity;
      try {
        canonicalDirectory = await fileSystem.canonicalize(
          grant.canonicalDirectory
        );
        directoryIdentity = await fileSystem.statIdentity(canonicalDirectory);
        if (directoryIdentity.kind !== "directory") throw new Error("not directory");
      } catch {
        throw new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
      }
      if (pathKey(canonicalDirectory) !== pathKey(grant.canonicalDirectory)) {
        throw new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
      }

      const stem = safeStem(request.baseFilename, request.format);
      const finalPath = containedSibling(
        canonicalDirectory,
        `${stem}.${request.format}`
      );
      if (pathKey(finalPath) === pathKey(canonicalSource)) {
        throw new CadSaveError("CAD_SAVE_SOURCE_OUTPUT_EQUAL");
      }
      if (await fileSystem.exists(finalPath)) {
        throw new CadSaveError("CAD_SAVE_OUTPUT_EXISTS");
      }

      const saveRequestId = randomUUID();
      const temporaryPath = containedSibling(
        canonicalDirectory,
        `.${stem}.${saveRequestId}.click-around.tmp.${request.format}`
      );
      if (await fileSystem.exists(temporaryPath)) {
        throw new CadSaveError("CAD_SAVE_OUTPUT_EXISTS");
      }
      throwIfAborted(signal);
      try {
        fileSystem.preflightNoReplace(canonicalDirectory);
      } catch (error) {
        if (error instanceof CadSaveError) throw error;
        throw new CadSaveError("CAD_SAVE_DESTINATION_UNSUPPORTED");
      }
      throwIfAborted(signal);

      let published = false;
      let temporaryHandle: Awaited<
        ReturnType<CadSaveFileSystem["openRead"]>
      > | null = null;
      let temporaryHandleClosed = false;
      try {
        const lineage = writerLineage(saveState);
        let writer;
        try {
          writer = await dependencies.cadIo.writeCopy({
            sourcePath: canonicalSource,
            temporaryOutputPath: temporaryPath,
            format: request.format,
            version: request.version,
            lineage
          }, signal);
        } catch (error) {
          if (isAbort(error) || signal?.aborted) throw abortError();
          throw new CadSaveError("CAD_SAVE_WRITE_FAILED");
        }
        throwIfAborted(signal);
        const temporaryPathIdentity = await assertTemporaryRegularFile(
          fileSystem,
          temporaryPath,
          canonicalDirectory
        );
        throwIfAborted(signal);
        temporaryHandle = await fileSystem.openRead(temporaryPath);
        const temporaryIdentity = temporaryHandle.identity();
        if (
          temporaryPathIdentity.nlink !== "1"
          || temporaryIdentity.nlink !== "1"
          || !sameFileIdentity(temporaryIdentity, temporaryPathIdentity)
        ) {
          throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
        }
        const outputSha256 = await temporaryHandle.sha256(signal);
        throwIfAborted(signal);

        let reopened;
        try {
          reopened = await dependencies.readDocument(temporaryPath, signal);
        } catch (error) {
          if (isAbort(error) || signal?.aborted) throw abortError();
          throw new CadSaveError("CAD_SAVE_REOPEN_FAILED");
        }
        throwIfAborted(signal);
        const verification = verifySavedOutput({
          verificationId: saveRequestId,
          format: request.format,
          requestedVersion: request.version,
          outputSha256,
          saveState,
          writer,
          reopened,
          expectedTemporaryIds: temporaryIds(lineage)
        });

        await revalidateBeforePublication({
          fileSystem,
          canonicalSource,
          sourceIdentity,
          sourceHashBefore,
          canonicalDirectory,
          directoryIdentity,
          grantDirectory: grant.canonicalDirectory,
          temporaryPath,
          temporaryHandle,
          temporaryIdentity,
          signal
        });
        throwIfAborted(signal);
        let finalIdentity: CadSaveFileIdentity;
        try {
          finalIdentity = fileSystem.publishVerifiedNoReplace({
            temporaryPath,
            finalPath,
            expectedTemporaryIdentity: temporaryIdentity
          });
        } catch (error) {
          if (error instanceof CadSaveError) throw error;
          throw new CadSaveError("CAD_SAVE_FINALIZE_FAILED");
        }
        published = true;
        throwIfAborted(signal);
        const linkedFileIdentity = temporaryHandle.identity();
        if (
          linkedFileIdentity.nlink !== "2"
          || !sameFileIdentity(linkedFileIdentity, finalIdentity)
        ) {
          throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
        }

        const temporaryCleanup = await cleanupPath(fileSystem, temporaryPath);
        if (temporaryCleanup.disposition === "quarantined") {
          throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
        }
        throwIfAborted(signal);
        const committedFileIdentity = temporaryHandle.identity();
        if (
          committedFileIdentity.nlink !== "1"
          || !sameFileObjectSizeAndMtime(
            committedFileIdentity,
            finalIdentity
          )
        ) {
          throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
        }
        const storedVerification = structuredClone(verification);
        const returnedVerification = structuredClone(verification);
        fileSystem.validateCommit({
          sourcePath: canonicalSource,
          expectedSourceIdentity: sourceIdentity,
          directoryPath: canonicalDirectory,
          expectedDirectoryIdentity: directoryIdentity,
          finalPath,
          expectedFinalIdentity: committedFileIdentity
        });
        throwIfAborted(signal);
        const finalCommitIdentity = temporaryHandle.identity();
        if (
          finalCommitIdentity.nlink !== "1"
          || !sameFileIdentity(
            finalCommitIdentity,
            committedFileIdentity
          )
        ) {
          throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
        }
        verifications.set(verification.id, storedVerification);
        try {
          temporaryHandle.close();
          temporaryHandleClosed = true;
        } catch {
          verifications.delete(verification.id);
          throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
        }
        return returnedVerification;
      } catch (error) {
        verifications.delete(saveRequestId);
        let cleanupFailed = false;
        let sanitizedIdentity: CadSaveFileIdentity | null = null;
        if (temporaryHandle && !temporaryHandleClosed) {
          try {
            sanitizedIdentity = temporaryHandle.sanitize();
          } catch {
            cleanupFailed = true;
          }
        }
        let provenQuarantinedAliases = 0n;
        if (published) {
          try {
            const result = await cleanupPath(fileSystem, finalPath);
            provenQuarantinedAliases += await provenQuarantineCount(
              fileSystem,
              result,
              sanitizedIdentity
            );
          } catch {
            cleanupFailed = true;
          }
        }
        try {
          const result = await cleanupPath(fileSystem, temporaryPath);
          provenQuarantinedAliases += await provenQuarantineCount(
            fileSystem,
            result,
            sanitizedIdentity
          );
        } catch {
          cleanupFailed = true;
        }
        if (temporaryHandle && !temporaryHandleClosed) {
          try {
            if (
              BigInt(temporaryHandle.identity().nlink)
              !== provenQuarantinedAliases
            ) {
              cleanupFailed = true;
            }
          } catch {
            cleanupFailed = true;
          }
        }
        if (temporaryHandle && !temporaryHandleClosed) {
          try {
            temporaryHandle.close();
            temporaryHandleClosed = true;
          } catch {
            cleanupFailed = true;
          }
        }
        if (cleanupFailed) {
          throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
        }
        throw error;
      }
    },

    getVerification(id) {
      const verification = verifications.get(id);
      return verification ? structuredClone(verification) : null;
    }
  };
}

export type { CadSaveFileSystem } from "./contracts.js";

export function createNodeCadSaveFileSystem(): CadSaveFileSystem {
  return {
    canonicalize: realpath,
    async statIdentity(path) {
      return fileIdentity(await stat(path, { bigint: true }));
    },
    async lstatIdentity(path) {
      return fileIdentity(await lstat(path, { bigint: true }));
    },
    async openRead(path) {
      const descriptor = openSync(path, "r+");
      let closed = false;
      const assertOpen = (): void => {
        if (closed) throw new Error("file handle closed");
      };
      return {
        identity() {
          assertOpen();
          return fileIdentity(fstatSync(descriptor, { bigint: true }));
        },
        async sha256(signal) {
          assertOpen();
          return hashDescriptorAsync(descriptor, signal);
        },
        sanitize() {
          assertOpen();
          ftruncateSync(descriptor, 0);
          fsyncSync(descriptor);
          return fileIdentity(fstatSync(descriptor, { bigint: true }));
        },
        close() {
          assertOpen();
          closeSync(descriptor);
          closed = true;
        }
      };
    },
    async sha256(path, signal) {
      return hashPathAsync(path, signal);
    },
    async exists(path) {
      try {
        await lstat(path);
        return true;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
        throw error;
      }
    },
    preflightNoReplace,
    publishVerifiedNoReplace,
    validateCommit,
    async remove(path) {
      await rm(path);
    },
    move: rename
  };
}

function preflightNoReplace(directory: string): void {
  const probeId = randomUUID();
  const sourcePath = join(
    directory,
    `.click-around.preflight.${probeId}.source`
  );
  const targetPath = join(
    directory,
    `.click-around.preflight.${probeId}.target`
  );
  let descriptor = -1;
  let sourceCreated = false;
  let targetCreated = false;
  let failure: CadSaveError | null = null;
  let cleanupFailed = false;
  try {
    descriptor = openSync(sourcePath, "wx");
    sourceCreated = true;
    closeSync(descriptor);
    descriptor = -1;
    try {
      linkSync(sourcePath, targetPath);
      targetCreated = true;
    } catch {
      failure = new CadSaveError("CAD_SAVE_DESTINATION_UNSUPPORTED");
    }
  } catch {
    failure = new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
  } finally {
    if (descriptor !== -1) {
      try {
        closeSync(descriptor);
      } catch {
        cleanupFailed = true;
      }
    }
    if (targetCreated && !removeSyncIfPresent(targetPath)) {
      cleanupFailed = true;
    }
    if (sourceCreated && !removeSyncIfPresent(sourcePath)) {
      cleanupFailed = true;
    }
  }
  if (cleanupFailed) throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
  if (failure) throw failure;
}

function publishVerifiedNoReplace(
  input: CadSavePublicationInput
): CadSaveFileIdentity {
  let temporaryDescriptor = -1;
  let finalDescriptor = -1;
  let linked = false;
  let stage: "verify" | "link" | "post-link" = "verify";
  let result: CadSaveFileIdentity | null = null;
  let failure: CadSaveError | null = null;
  let cleanupFailed = false;

  try {
    temporaryDescriptor = openSync(input.temporaryPath, "r+");
    assertExpectedIdentityAtPath(
      temporaryDescriptor,
      input.temporaryPath,
      input.expectedTemporaryIdentity
    );
    stage = "link";
    linkSync(input.temporaryPath, input.finalPath);
    linked = true;
    stage = "post-link";
    finalDescriptor = openSync(input.finalPath, "r");
    const temporaryIdentity = fileIdentity(
      fstatSync(temporaryDescriptor, { bigint: true })
    );
    const temporaryPathIdentity = fileIdentity(
      lstatSync(input.temporaryPath, { bigint: true })
    );
    const finalIdentity = fileIdentity(
      fstatSync(finalDescriptor, { bigint: true })
    );
    const finalPathIdentity = fileIdentity(
      lstatSync(input.finalPath, { bigint: true })
    );
    if (
      input.expectedTemporaryIdentity.nlink !== "1"
      || temporaryIdentity.nlink !== "2"
      || temporaryPathIdentity.nlink !== "2"
      || finalIdentity.nlink !== "2"
      || finalPathIdentity.nlink !== "2"
      || !sameFileObjectSizeAndMtime(
        temporaryIdentity,
        input.expectedTemporaryIdentity
      )
      || !sameFileIdentity(temporaryIdentity, temporaryPathIdentity)
      || !sameFileIdentity(temporaryIdentity, finalIdentity)
      || !sameFileIdentity(temporaryIdentity, finalPathIdentity)
    ) {
      throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
    }
    result = finalIdentity;
  } catch (error) {
    failure = normalizePublicationFailure(stage, error);
  }

  if (failure && linked && temporaryDescriptor !== -1) {
    if (!sanitizeDescriptor(temporaryDescriptor)) cleanupFailed = true;
  }
  for (const descriptor of [finalDescriptor, temporaryDescriptor]) {
    if (descriptor === -1) continue;
    if (
      cleanupFailed
      && linked
      && descriptor === temporaryDescriptor
      && !sanitizeDescriptor(descriptor)
    ) {
      cleanupFailed = true;
    }
    try {
      closeSync(descriptor);
    } catch {
      cleanupFailed = true;
      if (linked && !sanitizeDescriptor(descriptor)) cleanupFailed = true;
    }
  }
  if ((failure || cleanupFailed) && linked) {
    if (!removeSyncIfPresent(input.finalPath)) cleanupFailed = true;
  }
  if (cleanupFailed) throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
  if (failure) throw failure;
  if (!result) throw new CadSaveError("CAD_SAVE_FINALIZE_FAILED");
  return result;
}

function validateCommit(input: Parameters<
  CadSaveFileSystem["validateCommit"]
>[0]): void {
  try {
    const directoryIdentity = fileIdentity(
      lstatSync(input.directoryPath, { bigint: true })
    );
    if (
      directoryIdentity.kind !== "directory"
      || directoryIdentity.symbolicLink
      || !sameObjectIdentity(
        directoryIdentity,
        input.expectedDirectoryIdentity
      )
    ) {
      throw new Error("destination changed");
    }
  } catch (error) {
    if (error instanceof CadSaveError) throw error;
    throw new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
  }

  try {
    assertExpectedPath(
      input.sourcePath,
      input.expectedSourceIdentity
    );
  } catch (error) {
    if (
      error instanceof CadSaveError
      && error.code === "CAD_SAVE_CLEANUP_FAILED"
    ) {
      throw error;
    }
    throw new CadSaveError("CAD_SAVE_SOURCE_MUTATED");
  }

  try {
    assertExpectedPath(
      input.finalPath,
      input.expectedFinalIdentity
    );
  } catch (error) {
    if (
      error instanceof CadSaveError
      && error.code === "CAD_SAVE_CLEANUP_FAILED"
    ) {
      throw error;
    }
    throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
  }
}

function parseInput(input: CadSaveInput): CadSaveInput {
  if (
    !isPlainObject(input)
    || !hasExactKeys(input, [
      "documentId",
      "expectedRevision",
      "destinationGrantId",
      "baseFilename",
      "format",
      "version"
    ])
    || typeof input.documentId !== "string"
    || input.documentId.length < 1
    || input.documentId.length > 512
    || !Number.isSafeInteger(input.expectedRevision)
    || input.expectedRevision < 0
    || typeof input.destinationGrantId !== "string"
    || !UUID_PATTERN.test(input.destinationGrantId)
    || typeof input.baseFilename !== "string"
    || input.baseFilename.length < 1
    || input.baseFilename.length > 255
    || (input.format !== "dxf" && input.format !== "dwg")
    || typeof input.version !== "string"
    || !VERSION_PATTERN.test(input.version)
  ) {
    throw new CadSaveError("CAD_SAVE_INPUT_INVALID");
  }
  return { ...input };
}

function validateSaveState(
  state: CadSaveState,
  request: CadSaveInput
): void {
  if (
    state.documentId !== request.documentId
    || state.revision !== request.expectedRevision
    || state.source.documentId !== request.documentId
    || state.current.documentId !== request.documentId
    || state.source.revision !== 0
    || state.current.revision !== state.revision
    || !Array.isArray(state.lineage)
  ) {
    throw new CadSaveError("CAD_SAVE_LINEAGE_INVALID");
  }
  if (state.lineage.length > MAX_LINEAGE_TRANSACTIONS) {
    throw new CadSaveError("CAD_SAVE_LINEAGE_LIMIT");
  }
  let commands = 0;
  let predecessor = state.source;
  const transactionIds = new Set<string>();
  for (const transaction of state.lineage) {
    if (
      transaction.status !== "applied"
      || transaction.batch.documentId !== state.documentId
      || transactionIds.has(transaction.batch.transactionId)
      || !Array.isArray(transaction.batch.commands)
      || transaction.batch.commands.length === 0
      || !sameContent(predecessor, transaction.before)
    ) {
      throw new CadSaveError("CAD_SAVE_LINEAGE_INVALID");
    }
    transactionIds.add(transaction.batch.transactionId);
    commands += transaction.batch.commands.length;
    if (commands > MAX_LINEAGE_COMMANDS) {
      throw new CadSaveError("CAD_SAVE_LINEAGE_LIMIT");
    }
    predecessor = transaction.after;
  }
  if (!sameContent(predecessor, state.current)) {
    throw new CadSaveError("CAD_SAVE_LINEAGE_INVALID");
  }
}

function writerLineage(state: CadSaveState): CadIoWriteTransaction[] {
  const normalized: CadCommittedTransaction[] = state.lineage.map(
    (transaction, index) => ({
      ...structuredClone(transaction),
      before: { ...structuredClone(transaction.before), revision: index },
      after: { ...structuredClone(transaction.after), revision: index + 1 }
    })
  );
  try {
    return mapCadSaveLineage(normalized);
  } catch {
    throw new CadSaveError("CAD_SAVE_LINEAGE_INVALID");
  }
}

function sameContent(
  left: CadSaveState["source"],
  right: CadSaveState["source"]
): boolean {
  const normalizedLeft = structuredClone(left);
  const normalizedRight = structuredClone(right);
  normalizedLeft.revision = 0;
  normalizedRight.revision = 0;
  return JSON.stringify(normalizedLeft) === JSON.stringify(normalizedRight);
}

function safeStem(value: string, format: "dxf" | "dwg"): string {
  const normalizedValue = value.normalize("NFKC");
  if (
    normalizedValue !== basename(normalizedValue)
    || /[\\/:\u0000-\u001f]/u.test(normalizedValue)
    || normalizedValue === "."
    || normalizedValue === ".."
  ) {
    throw new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
  }
  const withoutExtension = extname(normalizedValue).toLowerCase() === `.${format}`
    ? normalizedValue.slice(0, -1 * (format.length + 1))
    : normalizedValue;
  const stem = withoutExtension
    .replace(/[<>:"/\\|?*\u0000-\u001f]+/gu, "-")
    .replace(/[^\p{L}\p{N}._ -]+/gu, "-")
    .replace(/[ .]+$/u, "")
    .replace(/^[-. ]+|[-. ]+$/gu, "")
    .slice(0, 120);
  if (
    stem.length === 0
    || /^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/iu.test(stem)
  ) {
    throw new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
  }
  return stem;
}

function containedSibling(directory: string, filename: string): string {
  const path = resolve(directory, filename);
  if (
    pathKey(dirname(path)) !== pathKey(directory)
    || basename(path) !== filename
  ) {
    throw new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
  }
  return path;
}

async function assertTemporaryRegularFile(
  fileSystem: CadSaveFileSystem,
  path: string,
  directory: string
): Promise<CadSaveFileIdentity> {
  try {
    const identity = await fileSystem.lstatIdentity(path);
    if (identity.kind !== "file" || identity.symbolicLink) {
      throw new Error("unsafe output");
    }
    if (
      pathKey(dirname(await fileSystem.canonicalize(path))) !== pathKey(directory)
    ) {
      throw new Error("escaped output");
    }
    return identity;
  } catch {
    throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
  }
}

async function revalidateBeforePublication(input: {
  fileSystem: CadSaveFileSystem;
  canonicalSource: string;
  sourceIdentity: CadSaveFileIdentity;
  sourceHashBefore: string;
  canonicalDirectory: string;
  directoryIdentity: CadSaveFileIdentity;
  grantDirectory: string;
  temporaryPath: string;
  temporaryHandle: Awaited<ReturnType<CadSaveFileSystem["openRead"]>>;
  temporaryIdentity: CadSaveFileIdentity;
  signal?: AbortSignal;
}): Promise<void> {
  throwIfAborted(input.signal);
  let currentDirectory: string;
  let currentDirectoryIdentity: CadSaveFileIdentity;
  try {
    currentDirectory = await input.fileSystem.canonicalize(input.grantDirectory);
    currentDirectoryIdentity = await input.fileSystem.statIdentity(
      currentDirectory
    );
  } catch {
    throw new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
  }
  throwIfAborted(input.signal);
  if (
    pathKey(currentDirectory) !== pathKey(input.canonicalDirectory)
    || !sameObjectIdentity(currentDirectoryIdentity, input.directoryIdentity)
  ) {
    throw new CadSaveError("CAD_SAVE_DESTINATION_INVALID");
  }

  const handleIdentity = input.temporaryHandle.identity();
  throwIfAborted(input.signal);
  let pathIdentity: CadSaveFileIdentity;
  try {
    pathIdentity = await input.fileSystem.lstatIdentity(input.temporaryPath);
  } catch {
    throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
  }
  if (
    !sameFileIdentity(handleIdentity, input.temporaryIdentity)
    || !sameFileIdentity(pathIdentity, input.temporaryIdentity)
    || handleIdentity.nlink !== "1"
    || pathIdentity.nlink !== "1"
    || pathIdentity.kind !== "file"
    || pathIdentity.symbolicLink
  ) {
    throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
  }
  const canonicalTemporary = await input.fileSystem.canonicalize(
    input.temporaryPath
  );
  throwIfAborted(input.signal);
  if (pathKey(dirname(canonicalTemporary)) !== pathKey(input.canonicalDirectory)) {
    throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
  }
  let currentSourceIdentity: CadSaveFileIdentity;
  try {
    currentSourceIdentity = await input.fileSystem.statIdentity(
      input.canonicalSource
    );
  } catch {
    throw new CadSaveError("CAD_SAVE_SOURCE_MUTATED");
  }
  if (
    !sameFileIdentity(currentSourceIdentity, input.sourceIdentity)
    || await input.fileSystem.sha256(
      input.canonicalSource,
      input.signal
    )
      !== input.sourceHashBefore
  ) {
    throw new CadSaveError("CAD_SAVE_SOURCE_MUTATED");
  }
  throwIfAborted(input.signal);
}

async function cleanupPath(
  fileSystem: CadSaveFileSystem,
  path: string
): Promise<{
  disposition: "absent" | "removed" | "quarantined";
  quarantinePath?: string;
}> {
  let exists: boolean;
  try {
    exists = await fileSystem.exists(path);
  } catch {
    throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
  }
  if (!exists) return { disposition: "absent" };
  try {
    await fileSystem.remove(path);
    return { disposition: "removed" };
  } catch {
    const quarantine = join(
      dirname(path),
      `.${basename(path)}.failed.${randomUUID()}`
    );
    try {
      await fileSystem.move(path, quarantine);
      return { disposition: "quarantined", quarantinePath: quarantine };
    } catch {
      throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
    }
  }
}

async function provenQuarantineCount(
  fileSystem: CadSaveFileSystem,
  cleanup: Awaited<ReturnType<typeof cleanupPath>>,
  expectedIdentity: CadSaveFileIdentity | null
): Promise<bigint> {
  if (
    cleanup.disposition !== "quarantined"
    || !cleanup.quarantinePath
    || !expectedIdentity
  ) {
    return 0n;
  }
  try {
    const identity = await fileSystem.lstatIdentity(cleanup.quarantinePath);
    return sameObjectIdentity(identity, expectedIdentity) ? 1n : 0n;
  } catch {
    throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
  }
}

function temporaryIds(lineage: readonly CadIoWriteTransaction[]): string[] {
  return lineage.flatMap((transaction) =>
    transaction.commands.flatMap((command) =>
      command.kind === "entity.copy" ? command.temporaryIds : []
    )
  );
}

function fileIdentity(metadata: {
  dev: bigint;
  ino: bigint;
  size: bigint;
  mtimeNs: bigint;
  ctimeNs: bigint;
  nlink: bigint;
  isFile(): boolean;
  isDirectory(): boolean;
  isSymbolicLink(): boolean;
}): CadSaveFileIdentity {
  return {
    dev: metadata.dev.toString(),
    ino: metadata.ino.toString(),
    size: metadata.size.toString(),
    mtimeNs: metadata.mtimeNs.toString(),
    ctimeNs: metadata.ctimeNs.toString(),
    nlink: metadata.nlink.toString(),
    kind: metadata.isFile()
      ? "file"
      : metadata.isDirectory()
        ? "directory"
        : "other",
    symbolicLink: metadata.isSymbolicLink()
  };
}

function sameObjectIdentity(
  left: CadSaveFileIdentity,
  right: CadSaveFileIdentity
): boolean {
  return (
    left.dev === right.dev
    && left.ino === right.ino
    && left.kind === right.kind
    && left.symbolicLink === right.symbolicLink
  );
}

function sameFileIdentity(
  left: CadSaveFileIdentity,
  right: CadSaveFileIdentity
): boolean {
  return (
    sameFileObjectAndSize(left, right)
    && left.mtimeNs === right.mtimeNs
    && left.ctimeNs === right.ctimeNs
    && left.nlink === right.nlink
  );
}

function sameFileObjectAndSize(
  left: CadSaveFileIdentity,
  right: CadSaveFileIdentity
): boolean {
  return sameObjectIdentity(left, right) && left.size === right.size;
}

function sameFileObjectSizeAndMtime(
  left: CadSaveFileIdentity,
  right: CadSaveFileIdentity
): boolean {
  return (
    sameFileObjectAndSize(left, right)
    && left.mtimeNs === right.mtimeNs
  );
}

function assertExpectedPath(
  path: string,
  expectedIdentity: CadSaveFileIdentity
): void {
  let descriptor = -1;
  let failure: unknown;
  try {
    descriptor = openSync(path, "r");
    assertExpectedIdentityAtPath(
      descriptor,
      path,
      expectedIdentity
    );
  } catch (error) {
    failure = error;
  }
  if (descriptor !== -1) {
    try {
      closeSync(descriptor);
    } catch {
      throw new CadSaveError("CAD_SAVE_CLEANUP_FAILED");
    }
  }
  if (failure) throw failure;
}

function assertExpectedIdentityAtPath(
  descriptor: number,
  path: string,
  expectedIdentity: CadSaveFileIdentity
): void {
  const handleIdentity = fileIdentity(
    fstatSync(descriptor, { bigint: true })
  );
  const pathIdentity = fileIdentity(lstatSync(path, { bigint: true }));
  if (
    handleIdentity.kind !== "file"
    || handleIdentity.symbolicLink
    || pathIdentity.kind !== "file"
    || pathIdentity.symbolicLink
    || !sameFileIdentity(handleIdentity, expectedIdentity)
    || !sameFileIdentity(pathIdentity, expectedIdentity)
  ) {
    throw new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
  }
}

async function hashDescriptorAsync(
  descriptor: number,
  signal?: AbortSignal
): Promise<string> {
  const hash = createHash("sha256");
  const buffer = Buffer.allocUnsafe(64 * 1024);
  let position = 0;
  while (true) {
    throwIfAborted(signal);
    const bytesRead = await readDescriptor(
      descriptor,
      buffer,
      position
    );
    throwIfAborted(signal);
    if (bytesRead === 0) break;
    hash.update(buffer.subarray(0, bytesRead));
    position += bytesRead;
  }
  throwIfAborted(signal);
  return hash.digest("hex").toUpperCase();
}

async function hashPathAsync(
  path: string,
  signal?: AbortSignal
): Promise<string> {
  throwIfAborted(signal);
  const handle = await open(path, "r");
  try {
    throwIfAborted(signal);
    const hash = createHash("sha256");
    const buffer = Buffer.allocUnsafe(64 * 1024);
    let position = 0;
    while (true) {
      throwIfAborted(signal);
      const { bytesRead } = await handle.read(
        buffer,
        0,
        buffer.byteLength,
        position
      );
      throwIfAborted(signal);
      if (bytesRead === 0) break;
      hash.update(buffer.subarray(0, bytesRead));
      position += bytesRead;
    }
    throwIfAborted(signal);
    return hash.digest("hex").toUpperCase();
  } finally {
    await handle.close();
  }
}

async function readDescriptor(
  descriptor: number,
  buffer: Buffer,
  position: number
): Promise<number> {
  return new Promise((resolveRead, rejectRead) => {
    read(
      descriptor,
      buffer,
      0,
      buffer.byteLength,
      position,
      (error, bytesRead) => {
        if (error) rejectRead(error);
        else resolveRead(bytesRead);
      }
    );
  });
}

function normalizePublicationFailure(
  stage: "verify" | "link" | "post-link",
  error: unknown
): CadSaveError {
  if (error instanceof CadSaveError) return error;
  if (stage === "link") {
    return (error as NodeJS.ErrnoException).code === "EEXIST"
      ? new CadSaveError("CAD_SAVE_OUTPUT_EXISTS")
      : new CadSaveError("CAD_SAVE_FINALIZE_FAILED");
  }
  return new CadSaveError("CAD_SAVE_VERIFICATION_FAILED");
}

function sanitizeDescriptor(descriptor: number): boolean {
  try {
    ftruncateSync(descriptor, 0);
    fsyncSync(descriptor);
    return true;
  } catch {
    return false;
  }
}

function removeSyncIfPresent(path: string): boolean {
  try {
    rmSync(path);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "ENOENT";
  }
}

function pathKey(path: string): string {
  return normalize(resolve(path)).replaceAll("\\", "/").toLowerCase();
}

function upperHash(value: string): string {
  return value.toUpperCase();
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasExactKeys(value: object, expected: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return keys.length === sortedExpected.length
    && keys.every((key, index) => key === sortedExpected[index]);
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
