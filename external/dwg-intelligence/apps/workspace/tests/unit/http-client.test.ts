import assert from "node:assert/strict";
import test from "node:test";

import { getJson } from "../../src/shared/api/httpClient";

interface ValidPayload {
  value: string;
}

function isValidPayload(value: unknown): value is ValidPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Record<string, unknown>).value === "expected"
  );
}

test("rejects a successful HTTP response that violates its runtime contract", async () => {
  const url = `data:application/json,${encodeURIComponent(JSON.stringify({
    value: "wrong"
  }))}`;

  await assert.rejects(
    getJson<ValidPayload>(url, undefined, isValidPayload),
    /Response contract validation failed/
  );
});

test("reports a stable error when an HTTP response is not JSON", async () => {
  await assert.rejects(
    getJson<ValidPayload>(
      "data:text/plain,not-json",
      undefined,
      isValidPayload
    ),
    /Invalid JSON response/
  );
});
