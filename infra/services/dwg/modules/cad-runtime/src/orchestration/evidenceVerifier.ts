import type { CadToolMatch } from "../domain/cad-index/types.js";

export type EvidenceField = "id" | "handle" | "type" | "layer" | "bbox";

export interface EvidenceIssue {
  entityId: string;
  missing: EvidenceField[];
}

export interface EvidenceVerification {
  status: "accepted" | "rejected";
  matches: CadToolMatch[];
  issues: EvidenceIssue[];
}

export function verifyMatches(
  matches: readonly CadToolMatch[]
): EvidenceVerification {
  const issues = matches.flatMap((match) => {
    const missing: EvidenceField[] = [];
    if (!match.id) {
      missing.push("id");
    }
    if (!match.handle) {
      missing.push("handle");
    }
    if (!match.type) {
      missing.push("type");
    }
    if (!match.layer) {
      missing.push("layer");
    }
    if (!match.bbox) {
      missing.push("bbox");
    }

    return missing.length > 0
      ? [{ entityId: match.id || "(missing-id)", missing }]
      : [];
  });

  if (issues.length > 0) {
    return {
      status: "rejected",
      matches: [],
      issues
    };
  }

  return {
    status: "accepted",
    matches: [...matches],
    issues: []
  };
}
