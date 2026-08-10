import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { resolve } from "node:path";

import {
  isCadEntityIndexV02,
  type CadEntityIndexV02
} from "@dwg/contracts";
import {
  createRepositoryPaths,
  findRepositoryRoot
} from "../../platform/repositoryPaths.js";

const execFileAsync = promisify(execFile);
const defaultParserProject = createRepositoryPaths(
  findRepositoryRoot(import.meta.url)
).parserProject;
const indexByCacheKey = new Map<string, Promise<CadEntityIndexV02>>();

export type DwgParserRunner = (
  fullPath: string,
  parserProject: string
) => Promise<CadEntityIndexV02>;

export interface DwgIndexerOptions {
  parserProject?: string;
  runParser?: DwgParserRunner;
}

export async function buildIndexFromDwgFile(
  path: string,
  options: DwgIndexerOptions = {}
): Promise<CadEntityIndexV02> {
  const fullPath = resolve(path);
  const parserProject = resolve(options.parserProject ?? defaultParserProject);
  const cacheKey = JSON.stringify([fullPath, parserProject]);
  const existing = indexByCacheKey.get(cacheKey);
  if (existing) return existing;

  const pending = (options.runParser ?? runDwgParser)(
    fullPath,
    parserProject
  ).catch((error) => {
    indexByCacheKey.delete(cacheKey);
    throw error;
  });
  indexByCacheKey.set(cacheKey, pending);
  return pending;
}

async function runDwgParser(
  fullPath: string,
  parserProject: string
): Promise<CadEntityIndexV02> {
  let stdout: string;
  try {
    const result = await execFileAsync(
      "dotnet",
      [
        "run",
        "--project",
        parserProject,
        "--no-build",
        "--no-launch-profile",
        "--",
        "index",
        fullPath
      ],
      {
        encoding: "utf8",
        maxBuffer: 20 * 1024 * 1024,
        windowsHide: true
      }
    );
    stdout = result.stdout;
  } catch (error) {
    const processError = error as Error & { stderr?: string };
    const detail = processError.stderr?.trim() || processError.message;
    throw new Error(`DWG parser failed: ${detail}`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    throw new Error("DWG parser returned invalid JSON");
  }

  // The ACadSharp parser emits cad-index/v0.2 for both formats and reports the
  // source extension it read. Save verification reopens written DXF copies
  // through this parser, so a "dxf" source is expected here.
  if (
    !isCadEntityIndexV02(parsed)
    || (parsed.source.kind !== "dwg" && parsed.source.kind !== "dxf")
  ) {
    throw new Error("DWG parser returned an incompatible cad-index document");
  }

  return parsed;
}
