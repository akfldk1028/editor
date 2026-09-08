import { open, realpath, stat } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";
import { TextDecoder } from "node:util";

import {
  parseCadSkillWorkflow,
  type CadSkillWorkflow
} from "@dwg/skill-contracts";

import type { InstalledCadSkill } from "./discovery.js";

export const MAX_CAD_SKILL_WORKFLOW_BYTES = 64 * 1024;
const UTF8_BOM = Buffer.from([0xef, 0xbb, 0xbf]);

export async function loadCadSkillWorkflow(
  skill: Pick<InstalledCadSkill, "root" | "discoveryRoot">
): Promise<CadSkillWorkflow> {
  try {
    const discoveryRoot = await canonicalDirectory(skill.discoveryRoot ?? skill.root);
    const skillRoot = await canonicalDirectory(skill.root);
    assertContainedOrEqual(discoveryRoot, skillRoot);
    const workflowRoot = await canonicalDirectory(resolve(skillRoot, "workflows"));
    assertContained(discoveryRoot, workflowRoot);
    assertContained(skillRoot, workflowRoot);

    const workflowPath = await realpath(resolve(workflowRoot, "default.json"));
    assertContained(discoveryRoot, workflowPath);
    assertContained(skillRoot, workflowPath);
    assertContained(workflowRoot, workflowPath);
    if (!(await stat(workflowPath)).isFile()) throw new Error("SKILL_WORKFLOW_INVALID");

    const handle = await open(workflowPath, "r");
    try {
      const details = await handle.stat();
      if (!details.isFile() || details.size > MAX_CAD_SKILL_WORKFLOW_BYTES) {
        throw new Error("SKILL_WORKFLOW_INVALID");
      }
      const bytes = await handle.readFile();
      if (bytes.byteLength > MAX_CAD_SKILL_WORKFLOW_BYTES || bytes.subarray(0, 3).equals(UTF8_BOM)) {
        throw new Error("SKILL_WORKFLOW_INVALID");
      }
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      return parseCadSkillWorkflow(JSON.parse(text));
    } finally {
      await handle.close();
    }
  } catch {
    throw new Error("SKILL_WORKFLOW_INVALID");
  }
}

async function canonicalDirectory(path: string): Promise<string> {
  const canonical = await realpath(path);
  if (!(await stat(canonical)).isDirectory()) throw new Error("SKILL_WORKFLOW_INVALID");
  return canonical;
}

function assertContained(root: string, candidate: string): void {
  const pathFromRoot = relative(root, candidate);
  if (
    pathFromRoot === "" ||
    pathFromRoot === ".." ||
    pathFromRoot.startsWith(`..${sep}`) ||
    isAbsolute(pathFromRoot)
  ) throw new Error("SKILL_WORKFLOW_INVALID");
}

function assertContainedOrEqual(root: string, candidate: string): void {
  if (root !== candidate) assertContained(root, candidate);
}
