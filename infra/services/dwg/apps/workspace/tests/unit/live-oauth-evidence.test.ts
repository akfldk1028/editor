import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";

import {
  createSafeLiveOAuthSummary,
  createLiveOAuthFailureSafetyInitScript,
  hasCadHandleEvidence,
  hasNoConsoleErrors,
  isProviderSessionId,
  isSameProviderSession,
  LIVE_OAUTH_SENSITIVE_SELECTORS,
  renderSafeLiveOAuthEvidence
} from "../support/liveOAuthEvidence.js";

test("live OAuth evidence excludes prompts, responses, and provider session IDs", () => {
  const prompt = "PROMPT_SECRET_SENTINEL";
  const response = "RESPONSE_SECRET_SENTINEL";
  const sessionId = "SESSION_SECRET_SENTINEL";
  const summary = createSafeLiveOAuthSummary({
    provider: "codex",
    authenticated: true,
    firstSessionId: sessionId,
    resumedSessionId: sessionId,
    prompt,
    response
  });
  const rendered = renderSafeLiveOAuthEvidence(summary);

  assert.deepEqual(summary, {
    provider: "Codex",
    authenticated: true,
    resumed: true
  });
  for (const secret of [prompt, response, sessionId]) {
    assert.equal(JSON.stringify(summary).includes(secret), false);
    assert.equal(rendered.includes(secret), false);
  }
});

test("live OAuth init script hides sensitive regions as soon as they mount", () => {
  assert.deepEqual(
    LIVE_OAUTH_SENSITIVE_SELECTORS,
    [".conversation", ".composer", ".agent-context", ".session-list"]
  );

  const attributes = new Map<string, string>();
  const elements = new Map<
    string,
    {
      getAttribute(name: string): string | undefined;
      setAttribute(name: string, value: string): void;
    }
  >();
  const mountedElements = new Map([
    [".conversation", {
      getAttribute(name: string) {
        return attributes.get(`conversation:${name}`);
      },
      setAttribute(name: string, value: string) {
        attributes.set(`conversation:${name}`, value);
      }
    }],
    [".composer", {
      getAttribute(name: string) {
        return attributes.get(`composer:${name}`);
      },
      setAttribute(name: string, value: string) {
        attributes.set(`composer:${name}`, value);
      }
    }],
    [".agent-context", {
      getAttribute(name: string) {
        return attributes.get(`agent-context:${name}`);
      },
      setAttribute(name: string, value: string) {
        attributes.set(`agent-context:${name}`, value);
      }
    }],
    [".session-list", {
      getAttribute(name: string) {
        return attributes.get(`session-list:${name}`);
      },
      setAttribute(name: string, value: string) {
        attributes.set(`session-list:${name}`, value);
      }
    }]
  ]);
  const observed: {
    attributeFilter?: string[];
    attributes?: boolean;
    childList?: boolean;
    subtree?: boolean;
  }[] = [];
  let observerCallback: (() => void) | undefined;
  const document = {
    querySelectorAll(selector: string) {
      const element = elements.get(selector);
      return element ? [element] : [];
    }
  };
  class FakeMutationObserver {
    constructor(callback: () => void) {
      observerCallback = callback;
    }

    observe(
      _target: unknown,
      options: {
        attributeFilter?: string[];
        attributes?: boolean;
        childList?: boolean;
        subtree?: boolean;
      }
    ) {
      observed.push(options);
    }
  }

  vm.runInNewContext(createLiveOAuthFailureSafetyInitScript(), {
    document,
    MutationObserver: FakeMutationObserver
  });
  assert.equal(observed.length, 1);
  assert.equal(observed[0]?.attributes, true);
  assert.equal(observed[0]?.childList, true);
  assert.equal(observed[0]?.subtree, true);
  assert.deepEqual(
    Array.from(observed[0]?.attributeFilter ?? []),
    ["aria-hidden"]
  );
  assert.equal(attributes.size, 0);

  for (const [selector, element] of mountedElements) {
    elements.set(selector, element);
  }
  observerCallback?.();
  assert.equal(attributes.get("conversation:aria-hidden"), "true");
  assert.equal(attributes.get("composer:aria-hidden"), "true");
  assert.equal(attributes.get("agent-context:aria-hidden"), "true");
  assert.equal(attributes.get("session-list:aria-hidden"), "true");
});

test("live OAuth validation primitives return booleans without exposing values", () => {
  const sessionId = "11111111-1111-4111-8111-111111111111";
  const contractSessionId = "77777777-7777-7777-7777-777777777777";
  assert.equal(hasCadHandleEvidence("safe [handle:AB12]"), true);
  assert.equal(hasCadHandleEvidence("RESPONSE_SECRET_SENTINEL"), false);
  assert.equal(isProviderSessionId(sessionId), true);
  assert.equal(isProviderSessionId(contractSessionId), true);
  assert.equal(isProviderSessionId("SESSION_SECRET_SENTINEL"), false);
  assert.equal(isSameProviderSession(sessionId, sessionId), true);
  assert.equal(
    isSameProviderSession(
      sessionId,
      "22222222-2222-4222-8222-222222222222"
    ),
    false
  );
  assert.equal(hasNoConsoleErrors(0), true);
  assert.equal(hasNoConsoleErrors(1), false);
});
