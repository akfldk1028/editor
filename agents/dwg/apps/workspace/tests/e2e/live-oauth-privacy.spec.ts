import { expect, test } from "@playwright/test";
import { setSensitiveInputValue } from "../support/liveOAuthEvidence.ts";

test("sensitive input setter omits its value from Playwright failure logs", async ({
  page
}) => {
  const sentinel = "DWG_PRIVATE_PROMPT_SENTINEL_7E68F3";
  await page.setContent('<input data-testid="present-input" />');

  const presentInput = page.getByTestId("present-input");
  await setSensitiveInputValue(presentInput, sentinel);
  expect(
    await presentInput.evaluate(
      (element, expected) =>
        (element as HTMLInputElement).value === expected,
      sentinel
    )
  ).toBe(true);

  page.setDefaultTimeout(100);
  let failureMessage = "";
  try {
    await setSensitiveInputValue(page.getByTestId("missing-input"), sentinel);
  } catch (error) {
    failureMessage = error instanceof Error ? error.message : String(error);
  }

  expect(failureMessage.length).toBeGreaterThan(0);
  expect(failureMessage.includes(sentinel)).toBe(false);
});
