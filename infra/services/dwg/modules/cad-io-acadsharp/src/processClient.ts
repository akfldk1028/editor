import { dirname, isAbsolute, normalize, resolve } from "node:path";

import type { CadCommittedTransaction } from "@dwg/cad-edit";
import type {
  CadCommandProposal,
  CadEditPoint3
} from "@dwg/contracts";

const MAX_JSON_BYTES = 1_048_576;
const MAX_COMMANDS = 10_000;
const MAX_STRING_CHARS = 16_384;
const MAX_WARNINGS = 1_000;
const MAX_WARNING_CHARS = 240;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const HANDLE_PATTERN = /^[1-9A-F][0-9A-F]{0,15}$/u;
const TEMPORARY_ID_PATTERN =
  /^copy:([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}):([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}):(0|[1-9][0-9]*)$/iu;
const VERSION_PATTERN = /^AC[0-9]{4}$/u;
const LAYER_ID_PATTERN = /^layer:(?:imported|created):[A-Za-z0-9_-]+$/u;

export interface CadIoWriteRequest {
  sourcePath: string;
  temporaryOutputPath: string;
  format: "dxf" | "dwg";
  version: string;
  lineage: readonly CadIoWriteTransaction[];
}

export interface CadIoWriteTransaction {
  transactionId: string;
  beforeRevision: number;
  afterRevision: number;
  commands: readonly CadIoWriteCommand[];
}

export type CadIoWriteCommand =
  | { kind: "layer.create"; layerId: string; name: string; color: number }
  | {
      kind: "layer.update";
      layerId: string;
      name?: string;
      color?: number;
      visible?: boolean;
      frozen?: boolean;
      locked?: boolean;
    }
  | { kind: "text.replace"; handle: string; value: string }
  | { kind: "entity.move"; handles: string[]; delta: CadEditPoint3 }
  | {
      kind: "entity.copy";
      sourceHandles: string[];
      temporaryIds: string[];
      delta: CadEditPoint3;
    }
  | { kind: "entity.delete"; handles: string[] };

export interface CadIoWriteResult {
  format: "dxf" | "dwg";
  version: string;
  entityCount: number;
  copiedHandleMap: Record<string, string>;
  warnings: string[];
}

export interface CadIoClient {
  writeCopy(
    request: CadIoWriteRequest,
    signal?: AbortSignal
  ): Promise<CadIoWriteResult>;
}

export interface CadProcessRunner {
  run(
    spec: {
      command: string;
      args: string[];
      cwd: string;
      stdin: string;
      maxOutputBytes: number;
    },
    signal?: AbortSignal
  ): Promise<{
    exitCode: number;
    stdout: string;
    stderr: string;
  }>;
}

export class CadIoError extends Error {
  constructor(
    readonly code: string,
    message = "CAD I/O operation failed."
  ) {
    super(message);
    this.name = "CadIoError";
  }
}

export function createAcadSharpCadIoClient(options: {
  projectPath: string;
  processRunner: CadProcessRunner;
  dwgVersionManifestPath?: string;
}): CadIoClient {
  const projectPath = requireAbsolutePath(options.projectPath);
  const manifestPath = options.dwgVersionManifestPath === undefined
    ? undefined
    : requireAbsolutePath(options.dwgVersionManifestPath);
  if (
    !options.processRunner
    || typeof options.processRunner.run !== "function"
  ) {
    throw new CadIoError("CAD_CLIENT_INVALID");
  }

  return {
    async writeCopy(request, signal) {
      throwIfAborted(signal);
      const wire = validateWriteRequest(request);
      if (wire.format === "dwg" && manifestPath === undefined) {
        throw new CadIoError("DWG_POLICY_NOT_CONFIGURED");
      }
      const stdin = JSON.stringify({
        schemaVersion: "cad-io/v1",
        operation: "write-copy",
        ...wire
      });
      if (utf8Bytes(stdin) > MAX_JSON_BYTES) {
        throw new CadIoError("CAD_REQUEST_LIMIT");
      }
      const args = [
        "run",
        "--project",
        projectPath,
        "--no-build",
        "--no-launch-profile",
        "--"
      ];
      if (wire.format === "dwg" && manifestPath !== undefined) {
        args.push("--dwg-policy-manifest", manifestPath);
      }

      let processResult: Awaited<
        ReturnType<CadProcessRunner["run"]>
      >;
      try {
        processResult = await options.processRunner.run({
          command: "dotnet",
          args,
          cwd: dirname(projectPath),
          stdin,
          maxOutputBytes: MAX_JSON_BYTES
        }, signal);
      } catch (error) {
        if (isAbortError(error) || signal?.aborted) throw abortError();
        throw new CadIoError("CAD_PROCESS_FAILED");
      }
      throwIfAborted(signal);
      if (
        utf8Bytes(processResult.stdout)
        + utf8Bytes(processResult.stderr)
        > MAX_JSON_BYTES
      ) {
        throw new CadIoError("CAD_PROCESS_OUTPUT_LIMIT");
      }

      const response = parseProcessResponse(processResult.stdout);
      if (processResult.exitCode !== 0) {
        if (response.status === "error") {
          throw new CadIoError(response.error.code);
        }
        throw new CadIoError("CAD_PROCESS_FAILED");
      }
      if (response.status !== "ok") {
        throw new CadIoError("CAD_RESPONSE_INVALID");
      }
      validateResponseMatchesRequest(response, wire);
      return {
        format: response.format,
        version: response.version,
        entityCount: response.entityCount,
        copiedHandleMap: { ...response.copiedHandleMap },
        warnings: [...response.warnings]
      };
    }
  };
}

export function mapCadSaveLineage(
  lineage: readonly CadCommittedTransaction[]
): CadIoWriteTransaction[] {
  if (!Array.isArray(lineage)) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  const mapped = lineage.map((transaction) => {
    if (
      transaction.status !== "applied"
      || !isPlainObject(transaction.batch)
      || !Array.isArray(transaction.batch.commands)
    ) {
      throw new CadIoError("CAD_LINEAGE_INVALID");
    }
    return {
      transactionId: transaction.batch.transactionId,
      beforeRevision: transaction.before.revision,
      afterRevision: transaction.after.revision,
      commands: transaction.batch.commands.map(
        (proposal: CadCommandProposal) => {
        const operation = proposal.operation;
        switch (operation.kind) {
          case "layer.create":
            return {
              kind: operation.kind,
              layerId: operation.layerId,
              name: operation.name,
              color: operation.color
            };
          case "layer.update":
            return compactOptional({
              kind: operation.kind,
              layerId: operation.layerId,
              name: operation.name,
              color: operation.color,
              visible: operation.visible,
              locked: operation.locked
            });
          case "text.replace":
            return {
              kind: operation.kind,
              handle: operation.handle,
              value: operation.text
            };
          case "entity.move":
            return {
              kind: operation.kind,
              handles: [...operation.handles],
              delta: [...operation.delta] as CadEditPoint3
            };
          case "entity.copy":
            return {
              kind: operation.kind,
              sourceHandles: [...operation.handles],
              temporaryIds: operation.handles.map(
                (_handle: string, index: number) =>
                  `copy:${transaction.batch.transactionId}:${proposal.commandId}:${index}`
              ),
              delta: [...operation.delta] as CadEditPoint3
            };
          case "entity.delete":
            return {
              kind: operation.kind,
              handles: [...operation.handles]
            };
        }
      })
    };
  });
  return validateLineage(mapped);
}

interface OkResponse extends CadIoWriteResult {
  status: "ok";
}

interface ErrorResponse {
  status: "error";
  error: {
    code: string;
    message: string;
  };
}

function validateWriteRequest(value: unknown): CadIoWriteRequest {
  const object = requireStrictObject(value, [
    "sourcePath",
    "temporaryOutputPath",
    "format",
    "version",
    "lineage"
  ]);
  const sourcePath = requireAbsolutePath(
    requireString(object.sourcePath, 1, 32_767)
  );
  const temporaryOutputPath = requireAbsolutePath(
    requireString(object.temporaryOutputPath, 1, 32_767)
  );
  if (
    normalize(resolve(sourcePath)).toLowerCase()
    === normalize(resolve(temporaryOutputPath)).toLowerCase()
  ) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  if (object.format !== "dxf" && object.format !== "dwg") {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  const version = requireString(object.version, 1, 16);
  if (!VERSION_PATTERN.test(version)) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return {
    sourcePath,
    temporaryOutputPath,
    format: object.format,
    version,
    lineage: validateLineage(object.lineage)
  };
}

function validateLineage(value: unknown): CadIoWriteTransaction[] {
  if (!Array.isArray(value)) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  let expectedRevision = 0;
  let commandCount = 0;
  const transactionIds = new Set<string>();
  const temporaryIds = new Set<string>();
  return value.map((candidate) => {
    const object = requireStrictObject(candidate, [
      "transactionId",
      "beforeRevision",
      "afterRevision",
      "commands"
    ]);
    const transactionId = requireString(
      object.transactionId,
      1,
      64
    );
    if (
      !UUID_PATTERN.test(transactionId)
      || transactionIds.has(transactionId)
    ) {
      throw new CadIoError("CAD_LINEAGE_INVALID");
    }
    transactionIds.add(transactionId);
    const beforeRevision = requireRevision(object.beforeRevision);
    const afterRevision = requireRevision(object.afterRevision);
    if (
      beforeRevision !== expectedRevision
      || afterRevision !== beforeRevision + 1
    ) {
      throw new CadIoError("CAD_LINEAGE_INVALID");
    }
    expectedRevision = afterRevision;
    if (!Array.isArray(object.commands)) {
      throw new CadIoError("CAD_REQUEST_INVALID");
    }
    commandCount += object.commands.length;
    if (commandCount > MAX_COMMANDS) {
      throw new CadIoError("CAD_REQUEST_LIMIT");
    }
    return {
      transactionId,
      beforeRevision,
      afterRevision,
      commands: object.commands.map((command) =>
        validateCommand(command, transactionId, temporaryIds)
      )
    };
  });
}

function validateCommand(
  candidate: unknown,
  transactionId: string,
  allTemporaryIds: Set<string>
): CadIoWriteCommand {
  if (!isPlainObject(candidate) || typeof candidate.kind !== "string") {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  switch (candidate.kind) {
    case "layer.create": {
      const object = requireStrictObject(candidate, [
        "kind",
        "layerId",
        "name",
        "color"
      ]);
      return {
        kind: "layer.create",
        layerId: requireLayerId(object.layerId),
        name: requireString(object.name, 1, 255),
        color: requireColor(object.color)
      };
    }
    case "layer.update": {
      const object = requireStrictObject(candidate, [
        "kind",
        "layerId",
        "name",
        "color",
        "visible",
        "frozen",
        "locked"
      ], ["name", "color", "visible", "frozen", "locked"]);
      const command = compactOptional({
        kind: "layer.update" as const,
        layerId: requireLayerId(object.layerId),
        name: optionalString(object.name, 1, 255),
        color: optionalColor(object.color),
        visible: optionalBoolean(object.visible),
        frozen: optionalBoolean(object.frozen),
        locked: optionalBoolean(object.locked)
      });
      if (Object.keys(command).length === 2) {
        throw new CadIoError("CAD_REQUEST_INVALID");
      }
      return command;
    }
    case "text.replace": {
      const object = requireStrictObject(candidate, [
        "kind",
        "handle",
        "value"
      ]);
      return {
        kind: "text.replace",
        handle: requireHandle(object.handle),
        value: requireString(object.value, 0, MAX_STRING_CHARS)
      };
    }
    case "entity.move": {
      const object = requireStrictObject(candidate, [
        "kind",
        "handles",
        "delta"
      ]);
      return {
        kind: "entity.move",
        handles: requireHandles(object.handles),
        delta: requirePoint(object.delta)
      };
    }
    case "entity.copy": {
      const object = requireStrictObject(candidate, [
        "kind",
        "sourceHandles",
        "temporaryIds",
        "delta"
      ]);
      const sourceHandles = requireHandles(object.sourceHandles);
      const temporaryIds = requireTemporaryIds(
        object.temporaryIds,
        transactionId,
        allTemporaryIds
      );
      if (sourceHandles.length !== temporaryIds.length) {
        throw new CadIoError("CAD_REQUEST_INVALID");
      }
      return {
        kind: "entity.copy",
        sourceHandles,
        temporaryIds,
        delta: requirePoint(object.delta)
      };
    }
    case "entity.delete": {
      const object = requireStrictObject(candidate, [
        "kind",
        "handles"
      ]);
      return {
        kind: "entity.delete",
        handles: requireHandles(object.handles)
      };
    }
    default:
      throw new CadIoError("CAD_REQUEST_INVALID");
  }
}

function parseProcessResponse(stdout: string): OkResponse | ErrorResponse {
  if (utf8Bytes(stdout) > MAX_JSON_BYTES) {
    throw new CadIoError("CAD_PROCESS_OUTPUT_LIMIT");
  }
  let value: unknown;
  try {
    assertNoDuplicateJsonKeys(stdout);
    value = JSON.parse(stdout);
  } catch {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
  if (!isPlainObject(value) || value.status === "error") {
    const object = requireStrictResponseObject(value, ["status", "error"]);
    if (object.status !== "error") {
      throw new CadIoError("CAD_RESPONSE_INVALID");
    }
    const error = requireStrictResponseObject(object.error, [
      "code",
      "message"
    ]);
    const code = requireResponseString(error.code, 1, 64);
    if (!/^[A-Z][A-Z0-9_]{1,63}$/u.test(code)) {
      throw new CadIoError("CAD_RESPONSE_INVALID");
    }
    return {
      status: "error",
      error: {
        code,
        message: requireResponseString(error.message, 1, 240)
      }
    };
  }
  const object = requireStrictResponseObject(value, [
    "status",
    "format",
    "version",
    "entityCount",
    "copiedHandleMap",
    "warnings"
  ]);
  if (
    object.status !== "ok"
    || (object.format !== "dxf" && object.format !== "dwg")
  ) {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
  const version = requireResponseString(object.version, 1, 16);
  if (
    !VERSION_PATTERN.test(version)
    || !Number.isSafeInteger(object.entityCount)
    || (object.entityCount as number) < 0
  ) {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
  if (!isPlainObject(object.copiedHandleMap)) {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
  const copiedHandleMap = object.copiedHandleMap;
  const handles = new Set<string>();
  for (const [temporaryId, handle] of Object.entries(copiedHandleMap)) {
    if (
      !temporaryId.startsWith("copy:")
      || typeof handle !== "string"
      || !HANDLE_PATTERN.test(handle)
      || handles.has(handle)
    ) {
      throw new CadIoError("CAD_RESPONSE_INVALID");
    }
    handles.add(handle);
  }
  if (
    !Array.isArray(object.warnings)
    || object.warnings.length > MAX_WARNINGS
  ) {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
  const warnings = object.warnings.map((warning) =>
    requireResponseString(warning, 1, MAX_WARNING_CHARS)
  );
  return {
    status: "ok",
    format: object.format,
    version,
    entityCount: object.entityCount as number,
    copiedHandleMap: copiedHandleMap as Record<string, string>,
    warnings
  };
}

function validateResponseMatchesRequest(
  response: OkResponse,
  request: CadIoWriteRequest
): void {
  if (
    response.format !== request.format
    || response.version !== request.version
  ) {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
  const expectedIds = request.lineage.flatMap((transaction) =>
    transaction.commands.flatMap((command) =>
      command.kind === "entity.copy" ? command.temporaryIds : []
    )
  );
  const actualIds = Object.keys(response.copiedHandleMap);
  if (
    expectedIds.length !== actualIds.length
    || expectedIds.some((id) => !(id in response.copiedHandleMap))
  ) {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
}

function requireStrictObject(
  value: unknown,
  allowed: readonly string[],
  optional: readonly string[] = []
): Record<string, unknown> {
  if (!isPlainObject(value)) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  const keys = Object.keys(value);
  if (keys.some((key) => !allowed.includes(key))) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  const required = allowed.filter((key) => !optional.includes(key));
  if (required.some((key) => !Object.hasOwn(value, key))) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return value;
}

function requireStrictResponseObject(
  value: unknown,
  allowed: readonly string[]
): Record<string, unknown> {
  try {
    return requireStrictObject(value, allowed);
  } catch {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return false;
  return Object.values(Object.getOwnPropertyDescriptors(value)).every(
    (descriptor) => "value" in descriptor
  );
}

function requireAbsolutePath(value: unknown): string {
  if (typeof value !== "string" || !isAbsolute(value)) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return value;
}

function requireString(
  value: unknown,
  min: number,
  max: number
): string {
  if (
    typeof value !== "string"
    || value.length < min
    || value.length > max
    || /[\u0000]/u.test(value)
  ) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return value;
}

function requireResponseString(
  value: unknown,
  min: number,
  max: number
): string {
  try {
    return requireString(value, min, max);
  } catch {
    throw new CadIoError("CAD_RESPONSE_INVALID");
  }
}

function optionalString(
  value: unknown,
  min: number,
  max: number
): string | undefined {
  return value === undefined ? undefined : requireString(value, min, max);
}

function requireRevision(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new CadIoError("CAD_LINEAGE_INVALID");
  }
  return value as number;
}

function requireColor(value: unknown): number {
  if (
    !Number.isInteger(value)
    || (value as number) < 1
    || (value as number) > 255
  ) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return value as number;
}

function optionalColor(value: unknown): number | undefined {
  return value === undefined ? undefined : requireColor(value);
}

function optionalBoolean(value: unknown): boolean | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "boolean") {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return value;
}

function requireLayerId(value: unknown): string {
  const id = requireString(value, 1, 512);
  if (!LAYER_ID_PATTERN.test(id)) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return id;
}

function requireHandle(value: unknown): string {
  const handle = requireString(value, 1, 32);
  if (!HANDLE_PATTERN.test(handle)) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return handle;
}

function requireHandles(value: unknown): string[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 200) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  const handles = value.map(requireHandle);
  if (new Set(handles).size !== handles.length) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return handles;
}

function requireTemporaryIds(
  value: unknown,
  transactionId: string,
  allIds: Set<string>
): string[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 200) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return value.map((candidate) => {
    const id = requireString(candidate, 1, 256);
    const match = TEMPORARY_ID_PATTERN.exec(id);
    const index = match?.[3];
    if (
      match === null
      || match[1]?.toLowerCase() !== transactionId.toLowerCase()
      || index === undefined
      || index.length > 10
      || (index.length === 10 && index > "2147483647")
      || allIds.has(id)
    ) {
      throw new CadIoError("CAD_REQUEST_INVALID");
    }
    allIds.add(id);
    return id;
  });
}

function requirePoint(value: unknown): CadEditPoint3 {
  if (
    !Array.isArray(value)
    || value.length !== 3
    || value.some((coordinate) =>
      typeof coordinate !== "number" || !Number.isFinite(coordinate)
    )
  ) {
    throw new CadIoError("CAD_REQUEST_INVALID");
  }
  return [value[0] as number, value[1] as number, value[2] as number];
}

function compactOptional<T extends Record<string, unknown>>(
  value: T
): T {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== undefined)
  ) as T;
}

function utf8Bytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortError();
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function assertNoDuplicateJsonKeys(json: string): void {
  let index = 0;
  parseValue();
  skipWhitespace();
  if (index !== json.length) throw new Error("Trailing JSON data.");

  function parseValue(): void {
    skipWhitespace();
    const token = json[index];
    if (token === "{") return parseObject();
    if (token === "[") return parseArray();
    if (token === "\"") {
      parseString();
      return;
    }
    if (token === "t" && json.slice(index, index + 4) === "true") {
      index += 4;
      return;
    }
    if (token === "f" && json.slice(index, index + 5) === "false") {
      index += 5;
      return;
    }
    if (token === "n" && json.slice(index, index + 4) === "null") {
      index += 4;
      return;
    }
    const match = json.slice(index).match(
      /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/u
    );
    if (!match) throw new Error("Invalid JSON value.");
    index += match[0].length;
  }

  function parseObject(): void {
    index += 1;
    skipWhitespace();
    const keys = new Set<string>();
    if (json[index] === "}") {
      index += 1;
      return;
    }
    while (true) {
      skipWhitespace();
      const key = parseString();
      if (keys.has(key)) throw new Error("Duplicate JSON key.");
      keys.add(key);
      skipWhitespace();
      if (json[index] !== ":") throw new Error("Missing JSON colon.");
      index += 1;
      parseValue();
      skipWhitespace();
      if (json[index] === "}") {
        index += 1;
        return;
      }
      if (json[index] !== ",") throw new Error("Invalid JSON object.");
      index += 1;
    }
  }

  function parseArray(): void {
    index += 1;
    skipWhitespace();
    if (json[index] === "]") {
      index += 1;
      return;
    }
    while (true) {
      parseValue();
      skipWhitespace();
      if (json[index] === "]") {
        index += 1;
        return;
      }
      if (json[index] !== ",") throw new Error("Invalid JSON array.");
      index += 1;
    }
  }

  function parseString(): string {
    if (json[index] !== "\"") throw new Error("Invalid JSON string.");
    const start = index;
    index += 1;
    while (index < json.length) {
      const character = json[index]!;
      if (character === "\"") {
        index += 1;
        return JSON.parse(json.slice(start, index)) as string;
      }
      if (character === "\\") {
        index += 2;
      } else {
        if (character < " ") throw new Error("Invalid JSON string.");
        index += 1;
      }
    }
    throw new Error("Unterminated JSON string.");
  }

  function skipWhitespace(): void {
    while (
      json[index] === " "
      || json[index] === "\n"
      || json[index] === "\r"
      || json[index] === "\t"
    ) {
      index += 1;
    }
  }
}
