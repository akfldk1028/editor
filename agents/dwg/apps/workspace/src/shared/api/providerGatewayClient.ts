import {
  isProviderChatResult,
  isProviderStatus
} from "@dwg/contracts";

import type {
  ProviderChatPayload,
  ProviderChatResult,
  ProviderStatus
} from "../types";
import { getJson, postJson } from "./httpClient";

interface ProviderStatusResponse {
  providers: ProviderStatus[];
}

export async function loadProviderStatuses(signal?: AbortSignal) {
  const response = await getJson(
    "/api/providers",
    signal,
    isProviderStatusResponse
  );
  return response.providers;
}

export function sendProviderChat(request: ProviderChatPayload, signal?: AbortSignal) {
  return postJson<ProviderChatResult>(
    "/api/chat",
    request,
    signal,
    isProviderChatResult
  );
}

function isProviderStatusResponse(value: unknown): value is ProviderStatusResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as Record<string, unknown>).providers) &&
    (value as { providers: unknown[] }).providers.every(isProviderStatus)
  );
}
