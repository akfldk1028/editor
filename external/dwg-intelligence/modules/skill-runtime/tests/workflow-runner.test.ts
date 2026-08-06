import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_CAD_SKILL_ID_CHARS,
  parseCadSkillWorkflow,
  type CadSkillWorkflow,
  type CadSkillManifest
} from "@dwg/skill-contracts";
import type { CadCapabilityName, CadCapabilityRuntime } from "@dwg/cad-capabilities";

import {
  MAX_CAD_SKILL_RUN_RESULT_BYTES,
  runCadSkillWorkflow,
  type InstalledCadSkill
} from "../src/index.js";

const readManifest: CadSkillManifest = {
  id: "workflow-test",
  version: "1.0.0",
  purpose: "Exercise declarative workflow execution.",
  capabilityContract: "cad-capabilities/v1",
  permissions: ["read"],
  capabilities: ["document.open", "query.layers"],
  formats: ["dwg", "dxf"],
  entityTypes: ["LAYER"],
  failureCodes: ["CAPABILITY_FAILED"],
  limitationCodes: ["NO_VISUAL_INFERENCE"],
  inputSchema: {
    type: "object",
    required: ["path"],
    properties: { path: { type: "string" } },
    additionalProperties: false
  },
  outputSchema: {
    type: "object",
    required: ["layers"],
    properties: { layers: { type: "array", items: { type: "string" } } },
    additionalProperties: false
  }
};

test("runs declared read capabilities in workflow order with safe input and step bindings", async () => {
  const calls: Array<{ name: CadCapabilityName; input: unknown }> = [];
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([
      { id: "open", capability: "document.open", input: { path: "$input.path" } },
      { id: "layers", capability: "query.layers", input: { drawingId: "$steps.open.output.drawingId" } }
    ]),
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    capabilities: runtime(async (name, input) => {
      calls.push({ name, input });
      if (name === "document.open") return { drawingId: "drawing-1" };
      return { layers: ["A-WALL"] };
    })
  });

  assert.deepEqual(calls, [
    { name: "document.open", input: { path: "drawing.dwg" } },
    { name: "query.layers", input: { drawingId: "drawing-1" } }
  ]);
  assert.deepEqual(result, {
    skillId: "workflow-test",
    status: "passed",
    steps: [
      { id: "open", status: "passed", output: { drawingId: "drawing-1" } },
      { id: "layers", status: "passed", output: { layers: ["A-WALL"] } }
    ],
    warnings: []
  });
});

test("rejects malformed workflow values, unsafe IDs, duplicate IDs, and more than thirty-two steps", () => {
  assert.throws(() => parseCadSkillWorkflow({
    schemaVersion: "cad-skill-workflow/v1",
    steps: [{ id: "__proto__", capability: "query.layers", input: {} }]
  }), /WORKFLOW_INVALID/);
  assert.throws(() => parseCadSkillWorkflow({
    schemaVersion: "cad-skill-workflow/v1",
    steps: [
      { id: "same", capability: "query.layers", input: {} },
      { id: "same", capability: "query.layers", input: {} }
    ]
  }), /WORKFLOW_INVALID/);
  assert.throws(() => parseCadSkillWorkflow({
    schemaVersion: "cad-skill-workflow/v1",
    steps: Array.from({ length: 33 }, (_, index) => ({
      id: `step-${index}`,
      capability: "query.layers",
      input: {}
    }))
  }), /WORKFLOW_INVALID/);

  const circular: Record<string, unknown> = {};
  circular.self = circular;
  assert.throws(() => parseCadSkillWorkflow({
    schemaVersion: "cad-skill-workflow/v1",
    steps: [{ id: "one", capability: "query.layers", input: circular }]
  }), /WORKFLOW_VALUE_NOT_JSON/);
  assert.throws(() => parseCadSkillWorkflow({
    schemaVersion: "cad-skill-workflow/v1",
    steps: [{ id: "one", capability: "query.layers", input: { count: Number.NaN } }]
  }), /WORKFLOW_VALUE_NOT_JSON/);
});

test("rejects forward, unknown, and prototype binding paths before capability execution", async () => {
  const cases = [
    "$steps.later.output",
    "$steps.missing.output.value",
    "$input.__proto__",
    "$steps.open.output.constructor"
  ];

  for (const binding of cases) {
    let calls = 0;
    await assert.rejects(() => runCadSkillWorkflow({
      skill: installedSkill(),
      workflow: workflow([
        { id: "open", capability: "document.open", input: { path: binding } },
        { id: "later", capability: "query.layers", input: {} }
      ]),
      input: { path: "drawing.dwg" },
      grantedPermissions: ["read"],
      capabilities: runtime(async () => {
        calls += 1;
        return { drawingId: "drawing-1" };
      })
    }), /WORKFLOW_BINDING_INVALID/);
    assert.equal(calls, 0);
  }
});

test("fails with a bounded error when a capability is missing from the manifest", async () => {
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([{ id: "undeclared", capability: "query.text", input: {} }]),
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    capabilities: runtime(async () => {
      throw new Error("must not run");
    })
  });

  assert.deepEqual(result, failed("undeclared", "CAPABILITY_NOT_DECLARED"));
});

test("fails when the skill is incompatible or permissions are not both declared and granted", async () => {
  const incompatible = await runCadSkillWorkflow({
    skill: installedSkill({ compatible: false, incompatibility: "CAPABILITY_CONTRACT_MISMATCH" }),
    workflow: workflow([{ id: "layers", capability: "query.layers", input: {} }]),
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    capabilities: runtime(async () => ({ layers: [] }))
  });
  assert.deepEqual(incompatible, failed("layers", "SKILL_INCOMPATIBLE"));

  const readDenied = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([{ id: "layers", capability: "query.layers", input: {} }]),
    input: { path: "drawing.dwg" },
    grantedPermissions: [],
    capabilities: runtime(async () => ({ layers: [] }))
  });
  assert.deepEqual(readDenied, failed("layers", "PERMISSION_DENIED"));

  const proposedEditDenied = await runCadSkillWorkflow({
    skill: installedSkill({
      manifest: { ...readManifest, permissions: ["propose-edit"], capabilities: ["edit.preview"] }
    }),
    workflow: workflow([{ id: "preview", capability: "edit.preview", input: {} }]),
    input: { path: "drawing.dwg" },
    grantedPermissions: [],
    capabilities: runtime(async () => ({ layers: [] }))
  });
  assert.deepEqual(proposedEditDenied, failed("preview", "PERMISSION_DENIED"));
});

test("fails safely when a capability output violates the skill output schema", async () => {
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([{ id: "layers", capability: "query.layers", input: {} }]),
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    capabilities: runtime(async () => ({ layers: [3] }))
  });

  assert.deepEqual(result, failed("layers", "OUTPUT_SCHEMA_INVALID"));
});

test("bounds every encoded result to one MiB without exposing capability data", async () => {
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([{ id: "layers", capability: "query.layers", input: {} }]),
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    capabilities: runtime(async () => ({ layers: ["sensitive-" + "x".repeat(1024 * 1024)] }))
  });

  assert.deepEqual(result, {
    skillId: "bounded-skill-result",
    status: "failed",
    steps: [
      { id: "result", status: "failed", output: { error: { code: "RESULT_TOO_LARGE" } } }
    ],
    warnings: []
  });
  assertResultBounded(result);
});

test("bounds ordinary and fallback failures even when a caller supplies an oversized skill ID", async () => {
  const boundaryId = "a".repeat(MAX_CAD_SKILL_ID_CHARS);
  const ordinary = await runCadSkillWorkflow({
    skill: installedSkill({ manifest: { ...readManifest, id: boundaryId } }),
    workflow: workflow([{ id: "layers", capability: "query.layers", input: {} }]),
    input: { path: "drawing.dwg" },
    grantedPermissions: [],
    capabilities: runtime(async () => ({ layers: [] }))
  });
  assert.equal(ordinary.skillId, boundaryId);
  assertResultBounded(ordinary);

  const oversized = await runCadSkillWorkflow({
    skill: installedSkill({
      manifest: {
        ...readManifest,
        id: "a".repeat(MAX_CAD_SKILL_RUN_RESULT_BYTES + 128)
      }
    }),
    workflow: workflow([{ id: "layers", capability: "query.layers", input: {} }]),
    input: null,
    grantedPermissions: ["read"],
    capabilities: runtime(async () => ({ layers: [] }))
  });
  assert.deepEqual(oversized, {
    skillId: "bounded-skill-result",
    status: "failed",
    steps: [],
    warnings: ["SKILL_MANIFEST_INVALID"]
  });
  assertResultBounded(oversized);
});

test("rejects non-data arrays in workflows", () => {
  const alteredPrototype: unknown[] = [];
  Object.setPrototypeOf(alteredPrototype, {});

  const ownPrototypeKey: unknown[] = [];
  Object.defineProperty(ownPrototypeKey, "__proto__", {
    value: "polluted",
    enumerable: true
  });

  const ownConstructorKey: unknown[] = [];
  Object.defineProperty(ownConstructorKey, "constructor", {
    value: "polluted",
    enumerable: true
  });

  const ownPrototypeName: unknown[] = [];
  Object.defineProperty(ownPrototypeName, "prototype", {
    value: "polluted",
    enumerable: true
  });

  const extraProperty: unknown[] = [];
  Object.defineProperty(extraProperty, "extra", {
    value: "not-an-index",
    enumerable: true
  });

  const symbolProperty: unknown[] = [];
  Object.defineProperty(symbolProperty, Symbol("extra"), {
    value: "not-json",
    enumerable: true
  });

  const sparse = new Array(1);
  const accessor: unknown[] = [];
  let getterCalls = 0;
  Object.defineProperty(accessor, "0", {
    get() {
      getterCalls += 1;
      return "executed";
    },
    enumerable: true,
    configurable: true
  });
  accessor.length = 1;

  for (const value of [
    alteredPrototype,
    ownPrototypeKey,
    ownConstructorKey,
    ownPrototypeName,
    extraProperty,
    symbolProperty,
    sparse,
    accessor
  ]) {
    assert.throws(() => parseCadSkillWorkflow({
      schemaVersion: "cad-skill-workflow/v1",
      steps: [{ id: "one", capability: "query.layers", input: { value } }]
    }), /WORKFLOW_VALUE_NOT_JSON/);
  }
  assert.equal(getterCalls, 0);
});

test("rejects object accessors and unexpected own metadata without reading them", () => {
  let getterCalls = 0;
  const accessor: Record<string, unknown> = {};
  Object.defineProperty(accessor, "secret", {
    get() {
      getterCalls += 1;
      return "executed";
    },
    enumerable: true
  });

  const hidden: Record<string, unknown> = {};
  Object.defineProperty(hidden, "secret", {
    value: "hidden",
    enumerable: false
  });

  const symbolKeyed: Record<string | symbol, unknown> = {
    [Symbol("secret")]: "hidden"
  };

  for (const value of [accessor, hidden, symbolKeyed]) {
    assert.throws(() => parseCadSkillWorkflow({
      schemaVersion: "cad-skill-workflow/v1",
      steps: [{ id: "one", capability: "query.layers", input: { value } }]
    }), /WORKFLOW_VALUE_NOT_JSON/);
  }
  assert.equal(getterCalls, 0);
});

test("returns bounded failures for accessor input and capability output without invoking getters", async () => {
  let inputGetterCalls = 0;
  const input: Record<string, unknown> = {};
  Object.defineProperty(input, "path", {
    get() {
      inputGetterCalls += 1;
      return "drawing.dwg";
    },
    enumerable: true
  });
  const invalidInput = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([{ id: "layers", capability: "query.layers", input: {} }]),
    input,
    grantedPermissions: ["read"],
    capabilities: runtime(async () => ({ layers: [] }))
  });
  assert.deepEqual(invalidInput, {
    skillId: "workflow-test",
    status: "failed",
    steps: [],
    warnings: ["INPUT_VALUE_INVALID"]
  });
  assert.equal(inputGetterCalls, 0);
  assertResultBounded(invalidInput);

  let outputGetterCalls = 0;
  const output: Record<string, unknown> = {};
  Object.defineProperty(output, "layers", {
    get() {
      outputGetterCalls += 1;
      return [];
    },
    enumerable: true
  });
  const invalidOutput = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([{ id: "layers", capability: "query.layers", input: {} }]),
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    capabilities: runtime(async () => output)
  });
  assert.deepEqual(invalidOutput, failed("layers", "CAPABILITY_OUTPUT_INVALID"));
  assert.equal(outputGetterCalls, 0);
  assertResultBounded(invalidOutput);
});

test("uses the identical AbortSignal for every capability and returns cancelled without leaking errors", async () => {
  const controller = new AbortController();
  const signals: AbortSignal[] = [];
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([
      { id: "open", capability: "document.open", input: { path: "$input.path" } },
      { id: "layers", capability: "query.layers", input: {} }
    ]),
    input: { path: "drawing.dwg" },
    documentId: "drawing-1",
    grantedPermissions: ["read"],
    signal: controller.signal,
    capabilities: runtime(async (name, _input, signal) => {
      signals.push(signal!);
      if (name === "document.open") {
        controller.abort();
        return { drawingId: "drawing-1" };
      }
      throw new Error("must not run");
    })
  });

  assert.deepEqual(signals, [controller.signal]);
  assert.deepEqual(result, {
    skillId: "workflow-test",
    status: "cancelled",
    steps: [
      { id: "open", status: "cancelled", output: { error: { code: "CANCELLED" } } }
    ],
    warnings: []
  });
  assertResultBounded(result);
});

test("injects the authoritative document ID for workflow bindings", async () => {
  const calls: Array<{ name: CadCapabilityName; input: unknown }> = [];
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([
      { id: "open", capability: "document.open", input: { path: "$input.path" } },
      { id: "layers", capability: "query.layers", input: { drawingId: "$input.documentId" } }
    ]),
    documentId: "drawing-1",
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    capabilities: runtime(async (name, input) => {
      calls.push({ name, input });
      return name === "document.open" ? { drawingId: "drawing-1" } : { layers: ["A-WALL"] };
    })
  });

  assert.equal(result.status, "passed");
  assert.deepEqual(calls[1], { name: "query.layers", input: { drawingId: "drawing-1" } });
});

test("rejects conflicting input document IDs before capability execution", async () => {
  let calls = 0;
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([{ id: "open", capability: "document.open", input: { path: "$input.path" } }]),
    documentId: "drawing-1",
    input: { path: "drawing.dwg", documentId: "drawing-other" },
    grantedPermissions: ["read"],
    capabilities: runtime(async () => { calls += 1; return { drawingId: "drawing-1" }; })
  });

  assert.equal(calls, 0);
  assert.deepEqual(result, { skillId: "workflow-test", status: "failed", steps: [], warnings: ["DOCUMENT_SCOPE_MISMATCH"] });
});

test("accepts a matching transport document ID even when the skill schema does not declare it", async () => {
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([
      { id: "open", capability: "document.open", input: { path: "$input.path" } },
      { id: "layers", capability: "query.layers", input: { drawingId: "$input.documentId" } }
    ]),
    documentId: "drawing-1",
    input: { path: "drawing.dwg", documentId: "drawing-1" },
    grantedPermissions: ["read"],
    capabilities: runtime(async (name) => name === "document.open" ? { drawingId: "drawing-1" } : { layers: [] })
  });

  assert.equal(result.status, "passed");
});

test("rejects a mismatched document.open result before subsequent steps", async () => {
  const calls: CadCapabilityName[] = [];
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([
      { id: "open", capability: "document.open", input: { path: "$input.path" } },
      { id: "layers", capability: "query.layers", input: { drawingId: "$steps.open.output.drawingId" } }
    ]),
    documentId: "drawing-1",
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    capabilities: runtime(async (name) => {
      calls.push(name);
      return name === "document.open" ? { drawingId: "drawing-other" } : { layers: [] };
    })
  });

  assert.deepEqual(calls, ["document.open"]);
  assert.deepEqual(result, failed("open", "CAPABILITY_EXECUTION_FAILED"));
});

test("blocks access to another cached drawing and cross-document edit proposals", async () => {
  for (const testCase of [
    {
      skill: installedSkill({ manifest: { ...readManifest, capabilities: ["query.layers"] } }),
      step: { id: "layers", capability: "query.layers", input: { drawingId: "drawing-other" } },
      permissions: ["read"] as const
    },
    {
      skill: installedSkill({ manifest: { ...readManifest, permissions: ["propose-edit"], capabilities: ["edit.preview"] } }),
      step: { id: "preview", capability: "edit.preview", input: { batch: { documentId: "drawing-other" } } },
      permissions: ["propose-edit"] as const
    }
  ]) {
    let calls = 0;
    const result = await runCadSkillWorkflow({
      skill: testCase.skill,
      workflow: workflow([testCase.step]),
      documentId: "drawing-1",
      input: { path: "drawing.dwg" },
      grantedPermissions: [...testCase.permissions],
      capabilities: runtime(async () => { calls += 1; return { layers: [] }; })
    });
    assert.equal(calls, 0);
    assert.equal(result.status, "failed");
    assert.equal((result.steps[0]?.output as { error: { code: string } }).error.code, "CAPABILITY_EXECUTION_FAILED");
  }
});

test("allows an explicitly related comparison document", async () => {
  const calls: unknown[] = [];
  const result = await runCadSkillWorkflow({
    skill: installedSkill({
      manifest: { ...readManifest, capabilities: ["query.compare"] }
    }),
    workflow: workflow([{
      id: "compare",
      capability: "query.compare",
      input: {
        beforeDrawingId: "drawing-before",
        afterDrawingId: "drawing-after"
      }
    }]),
    documentId: "drawing-before",
    relatedDocumentIds: ["drawing-after"],
    input: {
      path: "drawing.dwg"
    },
    grantedPermissions: ["read"],
    capabilities: runtime(async (_name, input) => {
      calls.push(input);
      return { layers: [] };
    })
  });

  assert.equal(result.status, "passed");
  assert.deepEqual(calls, [{
    beforeDrawingId: "drawing-before",
    afterDrawingId: "drawing-after"
  }]);
});

test("denies comparison documents missing from or outside the explicit related scope", async () => {
  for (const testCase of [
    { relatedDocumentIds: [] as string[], afterDrawingId: "drawing-after" },
    { relatedDocumentIds: ["drawing-after"], afterDrawingId: "drawing-third" }
  ]) {
    let calls = 0;
    const result = await runCadSkillWorkflow({
      skill: installedSkill({
        manifest: { ...readManifest, capabilities: ["query.compare"] }
      }),
      workflow: workflow([{
        id: "compare",
        capability: "query.compare",
        input: {
          beforeDrawingId: "drawing-before",
          afterDrawingId: testCase.afterDrawingId
        }
      }]),
      documentId: "drawing-before",
      relatedDocumentIds: testCase.relatedDocumentIds,
      input: {
        path: "drawing.dwg"
      },
      grantedPermissions: ["read"],
      capabilities: runtime(async () => { calls += 1; return { layers: [] }; })
    });
    assert.equal(calls, 0);
    assert.deepEqual(result, failed("compare", "CAPABILITY_EXECUTION_FAILED"));
  }
});

test("keeps an overflowing cancellation fallback bounded and cancellation-only", async () => {
  const controller = new AbortController();
  const result = await runCadSkillWorkflow({
    skill: installedSkill(),
    workflow: workflow([
      { id: "open", capability: "document.open", input: {} },
      { id: "layers", capability: "query.layers", input: {} }
    ]),
    input: { path: "drawing.dwg" },
    grantedPermissions: ["read"],
    signal: controller.signal,
    capabilities: runtime(async (name) => {
      if (name === "document.open") {
        return {
          padding: "x".repeat(MAX_CAD_SKILL_RUN_RESULT_BYTES - 180)
        };
      }
      controller.abort();
      return { layers: [] };
    })
  });

  assert.deepEqual(result, {
    skillId: "bounded-skill-result",
    status: "cancelled",
    steps: [
      { id: "result", status: "cancelled", output: { error: { code: "CANCELLED" } } }
    ],
    warnings: []
  });
  assertResultBounded(result);
});

function workflow(steps: CadSkillWorkflow["steps"]): CadSkillWorkflow {
  return { schemaVersion: "cad-skill-workflow/v1", steps };
}

function installedSkill(overrides: Partial<InstalledCadSkill> = {}): InstalledCadSkill {
  return {
    root: "C:\\skills\\workflow-test",
    manifest: readManifest,
    instructions: "Use only deterministic evidence.",
    compatible: true,
    incompatibility: null,
    ...overrides
  };
}

function runtime(
  execute: (name: CadCapabilityName, input: unknown, signal?: AbortSignal) => Promise<unknown>
): CadCapabilityRuntime {
  return { execute };
}

function failed(id: string, code: string) {
  return {
    skillId: "workflow-test",
    status: "failed",
    steps: [{ id, status: "failed", output: { error: { code } } }],
    warnings: []
  };
}

function assertResultBounded(result: unknown) {
  assert.ok(
    Buffer.byteLength(JSON.stringify(result), "utf8") <=
      MAX_CAD_SKILL_RUN_RESULT_BYTES
  );
}
