import type { ProviderChatRequest } from "../contracts.js";

export function buildProviderPrompt(request: ProviderChatRequest) {
  return [
    request.systemPrompt,
    "",
    "<cad_context>",
    request.context,
    "</cad_context>",
    "",
    "<user_request>",
    request.message,
    "</user_request>"
  ].join("\n");
}

export function describeCliFailure(errorCode?: string) {
  return errorCode === "ENOENT" ? "CLI not installed" : "CLI execution error";
}
