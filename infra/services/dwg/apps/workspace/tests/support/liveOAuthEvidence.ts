import { isProviderSessionId as isContractProviderSessionId } from "@dwg/contracts";
import type { Locator } from "@playwright/test";

export interface LiveOAuthEvidenceInput {
  provider: "codex" | "claude";
  authenticated: boolean;
  firstSessionId: string;
  resumedSessionId: string;
  prompt: string;
  response: string;
}

export interface SafeLiveOAuthSummary {
  provider: "Codex" | "Claude";
  authenticated: boolean;
  resumed: boolean;
}

export const LIVE_OAUTH_SENSITIVE_SELECTORS = [
  ".conversation",
  ".composer",
  ".agent-context",
  ".session-list"
] as const;

export const LIVE_OAUTH_PROMPTS = {
  initial:
    "List one TEXT or MTEXT object from the indexed drawing and cite its [handle:...].",
  resume:
    "Continue the same session and repeat the first cited CAD handle."
} as const;

export function createLiveOAuthFailureSafetyInitScript(): string {
  const selectors = JSON.stringify(LIVE_OAUTH_SENSITIVE_SELECTORS);
  return `(() => {
    const selectors = ${selectors};
    const hideSensitiveRegions = () => {
      for (const selector of selectors) {
        for (const element of document.querySelectorAll(selector)) {
          if (element.getAttribute("aria-hidden") !== "true") {
            element.setAttribute("aria-hidden", "true");
          }
        }
      }
    };
    hideSensitiveRegions();
    new MutationObserver(hideSensitiveRegions).observe(document, {
      attributes: true,
      attributeFilter: ["aria-hidden"],
      childList: true,
      subtree: true
    });
  })();`;
}

export interface LiveOAuthInitScriptPage {
  addInitScript(options: { content: string }): Promise<unknown>;
}

export async function installLiveOAuthFailureSafety(
  page: LiveOAuthInitScriptPage
): Promise<void> {
  await page.addInitScript({
    content: createLiveOAuthFailureSafetyInitScript()
  });
}

export async function setSensitiveInputValue(
  input: Locator,
  value: string
): Promise<void> {
  await input.evaluate((element, nextValue) => {
    if (!(element instanceof HTMLInputElement)) {
      throw new Error("Sensitive input target is not an HTML input");
    }
    const valueSetter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value"
    )?.set;
    if (!valueSetter) {
      throw new Error("Sensitive input value setter is unavailable");
    }
    valueSetter.call(element, nextValue);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

export function hasCadHandleEvidence(value: unknown): boolean {
  return typeof value === "string" && /\[handle:[0-9A-F]+\]/i.test(value);
}

export function isProviderSessionId(value: unknown): value is string {
  return isContractProviderSessionId(value);
}

export function isSameProviderSession(
  firstSessionId: unknown,
  resumedSessionId: unknown
): boolean {
  return (
    isProviderSessionId(firstSessionId) &&
    isProviderSessionId(resumedSessionId) &&
    resumedSessionId === firstSessionId
  );
}

export function hasNoConsoleErrors(errorCount: number): boolean {
  return errorCount === 0;
}

export function createSafeLiveOAuthSummary(
  input: LiveOAuthEvidenceInput
): SafeLiveOAuthSummary {
  return {
    provider: input.provider === "codex" ? "Codex" : "Claude",
    authenticated: input.authenticated,
    resumed: input.firstSessionId === input.resumedSessionId
  };
}

export function renderSafeLiveOAuthEvidence(
  summary: SafeLiveOAuthSummary
): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="color-scheme" content="light" />
    <title>Live OAuth verification</title>
    <style>
      :root { font-family: Arial, sans-serif; color: #172033; background: #fff; }
      body { min-height: 100vh; margin: 0; display: grid; place-items: center; }
      main { width: 560px; padding: 48px; border: 1px solid #d9dfeb; border-radius: 20px; }
      h1 { margin: 0 0 28px; font-size: 28px; }
      dl { display: grid; grid-template-columns: 1fr auto; gap: 18px; margin: 0; }
      dt { color: #526078; }
      dd { margin: 0; font-weight: 700; color: #166534; }
      footer { margin-top: 28px; color: #667085; font-size: 13px; }
    </style>
  </head>
  <body>
    <main data-testid="safe-live-oauth-evidence">
      <h1>${summary.provider} live OAuth verification</h1>
      <dl>
        <dt>Authenticated CLI</dt><dd>${summary.authenticated ? "Verified" : "Failed"}</dd>
        <dt>Session resume</dt><dd>${summary.resumed ? "Verified" : "Failed"}</dd>
      </dl>
      <footer>Prompts, responses, and provider session identifiers are intentionally omitted.</footer>
    </main>
  </body>
</html>`;
}
