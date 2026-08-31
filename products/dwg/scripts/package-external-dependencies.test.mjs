import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join, posix, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));

// packages/** are the surfaces a host repository may take on its own. A package
// that resolves an external dependency through the monorepo's hoisted
// node_modules installs cleanly here and fails in the host repository, so every
// runtime import a published surface makes must be declared by that surface.
const publicWorkspaceRoot = "packages";
const ignoredDirectories = new Set(["node_modules", "dist", "bin", "obj"]);
const sourcePattern = /\.(?:ts|tsx|mts|mjs|js)$/u;
const testPattern = /\.test\.(?:ts|tsx|mts|mjs|js)$/u;

test("public packages declare every external runtime import", async () => {
  for (const workspace of await findPublicPackages()) {
    const declared = new Set([
      ...Object.keys(workspace.manifest.dependencies ?? {}),
      ...Object.keys(workspace.manifest.peerDependencies ?? {})
    ]);
    for (const specifier of await collectExternalImports(workspace)) {
      assert.ok(
        declared.has(specifier),
        `${workspace.path} imports ${specifier} without declaring it; a host repository cannot resolve it`
      );
    }
  }
});

test("the scan reaches at least one declared external dependency", async () => {
  const packages = await findPublicPackages();
  assert.ok(packages.length > 0, "packages/** must contain workspace packages");
  const scanned = await Promise.all(packages.map((workspace) => collectExternalImports(workspace)));
  assert.ok(
    scanned.some((specifiers) => specifiers.size > 0),
    "the import scan found no external imports and would pass vacuously"
  );
});

async function collectExternalImports(workspace) {
  const specifiers = new Set();
  await walk(join(repositoryRoot, workspace.path));
  return specifiers;

  async function walk(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const entryPath = join(directory, entry.name);
      if (entry.isDirectory()) {
        if (!ignoredDirectories.has(entry.name)) await walk(entryPath);
        continue;
      }
      if (!sourcePattern.test(entry.name) || testPattern.test(entry.name)) continue;
      const source = await readFile(entryPath, "utf8");
      for (const match of source.matchAll(/from "([^"]+)"/gu)) {
        const specifier = match[1];
        if (specifier.startsWith(".") || specifier.startsWith("node:")) continue;
        const name = specifier.startsWith("@")
          ? specifier.split("/").slice(0, 2).join("/")
          : specifier.split("/")[0];
        if (name === workspace.manifest.name) continue;
        specifiers.add(name);
      }
    }
  }
}

async function findPublicPackages() {
  const packages = [];
  for (const entry of await readdir(join(repositoryRoot, publicWorkspaceRoot), { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const path = posix.join(publicWorkspaceRoot, entry.name);
    try {
      const manifest = JSON.parse(
        await readFile(join(repositoryRoot, path, "package.json"), "utf8")
      );
      packages.push({ path, manifest });
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  return packages;
}
