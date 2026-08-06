import { z } from "zod";

import {
  SKILL_PERMISSIONS,
  type SkillPermission
} from "./permissions.js";

export const MAX_CAD_SKILL_ID_CHARS = 64;
export const MAX_CAD_SKILL_VERSION_CHARS = 128;
export const MAX_CAD_SKILL_PURPOSE_CHARS = 2_048;
export const MAX_CAD_SKILL_CAPABILITY_CHARS = 128;
export const MAX_CAD_SKILL_CAPABILITIES = 64;
export const MAX_CAD_SKILL_ENTITY_TYPE_CHARS = 128;
export const MAX_CAD_SKILL_ENTITY_TYPES = 128;
export const MAX_CAD_SKILL_CODE_CHARS = 64;
export const MAX_CAD_SKILL_CODES = 64;

const identifier = z.string().max(MAX_CAD_SKILL_ID_CHARS)
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
const semanticVersion = z.string().max(MAX_CAD_SKILL_VERSION_CHARS).regex(
  /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/
);
const code = z.string().max(MAX_CAD_SKILL_CODE_CHARS)
  .regex(/^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$/);

export interface CadSkillManifest {
  id: string;
  version: string;
  purpose: string;
  capabilityContract: "cad-capabilities/v1";
  permissions: SkillPermission[];
  capabilities: string[];
  formats: Array<"dwg" | "dxf">;
  entityTypes: string[];
  failureCodes: string[];
  limitationCodes: string[];
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
}

export const cadSkillManifestSchema = z.object({
  id: identifier,
  version: semanticVersion,
  purpose: z.string().trim().min(1).max(MAX_CAD_SKILL_PURPOSE_CHARS),
  capabilityContract: z.literal("cad-capabilities/v1"),
  permissions: z.array(z.enum(SKILL_PERMISSIONS))
    .max(SKILL_PERMISSIONS.length).refine(isUnique),
  capabilities: z.array(
    z.string().trim().min(1).max(MAX_CAD_SKILL_CAPABILITY_CHARS)
  ).max(MAX_CAD_SKILL_CAPABILITIES).refine(isUnique),
  formats: z.array(z.enum(["dwg", "dxf"])).max(2).refine(isUnique),
  entityTypes: z.array(
    z.string().trim().min(1).max(MAX_CAD_SKILL_ENTITY_TYPE_CHARS)
  ).max(MAX_CAD_SKILL_ENTITY_TYPES).refine(isUnique),
  failureCodes: z.array(code).min(1).max(MAX_CAD_SKILL_CODES).refine(isUnique),
  limitationCodes: z.array(code).min(1).max(MAX_CAD_SKILL_CODES).refine(isUnique),
  inputSchema: z.record(z.unknown()),
  outputSchema: z.record(z.unknown())
}).strict();

export function parseCadSkillManifest(value: unknown): CadSkillManifest {
  return cadSkillManifestSchema.parse(value);
}

function isUnique(values: readonly string[]) {
  return new Set(values).size === values.length;
}
