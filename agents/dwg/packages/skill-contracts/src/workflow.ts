import { z } from "zod";

export const MAX_CAD_SKILL_WORKFLOW_STEPS = 32;

export interface CadSkillWorkflowStep {
  id: string;
  capability: string;
  input: Record<string, unknown>;
}

export interface CadSkillWorkflow {
  schemaVersion: "cad-skill-workflow/v1";
  steps: CadSkillWorkflowStep[];
}

const identifier = /^[a-z][a-z0-9-]{0,63}$/;
const forbiddenKeys = new Set(["__proto__", "constructor", "prototype"]);

const workflowSchema = z.object({
  schemaVersion: z.literal("cad-skill-workflow/v1"),
  steps: z.array(z.object({
    id: z.string().regex(identifier),
    capability: z.string().regex(/^(?:document|query|edit|export|verification)\.[a-z][a-z0-9-]*$/),
    input: z.record(z.unknown())
  }).strict()).min(1).max(MAX_CAD_SKILL_WORKFLOW_STEPS)
}).strict();

export function parseCadSkillWorkflow(value: unknown): CadSkillWorkflow {
  assertJsonValue(value);
  let workflow: CadSkillWorkflow;
  try {
    workflow = workflowSchema.parse(value);
  } catch {
    throw new Error("WORKFLOW_INVALID");
  }
  if (new Set(workflow.steps.map((step) => step.id)).size !== workflow.steps.length) {
    throw new Error("WORKFLOW_INVALID");
  }
  return workflow;
}

export function assertCadSkillJsonValue(value: unknown): void {
  assertJsonValue(value);
}

export function cloneCadSkillJsonValue<T>(value: T): T {
  return cloneDataValue(value, new Set<object>()) as T;
}

function assertJsonValue(value: unknown): void {
  cloneDataValue(value, new Set<object>());
}

function cloneDataValue(value: unknown, ancestors: Set<object>): unknown {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "number") {
    if (Number.isFinite(value)) return value;
    throw new Error("WORKFLOW_VALUE_NOT_JSON");
  }
  if (typeof value !== "object") throw new Error("WORKFLOW_VALUE_NOT_JSON");
  if (ancestors.has(value)) throw new Error("WORKFLOW_VALUE_NOT_JSON");

  ancestors.add(value);
  try {
    return Array.isArray(value)
      ? cloneDataArray(value, ancestors)
      : cloneDataObject(value, ancestors);
  } finally {
    ancestors.delete(value);
  }
}

function cloneDataArray(value: unknown[], ancestors: Set<object>): unknown[] {
  if (Object.getPrototypeOf(value) !== Array.prototype) {
    throw new Error("WORKFLOW_VALUE_NOT_JSON");
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const lengthDescriptor = Object.getOwnPropertyDescriptor(value, "length");
  if (
    !lengthDescriptor ||
    !("value" in lengthDescriptor) ||
    lengthDescriptor.enumerable ||
    lengthDescriptor.configurable ||
    !Number.isSafeInteger(lengthDescriptor.value) ||
    lengthDescriptor.value < 0
  ) {
    throw new Error("WORKFLOW_VALUE_NOT_JSON");
  }

  const length = lengthDescriptor.value as number;
  const keys = Reflect.ownKeys(descriptors);
  if (keys.length !== length + 1) throw new Error("WORKFLOW_VALUE_NOT_JSON");

  const copied: unknown[] = [];
  for (let index = 0; index < length; index += 1) {
    const descriptor = descriptors[String(index)];
    if (
      !descriptor ||
      !("value" in descriptor) ||
      !descriptor.enumerable
    ) {
      throw new Error("WORKFLOW_VALUE_NOT_JSON");
    }
    copied.push(cloneDataValue(descriptor.value, ancestors));
  }
  return copied;
}

function cloneDataObject(
  value: object,
  ancestors: Set<object>
): Record<string, unknown> {
  if (Object.getPrototypeOf(value) !== Object.prototype) {
    throw new Error("WORKFLOW_VALUE_NOT_JSON");
  }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  const copied: Record<string, unknown> = {};
  for (const key of Reflect.ownKeys(descriptors)) {
    if (typeof key !== "string" || forbiddenKeys.has(key)) {
      throw new Error("WORKFLOW_VALUE_NOT_JSON");
    }
    const descriptor = descriptors[key]!;
    if (!("value" in descriptor) || !descriptor.enumerable) {
      throw new Error("WORKFLOW_VALUE_NOT_JSON");
    }
    copied[key] = cloneDataValue(descriptor.value, ancestors);
  }
  return copied;
}
