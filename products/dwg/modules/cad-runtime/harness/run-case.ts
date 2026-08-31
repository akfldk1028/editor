import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { createCadToolRuntime } from "../src/application/cad-tools/runtime.js";
import { createCadApplication } from "../src/application/createCadApplication.js";
import {
  createRepositoryPaths,
  findRepositoryRoot
} from "../src/platform/repositoryPaths.js";

interface HarnessStep {
  tool: string;
  args: Record<string, unknown>;
}

interface HarnessCase {
  name: string;
  fixture: string;
  steps: HarnessStep[];
  expect: {
    minMatches?: number;
    requiredFields?: string[];
  };
}

const repositoryPaths = createRepositoryPaths(findRepositoryRoot());
const casePath = process.argv[2] ?? "tests/harness/scenarios/find-layer-a-wall.json";
const harnessCase = JSON.parse(
  await readFile(resolve(repositoryPaths.repositoryRoot, casePath), "utf8")
) as HarnessCase;
const application = await createCadApplication({
  workspaceRoot: repositoryPaths.repositoryRoot
});
const runtime = createCadToolRuntime(application.capabilities);
let last: any = {};

for (const step of harnessCase.steps) {
  last = await runtime.call(step.tool, resolveArgs(step.args, harnessCase.fixture, last));
}

verifyExpectations(harnessCase, last);
console.log(JSON.stringify({ name: harnessCase.name, ok: true, result: last }, null, 2));

function resolveArgs(args: Record<string, unknown>, fixture: string, previous: any): Record<string, unknown> {
  const resolved: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(args)) {
    if (value === "$fixture") {
      resolved[key] = fixture;
    } else if (value === "$last.drawingId") {
      resolved[key] = previous.drawingId;
    } else {
      resolved[key] = value;
    }
  }
  return resolved;
}

function verifyExpectations(harnessCase: HarnessCase, result: any) {
  const matches = Array.isArray(result.matches) ? result.matches : [];
  if (harnessCase.expect.minMatches !== undefined && matches.length < harnessCase.expect.minMatches) {
    throw new Error(
      `${harnessCase.name}: expected at least ${harnessCase.expect.minMatches} matches, got ${matches.length}`
    );
  }

  for (const field of harnessCase.expect.requiredFields ?? []) {
    for (const match of matches) {
      if (!(field in match) || match[field] === undefined) {
        throw new Error(`${harnessCase.name}: match missing required field ${field}`);
      }
    }
  }
}
