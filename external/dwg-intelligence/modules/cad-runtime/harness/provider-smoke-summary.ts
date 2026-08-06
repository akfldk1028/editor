import { isProviderSessionId } from "@dwg/contracts";

export interface ProviderSmokeSummaryInput {
  provider: string;
  authMethod: string;
  subscription?: string;
  resumed: boolean;
  sessionId?: string;
  response?: string;
  resumedResponse?: string;
  prompt?: string;
  environment?: unknown;
}

export function createProviderSmokeSummary(
  input: ProviderSmokeSummaryInput
) {
  return {
    provider: input.provider,
    authMethod: input.authMethod,
    subscription: input.subscription ?? null,
    resumed: input.resumed
  };
}

export interface ProviderSmokeInitialResult {
  response: unknown;
  sessionId: unknown;
}

export interface ProviderSmokeResumedResult {
  resumedResponse: unknown;
  sessionId: unknown;
  resumedSessionId: unknown;
}

export interface ProviderSmokeValidationInput
  extends ProviderSmokeInitialResult,
    ProviderSmokeResumedResult {}

export function validateProviderSmokeInitialResult(
  input: ProviderSmokeInitialResult
): asserts input is { response: string; sessionId: string } {
  if (!hasCadHandleEvidence(input.response)) {
    throw new Error("Provider response has no CAD handle evidence");
  }
  if (!isProviderSessionId(input.sessionId)) {
    throw new Error("Provider returned an invalid session identifier");
  }
}

export function validateProviderSmokeResumedResult(
  input: ProviderSmokeResumedResult
): void {
  if (!hasCadHandleEvidence(input.resumedResponse)) {
    throw new Error("Provider resumed response has no CAD handle evidence");
  }
  if (!isProviderSessionId(input.resumedSessionId)) {
    throw new Error("Provider returned an invalid resumed session identifier");
  }
  if (input.resumedSessionId !== input.sessionId) {
    throw new Error("Provider session did not resume");
  }
}

export function validateProviderSmokeResult(
  input: ProviderSmokeValidationInput
): void {
  validateProviderSmokeInitialResult(input);
  validateProviderSmokeResumedResult(input);
}

function hasCadHandleEvidence(value: unknown): boolean {
  return typeof value === "string" && /\[handle:[0-9A-F]+\]/i.test(value);
}
