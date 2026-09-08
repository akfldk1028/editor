import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));

// A clone on a machine with core.autocrlf=true rewrites attribute-less text
// files to CRLF. Retained fixtures are hashed byte for byte and skill
// instructions are compared as exact strings, so that rewrite fails fixture
// integrity and skill discovery in a fresh clone while passing in the clone
// that produced the baselines.
const exactTextFiles = [
  "tests/fixtures/dwg/roundtrip-manifest.json",
  "tests/skills/fixtures/valid-skill/SKILL.md"
];

test("the checkout policy pins every text file to LF", async () => {
  const attributes = await readFile(resolve(repositoryRoot, ".gitattributes"), "utf8");
  const rules = attributes
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("#"));
  assert.ok(
    rules.includes("* text=auto eol=lf"),
    ".gitattributes must pin every text file to LF so clones stay byte-identical"
  );
  for (const rule of ["*.dwg binary", "*.dxf binary"]) {
    assert.ok(rules.includes(rule), `.gitattributes must keep source CAD files binary: ${rule}`);
  }
});

test("hash-pinned and exactly compared text files carry no carriage return", async () => {
  for (const path of exactTextFiles) {
    const bytes = await readFile(resolve(repositoryRoot, path));
    assert.equal(
      bytes.includes(0x0d),
      false,
      `${path} contains a carriage return; re-clone or run: git add --renormalize .`
    );
  }
});

test("every text fixture the manifest hashes carries no carriage return", async () => {
  const manifest = JSON.parse(
    await readFile(resolve(repositoryRoot, "tests/fixtures/manifest.json"), "utf8")
  );
  const textFixtures = manifest.fixtures.filter(
    (fixture) => !/\.(?:dwg|dxf)$/iu.test(fixture.path)
  );
  assert.ok(textFixtures.length > 0, "the fixture manifest must hash at least one text fixture");
  for (const fixture of textFixtures) {
    const bytes = await readFile(resolve(repositoryRoot, fixture.path));
    assert.equal(
      bytes.includes(0x0d),
      false,
      `${fixture.path} contains a carriage return and cannot match its retained hash`
    );
  }
});
