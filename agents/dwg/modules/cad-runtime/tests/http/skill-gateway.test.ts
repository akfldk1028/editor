import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

import { createCadApplication } from "../../src/application/createCadApplication.js";
import { createCadGatewayServer } from "../../src/http/gateway.js";
import {
  parseSkillRunRequest,
  parseSkillRunResponse,
  type JsonValue
} from "@dwg/contracts";

const index = {
  schemaVersion: "cad-index/v0.1" as const,
  drawingId: "dwg:skill-test",
  source: { kind: "dxf" as const, displayName: "skill-test.dxf", parser: "test" },
  summary: { entityCount: 0, layerCount: 0, unsupportedCount: 0, modelSpaceCount: 0, paperSpaceCount: 0 },
  layers: [], entities: [], unsupported: []
};

test("assembled gateway lists visible skills and runs a selected compatible workflow", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf"
  });
  const baseUrl = await listen(server, context);

  const listed = await fetch(`${baseUrl}/api/skills`);
  assert.equal(listed.status, 200);
  const list = await listed.json() as { skills: Array<{ id: string; compatible: boolean; recentStatus: string }> };
  assert.deepEqual(list.skills.map((skill) => skill.id), ["compare-drawings", "export-drawing", "export-report", "extract-schedule", "inspect-drawing"]);
  assert.ok(list.skills.every((skill) => skill.compatible && skill.recentStatus === "idle"));

  const run = await post(baseUrl, {
    skillId: "inspect-drawing",
    version: "1.0.0",
    documentId: "86be7bbdf2ca52e4",
    input: { path: "tests/fixtures/dxf/minimal-architectural.dxf", layer: "A-WALL" }
  });
  assert.equal(run.status, 200);
  const result = parseSkillRunResponse(await run.json());
  assert.equal(result.status, "passed");
  assert.equal(result.skillId, "inspect-drawing");
  assert.deepEqual(Object.keys(result).sort(), ["changeCount", "previewId", "result", "runId", "skillId", "status", "version", "warningCodes"]);
  assert.equal(Array.isArray((result.result as { matches?: unknown }).matches), true);
});

test("assembled gateway rejects a document scope mismatch without opening another drawing", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf"
  });
  const baseUrl = await listen(server, context);
  const run = await post(baseUrl, {
    skillId: "inspect-drawing", version: "1.0.0", documentId: "drawing-other",
    input: { path: "tests/fixtures/dxf/minimal-architectural.dxf", layer: "A-WALL" }
  });
  assert.equal(run.status, 200);
  const result = parseSkillRunResponse(await run.json());
  assert.equal(result.status, "failed");
  assert.deepEqual(result.warningCodes, ["CAPABILITY_EXECUTION_FAILED"]);
  assert.equal(result.result, null);
});

test("assembled gateway allows only explicitly scoped two-document comparisons", async (context) => {
  const before = { ...index, drawingId: "drawing-before" };
  const after = { ...index, drawingId: "drawing-after" };
  const application = await createCadApplication({
    loadInitialIndex: async () => before,
    read: {
      open: async () => before,
      get: (drawingId) => {
        if (drawingId === before.drawingId) return before;
        if (drawingId === after.drawingId) return after;
        return null;
      }
    }
  });
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    application
  });
  const baseUrl = await listen(server, context);
  const baseRequest = {
    skillId: "compare-drawings",
    version: "1.0.0",
    documentId: before.drawingId,
    input: {
      beforeDrawingId: before.drawingId,
      afterDrawingId: after.drawingId
    }
  };

  const allowed = await post(baseUrl, {
    ...baseRequest,
    relatedDocumentIds: [after.drawingId]
  });
  assert.equal(allowed.status, 200);
  assert.equal(parseSkillRunResponse(await allowed.json()).status, "passed");

  const missingRelated = await post(baseUrl, baseRequest);
  assert.equal(missingRelated.status, 200);
  assert.deepEqual(parseSkillRunResponse(await missingRelated.json()).warningCodes, ["CAPABILITY_EXECUTION_FAILED"]);

  const unrelated = await post(baseUrl, {
    ...baseRequest,
    relatedDocumentIds: [after.drawingId],
    input: {
      beforeDrawingId: before.drawingId,
      afterDrawingId: "drawing-third"
    }
  });
  assert.equal(unrelated.status, 200);
  assert.deepEqual(parseSkillRunResponse(await unrelated.json()).warningCodes, ["CAPABILITY_EXECUTION_FAILED"]);
});

test("assembled gateway keeps incompatible skills visible but rejects execution", async (context) => {
  const server = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    drawingPath: "tests/fixtures/dxf/minimal-architectural.dxf",
    capabilityVersion: "cad-capabilities/v0"
  });
  const baseUrl = await listen(server, context);
  const listed = await fetch(`${baseUrl}/api/skills`);
  const list = await listed.json() as { skills: Array<{ id: string; compatible: boolean }> };
  assert.equal(list.skills.find((skill) => skill.id === "inspect-drawing")?.compatible, false);
  const run = await post(baseUrl, {
    skillId: "inspect-drawing", version: "1.0.0", documentId: "dwg:skill-test",
    input: { path: "tests/fixtures/dxf/minimal-architectural.dxf", layer: "A-WALL" }
  });
  assert.equal(run.status, 409);
  assert.deepEqual(await run.json(), { error: { code: "SKILL_INCOMPATIBLE", message: "Requested skill is not executable." } });
});

test("skill contract parsers reject unknown fields, non-data values, invalid semver, excessive depth, bytes, counts, and scalars", () => {
  assert.throws(() => parseSkillRunRequest({ skillId: "inspect-drawing", version: "bad", documentId: "dwg:test", input: {} }), /SKILL_RUN_REQUEST_INVALID/);
  assert.throws(() => parseSkillRunRequest({ skillId: "inspect-drawing", version: "1.0.0", documentId: "dwg:test", input: {}, extra: true }), /SKILL_RUN_REQUEST_INVALID/);
  assert.throws(() => parseSkillRunRequest({ skillId: "inspect-drawing", version: "1.0.0", documentId: "dwg:test", input: nested(33) }), /SKILL_RUN_REQUEST_INVALID/);
  assert.throws(() => parseSkillRunRequest({ skillId: "inspect-drawing", version: "1.0.0", documentId: "dwg:test", input: "x".repeat(65 * 1024) }), /SKILL_RUN_REQUEST_INVALID/);
  assert.throws(() => parseSkillRunRequest({ skillId: "inspect-drawing", version: "1.0.0", documentId: "dwg:test", input: Array.from({ length: 257 }, () => null) }), /SKILL_RUN_REQUEST_INVALID/);
  const accessor: Record<string, unknown> = {};
  let accessed = false;
  Object.defineProperty(accessor, "value", { enumerable: true, get() { accessed = true; return "no"; } });
  assert.throws(() => parseSkillRunRequest({ skillId: "inspect-drawing", version: "1.0.0", documentId: "dwg:test", input: accessor }), /SKILL_RUN_REQUEST_INVALID/);
  assert.equal(accessed, false);
  assert.throws(() => parseSkillRunResponse({ runId: "11111111-1111-4111-8111-111111111111", skillId: "inspect-drawing", version: "1.0.0", documentId: "dwg:test", status: "passed", previewId: null, changeCount: 0, warningCodes: [], result: Number.NaN }), /SKILL_RUN_RESPONSE_INVALID/);
  assert.deepEqual(parseSkillRunRequest({
    skillId: "compare-drawings",
    version: "1.0.0",
    documentId: "drawing-before",
    relatedDocumentIds: ["drawing-after"],
    input: {}
  }).relatedDocumentIds, ["drawing-after"]);
  for (const relatedDocumentIds of [
    ["drawing-after", "drawing-after"],
    ["drawing-before"],
    ["one", "two", "three", "four"]
  ]) {
    assert.throws(() => parseSkillRunRequest({
      skillId: "compare-drawings",
      version: "1.0.0",
      documentId: "drawing-before",
      relatedDocumentIds,
      input: {}
    }), /SKILL_RUN_REQUEST_INVALID/);
  }
});

test("assembled gateway redacts malformed oversized and invalid-output skill executions", async (context) => {
  const skills = await temporarySkills(context, "invalid-output", {
    inputSchema: { type: "object", required: ["path"], properties: { path: { type: "string" } }, additionalProperties: false },
    outputSchema: { type: "object", required: ["impossible"], properties: { impossible: { type: "string" } }, additionalProperties: false }
  });
  const application = await createCadApplication({
    loadInitialIndex: async () => index,
    read: { open: async () => index, get: () => index }
  });
  const server = await createCadGatewayServer({ workspaceRoot: process.cwd(), skillRoot: skills, application });
  const baseUrl = await listen(server, context);

  const malformed = await post(baseUrl, { skillId: "invalid-output", version: "wrong", documentId: "dwg:test", input: {} });
  assert.equal(malformed.status, 400);
  assert.deepEqual(await malformed.json(), { error: { code: "SKILL_REQUEST_INVALID", message: "Invalid skill request." } });

  const oversized = await fetch(`${baseUrl}/api/skills/run`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ skillId: "invalid-output", version: "1.0.0", documentId: "dwg:test", input: "x".repeat(65 * 1024) }) });
  assert.equal(oversized.status, 413);
  assert.deepEqual(await oversized.json(), { error: { code: "SKILL_REQUEST_TOO_LARGE", message: "Skill request exceeds the limit." } });

  const invalid = await post(baseUrl, { skillId: "invalid-output", version: "1.0.0", documentId: "dwg:skill-test", input: { path: "test.dxf" } });
  assert.equal(invalid.status, 200);
  const invalidResult = await invalid.json() as { runId: string; [key: string]: unknown };
  assert.deepEqual(invalidResult, {
    runId: invalidResult.runId,
    skillId: "invalid-output", version: "1.0.0", status: "failed", previewId: null, changeCount: 0, warningCodes: ["OUTPUT_SCHEMA_INVALID"], result: null
  });
});

test("assembled gateway keeps the latest concurrent status and clears cancelled runs", async (context) => {
  const skills = await temporarySkills(context, "slow-open", {
    inputSchema: { type: "object", required: ["path"], properties: { path: { type: "string" } }, additionalProperties: false },
    outputSchema: { type: "object", required: ["drawingId"], properties: { drawingId: { type: "string" } } }
  });
  const pending: Array<{ resolve(): void; signal: AbortSignal | undefined }> = [];
  const application = await createCadApplication({
    loadInitialIndex: async () => index,
    read: {
      open: async (_path, signal) => new Promise((resolve) => {
        const complete = () => resolve(index);
        pending.push({ resolve: complete, signal });
      }),
      get: () => index
    }
  });
  const server = await createCadGatewayServer({ workspaceRoot: process.cwd(), skillRoot: skills, application });
  const baseUrl = await listen(server, context);
  const body = { skillId: "slow-open", version: "1.0.0", documentId: "dwg:skill-test", input: { path: "test.dxf" } };

  const first = post(baseUrl, body);
  await waitFor(() => pending.length === 1);
  const second = post(baseUrl, body);
  await waitFor(() => pending.length === 2);
  pending[0]!.resolve();
  await first;
  assert.equal((await (await fetch(`${baseUrl}/api/skills`)).json() as { skills: Array<{ recentStatus: string }> }).skills[0]!.recentStatus, "running");
  pending[1]!.resolve();
  assert.equal((await second).status, 200);
  assert.equal((await (await fetch(`${baseUrl}/api/skills`)).json() as { skills: Array<{ recentStatus: string }> }).skills[0]!.recentStatus, "passed");

  const cancellationPending: Array<{ resolve(): void; signal: AbortSignal | undefined }> = [];
  const cancellationApplication = await createCadApplication({
    loadInitialIndex: async () => index,
    read: {
      open: async (_path, signal) => new Promise((resolve) => {
        cancellationPending.push({ resolve: () => resolve(index), signal });
      }),
      get: () => index
    }
  });
  const cancellationServer = await createCadGatewayServer({
    workspaceRoot: process.cwd(),
    skillRoot: skills,
    application: cancellationApplication
  });
  const cancellationBaseUrl = await listen(cancellationServer, context);
  const controller = new AbortController();
  const cancelled = fetch(`${cancellationBaseUrl}/api/skills/run`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal: controller.signal });
  await waitFor(() => cancellationPending.length === 1);
  controller.abort();
  await assert.rejects(cancelled, /abort/i);
  await waitFor(() => cancellationPending[0]!.signal?.aborted === true);
  cancellationPending[0]!.resolve();
  await waitFor(async () =>
    (await (await fetch(`${cancellationBaseUrl}/api/skills`)).json() as { skills: Array<{ recentStatus: string }> }).skills[0]!.recentStatus === "failed"
  );
  assert.equal((await (await fetch(`${cancellationBaseUrl}/api/skills`)).json() as { skills: Array<{ recentStatus: string }> }).skills[0]!.recentStatus, "failed");
});

function nested(depth: number): JsonValue { return depth === 0 ? null : { value: nested(depth - 1) }; }

async function temporarySkills(context: test.TestContext, id: string, schemas: { inputSchema: object; outputSchema: object }): Promise<string> {
  const root = await mkdtemp(resolve(tmpdir(), "cad-skills-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const skill = resolve(root, id);
  await mkdir(resolve(skill, "workflows"), { recursive: true });
  await writeFile(resolve(skill, "SKILL.md"), "---\nname: slow-open\ndescription: Use when deterministic CAD evidence is required.\n---\n");
  await writeFile(resolve(skill, "manifest.json"), JSON.stringify({ id, version: "1.0.0", purpose: "Test only deterministic read skill.", capabilityContract: "cad-capabilities/v1", permissions: ["read"], capabilities: ["document.open"], formats: ["dxf"], entityTypes: ["LINE"], failureCodes: ["OUTPUT_SCHEMA_INVALID"], limitationCodes: ["NO_VISUAL_INFERENCE"], ...schemas }));
  await writeFile(resolve(skill, "workflows/default.json"), JSON.stringify({ schemaVersion: "cad-skill-workflow/v1", steps: [{ id: "open", capability: "document.open", input: { path: "$input.path" } }] }));
  return root;
}

async function listen(server: Awaited<ReturnType<typeof createCadGatewayServer>>, context: test.TestContext): Promise<string> {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  context.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address === "object");
  return `http://127.0.0.1:${address.port}`;
}

function post(baseUrl: string, body: unknown): Promise<Response> {
  return fetch(`${baseUrl}/api/skills/run`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}

async function waitFor(predicate: () => boolean | Promise<boolean>, timeout = 1_000): Promise<void> {
  const until = Date.now() + timeout;
  while (!await predicate()) {
    if (Date.now() > until) throw new Error("condition timed out");
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}
