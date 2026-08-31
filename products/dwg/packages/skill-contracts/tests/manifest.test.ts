import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_CAD_SKILL_CAPABILITIES,
  MAX_CAD_SKILL_CAPABILITY_CHARS,
  MAX_CAD_SKILL_CODE_CHARS,
  MAX_CAD_SKILL_CODES,
  MAX_CAD_SKILL_ENTITY_TYPE_CHARS,
  MAX_CAD_SKILL_ENTITY_TYPES,
  MAX_CAD_SKILL_ID_CHARS,
  MAX_CAD_SKILL_PURPOSE_CHARS,
  MAX_CAD_SKILL_VERSION_CHARS,
  parseCadSkillManifest,
  type CadSkillManifest
} from "@dwg/skill-contracts";

const validManifest: CadSkillManifest = {
  id: "layer-inspection",
  version: "1.2.3",
  purpose: "Inspect drawing layers using deterministic CAD evidence.",
  capabilityContract: "cad-capabilities/v1",
  permissions: ["read"],
  capabilities: ["cad.get_layers"],
  formats: ["dwg", "dxf"],
  entityTypes: ["LAYER"],
  failureCodes: ["DRAWING_NOT_FOUND"],
  limitationCodes: ["NO_VISUAL_INFERENCE"],
  inputSchema: { type: "object", properties: {} },
  outputSchema: { type: "object", properties: {} }
};

test("parses a valid versioned CAD skill manifest", () => {
  assert.deepEqual(parseCadSkillManifest(validManifest), validManifest);
});

test("rejects a blank manifest purpose", () => {
  assertManifestRejected({ purpose: "   " });
});

test("rejects duplicate manifest permissions", () => {
  assertManifestRejected({ permissions: ["read", "read"] });
});

test("rejects path-bearing manifest IDs", () => {
  assertManifestRejected({ id: "../layer-inspection" });
  assertManifestRejected({ id: "layer/inspection" });
});

test("rejects unknown manifest permissions", () => {
  assertManifestRejected({ permissions: ["admin"] });
});

test("rejects non-semver manifest versions", () => {
  assertManifestRejected({ version: "v1.2" });
});

test("accepts valid semver prerelease and build identifiers", () => {
  const manifest = parseCadSkillManifest({
    ...validManifest,
    version: "1.0.0-rc.1+build.5"
  });

  assert.equal(manifest.version, "1.0.0-rc.1+build.5");
});

test("rejects numeric semver prerelease identifiers with leading zeroes", () => {
  assertManifestRejected({ version: "1.0.0-01" });
  assertManifestRejected({ version: "1.0.0-alpha.01" });
});

test("rejects malformed failure and limitation codes", () => {
  assertManifestRejected({ failureCodes: ["drawing-not-found"] });
  assertManifestRejected({ limitationCodes: ["no visual inference"] });
});

test("requires nonempty unique failure codes", () => {
  assertManifestRejected({ failureCodes: [] });
  assertManifestRejected({
    failureCodes: ["DRAWING_NOT_FOUND", "DRAWING_NOT_FOUND"]
  });
});

test("requires nonempty unique limitation codes", () => {
  assertManifestRejected({ limitationCodes: [] });
  assertManifestRejected({
    limitationCodes: ["NO_VISUAL_INFERENCE", "NO_VISUAL_INFERENCE"]
  });
});

test("rejects unknown manifest properties", () => {
  assertManifestRejected({ unexpected: true });
});

test("bounds every manifest scalar that can identify or describe a skill", () => {
  assertManifestRejected({ id: "a".repeat(MAX_CAD_SKILL_ID_CHARS + 1) });
  assertManifestRejected({
    version: `1.0.0+${"a".repeat(MAX_CAD_SKILL_VERSION_CHARS)}`
  });
  assertManifestRejected({
    purpose: "p".repeat(MAX_CAD_SKILL_PURPOSE_CHARS + 1)
  });
  assertManifestRejected({
    capabilities: ["q." + "a".repeat(MAX_CAD_SKILL_CAPABILITY_CHARS)]
  });
  assertManifestRejected({
    entityTypes: ["E".repeat(MAX_CAD_SKILL_ENTITY_TYPE_CHARS + 1)]
  });
  assertManifestRejected({
    failureCodes: ["E".repeat(MAX_CAD_SKILL_CODE_CHARS + 1)]
  });
});

test("bounds and de-duplicates every manifest string array", () => {
  assertManifestRejected({
    capabilities: Array.from(
      { length: MAX_CAD_SKILL_CAPABILITIES + 1 },
      (_, index) => `query.capability-${index}`
    )
  });
  assertManifestRejected({
    entityTypes: Array.from(
      { length: MAX_CAD_SKILL_ENTITY_TYPES + 1 },
      (_, index) => `ENTITY_${index}`
    )
  });
  assertManifestRejected({
    failureCodes: Array.from(
      { length: MAX_CAD_SKILL_CODES + 1 },
      (_, index) => `FAILURE_${index}`
    )
  });
  assertManifestRejected({
    capabilities: ["query.layers", "query.layers"]
  });
  assertManifestRejected({
    entityTypes: ["LAYER", "LAYER"]
  });
  assertManifestRejected({
    formats: ["dwg", "dwg"]
  });
});

function assertManifestRejected(overrides: Record<string, unknown>) {
  assert.throws(() => parseCadSkillManifest({ ...validManifest, ...overrides }));
}
