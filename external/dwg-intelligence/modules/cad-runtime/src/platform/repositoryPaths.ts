import { existsSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export interface RepositoryPaths {
  repositoryRoot: string;
  parserProject: string;
  fixturesRoot: string;
  defaultDrawing: string;
  cadIoHostProject: string;
  dwgVersionManifest: string;
}

export interface RuntimePaths {
  workspace: string;
  drawingPath: string;
}

export function findRepositoryRoot(fromUrl = import.meta.url): string {
  let cursor = dirname(fileURLToPath(fromUrl));
  while (true) {
    const packagePath = join(cursor, "package.json");
    if (existsSync(packagePath)) {
      const manifest = JSON.parse(readFileSync(packagePath, "utf8"));
      if (manifest.name === "click-around") return cursor;
    }
    const parent = dirname(cursor);
    if (parent === cursor) {
      throw new Error("Click Around repository root was not found");
    }
    cursor = parent;
  }
}

export function createRepositoryPaths(repositoryRoot: string): RepositoryPaths {
  const root = resolve(repositoryRoot);
  return {
    repositoryRoot: root,
    parserProject: resolve(
      root,
      "modules/dwg-parser/src/DwgIntelligence.DwgParser/DwgIntelligence.DwgParser.csproj"
    ),
    fixturesRoot: resolve(root, "tests/fixtures"),
    defaultDrawing: resolve(root, "tests/fixtures/dwg/export_sample.dwg")
    ,
    cadIoHostProject: resolve(
      root,
      "modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgIntelligence.CadIo.Host.csproj"
    ),
    dwgVersionManifest: resolve(root, "tests/fixtures/dwg/roundtrip-manifest.json")
  };
}

export function createRuntimePaths(
  paths: RepositoryPaths,
  workspaceRoot?: string,
  drawingPath?: string
): RuntimePaths {
  return {
    workspace: resolve(workspaceRoot ?? paths.repositoryRoot),
    drawingPath: drawingPath ?? relative(paths.repositoryRoot, paths.defaultDrawing)
  };
}
