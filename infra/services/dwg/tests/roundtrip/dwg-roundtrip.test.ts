import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import test from "node:test";

const repositoryRoot = resolve(import.meta.dirname, "../..");
const manifestPath = resolve(
  repositoryRoot,
  "tests/fixtures/dwg/roundtrip-manifest.json"
);
const sourcePath = resolve(
  repositoryRoot,
  "tests/fixtures/dwg/export_sample.dwg"
);
const candidates = [
  "AC1014",
  "AC1015",
  "AC1018",
  "AC1024",
  "AC1027",
  "AC1032"
] as const;
const sha256Pattern = /^[0-9A-F]{64}$/u;

test("DWG release policy contains only probed complete allowlist evidence", async () => {
  const json = await readFile(manifestPath, "utf8");
  assertNoDuplicateJsonKeys(json);
  const manifest = strictObject(JSON.parse(json), [
    "schemaVersion",
    "candidates"
  ]);
  assert.equal(manifest.schemaVersion, "dwg-roundtrip-policy/v1");
  assert.ok(Array.isArray(manifest.candidates));
  assert.equal(manifest.candidates.length, candidates.length);
  const sourceHash = createHash("sha256")
    .update(await readFile(sourcePath))
    .digest("hex")
    .toUpperCase();
  let verifiedCount = 0;

  manifest.candidates.forEach((candidate, index) => {
    const entry = strictObject(candidate, [
      "version",
      "probeFixtureSha256",
      "verified",
      "invariantSha256"
    ]);
    assert.equal(entry.version, candidates[index]);
    assert.equal(typeof entry.verified, "boolean");
    assert.equal(typeof entry.probeFixtureSha256, "string");
    assert.equal(typeof entry.invariantSha256, "string");
    if (entry.verified) {
      verifiedCount += 1;
      assert.equal(entry.probeFixtureSha256, sourceHash);
      assert.match(entry.probeFixtureSha256, sha256Pattern);
      assert.match(entry.invariantSha256, sha256Pattern);
    } else {
      assert.equal(entry.probeFixtureSha256, "");
      assert.equal(entry.invariantSha256, "");
    }
  });

  assert.ok(verifiedCount > 0, "at least one DWG version must be probe-verified");
});

function strictObject(
  value: unknown,
  keys: readonly string[]
): Record<string, unknown> {
  assert.ok(
    value !== null
      && typeof value === "object"
      && !Array.isArray(value)
  );
  assert.deepEqual(Object.keys(value).sort(), [...keys].sort());
  return value as Record<string, unknown>;
}

function assertNoDuplicateJsonKeys(json: string): void {
  let index = 0;
  parseValue();
  skipWhitespace();
  assert.equal(index, json.length);

  function parseValue(): void {
    skipWhitespace();
    const token = json[index];
    if (token === "{") return parseObject();
    if (token === "[") return parseArray();
    if (token === "\"") {
      parseString();
      return;
    }
    if (token === "t" && json.slice(index, index + 4) === "true") {
      index += 4;
      return;
    }
    if (token === "f" && json.slice(index, index + 5) === "false") {
      index += 5;
      return;
    }
    if (token === "n" && json.slice(index, index + 4) === "null") {
      index += 4;
      return;
    }
    const match = json.slice(index).match(
      /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/u
    );
    assert.ok(match);
    index += match[0].length;
  }

  function parseObject(): void {
    index += 1;
    skipWhitespace();
    const keys = new Set<string>();
    if (json[index] === "}") {
      index += 1;
      return;
    }
    while (true) {
      skipWhitespace();
      const key = parseString();
      assert.ok(!keys.has(key), "duplicate JSON key");
      keys.add(key);
      skipWhitespace();
      assert.equal(json[index], ":");
      index += 1;
      parseValue();
      skipWhitespace();
      if (json[index] === "}") {
        index += 1;
        return;
      }
      assert.equal(json[index], ",");
      index += 1;
    }
  }

  function parseArray(): void {
    index += 1;
    skipWhitespace();
    if (json[index] === "]") {
      index += 1;
      return;
    }
    while (true) {
      parseValue();
      skipWhitespace();
      if (json[index] === "]") {
        index += 1;
        return;
      }
      assert.equal(json[index], ",");
      index += 1;
    }
  }

  function parseString(): string {
    assert.equal(json[index], "\"");
    const start = index;
    index += 1;
    while (index < json.length) {
      const character = json[index]!;
      if (character === "\"") {
        index += 1;
        return JSON.parse(json.slice(start, index)) as string;
      }
      if (character === "\\") index += 2;
      else index += 1;
    }
    assert.fail("unterminated JSON string");
  }

  function skipWhitespace(): void {
    while (
      json[index] === " "
      || json[index] === "\n"
      || json[index] === "\r"
      || json[index] === "\t"
    ) {
      index += 1;
    }
  }
}
