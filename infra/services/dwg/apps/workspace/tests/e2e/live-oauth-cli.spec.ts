import { expect, test, type Page } from "@playwright/test";
import {
  createSafeLiveOAuthSummary,
  hasCadHandleEvidence,
  hasNoConsoleErrors,
  installLiveOAuthFailureSafety,
  isProviderSessionId,
  isSameProviderSession,
  LIVE_OAUTH_PROMPTS,
  LIVE_OAUTH_SENSITIVE_SELECTORS,
  renderSafeLiveOAuthEvidence,
  setSensitiveInputValue
} from "../support/liveOAuthEvidence.ts";
import { oauthArtifactPath } from "../support/repositoryOutputPaths.ts";

const providerCases = [
  { id: "codex", buttonName: "GPT" },
  { id: "claude", buttonName: "Claude" }
] as const;

const requestedProvider = process.env.DWG_LIVE_PROVIDER ?? "all";
const selectedProviders = providerCases.filter(
  ({ id }) => requestedProvider === "all" || requestedProvider === id
);

if (selectedProviders.length === 0) {
  throw new Error(
    `DWG_LIVE_PROVIDER must be all, codex, or claude; received ${requestedProvider}`
  );
}

test.describe.configure({ mode: "serial", timeout: 300_000 });

for (const provider of selectedProviders) {
  test(`${provider.id} browser gateway resumes the authenticated CLI session`, async ({
    page,
    request
  }) => {
    await installLiveOAuthFailureSafety(page);

    const healthResponse = await request.get("/api/health");
    expect(healthResponse.ok(), "Gateway health check failed").toBe(true);

    const drawingResponse = await request.get("/api/drawing");
    expect(drawingResponse.ok(), "Drawing request failed").toBe(true);

    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(error.message));

    await page.goto("/");
    await expectSensitiveRegionsToBeHidden(page);
    const providerButton = page
      .locator(".provider-switch button")
      .filter({ hasText: provider.buttonName });
    await expect(providerButton).toBeEnabled({ timeout: 30_000 });
    await providerButton.click();

    const firstPrompt = LIVE_OAUTH_PROMPTS.initial;
    const first = await submitAndReadSession(page, firstPrompt);

    await page.reload();
    await expectSensitiveRegionsToBeHidden(page);
    await expect(providerButton).toBeEnabled({ timeout: 30_000 });
    await providerButton.click();

    const resumedPrompt = LIVE_OAUTH_PROMPTS.resume;
    const resumed = await submitAndReadSession(page, resumedPrompt);

    expect(
      isSameProviderSession(first.sessionId, resumed.sessionId),
      "Provider session did not resume"
    ).toBe(true);
    expect(
      hasNoConsoleErrors(consoleErrors.length),
      "Browser emitted console errors"
    ).toBe(true);

    const safeSummary = createSafeLiveOAuthSummary({
      provider: provider.id,
      authenticated: true,
      firstSessionId: first.sessionId,
      resumedSessionId: resumed.sessionId,
      prompt: `${firstPrompt}\n${resumedPrompt}`,
      response: `${first.response}\n${resumed.response}`
    });
    await page.setContent(renderSafeLiveOAuthEvidence(safeSummary));
    await expect(page.getByTestId("safe-live-oauth-evidence")).toContainText(
      "Session resume"
    );
    await expect(page.getByTestId("safe-live-oauth-evidence")).toContainText(
      "Verified"
    );

    await page.screenshot({
      path: oauthArtifactPath(provider.id),
      fullPage: true
    });
  });
}

async function submitAndReadSession(page: Page, message: string) {
  const composer = page.locator(".composer input").first();
  await setSensitiveInputValue(composer, message);
  await page.locator(".composer").evaluate((form: HTMLFormElement) => {
    form.requestSubmit();
  });

  const response = page.locator('[data-testid="live-response"]');
  await expect.poll(
    async () => hasCadHandleEvidence(await response.textContent()),
    {
      message: "Provider response has no CAD handle evidence",
      timeout: 240_000
    }
  ).toBe(true);
  const sessionId = await response.locator("code").textContent();
  expect(
    isProviderSessionId(sessionId),
    "Provider returned an invalid session identifier"
  ).toBe(true);
  return {
    sessionId: sessionId!,
    response: (await response.textContent()) ?? ""
  };
}

async function expectSensitiveRegionsToBeHidden(page: Page) {
  const selector = LIVE_OAUTH_SENSITIVE_SELECTORS.join(", ");
  await expect.poll(
    () => page.locator(selector).evaluateAll(
      (elements, expectedCount) =>
        elements.length === expectedCount &&
        elements.every(
          (element) => element.getAttribute("aria-hidden") === "true"
        ),
      LIVE_OAUTH_SENSITIVE_SELECTORS.length
    ),
    {
      message: "Sensitive live OAuth regions were not hidden from ARIA",
      timeout: 30_000
    }
  ).toBe(true);
}
