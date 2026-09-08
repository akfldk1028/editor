import assert from "node:assert/strict";
import {
  cp,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";

import { discoverCadSkills } from "../src/index.js";

const fixtureRoot = resolve("tests/skills/fixtures/valid-skill");
const supportedContract = "cad-capabilities/v1" as const;

test("discovers a valid skill through its canonical root", async () => {
  const skills = await discoverCadSkills(
    resolve("tests/skills/fixtures"),
    supportedContract
  );

  assert.deepEqual(skills, [
    {
      root: await resolveCanonical(fixtureRoot),
      manifest: {
        id: "layer-inspection",
        version: "1.2.3",
        purpose: "Inspect drawing layers using deterministic CAD evidence.",
        capabilityContract: supportedContract,
        permissions: ["read"],
        capabilities: ["query.layers"],
        formats: ["dwg", "dxf"],
        entityTypes: ["LAYER"],
        failureCodes: ["DRAWING_NOT_FOUND"],
        limitationCodes: ["NO_VISUAL_INFERENCE"],
        inputSchema: { type: "object" },
        outputSchema: { type: "object" }
      },
      instructions: "# Layer inspection\n\nUse deterministic layer evidence only.\n",
      compatible: true,
      incompatibility: null
    }
  ]);
});

test("rejects a skill root symlink that canonically escapes discovery root", async (t) => {
  await withSkillRoot(t, async ({ root, outside }) => {
    await writeValidSkill(outside, "outside-skill");
    await symlink(outside, join(root, "escaped-skill"), "junction");

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /SKILL_ROOT_OUTSIDE/
    );
  });
});

test("rejects a skill missing its required instruction file", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    const skill = join(root, "missing-instructions");
    await mkdir(skill);
    await writeManifest(skill);

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /SKILL_INSTRUCTIONS_MISSING/
    );
  });
});

test("rejects an invalid manifest through the public manifest parser", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    const skill = join(root, "invalid-manifest");
    await writeValidSkill(skill, "invalid-manifest");
    await writeFile(join(skill, "manifest.json"), "{ invalid json");

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /SKILL_MANIFEST_INVALID/
    );
  });
});

test("rejects duplicate skill id and version pairs", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    await writeValidSkill(join(root, "one"), "duplicate-skill");
    await writeValidSkill(join(root, "two"), "duplicate-skill");

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /SKILL_DUPLICATE_ID_VERSION/
    );
  });
});

test("rejects instructions above the 64 KiB byte limit", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    const skill = join(root, "oversized-instructions");
    await writeValidSkill(skill, "oversized-instructions");
    await writeFile(join(skill, "SKILL.md"), "x".repeat(64 * 1024 + 1));

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /SKILL_INSTRUCTIONS_TOO_LARGE/
    );
  });
});

test("rejects an invalid UTF-8 byte sequence in SKILL.md", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    const skill = join(root, "invalid-instruction-encoding");
    await writeValidSkill(skill, "invalid-instruction-encoding");
    await writeFile(
      join(skill, "SKILL.md"),
      Buffer.from([0x23, 0x20, 0xc3, 0x28])
    );

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /^Error: SKILL_INSTRUCTIONS_INVALID_ENCODING$/
    );
  });
});

test("rejects a truncated UTF-8 sequence in SKILL.md", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    const skill = join(root, "truncated-instruction-encoding");
    await writeValidSkill(skill, "truncated-instruction-encoding");
    await writeFile(join(skill, "SKILL.md"), Buffer.from([0x23, 0x20, 0xe2, 0x82]));

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /^Error: SKILL_INSTRUCTIONS_INVALID_ENCODING$/
    );
  });
});

test("rejects an invalid UTF-8 byte sequence in manifest.json", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    const skill = join(root, "invalid-manifest-encoding");
    await writeValidSkill(skill, "invalid-manifest-encoding");
    await writeManifestWithPurposeBytes(skill, Buffer.from([0xc3, 0x28]));

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /^Error: SKILL_MANIFEST_INVALID$/
    );
  });
});

test("rejects a truncated UTF-8 sequence in manifest.json", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    const skill = join(root, "truncated-manifest-encoding");
    await writeValidSkill(skill, "truncated-manifest-encoding");
    await writeManifestWithPurposeBytes(skill, Buffer.from([0xe2, 0x82]));

    await assert.rejects(
      () => discoverCadSkills(root, supportedContract),
      /^Error: SKILL_MANIFEST_INVALID$/
    );
  });
});

test("rejects UTF-8 BOMs in both required skill files", async (t) => {
  for (const fileName of ["SKILL.md", "manifest.json"]) {
    await withSkillRoot(t, async ({ root }) => {
      const skill = join(root, `bom-${fileName.replace(".", "-")}`);
      await writeValidSkill(skill, `bom-${fileName === "SKILL.md" ? "skill" : "manifest"}`);
      const path = join(skill, fileName);
      const bytes = await readFile(path);
      await writeFile(path, Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), bytes]));

      const expectedCode =
        fileName === "SKILL.md"
          ? "SKILL_INSTRUCTIONS_INVALID_ENCODING"
          : "SKILL_MANIFEST_INVALID";
      await assert.rejects(
        () => discoverCadSkills(root, supportedContract),
        new RegExp(`^Error: ${expectedCode}$`)
      );
    });
  }
});

test("accepts exactly 64 KiB of valid Korean UTF-8 instructions", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    const skillRoot = join(root, "korean-instructions");
    await writeValidSkill(skillRoot, "korean-instructions");
    const instructions = `${"가".repeat(21_845)}\n`;
    assert.equal(Buffer.byteLength(instructions, "utf8"), 64 * 1024);
    await writeFile(join(skillRoot, "SKILL.md"), instructions);

    const [skill] = await discoverCadSkills(root, supportedContract);

    assert.equal(skill?.instructions, instructions);
  });
});

test("lists an incompatible capability contract without making it executable", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    await writeValidSkill(join(root, "layer-inspection"), "layer-inspection");

    const [skill] = await discoverCadSkills(
      root,
      "cad-capabilities/v0" as unknown as typeof supportedContract
    );

    assert.equal(skill?.compatible, false);
    assert.equal(skill?.incompatibility, "CAPABILITY_CONTRACT_MISMATCH");
  });
});

test("sorts skills by id then semantic version", async (t) => {
  await withSkillRoot(t, async ({ root }) => {
    await writeValidSkill(join(root, "zeta"), "zeta", "1.0.0");
    await writeValidSkill(join(root, "alpha-release"), "alpha", "1.0.0");
    await writeValidSkill(join(root, "alpha-pre"), "alpha", "1.0.0-rc.2");
    await writeValidSkill(join(root, "alpha-old"), "alpha", "0.9.0");

    const skills = await discoverCadSkills(root, supportedContract);

    assert.deepEqual(
      skills.map((skill) => `${skill.manifest.id}@${skill.manifest.version}`),
      ["alpha@0.9.0", "alpha@1.0.0-rc.2", "alpha@1.0.0", "zeta@1.0.0"]
    );
  });
});

async function withSkillRoot(
  t: test.TestContext,
  run: (paths: { root: string; outside: string }) => Promise<void>
) {
  const workspace = await mkdtemp(join(tmpdir(), "dwg-skill-runtime-"));
  t.after(() => rm(workspace, { recursive: true, force: true }));
  const root = join(workspace, "skills");
  const outside = join(workspace, "outside");
  await Promise.all([mkdir(root), mkdir(outside)]);
  await run({ root, outside });
}

async function writeValidSkill(root: string, id: string, version = "1.2.3") {
  await cp(fixtureRoot, root, { recursive: true });
  await writeManifest(root, { id, version });
}

async function writeManifest(root: string, overrides: Record<string, unknown> = {}) {
  const manifest = JSON.parse(await readFile(join(fixtureRoot, "manifest.json"), "utf8"));
  await writeFile(join(root, "manifest.json"), JSON.stringify({ ...manifest, ...overrides }));
}

async function writeManifestWithPurposeBytes(root: string, purpose: Buffer) {
  const manifest = await readFile(join(root, "manifest.json"), "utf8");
  const originalPurpose = "Inspect drawing layers using deterministic CAD evidence.";
  const [before, after] = manifest.split(originalPurpose);
  assert.notEqual(after, undefined);
  await writeFile(
    join(root, "manifest.json"),
    Buffer.concat([Buffer.from(before!), purpose, Buffer.from(after!)])
  );
}

async function resolveCanonical(path: string) {
  const { realpath } = await import("node:fs/promises");
  return realpath(path);
}
