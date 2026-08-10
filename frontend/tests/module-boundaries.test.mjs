import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import test from "node:test";

const sourceRoot = resolve(import.meta.dirname, "../src");
const importPattern = /(?:import|export)\s+(?:[^"']*?\s+from\s+)?["']([^"']+)["']/g;

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map((entry) => {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) return sourceFiles(path);
      return /\.[cm]?[jt]sx?$/.test(entry.name) ? [path] : [];
    }),
  );
  return nested.flat();
}

test("frontend relative imports stay inside the frontend source boundary", async () => {
  for (const file of await sourceFiles(sourceRoot)) {
    const source = await readFile(file, "utf8");
    for (const match of source.matchAll(importPattern)) {
      const specifier = match[1];
      if (!specifier.startsWith(".")) continue;
      const target = resolve(dirname(file), specifier);
      assert.equal(
        relative(sourceRoot, target).startsWith(".."),
        false,
        `${relative(sourceRoot, file)} crosses the frontend source boundary via ${specifier}`,
      );
    }
  }
});

test("DWG workspace resolves through its public package", () => {
  const resolved = import.meta.resolve("@click-around/workspace");
  assert.match(
    resolved,
    /node_modules[\\/]@click-around[\\/]workspace[\\/]src[\\/]public\.ts$/,
  );
});
