export const SKILL_PERMISSIONS = [
  "read",
  "propose-edit",
  "write-copy",
  "export"
] as const;

export type SkillPermission = (typeof SKILL_PERMISSIONS)[number];

export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export interface SkillListItem {
  id: string;
  version: string;
  compatible: boolean;
  permissions: SkillPermission[];
  recentStatus: "idle" | "running" | "passed" | "failed";
}

export interface SkillListResponse {
  skills: SkillListItem[];
}

export interface SkillRunRequest {
  skillId: string;
  version: string;
  documentId: string;
  relatedDocumentIds?: string[];
  input: JsonValue;
}

export interface SkillRunResponse {
  runId: string;
  skillId: string;
  version: string;
  status: "passed" | "failed";
  previewId: string | null;
  changeCount: number;
  warningCodes: string[];
  result: JsonValue | null;
}

export const MAX_SKILL_JSON_BYTES = 64 * 1024;
export const MAX_SKILL_JSON_DEPTH = 32;
export const MAX_SKILL_JSON_COLLECTION_ITEMS = 256;
export const MAX_SKILL_JSON_TOTAL_VALUES = 2_048;
export const MAX_SKILL_JSON_SCALAR_CHARS = 16 * 1024;
export const MAX_SKILL_RELATED_DOCUMENT_IDS = 3;

const skillIdentifier = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const semver = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const documentIdentifier = /^[A-Za-z0-9][A-Za-z0-9:._-]*$/;
const warningCode = /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const forbiddenKeys = new Set(["__proto__", "constructor", "prototype"]);

export function parseSkillListItem(value: unknown): SkillListItem {
  const object = parseObject(value, "SKILL_LIST_ITEM_INVALID");
  requireKeys(object, ["id", "version", "compatible", "permissions", "recentStatus"], "SKILL_LIST_ITEM_INVALID");
  const id = parseSkillId(object.id, "SKILL_LIST_ITEM_INVALID");
  const version = parseVersion(object.version, "SKILL_LIST_ITEM_INVALID");
  if (typeof object.compatible !== "boolean") throw new Error("SKILL_LIST_ITEM_INVALID");
  const permissions = parsePermissions(object.permissions, "SKILL_LIST_ITEM_INVALID");
  if (!isRecentStatus(object.recentStatus)) throw new Error("SKILL_LIST_ITEM_INVALID");
  return { id, version, compatible: object.compatible, permissions, recentStatus: object.recentStatus };
}

export function parseSkillListResponse(value: unknown): SkillListResponse {
  const object = parseObject(value, "SKILL_LIST_RESPONSE_INVALID");
  requireKeys(object, ["skills"], "SKILL_LIST_RESPONSE_INVALID");
  if (!Array.isArray(object.skills) || object.skills.length > MAX_SKILL_JSON_COLLECTION_ITEMS) {
    throw new Error("SKILL_LIST_RESPONSE_INVALID");
  }
  return { skills: object.skills.map((item) => parseSkillListItem(item)) };
}

export function parseSkillRunRequest(value: unknown): SkillRunRequest {
  const object = parseObject(value, "SKILL_RUN_REQUEST_INVALID");
  requireKeysWithOptional(
    object,
    ["skillId", "version", "documentId", "input"],
    ["relatedDocumentIds"],
    "SKILL_RUN_REQUEST_INVALID"
  );
  const skillId = parseSkillId(object.skillId, "SKILL_RUN_REQUEST_INVALID");
  const version = parseVersion(object.version, "SKILL_RUN_REQUEST_INVALID");
  if (!isDocumentId(object.documentId)) {
    throw new Error("SKILL_RUN_REQUEST_INVALID");
  }
  const relatedDocumentIds = parseRelatedDocumentIds(
    object.relatedDocumentIds,
    object.documentId
  );
  try {
    return {
      skillId,
      version,
      documentId: object.documentId,
      ...(relatedDocumentIds === undefined ? {} : { relatedDocumentIds }),
      input: cloneJsonValue(object.input)
    };
  } catch {
    throw new Error("SKILL_RUN_REQUEST_INVALID");
  }
}

export function parseSkillRunResponse(value: unknown): SkillRunResponse {
  const object = parseObject(value, "SKILL_RUN_RESPONSE_INVALID");
  requireKeys(object, ["runId", "skillId", "version", "status", "previewId", "changeCount", "warningCodes", "result"], "SKILL_RUN_RESPONSE_INVALID");
  if (typeof object.runId !== "string" || !uuid.test(object.runId)) throw new Error("SKILL_RUN_RESPONSE_INVALID");
  const skillId = parseSkillId(object.skillId, "SKILL_RUN_RESPONSE_INVALID");
  const version = parseVersion(object.version, "SKILL_RUN_RESPONSE_INVALID");
  if (object.status !== "passed" && object.status !== "failed") throw new Error("SKILL_RUN_RESPONSE_INVALID");
  if (object.previewId !== null && (typeof object.previewId !== "string" || !uuid.test(object.previewId))) throw new Error("SKILL_RUN_RESPONSE_INVALID");
  if (!Number.isSafeInteger(object.changeCount) || (object.changeCount as number) < 0 || (object.changeCount as number) > 1_000_000) throw new Error("SKILL_RUN_RESPONSE_INVALID");
  const warningCodes = parseWarningCodes(object.warningCodes);
  try {
    return { runId: object.runId, skillId, version, status: object.status, previewId: object.previewId, changeCount: object.changeCount as number, warningCodes, result: object.result === null ? null : cloneJsonValue(object.result) };
  } catch {
    throw new Error("SKILL_RUN_RESPONSE_INVALID");
  }
}

export function cloneJsonValue(value: unknown): JsonValue {
  const state = { values: 0, ancestors: new Set<object>() };
  const copied = cloneValue(value, state, 0);
  if (new TextEncoder().encode(JSON.stringify(copied)).byteLength > MAX_SKILL_JSON_BYTES) throw new Error("SKILL_JSON_INVALID");
  return copied;
}

function cloneValue(value: unknown, state: { values: number; ancestors: Set<object> }, depth: number): JsonValue {
  if (depth > MAX_SKILL_JSON_DEPTH || ++state.values > MAX_SKILL_JSON_TOTAL_VALUES) throw new Error("SKILL_JSON_INVALID");
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (Number.isFinite(value)) return value;
    throw new Error("SKILL_JSON_INVALID");
  }
  if (typeof value === "string") {
    if (value.length <= MAX_SKILL_JSON_SCALAR_CHARS) return value;
    throw new Error("SKILL_JSON_INVALID");
  }
  if (typeof value !== "object" || state.ancestors.has(value)) throw new Error("SKILL_JSON_INVALID");
  state.ancestors.add(value);
  try {
    if (Array.isArray(value)) return cloneArray(value, state, depth);
    return cloneObject(value, state, depth);
  } finally {
    state.ancestors.delete(value);
  }
}

function cloneArray(value: unknown[], state: { values: number; ancestors: Set<object> }, depth: number): JsonValue[] {
  if (Object.getPrototypeOf(value) !== Array.prototype || value.length > MAX_SKILL_JSON_COLLECTION_ITEMS) throw new Error("SKILL_JSON_INVALID");
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Reflect.ownKeys(descriptors).length !== value.length + 1) throw new Error("SKILL_JSON_INVALID");
  const result: JsonValue[] = [];
  for (let index = 0; index < value.length; index += 1) {
    const descriptor = descriptors[String(index)];
    if (!descriptor || !("value" in descriptor) || !descriptor.enumerable) throw new Error("SKILL_JSON_INVALID");
    result.push(cloneValue(descriptor.value, state, depth + 1));
  }
  return result;
}

function cloneObject(value: object, state: { values: number; ancestors: Set<object> }, depth: number): { [key: string]: JsonValue } {
  if (Object.getPrototypeOf(value) !== Object.prototype) throw new Error("SKILL_JSON_INVALID");
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const keys = Reflect.ownKeys(descriptors);
  if (keys.length > MAX_SKILL_JSON_COLLECTION_ITEMS) throw new Error("SKILL_JSON_INVALID");
  const result: { [key: string]: JsonValue } = {};
  for (const key of keys) {
    if (typeof key !== "string" || forbiddenKeys.has(key) || key.length > MAX_SKILL_JSON_SCALAR_CHARS) throw new Error("SKILL_JSON_INVALID");
    const descriptor = descriptors[key]!;
    if (!("value" in descriptor) || !descriptor.enumerable) throw new Error("SKILL_JSON_INVALID");
    result[key] = cloneValue(descriptor.value, state, depth + 1);
  }
  return result;
}

function parseObject(value: unknown, code: string): Record<string, unknown> {
  try {
    const parsed = cloneJsonValue(value);
    if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") throw new Error(code);
    return parsed;
  } catch {
    throw new Error(code);
  }
}

function requireKeys(value: Record<string, unknown>, expected: readonly string[], code: string): void {
  const keys = Object.keys(value).sort();
  if (keys.length !== expected.length || keys.some((key, index) => key !== [...expected].sort()[index])) throw new Error(code);
}

function requireKeysWithOptional(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[],
  code: string
): void {
  const keys = Object.keys(value);
  if (
    required.some((key) => !keys.includes(key)) ||
    keys.some((key) => !required.includes(key) && !optional.includes(key))
  ) throw new Error(code);
}

function parseSkillId(value: unknown, code: string): string {
  if (typeof value !== "string" || value.length < 1 || value.length > 64 || !skillIdentifier.test(value)) throw new Error(code);
  return value;
}

function parseVersion(value: unknown, code: string): string {
  if (typeof value !== "string" || value.length > 128 || !semver.test(value)) throw new Error(code);
  return value;
}

function parsePermissions(value: unknown, code: string): SkillPermission[] {
  if (!Array.isArray(value) || value.length > SKILL_PERMISSIONS.length || !value.every((item): item is SkillPermission => typeof item === "string" && (SKILL_PERMISSIONS as readonly string[]).includes(item)) || new Set(value).size !== value.length) throw new Error(code);
  return [...value];
}

function parseWarningCodes(value: unknown): string[] {
  if (!Array.isArray(value) || value.length > 64 || !value.every((item) => typeof item === "string" && item.length <= 64 && warningCode.test(item)) || new Set(value).size !== value.length) throw new Error("SKILL_RUN_RESPONSE_INVALID");
  return [...value];
}

function parseRelatedDocumentIds(
  value: unknown,
  primaryDocumentId: string
): string[] | undefined {
  if (value === undefined) return undefined;
  if (
    !Array.isArray(value) ||
    value.length > MAX_SKILL_RELATED_DOCUMENT_IDS ||
    !value.every(isDocumentId) ||
    new Set(value).size !== value.length ||
    value.includes(primaryDocumentId)
  ) throw new Error("SKILL_RUN_REQUEST_INVALID");
  return [...value];
}

function isDocumentId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 256 &&
    documentIdentifier.test(value)
  );
}

function isRecentStatus(value: unknown): value is SkillListItem["recentStatus"] {
  return value === "idle" || value === "running" || value === "passed" || value === "failed";
}
