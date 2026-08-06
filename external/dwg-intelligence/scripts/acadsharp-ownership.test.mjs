import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { join, relative } from "node:path";
import test from "node:test";

const adapterRoot = "modules/cad-io-acadsharp";
const mappingTypes = [
  "DwgIndexBuilder",
  "EntityGeometryExtractor",
  "LayoutEntityEnumerator"
];

test("ACadSharp document-to-index mapping has one adapter owner", async () => {
  const definitions = await findDefinitions("modules", mappingTypes);

  for (const typeName of mappingTypes) {
    const locations = definitions.get(typeName) ?? [];
    assert.deepEqual(locations.length, 1, `${typeName}: ${locations.join(", ")}`);
    assert.ok(
      locations[0].startsWith(`${adapterRoot}/`),
      `${typeName} must be owned by ${adapterRoot}, found ${locations[0]}`
    );
  }
});

async function findDefinitions(root, typeNames) {
  const definitions = new Map(typeNames.map((typeName) => [typeName, []]));
  for (const file of await listFiles(root)) {
    if (!file.endsWith(".cs")) continue;

    const source = await readFile(file, "utf8");
    for (const typeName of typeNames) {
      const pattern = new RegExp(`\\b(?:public|internal)\\s+(?:static\\s+)?class\\s+${typeName}\\b`);
      if (pattern.test(source)) {
        definitions.get(typeName).push(relative(".", file).replaceAll("\\", "/"));
      }
    }
  }
  return definitions;
}

async function listFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const path = join(directory, entry.name);
      return entry.isDirectory() ? listFiles(path) : [path];
    })
  );
  return nested.flat();
}
