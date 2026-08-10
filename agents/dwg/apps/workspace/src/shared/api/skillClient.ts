import { parseSkillListResponse, type SkillListResponse } from "@dwg/contracts";

import { getJson } from "./httpClient";

export function loadSkills(signal?: AbortSignal): Promise<SkillListResponse> {
  return getJson("/api/skills", signal, isSkillListResponse);
}

function isSkillListResponse(value: unknown): value is SkillListResponse {
  try {
    parseSkillListResponse(value);
    return true;
  } catch {
    return false;
  }
}
