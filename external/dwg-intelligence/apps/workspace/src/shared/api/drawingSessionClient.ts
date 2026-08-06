import {
  parseDrawingSessionListResponse,
  type DrawingSessionListResponse
} from "@dwg/contracts";

import { getJson, postJson } from "./httpClient";

const validates = (parse: (value: unknown) => DrawingSessionListResponse) =>
  (value: unknown): value is DrawingSessionListResponse => {
    parse(value);
    return true;
  };

const isSessionList = validates(parseDrawingSessionListResponse);

export function loadDrawingSessions(signal?: AbortSignal) {
  return getJson<DrawingSessionListResponse>("/api/drawings/sessions", signal, isSessionList);
}

/**
 * Resolves to null when the person dismissed the dialog. Dismissal is an
 * outcome, so it must not surface as an error the way a real failure does.
 */
export async function openDrawing(
  signal?: AbortSignal
): Promise<DrawingSessionListResponse | null> {
  const response = await fetch("/api/drawings/open", { method: "POST", signal });
  const payload: unknown = await response.json().catch(() => null);
  if (response.status === 409 && errorCode(payload) === "DRAWING_OPEN_CANCELLED") {
    return null;
  }
  if (!response.ok) throw new Error(errorMessage(payload) ?? `HTTP ${response.status}`);
  return parseDrawingSessionListResponse(payload);
}

function errorField(payload: unknown, field: "code" | "message"): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const error = (payload as { error?: unknown }).error;
  if (typeof error !== "object" || error === null) return null;
  const value = (error as Record<string, unknown>)[field];
  return typeof value === "string" ? value : null;
}

const errorCode = (payload: unknown) => errorField(payload, "code");
const errorMessage = (payload: unknown) => errorField(payload, "message");

export function activateDrawingSession(sessionId: string, signal?: AbortSignal) {
  return postJson<DrawingSessionListResponse>(
    `/api/drawings/sessions/${encodeURIComponent(sessionId)}/activate`,
    {},
    signal,
    isSessionList
  );
}
