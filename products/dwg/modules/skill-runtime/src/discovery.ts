import { readdir, realpath, readFile, stat } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { TextDecoder } from "node:util";

import {
  parseCadSkillManifest,
  type CadSkillManifest
} from "@dwg/skill-contracts";

import { assessCadSkillCompatibility } from "./compatibility.js";

const MAX_INSTRUCTION_BYTES = 64 * 1024;
const UTF8_BOM = Buffer.from([0xef, 0xbb, 0xbf]);

export interface InstalledCadSkill {
  discoveryRoot?: string;
  root: string;
  manifest: CadSkillManifest;
  instructions: string;
  compatible: boolean;
  incompatibility: string | null;
}

export async function discoverCadSkills(
  root: string,
  capabilityVersion: "cad-capabilities/v1"
): Promise<InstalledCadSkill[]> {
  const canonicalRoot = await canonicalDirectory(root, "SKILL_DISCOVERY_ROOT_INVALID");
  const entries = await readdir(canonicalRoot, { withFileTypes: true });
  const skills: InstalledCadSkill[] = [];

  for (const entry of entries) {
    if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;

    const skillRoot = await canonicalDirectory(
      resolve(canonicalRoot, entry.name),
      "SKILL_ROOT_INVALID"
    );
    assertContained(canonicalRoot, skillRoot, "SKILL_ROOT_OUTSIDE");

    const [instructions, manifest] = await Promise.all([
      readInstructions(canonicalRoot, skillRoot),
      readManifest(canonicalRoot, skillRoot)
    ]);
    const compatibility = assessCadSkillCompatibility(manifest, capabilityVersion);

    const skill: InstalledCadSkill = {
      root: skillRoot,
      manifest,
      instructions,
      ...compatibility
    };
    Object.defineProperty(skill, "discoveryRoot", {
      value: canonicalRoot,
      enumerable: false,
      writable: false,
      configurable: false
    });
    skills.push(skill);
  }

  assertUniqueSkillVersions(skills);
  return skills.sort(compareInstalledCadSkills);
}

async function canonicalDirectory(path: string, code: string): Promise<string> {
  try {
    const canonicalPath = await realpath(path);
    if (!(await stat(canonicalPath)).isDirectory()) throw new Error(code);
    return canonicalPath;
  } catch {
    throw new Error(code);
  }
}

async function readInstructions(root: string, skillRoot: string): Promise<string> {
  const instructionPath = await canonicalSkillFile(
    root,
    skillRoot,
    "SKILL.md",
    "SKILL_INSTRUCTIONS_MISSING"
  );
  const details = await stat(instructionPath);
  if (!details.isFile()) throw new Error("SKILL_INSTRUCTIONS_MISSING");
  if (details.size > MAX_INSTRUCTION_BYTES) {
    throw new Error("SKILL_INSTRUCTIONS_TOO_LARGE");
  }
  return decodeStrictUtf8(
    await readFile(instructionPath),
    "SKILL_INSTRUCTIONS_INVALID_ENCODING"
  );
}

async function readManifest(root: string, skillRoot: string): Promise<CadSkillManifest> {
  const manifestPath = await canonicalSkillFile(
    root,
    skillRoot,
    "manifest.json",
    "SKILL_MANIFEST_MISSING"
  );

  try {
    const manifest = decodeStrictUtf8(
      await readFile(manifestPath),
      "SKILL_MANIFEST_INVALID"
    );
    return parseCadSkillManifest(JSON.parse(manifest));
  } catch {
    throw new Error("SKILL_MANIFEST_INVALID");
  }
}

function decodeStrictUtf8(bytes: Buffer, errorCode: string): string {
  try {
    if (bytes.subarray(0, UTF8_BOM.length).equals(UTF8_BOM)) {
      throw new Error(errorCode);
    }
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error(errorCode);
  }
}

async function canonicalSkillFile(
  root: string,
  skillRoot: string,
  name: string,
  missingCode: string
): Promise<string> {
  try {
    const filePath = await realpath(resolve(skillRoot, name));
    assertContained(root, filePath, "SKILL_FILE_OUTSIDE");
    assertContained(skillRoot, filePath, "SKILL_FILE_OUTSIDE");
    return filePath;
  } catch (error) {
    if (error instanceof Error && error.message === "SKILL_FILE_OUTSIDE") {
      throw error;
    }
    throw new Error(missingCode);
  }
}

function assertContained(root: string, candidate: string, code: string) {
  const pathFromRoot = relative(root, candidate);
  if (
    pathFromRoot === "" ||
    pathFromRoot === ".." ||
    pathFromRoot.startsWith(`..${sep}`) ||
    isAbsolute(pathFromRoot)
  ) {
    throw new Error(code);
  }
}

function assertUniqueSkillVersions(skills: readonly InstalledCadSkill[]) {
  const identities = new Set<string>();
  for (const skill of skills) {
    const identity = `${skill.manifest.id}\u0000${skill.manifest.version}`;
    if (identities.has(identity)) throw new Error("SKILL_DUPLICATE_ID_VERSION");
    identities.add(identity);
  }
}

function compareInstalledCadSkills(
  left: InstalledCadSkill,
  right: InstalledCadSkill
): number {
  const idComparison = compareText(left.manifest.id, right.manifest.id);
  if (idComparison !== 0) return idComparison;

  const versionComparison = compareSemanticVersions(
    left.manifest.version,
    right.manifest.version
  );
  if (versionComparison !== 0) return versionComparison;

  return compareText(left.manifest.version, right.manifest.version);
}

function compareSemanticVersions(left: string, right: string): number {
  const leftVersion = parseSemanticVersion(left);
  const rightVersion = parseSemanticVersion(right);

  for (const index of [0, 1, 2]) {
    const comparison = compareNumericIdentifier(
      leftVersion.core[index]!,
      rightVersion.core[index]!
    );
    if (comparison !== 0) return comparison;
  }

  if (leftVersion.pre.length === 0 && rightVersion.pre.length === 0) return 0;
  if (leftVersion.pre.length === 0) return 1;
  if (rightVersion.pre.length === 0) return -1;

  const length = Math.max(leftVersion.pre.length, rightVersion.pre.length);
  for (let index = 0; index < length; index += 1) {
    const leftIdentifier = leftVersion.pre[index];
    const rightIdentifier = rightVersion.pre[index];
    if (leftIdentifier === undefined) return -1;
    if (rightIdentifier === undefined) return 1;
    const comparison = comparePreReleaseIdentifier(leftIdentifier, rightIdentifier);
    if (comparison !== 0) return comparison;
  }
  return 0;
}

function parseSemanticVersion(version: string) {
  const [withoutBuild] = version.split("+", 1);
  const [core, prerelease] = withoutBuild!.split("-", 2);
  return {
    core: core!.split("."),
    pre: prerelease === undefined ? [] : prerelease.split(".")
  };
}

function comparePreReleaseIdentifier(left: string, right: string): number {
  const leftIsNumber = /^\d+$/.test(left);
  const rightIsNumber = /^\d+$/.test(right);
  if (leftIsNumber && rightIsNumber) return compareNumericIdentifier(left, right);
  if (leftIsNumber) return -1;
  if (rightIsNumber) return 1;
  return compareText(left, right);
}

function compareNumericIdentifier(left: string, right: string): number {
  if (left.length !== right.length) return left.length - right.length;
  return compareText(left, right);
}

function compareText(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}
