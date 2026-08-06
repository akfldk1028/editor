import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";
import test from "node:test";

import { Ajv } from "ajv";
import { createReadCapabilityModule } from "@dwg/cad-capabilities";
import type { CadEntityIndex } from "@dwg/contracts";
import {
  parseCadSkillManifest,
  parseCadSkillWorkflow,
  type CadSkillWorkflow
} from "@dwg/skill-contracts";

import { buildCadIndexForPath } from "../../modules/cad-runtime/src/application/cad-tools/runtime.js";
import { createCadApplication } from "../../modules/cad-runtime/src/application/createCadApplication.js";
import {
  discoverCadSkills,
  loadCadSkillWorkflow,
  runCadSkillWorkflow,
  type CadSkillRunResult,
  type InstalledCadSkill
} from "../../modules/skill-runtime/src/index.js";

const skillRoot = resolve("skills");
const officialFixtureManifest = resolve("tests/fixtures/manifest.json");

const expectedCapabilities: Record<string, readonly string[]> = {
  "inspect-drawing": ["document.open", "document.describe", "query.layers", "query.entities"],
  "extract-schedule": ["query.text", "query.schedule"],
  "compare-drawings": ["query.compare"],
  "export-drawing": ["export.drawing"],
  "export-report": ["export.report"]
};
const stableRunnerFailureCodes = new Set([
  "CAPABILITY_EXECUTION_FAILED",
  "INPUT_SCHEMA_INVALID",
  "OUTPUT_SCHEMA_INVALID"
]);

interface FixtureEntry {
  id: string;
  path: string;
}

interface DeclaredCase {
  id: string;
  fixture: string;
  scenario:
    | "workflow-input"
    | "opened-fixture"
    | "fixture-text-change"
    | "fixture-missing-before";
  input: string;
  output: string;
  status: "passed" | "failed";
}

test("discovers the grounded built-in skills with exact permissions", async () => {
  const skills = await discoverCadSkills(skillRoot, "cad-capabilities/v1");

  assert.deepEqual(
    skills.map((skill) => skill.manifest.id),
    Object.keys(expectedCapabilities).sort()
  );
  for (const skill of skills) {
    assert.deepEqual(
      skill.manifest.permissions,
      skill.manifest.id === "export-drawing"
        ? ["write-copy", "export"]
        : skill.manifest.id === "export-report"
          ? ["export"]
          : ["read"]
    );
    assert.deepEqual(skill.manifest.capabilities, expectedCapabilities[skill.manifest.id]);
    if (skill.manifest.id.startsWith("export-")) continue;
    assert.match(skill.instructions, /^---\r?\nname: [a-z0-9]+(?:-[a-z0-9]+)*\r?\ndescription: Use when .+\r?\n---\r?\n/);
    assert.match(skill.instructions, /model geometry inference is forbidden/i);
    assert.match(skill.instructions, /unsupported/i);
    assert.doesNotMatch(skill.instructions, /(?:[A-Za-z]:[\\/]|\/Users\/|api[_ -]?key|secret)/i);
  }
});

test("built-in manifests advertise only stable runner-visible failures", async () => {
  const skills = await discoverCadSkills(skillRoot, "cad-capabilities/v1");

  for (const skill of skills.filter((item) => item.manifest.permissions.includes("read"))) {
    for (const code of skill.manifest.failureCodes) {
      assert.ok(
        stableRunnerFailureCodes.has(code),
        `${skill.manifest.id} advertises non-observable failure ${code}.`
      );
    }
  }
});

test("rejects an inspect case whose opened path disagrees with its fixture", async () => {
  await assert.rejects(
    () => assertFixtureBoundInput(
      "inspect-drawing",
      "workflow-input",
      resolve("tests/fixtures/dxf/minimal-architectural.dxf"),
      { path: "tests/fixtures/dwg/export_sample.dwg", layer: "A-WALL" }
    ),
    /CASE_FIXTURE_INPUT_MISMATCH/
  );
});

test("executes every declared built-in case against its official fixture", async (t) => {
  const skills = await discoverCadSkills(skillRoot, "cad-capabilities/v1");
  const fixtures = await loadOfficialFixtures();

  for (const skill of skills.filter((item) => item.manifest.permissions.includes("read"))) {
    const workflow = await loadCadSkillWorkflow(skill);
    const declaredCases = await loadCases(skill);

    for (const declaredCase of declaredCases) {
      await t.test(`${skill.manifest.id}/${declaredCase.id}`, async () => {
        const fixture = fixtures.get(declaredCase.fixture);
        assert.ok(fixture, `Unknown official fixture ${declaredCase.fixture}.`);
        const fixturePath = resolveOfficialFixture(fixture.path);
        const input = await readCaseJson(skill.root, declaredCase.input);
        const expected = await readCaseJson(skill.root, declaredCase.output);
        assertSanitized({ declaredCase, input, expected });
        const boundInput = await bindFixtureInput(
          skill.manifest.id,
          declaredCase.scenario,
          fixturePath,
          input
        );
        await assertFixtureBoundInput(
          skill.manifest.id,
          declaredCase.scenario,
          fixturePath,
          boundInput
        );

        const result = await executeCase(
          skill,
          workflow,
          declaredCase,
          fixturePath,
          boundInput
        );

        assert.equal(result.status, declaredCase.status);
        if (declaredCase.status === "passed") {
          const actual = finalOutput(result);
          assertManifestOutput(skill, expected);
          assertManifestOutput(skill, actual);
          assert.deepEqual(actual, expected);
          assertGroundedCaseEvidence(skill.manifest.id, result);
          return;
        }

        assert.deepEqual(result, expected);
        const code = runnerFailureCode(result);
        assert.ok(code, "Expected a stable runner-visible failure code.");
        assert.ok(
          skill.manifest.failureCodes.includes(code),
          `${skill.manifest.id} does not declare executed failure ${code}.`
        );
      });
    }
  }
});

async function assertFixtureBoundInput(
  skillId: string,
  scenario: DeclaredCase["scenario"],
  fixturePath: string,
  input: unknown
): Promise<void> {
  const args = input as Record<string, unknown>;
  if (skillId === "inspect-drawing") {
    if (
      typeof args.path !== "string" ||
      resolve(args.path) !== fixturePath
    ) {
      throw new Error("CASE_FIXTURE_INPUT_MISMATCH");
    }
    return;
  }

  const fixture = await buildCadIndexForPath(fixturePath);
  if (skillId === "extract-schedule") {
    if (args.drawingId !== fixture.drawingId) {
      throw new Error("CASE_FIXTURE_INPUT_MISMATCH");
    }
    return;
  }

  if (
    args.beforeDrawingId !== (
      scenario === "fixture-missing-before"
        ? `${fixture.drawingId}:missing`
        : `${fixture.drawingId}:before`
    ) ||
    args.afterDrawingId !== `${fixture.drawingId}:after`
  ) {
    throw new Error("CASE_FIXTURE_INPUT_MISMATCH");
  }
}

async function bindFixtureInput(
  skillId: string,
  scenario: DeclaredCase["scenario"],
  fixturePath: string,
  input: unknown
): Promise<Record<string, unknown>> {
  const args = structuredClone(input) as Record<string, unknown>;
  if (skillId === "inspect-drawing") {
    args.path = relative(resolve("."), fixturePath).split(sep).join("/");
    return args;
  }

  const fixture = await buildCadIndexForPath(fixturePath);
  if (skillId === "extract-schedule") {
    args.drawingId = fixture.drawingId;
    return args;
  }

  args.beforeDrawingId = scenario === "fixture-missing-before"
    ? `${fixture.drawingId}:missing`
    : `${fixture.drawingId}:before`;
  args.afterDrawingId = `${fixture.drawingId}:after`;
  return args;
}

async function executeCase(
  skill: InstalledCadSkill,
  workflow: CadSkillWorkflow,
  declaredCase: DeclaredCase,
  fixturePath: string,
  input: unknown
): Promise<CadSkillRunResult> {
  const capabilities = await capabilitiesForCase(
    skill.manifest.id,
    declaredCase.scenario,
    fixturePath
  );
  return runCadSkillWorkflow({
    skill,
    workflow,
    input,
    grantedPermissions: ["read"],
    capabilities
  });
}

async function capabilitiesForCase(
  skillId: string,
  scenario: DeclaredCase["scenario"],
  fixturePath: string
) {
  if (skillId === "inspect-drawing" && scenario === "workflow-input") {
    const application = await createCadApplication({ workspaceRoot: resolve(".") });
    return application.capabilities;
  }

  const fixture = await buildCadIndexForPath(fixturePath);
  if (skillId === "extract-schedule" && scenario === "opened-fixture") {
    return createReadCapabilityModule({
      async open() {
        return fixture;
      },
      get(drawingId) {
        return drawingId === fixture.drawingId ? fixture : null;
      }
    });
  }

  if (skillId === "compare-drawings" && scenario === "fixture-text-change") {
    const before = structuredClone(fixture);
    before.drawingId = `${fixture.drawingId}:before`;
    const after = changedFixtureIndex(
      before,
      `${fixture.drawingId}:after`
    );
    return createReadCapabilityModule({
      async open() {
        return before;
      },
      get(drawingId) {
        if (drawingId === before.drawingId) return before;
        if (drawingId === after.drawingId) return after;
        return null;
      }
    });
  }

  if (skillId === "compare-drawings" && scenario === "fixture-missing-before") {
    const before = structuredClone(fixture);
    before.drawingId = `${fixture.drawingId}:before`;
    const after = changedFixtureIndex(
      before,
      `${fixture.drawingId}:after`
    );
    return createReadCapabilityModule({
      async open() {
        return before;
      },
      get(drawingId) {
        if (drawingId === before.drawingId) return before;
        if (drawingId === after.drawingId) return after;
        return null;
      }
    });
  }

  assert.fail(`Unsupported case setup ${skillId}/${scenario}.`);
}

async function loadCases(skill: InstalledCadSkill): Promise<DeclaredCase[]> {
  const value = await readJson(resolve(skill.root, "tests/cases.json"));
  const cases = value as {
    schemaVersion?: unknown;
    skillId?: unknown;
    cases?: unknown;
  };
  assert.deepEqual(Object.keys(cases).sort(), ["cases", "schemaVersion", "skillId"]);
  assert.equal(cases.schemaVersion, "cad-skill-cases/v1");
  assert.equal(cases.skillId, skill.manifest.id);
  assert.ok(Array.isArray(cases.cases) && cases.cases.length > 0);

  const ids = new Set<string>();
  return cases.cases.map((value): DeclaredCase => {
    const entry = value as Record<string, unknown>;
    assert.deepEqual(
      Object.keys(entry).sort(),
      ["fixture", "id", "input", "output", "scenario", "status"]
    );
    assert.equal(typeof entry.id, "string");
    assert.ok(!ids.has(entry.id), `Duplicate case id ${entry.id}.`);
    ids.add(entry.id);
    assert.equal(typeof entry.fixture, "string");
    assert.ok(
      [
        "workflow-input",
        "opened-fixture",
        "fixture-text-change",
        "fixture-missing-before"
      ].includes(
        entry.scenario as string
      )
    );
    assert.equal(typeof entry.input, "string");
    assert.equal(typeof entry.output, "string");
    assert.ok(entry.status === "passed" || entry.status === "failed");
    return entry as unknown as DeclaredCase;
  });
}

async function loadOfficialFixtures(): Promise<Map<string, FixtureEntry>> {
  const value = await readJson(officialFixtureManifest) as {
    version?: unknown;
    fixtures?: unknown;
  };
  assert.equal(value.version, 1);
  assert.ok(Array.isArray(value.fixtures));
  return new Map(value.fixtures.map((entry) => {
    const fixture = entry as FixtureEntry;
    return [fixture.id, fixture];
  }));
}

function resolveOfficialFixture(path: string): string {
  const fixtureRoot = resolve("tests/fixtures");
  const candidate = resolve(path);
  assertContained(fixtureRoot, candidate);
  return candidate;
}

async function readCaseJson(root: string, path: string): Promise<unknown> {
  const candidate = resolve(root, path);
  assertContained(root, candidate);
  return readJson(candidate);
}

async function readJson(path: string): Promise<unknown> {
  return JSON.parse(await readFile(path, "utf8"));
}

function assertContained(root: string, candidate: string): void {
  const pathFromRoot = relative(root, candidate);
  assert.ok(
    pathFromRoot !== "" &&
      pathFromRoot !== ".." &&
      !pathFromRoot.startsWith(`..${sep}`) &&
      !isAbsolute(pathFromRoot),
    `Case path escapes its root: ${candidate}`
  );
}

function assertManifestOutput(skill: InstalledCadSkill, value: unknown): void {
  const manifest = parseCadSkillManifest(skill.manifest);
  const validate = new Ajv({ allErrors: true, strict: true }).compile(
    manifest.outputSchema
  );
  assert.equal(
    validate(value),
    true,
    `${skill.manifest.id} output violates its manifest: ${JSON.stringify(validate.errors)}`
  );
}

function finalOutput(result: CadSkillRunResult): unknown {
  const step = result.steps.at(-1);
  assert.ok(step, "Expected a workflow result step.");
  return step.output;
}

function runnerFailureCode(result: CadSkillRunResult): string | null {
  const lastOutput = result.steps.at(-1)?.output as {
    error?: { code?: unknown };
  } | undefined;
  if (typeof lastOutput?.error?.code === "string") return lastOutput.error.code;
  return result.warnings.length === 1 ? result.warnings[0]! : null;
}

function changedFixtureIndex(
  index: CadEntityIndex,
  drawingId: string
): CadEntityIndex {
  const changed = structuredClone(index);
  changed.drawingId = drawingId;
  const text = changed.entities.find((entity) => entity.handle === "30");
  assert.ok(text, "Expected TEXT handle 30 in the official DXF fixture.");
  text.text = "ROOM 102";
  return changed;
}

function assertGroundedCaseEvidence(skillId: string, result: CadSkillRunResult): void {
  if (skillId === "inspect-drawing") {
    assertGroundedMatches(finalOutput(result));
    return;
  }
  if (skillId === "extract-schedule") {
    assertGroundedMatches(result.steps[0]!.output);
    return;
  }

  const comparison = finalOutput(result) as {
    added: unknown[];
    removed: unknown[];
    changed: Array<{ before: unknown; after: unknown }>;
  };
  for (
    const match of [
      ...comparison.added,
      ...comparison.removed,
      ...comparison.changed.flatMap((change) => [change.before, change.after])
    ]
  ) {
    assertGroundedMatch(match);
  }
}

function assertGroundedMatches(value: unknown): void {
  const matches = (value as { matches?: unknown }).matches;
  assert.ok(Array.isArray(matches), "Expected a matches array.");
  for (const match of matches) assertGroundedMatch(match);
}

function assertGroundedMatch(value: unknown): void {
  const match = value as Record<string, unknown>;
  assert.equal(typeof match.handle, "string");
  assert.equal(typeof match.type, "string");
  assert.equal(typeof match.layer, "string");
  assert.ok(match.bbox && typeof match.bbox === "object");
}

function assertSanitized(value: unknown): void {
  assert.doesNotMatch(
    JSON.stringify(value),
    /(?:[A-Za-z]:[\\/]|\/Users\/|api[_ -]?key|secret)/i
  );
}
