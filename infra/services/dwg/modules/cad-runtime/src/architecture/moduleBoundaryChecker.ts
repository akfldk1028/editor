import { readdir, readFile, stat } from "node:fs/promises";
import { join, posix, relative, resolve, sep } from "node:path";

export interface ModuleImport {
  importer: string;
  specifier: string;
}

export interface ModuleBoundaryViolation extends ModuleImport {
  importedModule: string;
  rule:
    | "contracts-are-runtime-independent"
    | "workspace-does-not-import-runtime"
    | "runtime-does-not-import-workspace"
    | "workspace-shared-does-not-import-features"
    | "workspace-features-do-not-cross-import"
    | "cross-module-import-uses-public-entrypoint";
}

export function findModuleBoundaryViolations(
  imports: readonly ModuleImport[]
): ModuleBoundaryViolation[] {
  return imports.flatMap((moduleImport) => {
    const importedModule = resolveModule(
      moduleImport.importer,
      moduleImport.specifier
    );
    const rule = findViolatedRule(
      moduleImport.importer,
      moduleImport.specifier,
      importedModule ?? moduleImport.specifier
    );
    return rule
      ? [{
          ...moduleImport,
          importedModule: importedModule ?? moduleImport.specifier,
          rule
        }]
      : [];
  });
}

export async function scanWorkspaceModuleBoundaries(workspace: string) {
  const sourceRoots = await findWorkspaceSourceRoots(workspace);
  const imports: ModuleImport[] = [];

  for (const sourceRoot of sourceRoots) {
    const absoluteRoot = resolve(workspace, sourceRoot);
    for (const file of await listTypeScriptFiles(absoluteRoot)) {
      const importer = toPosix(relative(workspace, file));
      const source = await readFile(file, "utf8");
      for (const specifier of extractImportSpecifiers(source)) {
        imports.push({ importer, specifier });
      }
    }
  }

  return findModuleBoundaryViolations(imports);
}

async function findWorkspaceSourceRoots(workspace: string) {
  const sourceRoots: string[] = [];

  for (const workspaceRoot of ["apps", "packages", "modules"]) {
    const directory = resolve(workspace, workspaceRoot);
    for (const entry of await readDirectories(directory)) {
      const packageRoot = resolve(directory, entry);
      const isModule = workspaceRoot === "modules";
      if (
        !isModule &&
        !await isFile(resolve(packageRoot, "package.json"))
      ) {
        continue;
      }

      const sourceRoot = resolve(packageRoot, "src");
      if (await isDirectory(sourceRoot)) {
        sourceRoots.push(toPosix(relative(workspace, sourceRoot)));
      }
    }
  }

  return sourceRoots;
}

function findViolatedRule(
  importer: string,
  specifier: string,
  importedModule: string
): ModuleBoundaryViolation["rule"] | null {
  if (specifier.startsWith("@dwg/contracts/")) {
    return "cross-module-import-uses-public-entrypoint";
  }
  if (/^@dwg\/[^/]+\/src(?:\/|$)/.test(specifier)) {
    return "cross-module-import-uses-public-entrypoint";
  }
  if (
    !importer.startsWith("packages/contracts/") &&
    importedModule.startsWith("packages/contracts/src/") &&
    specifier !== "@dwg/contracts"
  ) {
    return "cross-module-import-uses-public-entrypoint";
  }
  if (
    importer.startsWith("packages/contracts/") &&
    (importedModule.startsWith("modules/cad-runtime/") ||
      importedModule.startsWith("apps/workspace/"))
  ) {
    return "contracts-are-runtime-independent";
  }
  if (
    importer.startsWith("modules/cad-runtime/") &&
    importedModule.startsWith("apps/workspace/")
  ) {
    return "runtime-does-not-import-workspace";
  }
  if (
    importer.startsWith("apps/workspace/") &&
    importedModule.startsWith("modules/cad-runtime/")
  ) {
    return "workspace-does-not-import-runtime";
  }
  const importerModule = getTopLevelModule(importer);
  const importedTopLevelModule = getTopLevelModule(importedModule);
  if (
    importerModule &&
    importedTopLevelModule &&
    importerModule !== importedTopLevelModule
  ) {
    return "cross-module-import-uses-public-entrypoint";
  }
  if (
    importer.startsWith("apps/workspace/src/shared/") &&
    importedModule.startsWith("apps/workspace/src/features/")
  ) {
    return "workspace-shared-does-not-import-features";
  }

  const importerFeature = getFrontendFeature(importer);
  const importedFeature = getFrontendFeature(importedModule);
  if (
    importerFeature &&
    importedFeature &&
    importerFeature !== importedFeature
  ) {
    return "workspace-features-do-not-cross-import";
  }
  return null;
}

function resolveModule(importer: string, specifier: string) {
  if (specifier === "@dwg/contracts") {
    return "packages/contracts/src/index.ts";
  }
  if (specifier.startsWith("@dwg/contracts/")) {
    return `packages/contracts/src/${specifier.slice("@dwg/contracts/".length)}`;
  }
  if (!specifier.startsWith(".")) return null;
  return posix.normalize(posix.join(posix.dirname(importer), specifier));
}

function getFrontendFeature(path: string) {
  const match = /^apps\/workspace\/src\/features\/([^/]+)\//.exec(path);
  return match?.[1] ?? null;
}

function getTopLevelModule(path: string) {
  const match = /^modules\/([^/]+)\/src(?:\/|$)/.exec(path);
  return match?.[1] ?? null;
}

export function extractImportSpecifiers(source: string) {
  const specifiers: string[] = [];
  const importPattern =
    /\b(?:import|export)\s+(?:type\s+)?(?:[^"'`;]*?\s+from\s+)?["']([^"']+)["']/g;
  const dynamicImportPattern = /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g;
  for (const match of source.matchAll(importPattern)) {
    specifiers.push(match[1]);
  }
  for (const match of source.matchAll(dynamicImportPattern)) {
    specifiers.push(match[1]);
  }
  return [...new Set(specifiers)];
}

async function listTypeScriptFiles(directory: string): Promise<string[]> {
  const files: string[] = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...await listTypeScriptFiles(path));
    } else if (entry.isFile() && /\.(?:ts|tsx)$/.test(entry.name)) {
      files.push(path);
    }
  }
  return files;
}

async function readDirectories(directory: string) {
  try {
    const entries = await readdir(directory, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name);
  } catch (error) {
    if (isMissingPathError(error)) return [];
    throw error;
  }
}

async function isDirectory(path: string) {
  try {
    return (await stat(path)).isDirectory();
  } catch (error) {
    if (isMissingPathError(error)) return false;
    throw error;
  }
}

async function isFile(path: string) {
  try {
    return (await stat(path)).isFile();
  } catch (error) {
    if (isMissingPathError(error)) return false;
    throw error;
  }
}

function isMissingPathError(error: unknown): error is NodeJS.ErrnoException {
  return (
    error instanceof Error &&
    "code" in error &&
    (error as NodeJS.ErrnoException).code === "ENOENT"
  );
}

function toPosix(path: string) {
  return path.split(sep).join("/");
}
