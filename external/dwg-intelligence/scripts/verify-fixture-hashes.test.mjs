import assert from "node:assert/strict";
import test from "node:test";

import { verifyFixtureManifest } from "./verify-fixture-hashes.mjs";

test("checked-in CAD fixtures match the migration baseline", async () => {
  await assert.doesNotReject(() =>
    verifyFixtureManifest("tests/fixtures/manifest.json")
  );
});
