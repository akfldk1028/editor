import { isInspectionRun } from "@dwg/contracts";

import type {
  InspectionPayload,
  InspectionRun
} from "../types";
import { postJson } from "./httpClient";

export function runInspection(
  payload: InspectionPayload,
  signal?: AbortSignal
) {
  return postJson<InspectionRun>(
    "/api/inspections",
    payload,
    signal,
    isInspectionRun
  );
}
