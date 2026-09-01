import { Ajv } from "ajv";

import type { CadCapabilityRuntime } from "@dwg/cad-capabilities";
import { MAX_SKILL_RELATED_DOCUMENT_IDS } from "@dwg/contracts";
import {
  cloneCadSkillJsonValue,
  parseCadSkillManifest,
  parseCadSkillWorkflow,
  type CadSkillWorkflow,
  type SkillPermission
} from "@dwg/skill-contracts";

import type { InstalledCadSkill } from "./discovery.js";
import { requiredSkillPermission } from "./permissions.js";

export const MAX_CAD_SKILL_RUN_RESULT_BYTES = 1024 * 1024;
const BOUNDED_SKILL_ID = "bounded-skill-result";

export interface CadSkillRunStepResult {
  id: string;
  status: "passed" | "failed" | "cancelled";
  output: unknown;
}

export interface CadSkillRunResult {
  skillId: string;
  status: "passed" | "failed" | "cancelled";
  steps: CadSkillRunStepResult[];
  warnings: string[];
}

export interface RunCadSkillWorkflowOptions {
  skill: InstalledCadSkill;
  workflow: CadSkillWorkflow;
  input: unknown;
  hostInput?: unknown;
  documentId?: string;
  relatedDocumentIds?: readonly string[];
  grantedPermissions: SkillPermission[];
  capabilities: CadCapabilityRuntime;
  signal?: AbortSignal;
}

export async function runCadSkillWorkflow(options: RunCadSkillWorkflowOptions): Promise<CadSkillRunResult> {
  const workflow = parseCadSkillWorkflow(options.workflow);
  let manifest;
  try {
    manifest = parseCadSkillManifest(cloneCadSkillJsonValue(options.skill.manifest));
  } catch {
    return failWithoutStep(createResult(BOUNDED_SKILL_ID), "SKILL_MANIFEST_INVALID");
  }
  const result = createResult(manifest.id);
  let safeInput: unknown;
  let safeHostInput: Record<string, unknown>;
  try {
    safeInput = cloneCadSkillJsonValue(options.input);
    const hostInput = cloneCadSkillJsonValue(options.hostInput ?? {});
    if (!isDataObject(hostInput)) throw new Error("HOST_INPUT_INVALID");
    safeHostInput = hostInput;
  } catch {
    return failWithoutStep(result, "INPUT_VALUE_INVALID");
  }

  const documentScope = createDocumentScope(
    options.documentId,
    options.relatedDocumentIds
  );
  if (options.documentId !== undefined || options.relatedDocumentIds !== undefined) {
    if (documentScope === null || !isDataObject(safeInput)) {
      return failWithoutStep(result, "DOCUMENT_SCOPE_INVALID");
    }
    if (Object.hasOwn(safeInput, "documentId") && safeInput.documentId !== options.documentId) {
      return failWithoutStep(result, "DOCUMENT_SCOPE_MISMATCH");
    }
    if (
      Object.hasOwn(safeInput, "relatedDocumentIds") &&
      !sameStringArray(safeInput.relatedDocumentIds, documentScope.relatedDocumentIds)
    ) return failWithoutStep(result, "DOCUMENT_SCOPE_MISMATCH");
  }

  if (!validates(manifest.inputSchema, safeInput)) {
    if (
      documentScope === null ||
      !isDataObject(safeInput) ||
      (!Object.hasOwn(safeInput, "documentId") && !Object.hasOwn(safeInput, "relatedDocumentIds")) ||
      !validates(manifest.inputSchema, withoutDocumentScope(safeInput))
    ) return failWithoutStep(result, "INPUT_SCHEMA_INVALID");
  }
  if (documentScope !== null) {
    safeInput = {
      ...safeInput as Record<string, unknown>,
      documentId: documentScope.documentId,
      relatedDocumentIds: documentScope.relatedDocumentIds
    };
  }
  const capabilities = documentScope === null
    ? options.capabilities
    : createDocumentScopedRuntime(options.capabilities, documentScope.allowed);

  for (const step of workflow.steps) {
    if (options.signal?.aborted) return cancel(result, step.id);
    if (!options.skill.compatible || manifest.capabilityContract !== "cad-capabilities/v1") {
      return fail(result, step.id, "SKILL_INCOMPATIBLE");
    }
    if (!manifest.capabilities.includes(step.capability)) return fail(result, step.id, "CAPABILITY_NOT_DECLARED");
    const permission = requiredSkillPermission(step.capability);
    if (permission === undefined || permission === null) return fail(result, step.id, "CAPABILITY_FORBIDDEN");
    if (!manifest.permissions.includes(permission) || !options.grantedPermissions.includes(permission)) {
      return fail(result, step.id, "PERMISSION_DENIED");
    }

    const boundInput = bindInput(step.input, safeInput, safeHostInput, result.steps);
    let output: unknown;
    try {
      output = await capabilities.execute(step.capability as never, boundInput, options.signal);
    } catch {
      if (options.signal?.aborted) return cancel(result, step.id);
      return fail(result, step.id, "CAPABILITY_EXECUTION_FAILED");
    }
    if (options.signal?.aborted) return cancel(result, step.id);
    try {
      output = cloneCadSkillJsonValue(output);
    } catch {
      return fail(result, step.id, "CAPABILITY_OUTPUT_INVALID");
    }
    result.steps.push({ id: step.id, status: "passed", output });
    if (!withinLimit(result)) {
      result.steps.pop();
      return oversizedResult("failed");
    }
  }

  const finalOutput = result.steps.at(-1)?.output;
  if (!validates(manifest.outputSchema, finalOutput)) {
    const finalStep = result.steps.at(-1)!;
    result.steps.pop();
    return fail(result, finalStep.id, "OUTPUT_SCHEMA_INVALID");
  }
  if (!withinLimit(result)) return fail(result, result.steps.at(-1)!.id, "RESULT_TOO_LARGE");
  return result;
}

function createDocumentScopedRuntime(
  capabilities: CadCapabilityRuntime,
  allowedDocumentIds: ReadonlySet<string>
): CadCapabilityRuntime {
  return {
    async execute(name, input, signal) {
      assertDocumentReferences(input, allowedDocumentIds);
      const output = await capabilities.execute(name, input, signal);
      if (name === "document.open") {
        const safeOutput = cloneCadSkillJsonValue(output);
        if (
          !isDataObject(safeOutput) ||
          typeof safeOutput.drawingId !== "string" ||
          !allowedDocumentIds.has(safeOutput.drawingId)
        ) {
          throw new Error("DOCUMENT_SCOPE_MISMATCH");
        }
        return safeOutput;
      }
      return output;
    }
  };
}

function assertDocumentReferences(
  value: unknown,
  allowedDocumentIds: ReadonlySet<string>
): void {
  const safeValue = cloneCadSkillJsonValue(value);
  visitDocumentReferences(safeValue, allowedDocumentIds);
}

function visitDocumentReferences(
  value: unknown,
  allowedDocumentIds: ReadonlySet<string>
): void {
  if (Array.isArray(value)) {
    for (const item of value) visitDocumentReferences(item, allowedDocumentIds);
    return;
  }
  if (!isDataObject(value)) return;
  for (const [key, item] of Object.entries(value)) {
    if (
      (key === "drawingId" || key === "documentId" || key === "beforeDrawingId" || key === "afterDrawingId") &&
      (typeof item !== "string" || !allowedDocumentIds.has(item))
    ) throw new Error("DOCUMENT_SCOPE_MISMATCH");
    visitDocumentReferences(item, allowedDocumentIds);
  }
}

function isDataObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validDocumentId(value: string): boolean {
  return value.length >= 1 && value.length <= 256 && /^[A-Za-z0-9][A-Za-z0-9:._-]*$/.test(value);
}

function withoutDocumentScope(value: Record<string, unknown>): Record<string, unknown> {
  const copy = { ...value };
  delete copy.documentId;
  delete copy.relatedDocumentIds;
  return copy;
}

function createDocumentScope(
  documentId: string | undefined,
  relatedDocumentIds: readonly string[] | undefined
): {
  documentId: string;
  relatedDocumentIds: string[];
  allowed: ReadonlySet<string>;
} | null {
  if (documentId === undefined) return null;
  let safeRelated: unknown;
  try {
    safeRelated = cloneCadSkillJsonValue(relatedDocumentIds ?? []);
  } catch {
    return null;
  }
  if (
    !validDocumentId(documentId) ||
    !Array.isArray(safeRelated) ||
    safeRelated.length > MAX_SKILL_RELATED_DOCUMENT_IDS ||
    !safeRelated.every((value): value is string => typeof value === "string" && validDocumentId(value)) ||
    new Set(safeRelated).size !== safeRelated.length ||
    safeRelated.includes(documentId)
  ) return null;
  return {
    documentId,
    relatedDocumentIds: safeRelated,
    allowed: new Set([documentId, ...safeRelated])
  };
}

function sameStringArray(value: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function bindInput(
  input: Record<string, unknown>,
  workflowInput: unknown,
  hostInput: Record<string, unknown>,
  previousSteps: readonly CadSkillRunStepResult[]
): Record<string, unknown> {
  return cloneCadSkillJsonValue(
    resolveBindings(input, workflowInput, hostInput, previousSteps)
  ) as Record<string, unknown>;
}

function resolveBindings(
  value: unknown,
  workflowInput: unknown,
  hostInput: Record<string, unknown>,
  previousSteps: readonly CadSkillRunStepResult[]
): unknown {
  if (typeof value === "string" && value.startsWith("$")) {
    return resolveBinding(value, workflowInput, hostInput, previousSteps);
  }
  if (Array.isArray(value)) {
    return value.map((item) => resolveBindings(item, workflowInput, hostInput, previousSteps));
  }
  if (value !== null && typeof value === "object") {
    const resolved: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      resolved[key] = resolveBindings(item, workflowInput, hostInput, previousSteps);
    }
    return resolved;
  }
  return value;
}

function resolveBinding(
  expression: string,
  workflowInput: unknown,
  hostInput: Record<string, unknown>,
  previousSteps: readonly CadSkillRunStepResult[]
): unknown {
  const input = /^\$input((?:\.[a-zA-Z_$][a-zA-Z0-9_$-]*)*)$/.exec(expression);
  if (input) return readBindingPath(workflowInput, input[1]!);
  const host = /^\$host((?:\.[a-zA-Z_$][a-zA-Z0-9_$-]*)*)$/.exec(expression);
  if (host) return readBindingPath(hostInput, host[1]!);
  const step = /^\$steps\.([a-z][a-z0-9-]{0,63})\.output((?:\.[a-zA-Z_$][a-zA-Z0-9_$-]*)*)$/.exec(expression);
  if (!step) throw new Error("WORKFLOW_BINDING_INVALID");
  const previous = previousSteps.find((item) => item.id === step[1]);
  if (!previous || previous.status !== "passed") throw new Error("WORKFLOW_BINDING_INVALID");
  return readBindingPath(previous.output, step[2]!);
}

function readBindingPath(value: unknown, suffix: string): unknown {
  let current = value;
  for (const key of suffix.split(".").filter(Boolean)) {
    if (key === "__proto__" || key === "constructor" || key === "prototype") throw new Error("WORKFLOW_BINDING_INVALID");
    if (current === null || typeof current !== "object" || Array.isArray(current) || !Object.hasOwn(current, key)) {
      throw new Error("WORKFLOW_BINDING_INVALID");
    }
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

function validates(schema: Record<string, unknown>, value: unknown): boolean {
  try {
    return new Ajv({ allErrors: true, strict: true }).compile(schema)(value) === true;
  } catch {
    return false;
  }
}

function createResult(skillId: string): CadSkillRunResult {
  return { skillId, status: "passed", steps: [], warnings: [] };
}

function fail(result: CadSkillRunResult, id: string, code: string): CadSkillRunResult {
  result.status = "failed";
  result.steps.push({ id, status: "failed", output: { error: { code } } });
  return bounded(result);
}

function failWithoutStep(result: CadSkillRunResult, code: string): CadSkillRunResult {
  result.status = "failed";
  result.warnings.push(code);
  return bounded(result);
}

function cancel(result: CadSkillRunResult, id: string): CadSkillRunResult {
  result.status = "cancelled";
  result.steps.push({ id, status: "cancelled", output: { error: { code: "CANCELLED" } } });
  return bounded(result);
}

function withinLimit(result: CadSkillRunResult): boolean {
  return Buffer.byteLength(JSON.stringify(result), "utf8") <= MAX_CAD_SKILL_RUN_RESULT_BYTES;
}

function bounded(result: CadSkillRunResult): CadSkillRunResult {
  if (withinLimit(result)) return result;
  return oversizedResult(result.status);
}

function oversizedResult(
  status: CadSkillRunResult["status"]
): CadSkillRunResult {
  const code = status === "cancelled" ? "CANCELLED" : "RESULT_TOO_LARGE";
  return {
    skillId: BOUNDED_SKILL_ID,
    status,
    steps: [{ id: "result", status: status === "cancelled" ? "cancelled" : "failed", output: { error: { code } } }],
    warnings: []
  };
}
