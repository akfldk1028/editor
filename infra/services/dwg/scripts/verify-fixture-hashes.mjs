import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));

export async function verifyFixtureManifest(manifestPath) {
  const manifest = JSON.parse(
    await readFile(resolve(repositoryRoot, manifestPath), "utf8")
  );
  for (const fixture of manifest.fixtures) {
    const bytes = await readFile(resolve(repositoryRoot, fixture.path));
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    if (bytes.byteLength !== fixture.bytes || sha256 !== fixture.sha256) {
      throw new Error(`Fixture integrity mismatch: ${fixture.id}`);
    }
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await verifyFixtureManifest(
    process.argv[2] ?? "tests/fixtures/manifest.json"
  );
}
