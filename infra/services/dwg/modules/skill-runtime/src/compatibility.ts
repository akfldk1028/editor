import type { CadSkillManifest } from "@dwg/skill-contracts";

export interface CadSkillCompatibility {
  compatible: boolean;
  incompatibility: string | null;
}

export function assessCadSkillCompatibility(
  manifest: CadSkillManifest,
  capabilityVersion: string
): CadSkillCompatibility {
  if (manifest.capabilityContract !== capabilityVersion) {
    return {
      compatible: false,
      incompatibility: "CAPABILITY_CONTRACT_MISMATCH"
    };
  }

  return { compatible: true, incompatibility: null };
}
