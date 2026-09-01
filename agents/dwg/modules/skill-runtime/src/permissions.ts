import type { CadCapabilityName } from "@dwg/cad-capabilities";
import type { SkillPermission } from "@dwg/skill-contracts";

const CAPABILITY_PERMISSIONS: Readonly<Record<CadCapabilityName, SkillPermission | null>> = {
  "document.open": "read",
  "document.describe": "read",
  "query.layers": "read",
  "query.entities": "read",
  "query.text": "read",
  "query.schedule": "read",
  "query.compare": "read",
  "edit.preview": "propose-edit",
  "edit.apply": null,
  "edit.undo": null,
  "edit.redo": null,
  "export.report": "export",
  "export.drawing": "write-copy",
  "verification.get": "read"
};

export function requiredSkillPermission(
  capability: string
): SkillPermission | null | undefined {
  return CAPABILITY_PERMISSIONS[capability as CadCapabilityName];
}
