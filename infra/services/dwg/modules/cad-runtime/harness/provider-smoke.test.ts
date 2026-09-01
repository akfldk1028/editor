import assert from "node:assert/strict";
import test from "node:test";

import {
  createProviderSmokeSummary,
  validateProviderSmokeResult
} from "./provider-smoke-summary.js";

test("provider smoke summary exposes only safe status fields", () => {
  const secrets = {
    sessionId: "SESSION_SECRET_SENTINEL",
    response: "RESPONSE_SECRET_SENTINEL",
    resumedResponse: "RESUMED_RESPONSE_SECRET_SENTINEL",
    prompt: "PROMPT_SECRET_SENTINEL",
    environment: "ENVIRONMENT_SECRET_SENTINEL"
  };
  const summary = createProviderSmokeSummary({
    provider: "claude",
    authMethod: "oauth",
    subscription: "max",
    resumed: true,
    ...secrets
  });
  const output = JSON.stringify(summary);

  assert.deepEqual(summary, {
    provider: "claude",
    authMethod: "oauth",
    subscription: "max",
    resumed: true
  });
  for (const secret of Object.values(secrets)) {
    assert.equal(output.includes(secret), false);
  }
});

test("provider smoke validation failures never include response or session values", () => {
  const firstSession = "11111111-1111-7111-7111-111111111111";
  const resumedSession = "22222222-2222-7222-7222-222222222222";
  const cases = [
    {
      input: {
        response: "INVALID_RESPONSE_SECRET_SENTINEL",
        sessionId: firstSession,
        resumedResponse: "safe [handle:AB12]",
        resumedSessionId: firstSession
      },
      message: "Provider response has no CAD handle evidence",
      secrets: ["INVALID_RESPONSE_SECRET_SENTINEL", firstSession]
    },
    {
      input: {
        response: "safe [handle:AB12]",
        sessionId: "INVALID_SESSION_SECRET_SENTINEL",
        resumedResponse: "safe [handle:AB12]",
        resumedSessionId: "INVALID_SESSION_SECRET_SENTINEL"
      },
      message: "Provider returned an invalid session identifier",
      secrets: ["INVALID_SESSION_SECRET_SENTINEL"]
    },
    {
      input: {
        response: "safe [handle:AB12]",
        sessionId: firstSession,
        resumedResponse: "safe [handle:AB12]",
        resumedSessionId: resumedSession
      },
      message: "Provider session did not resume",
      secrets: [firstSession, resumedSession]
    },
    {
      input: {
        response: "safe [handle:AB12]",
        sessionId: firstSession,
        resumedResponse: "INVALID_RESUMED_RESPONSE_SECRET_SENTINEL",
        resumedSessionId: firstSession
      },
      message: "Provider resumed response has no CAD handle evidence",
      secrets: ["INVALID_RESUMED_RESPONSE_SECRET_SENTINEL", firstSession]
    }
  ];

  for (const testCase of cases) {
    assert.throws(
      () => validateProviderSmokeResult(testCase.input),
      (error: unknown) => {
        assert.equal(error instanceof Error, true);
        assert.equal((error as Error).message, testCase.message);
        for (const secret of testCase.secrets) {
          assert.equal((error as Error).message.includes(secret), false);
        }
        return true;
      }
    );
  }
});
