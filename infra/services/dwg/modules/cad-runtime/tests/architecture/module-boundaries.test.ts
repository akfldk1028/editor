import assert from "node:assert/strict";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  extractImportSpecifiers,
  findModuleBoundaryViolations,
  scanWorkspaceModuleBoundaries
} from "../../src/architecture/moduleBoundaryChecker.js";

test("rejects imports that bypass public and feature boundaries", () => {
  const violations = findModuleBoundaryViolations([
    {
      importer: "packages/contracts/src/cad.ts",
      specifier: "../../../apps/workspace/src/shared/types"
    },
    {
      importer: "modules/cad-runtime/src/application/chat/chatService.ts",
      specifier: "../../../../../apps/workspace/src/shared/types"
    },
    {
      importer: "apps/workspace/src/shared/api/providerGatewayClient.ts",
      specifier: "../../../../../modules/cad-runtime/src/providers/contracts"
    },
    {
      importer: "apps/workspace/src/shared/types.ts",
      specifier: "../features/agent-chat/useProviderChat"
    },
    {
      importer: "apps/workspace/src/features/cad-viewer/CadViewer.tsx",
      specifier: "../drawing-explorer/useDrawingIndex"
    },
    {
      importer: "apps/workspace/src/app/App.tsx",
      specifier: "@dwg/contracts/src/cad"
    },
    {
      importer: "modules/cad-query/src/query.ts",
      specifier: "@dwg/cad-document/src/model"
    },
    {
      importer: "modules/cad-query/src/query.ts",
      specifier: "../../cad-edit/src/transaction"
    }
  ]);

  assert.deepEqual(
    violations.map((violation) => violation.rule),
    [
      "contracts-are-runtime-independent",
      "runtime-does-not-import-workspace",
      "workspace-does-not-import-runtime",
      "workspace-shared-does-not-import-features",
      "workspace-features-do-not-cross-import",
      "cross-module-import-uses-public-entrypoint",
      "cross-module-import-uses-public-entrypoint",
      "cross-module-import-uses-public-entrypoint"
    ]
  );
});

test("allows reusable CAD modules to use public package entrypoints", () => {
  const violations = findModuleBoundaryViolations([
    {
      importer: "modules/cad-query/src/query.ts",
      specifier: "@dwg/cad-document"
    },
    {
      importer: "modules/cad-query/src/query.ts",
      specifier: "@dwg/cad-edit"
    }
  ]);

  assert.deepEqual(violations, []);
});

test("extracts static dynamic imports", () => {
  assert.deepEqual(
    extractImportSpecifiers('const module = import("@dwg/contracts/src/cad")'),
    ["@dwg/contracts/src/cad"]
  );
});

test("allows contracts source files to be consumed only through their public entrypoint", () => {
  const violations = findModuleBoundaryViolations([
    {
      importer: "apps/workspace/src/app/App.tsx",
      specifier: "../../../../packages/contracts/src/cad"
    }
  ]);

  assert.deepEqual(
    violations.map((violation) => violation.rule),
    ["cross-module-import-uses-public-entrypoint"]
  );
});

test("current workspace respects enforced module boundaries", async () => {
  const violations = await scanWorkspaceModuleBoundaries(process.cwd());

  assert.deepEqual(violations, []);
});

test("workspace scan discovers imports in reusable module source roots", async (t) => {
  const workspace = await mkdtemp(join(tmpdir(), "dwg-module-boundary-"));
  t.after(() => rm(workspace, { recursive: true, force: true }));

  await Promise.all([
    mkdir(join(workspace, "packages/contracts/src"), { recursive: true }),
    mkdir(join(workspace, "modules/cad-runtime/src"), { recursive: true }),
    mkdir(join(workspace, "modules/cad-query/src"), { recursive: true }),
    mkdir(join(workspace, "apps/workspace/src"), { recursive: true })
  ]);
  await writeFile(
    join(workspace, "modules/cad-query/package.json"),
    JSON.stringify({ name: "@dwg/cad-query" })
  );
  await writeFile(
    join(workspace, "modules/cad-query/src/query.ts"),
    'import { x } from "@dwg/cad-document/src/model";'
  );

  const violations = await scanWorkspaceModuleBoundaries(workspace);

  assert.deepEqual(
    violations.map(({ importer, rule }) => ({ importer, rule })),
    [{
      importer: "modules/cad-query/src/query.ts",
      rule: "cross-module-import-uses-public-entrypoint"
    }]
  );
});

test("repository exposes explicit application and module roots", async () => {
  const root = JSON.parse(await readFile("package.json", "utf8"));
  const lock = JSON.parse(await readFile("package-lock.json", "utf8"));
  assert.deepEqual(root.workspaces, ["apps/*", "packages/*", "modules/*"]);
  assert.equal(
    Object.keys(lock.packages).some(
      (packagePath) => /^frontend(?:\/|$)/.test(packagePath)
    ),
    false
  );
  await access("apps/workspace/package.json");
  await access("modules/cad-runtime/src");
  await access("modules/dwg-parser/src");
  await assert.rejects(() => access("frontend"));
  await assert.rejects(() => access("agent"));
  await assert.rejects(() => access("backend"));
});

test("active setup documentation installs workspaces from the root", async () => {
  const setupDocs = await Promise.all([
    readFile("README.md", "utf8"),
    readFile("docs/architecture/ai-clone-handoff.md", "utf8")
  ]);

  for (const setupDoc of setupDocs) {
    assert.match(setupDoc, /npm install/);
    assert.doesNotMatch(setupDoc, /npm --prefix frontend install/);
  }
});
