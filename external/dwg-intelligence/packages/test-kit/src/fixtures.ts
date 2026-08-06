import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import { extname, isAbsolute, relative, resolve } from "node:path";

export interface FixtureDescriptor {
  id: string;
  path: string;
  sha256: string;
  kind: "dwg" | "dxf";
}

interface FixtureManifestEntry {
  id: string;
  path: string;
  sha256: string;
}

interface FixtureManifest {
  fixtures: FixtureManifestEntry[];
}

export async function loadFixtureManifest(
  repositoryRoot: string
): Promise<FixtureDescriptor[]> {
  const canonicalRepositoryRoot = await realpath(repositoryRoot);
  const fixtureRoot = await realpath(
    resolve(canonicalRepositoryRoot, "tests", "fixtures")
  );
  const manifestPath = resolve(fixtureRoot, "manifest.json");
  const manifest = parseManifest(await readFile(manifestPath, "utf8"));

  const fixtures = await Promise.all(
    manifest.fixtures.map(async (fixture) => {
      const fixturePath = await resolveFixturePath(
        canonicalRepositoryRoot,
        fixtureRoot,
        fixture.path
      );
      const kind = fixtureKind(fixture.path);

      await assertFileHash(fixturePath, fixture.sha256);
      return kind === null
        ? null
        : {
            id: fixture.id,
            path: fixture.path,
            sha256: fixture.sha256,
            kind
          };
    })
  );
  return fixtures.filter(
    (fixture): fixture is FixtureDescriptor => fixture !== null
  );
}

export async function assertFileHash(
  path: string,
  expectedSha256: string
): Promise<void> {
  const bytes = await readFile(path);
  const actualSha256 = createHash("sha256").update(bytes).digest("hex");

  if (actualSha256 !== expectedSha256) {
    throw new Error(`Fixture hash mismatch: ${path}`);
  }
}

function parseManifest(value: string): FixtureManifest {
  const manifest: unknown = JSON.parse(value);
  if (!isRecord(manifest) || !Array.isArray(manifest.fixtures)) {
    throw new Error("Fixture manifest must contain a fixtures array");
  }

  return {
    fixtures: manifest.fixtures.map((fixture) => {
      if (
        !isRecord(fixture) ||
        typeof fixture.id !== "string" ||
        typeof fixture.path !== "string" ||
        typeof fixture.sha256 !== "string"
      ) {
        throw new Error("Fixture manifest entry is invalid");
      }

      return {
        id: fixture.id,
        path: fixture.path,
        sha256: fixture.sha256
      };
    })
  };
}

async function resolveFixturePath(
  repositoryRoot: string,
  fixtureRoot: string,
  fixturePath: string
): Promise<string> {
  if (isAbsolute(fixturePath)) {
    throw new Error("Fixture path must be relative to tests/fixtures");
  }

  const unresolvedPath = resolve(repositoryRoot, fixturePath);
  assertWithinFixtureRoot(fixtureRoot, unresolvedPath);

  const canonicalFixturePath = await realpath(unresolvedPath);
  assertWithinFixtureRoot(fixtureRoot, canonicalFixturePath);
  return canonicalFixturePath;
}

function assertWithinFixtureRoot(fixtureRoot: string, candidatePath: string): void {
  const candidateRelativePath = relative(fixtureRoot, candidatePath);
  if (
    candidateRelativePath === "" ||
    isAbsolute(candidateRelativePath) ||
    candidateRelativePath.startsWith("..")
  ) {
    throw new Error("Fixture path must remain within tests/fixtures");
  }
}

function fixtureKind(path: string): FixtureDescriptor["kind"] | null {
  const extension = extname(path).toLowerCase();
  if (extension === ".dwg" || extension === ".dxf") {
    return extension.slice(1) as FixtureDescriptor["kind"];
  }
  if (extension === ".json") {
    return null;
  }

  throw new Error(
    "Fixture path must name a DWG, DXF, or JSON file"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
