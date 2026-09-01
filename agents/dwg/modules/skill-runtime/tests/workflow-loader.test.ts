import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  discoverCadSkills,
  loadCadSkillWorkflow,
  MAX_CAD_SKILL_WORKFLOW_BYTES
} from "../src/index.js";

test("loads a bounded workflow through its canonical installed skill path", async (context) => {
  const { root } = await createSkillRoot(context);
  const [skill] = await discoverCadSkills(root, "cad-capabilities/v1");
  assert.ok(skill);

  assert.deepEqual(await loadCadSkillWorkflow(skill), workflow());
});

test("rejects an external workflows directory symlink or Windows junction", async (context) => {
  const { root, skillRoot, outside } = await createSkillRoot(context, false);
  await writeFile(join(outside, "default.json"), JSON.stringify(workflow()));
  if (!await createLink(outside, join(skillRoot, "workflows"), process.platform === "win32" ? "junction" : "dir", context)) return;
  const [skill] = await discoverCadSkills(root, "cad-capabilities/v1");
  assert.ok(skill);

  await assert.rejects(() => loadCadSkillWorkflow(skill), /SKILL_WORKFLOW_INVALID/);
});

test("rejects an external workflow file symlink", async (context) => {
  const { root, skillRoot, outside } = await createSkillRoot(context, false);
  await mkdir(join(skillRoot, "workflows"));
  const externalFile = join(outside, "default.json");
  await writeFile(externalFile, JSON.stringify(workflow()));
  if (!await createLink(externalFile, join(skillRoot, "workflows", "default.json"), "file", context)) return;
  const [skill] = await discoverCadSkills(root, "cad-capabilities/v1");
  assert.ok(skill);

  await assert.rejects(() => loadCadSkillWorkflow(skill), /SKILL_WORKFLOW_INVALID/);
});

test("rejects non-files, invalid UTF-8, and oversized workflow bytes", async (context) => {
  const cases: Array<(path: string) => Promise<void>> = [
    async (path) => { await mkdir(path); },
    async (path) => { await writeFile(path, Buffer.from([0xc3, 0x28])); },
    async (path) => { await writeFile(path, "x".repeat(MAX_CAD_SKILL_WORKFLOW_BYTES + 1)); }
  ];

  for (const setup of cases) {
    const { root, skillRoot } = await createSkillRoot(context, false);
    await mkdir(join(skillRoot, "workflows"));
    await setup(join(skillRoot, "workflows", "default.json"));
    const [skill] = await discoverCadSkills(root, "cad-capabilities/v1");
    assert.ok(skill);
    await assert.rejects(() => loadCadSkillWorkflow(skill), /SKILL_WORKFLOW_INVALID/);
  }
});

async function createSkillRoot(context: test.TestContext, withWorkflow = true) {
  const container = await mkdtemp(join(tmpdir(), "cad-workflow-loader-"));
  context.after(() => rm(container, { recursive: true, force: true }));
  const root = join(container, "skills");
  const outside = join(container, "outside");
  const skillRoot = join(root, "test-skill");
  await mkdir(skillRoot, { recursive: true });
  await mkdir(outside);
  await writeFile(join(skillRoot, "SKILL.md"), "---\nname: test-skill\ndescription: Test.\n---\n");
  await writeFile(join(skillRoot, "manifest.json"), JSON.stringify({
    id: "test-skill", version: "1.0.0", purpose: "Test workflow loading.",
    capabilityContract: "cad-capabilities/v1", permissions: ["read"],
    capabilities: ["document.open"], formats: ["dxf"], entityTypes: ["LINE"],
    failureCodes: ["CAPABILITY_EXECUTION_FAILED"], limitationCodes: ["NO_VISUAL_INFERENCE"],
    inputSchema: { type: "object" }, outputSchema: { type: "object" }
  }));
  if (withWorkflow) {
    await mkdir(join(skillRoot, "workflows"));
    await writeFile(join(skillRoot, "workflows", "default.json"), JSON.stringify(workflow()));
  }
  return { root, skillRoot, outside };
}

async function createLink(
  target: string,
  path: string,
  type: "file" | "dir" | "junction",
  context: test.TestContext
): Promise<boolean> {
  try {
    await symlink(target, path, type);
    return true;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "EPERM" || code === "EACCES" || code === "ENOTSUP") {
      context.skip(`link privilege unavailable: ${code}`);
      return false;
    }
    throw error;
  }
}

function workflow() {
  return {
    schemaVersion: "cad-skill-workflow/v1" as const,
    steps: [{ id: "open", capability: "document.open", input: { path: "$input.path" } }]
  };
}
