import assert from "node:assert/strict";
import {
  access,
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  rm,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, posix, resolve } from "node:path";
import test from "node:test";

const workspaceRoots = ["apps", "packages", "modules"];
const wholeApplicationWorkspaces = new Set(["apps/workspace"]);

test("every declared workspace entrypoint exists", async () => {
  await validateWorkspaceEntrypoints(".");
});

test("reusable workspaces require src/index.ts", async (t) => {
  const workspace = await mkdtemp(join(tmpdir(), "dwg-entrypoint-"));
  t.after(() => rm(workspace, { recursive: true, force: true }));

  await Promise.all([
    mkdir(join(workspace, "apps"), { recursive: true }),
    mkdir(join(workspace, "packages"), { recursive: true }),
    mkdir(join(workspace, "modules/cad-query/src"), { recursive: true })
  ]);
  await writeFile(
    join(workspace, "modules/cad-query/package.json"),
    JSON.stringify({
      name: "@dwg/cad-query",
      exports: { ".": "./src/index.ts" }
    })
  );

  await assert.rejects(
    () => validateWorkspaceEntrypoints(workspace),
    /modules\/cad-query.*src\/index\.ts/
  );
});

test("reusable workspaces export src/index.ts from the package root", async (t) => {
  const workspace = await mkdtemp(join(tmpdir(), "dwg-root-export-"));
  t.after(() => rm(workspace, { recursive: true, force: true }));

  await Promise.all([
    mkdir(join(workspace, "apps"), { recursive: true }),
    mkdir(join(workspace, "packages"), { recursive: true }),
    mkdir(join(workspace, "modules/cad-query/src"), { recursive: true })
  ]);
  await writeFile(
    join(workspace, "modules/cad-query/package.json"),
    JSON.stringify({
      name: "@dwg/cad-query",
      exports: { ".": "./src/query.ts" }
    })
  );
  await writeFile(
    join(workspace, "modules/cad-query/src/index.ts"),
    "export const index = true;"
  );
  await writeFile(
    join(workspace, "modules/cad-query/src/query.ts"),
    "export const query = true;"
  );

  await assert.rejects(
    () => validateWorkspaceEntrypoints(workspace),
    /modules\/cad-query.*package root.*src\/index\.ts/
  );
});

test("root test command discovers package, module, workspace unit, and script tests", async () => {
  const root = JSON.parse(await readFile("package.json", "utf8"));

  assert.match(root.scripts.test, /"packages\/\*\*\/\*.test\.ts"/);
  assert.match(root.scripts.test, /"modules\/\*\*\/\*.test\.ts"/);
  assert.match(root.scripts.test, /"apps\/workspace\/tests\/unit\/\*\*\/\*.test\.ts"/);
  assert.match(root.scripts.test, /"scripts\/\*\*\/\*.test\.mjs"/);
});

async function validateWorkspaceEntrypoints(root) {
  for (const workspace of await findWorkspacePackages(root)) {
    if (wholeApplicationWorkspaces.has(workspace.path)) continue;

    const publicEntrypoint = resolve(workspace.absolutePath, "src/index.ts");
    try {
      await access(publicEntrypoint);
    } catch {
      throw new Error(`${workspace.path} must provide src/index.ts`);
    }

    const rootEntrypoints = packageRootEntrypoints(workspace.manifest.exports);
    if (
      rootEntrypoints.length === 0 ||
      rootEntrypoints.some(
        (entrypoint) => posix.normalize(entrypoint) !== "src/index.ts"
      )
    ) {
      throw new Error(
        `${workspace.path} package root must export src/index.ts`
      );
    }

    for (const entrypoint of collectEntrypointFiles(workspace.manifest.exports)) {
      await access(resolve(workspace.absolutePath, entrypoint));
    }
  }
}

async function findWorkspacePackages(root = ".") {
  const packages = [];
  const absoluteRoot = resolve(root);
  for (const workspaceRoot of workspaceRoots) {
    const entries = await readDirectories(resolve(absoluteRoot, workspaceRoot));
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;

      const path = posix.join(workspaceRoot, entry.name);
      const absolutePath = resolve(absoluteRoot, path);
      try {
        const manifest = JSON.parse(
          await readFile(join(absolutePath, "package.json"), "utf8")
        );
        packages.push({ path, absolutePath, manifest });
      } catch (error) {
        if (error?.code !== "ENOENT") throw error;
      }
    }
  }
  return packages;
}

async function readDirectories(directory) {
  try {
    return await readdir(directory, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
}

function packageRootEntrypoints(exports) {
  if (!exports || typeof exports !== "object" || Array.isArray(exports)) {
    return normalizeEntrypoints(collectEntrypointFiles(exports));
  }

  const hasSubpathKeys = Object.keys(exports).some((key) => key.startsWith("."));
  return normalizeEntrypoints(
    collectEntrypointFiles(hasSubpathKeys ? exports["."] : exports)
  );
}

function normalizeEntrypoints(entrypoints) {
  return entrypoints.map((entrypoint) => entrypoint.replace(/^\.\//, ""));
}

function collectEntrypointFiles(value) {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(collectEntrypointFiles);
  if (!value || typeof value !== "object") return [];
  return Object.values(value).flatMap(collectEntrypointFiles);
}
