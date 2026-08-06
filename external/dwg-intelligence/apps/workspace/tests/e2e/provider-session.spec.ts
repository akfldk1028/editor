import { expect, test } from "@playwright/test";

const sessionId = "98d84d53-7861-4c73-a789-d6c8f5490966";

test("continues the selected OAuth provider session after reload", async ({ page }) => {
  const chatRequests: Array<Record<string, unknown>> = [];

  await page.route("**/api/providers", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        providers: [
          {
            id: "codex",
            label: "GPT · Codex",
            installed: true,
            authenticated: true,
            authMethod: "chatgpt",
            detail: "ChatGPT OAuth"
          },
          {
            id: "claude",
            label: "Claude",
            installed: true,
            authenticated: true,
            authMethod: "claude.ai",
            detail: "Claude OAuth"
          }
        ]
      })
    })
  );
  await page.route("**/api/chat", async (route) => {
    chatRequests.push(route.request().postDataJSON());
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "claude",
        text: "grounded response",
        sessionId
      })
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Claude", exact: true }).click();
  await page.locator(".composer input:not([type=file])").fill("first question");
  await page.locator(".composer .send-button").click();
  await expect(page.getByTestId("live-response")).toContainText("grounded response");

  await page.reload();
  await expect(page.getByRole("button", { name: "Claude", exact: true })).toHaveClass(/active/);
  await page.locator(".composer input:not([type=file])").fill("follow-up");
  await page.locator(".composer .send-button").click();

  await expect.poll(() => chatRequests.length).toBe(2);
  expect(chatRequests[0]).toMatchObject({
    provider: "claude",
    message: "first question"
  });
  expect(chatRequests[0]).not.toHaveProperty("sessionId");
  expect(chatRequests[1]).toMatchObject({
    provider: "claude",
    message: "follow-up",
    sessionId
  });

  await page.getByRole("main", { name: "대화" })
    .getByRole("button", { name: "새 대화" })
    .click();
  await page.locator(".composer input:not([type=file])").fill("fresh thread");
  await page.locator(".composer .send-button").click();
  await expect.poll(() => chatRequests.length).toBe(3);
  expect(chatRequests[2]).toMatchObject({
    provider: "claude",
    message: "fresh thread"
  });
  expect(chatRequests[2]).not.toHaveProperty("sessionId");
});
