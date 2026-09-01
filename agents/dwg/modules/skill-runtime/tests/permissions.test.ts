import assert from "node:assert/strict";
import test from "node:test";

import { requiredSkillPermission } from "../src/permissions.js";

test("save and export capabilities require their exact declared skill permissions", () => {
  assert.equal(requiredSkillPermission("export.report"), "export");
  assert.equal(requiredSkillPermission("export.drawing"), "write-copy");
  assert.equal(requiredSkillPermission("verification.get"), "read");
});
