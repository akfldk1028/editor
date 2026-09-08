import { isCadEntityIndex } from "@dwg/contracts";

import type { CadIndex } from "../types";
import { getJson } from "./httpClient";

export function loadDrawingIndex(signal?: AbortSignal) {
  return getJson<CadIndex>("/api/drawing", signal, isCadEntityIndex);
}
