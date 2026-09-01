export type ProviderId = "codex" | "claude";
export const MAX_PROVIDER_MESSAGE_CHARS = 8_000;

export interface ProviderStatus {
  id: ProviderId;
  label: string;
  installed: boolean;
  authenticated: boolean;
  authMethod: "chatgpt" | "claude.ai" | "unknown";
  subscription?: string;
  detail: string;
}

export interface ProviderChatPayload {
  provider: ProviderId;
  drawingPath: string;
  message: string;
  sessionId?: string | null;
}

export interface ProviderChatResult {
  provider: ProviderId;
  text: string;
  sessionId: string | null;
}

export function isProviderSessionId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
  );
}

export function isProviderStatus(value: unknown): value is ProviderStatus {
  if (!isRecord(value)) return false;
  return (
    (value.id === "codex" || value.id === "claude") &&
    typeof value.label === "string" &&
    typeof value.installed === "boolean" &&
    typeof value.authenticated === "boolean" &&
    (
      value.authMethod === "chatgpt" ||
      value.authMethod === "claude.ai" ||
      value.authMethod === "unknown"
    ) &&
    (value.subscription === undefined || typeof value.subscription === "string") &&
    typeof value.detail === "string"
  );
}

export function isProviderChatResult(value: unknown): value is ProviderChatResult {
  if (!isRecord(value)) return false;
  return (
    (value.provider === "codex" || value.provider === "claude") &&
    typeof value.text === "string" &&
    (value.sessionId === null || isProviderSessionId(value.sessionId))
  );
}

export function isProviderChatPayload(value: unknown): value is ProviderChatPayload {
  if (!isRecord(value)) return false;
  const request = value;
  return (
    (request.provider === "codex" || request.provider === "claude") &&
    typeof request.drawingPath === "string" &&
    request.drawingPath.length > 0 &&
    typeof request.message === "string" &&
    request.message.length > 0 &&
    request.message.length <= MAX_PROVIDER_MESSAGE_CHARS &&
    (
      request.sessionId === undefined ||
      request.sessionId === null ||
      isProviderSessionId(request.sessionId)
    )
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
