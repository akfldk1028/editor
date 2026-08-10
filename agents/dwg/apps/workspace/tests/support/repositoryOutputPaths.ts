import { dirname, isAbsolute, posix, relative, resolve, sep, win32 } from "node:path";
import { fileURLToPath } from "node:url";

const workspaceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const repositoryRoot = resolve(workspaceRoot, "../..");

export const documentationCaptureDirectory = resolve(
  repositoryRoot,
  "docs/ui-captures"
);

const exportRootsDirectory = resolve(
  repositoryRoot,
  "tests/visual/test-results/export-roots"
);
export const e2eExportRoot = resolve(exportRootsDirectory, `e2e-${process.pid}`);
export const docsExportRoot = resolve(exportRootsDirectory, `docs-${process.pid}`);

export function resolveOwnedFile(rootDirectory: string, fileName: string) {
  const root = resolve(rootDirectory);
  const pathSegments = fileName.split(/[\\/]+/);

  if (
    !fileName ||
    isAbsolute(fileName) ||
    win32.isAbsolute(fileName) ||
    posix.isAbsolute(fileName) ||
    pathSegments.includes("..")
  ) {
    throw new Error("Output filename must remain within its owned output directory");
  }

  const outputPath = resolve(root, fileName);
  const outputRelativePath = relative(root, outputPath);

  if (
    !outputRelativePath ||
    outputRelativePath === ".." ||
    outputRelativePath.startsWith(`..${sep}`) ||
    isAbsolute(outputRelativePath) ||
    win32.isAbsolute(outputRelativePath) ||
    posix.isAbsolute(outputRelativePath)
  ) {
    throw new Error("Output filename must remain within its owned output directory");
  }

  return outputPath;
}

export function documentationCapturePath(fileName: string) {
  return resolveOwnedFile(documentationCaptureDirectory, fileName);
}

export const e2eArtifactDirectory = resolve(
  repositoryRoot,
  "tests/visual/test-results/e2e-artifacts"
);

export function e2eArtifactPath(fileName: string) {
  return resolveOwnedFile(e2eArtifactDirectory, fileName);
}

export function oauthArtifactPath(provider: "codex" | "claude") {
  return resolveOwnedFile(
    resolve(repositoryRoot, "tests/visual/test-results/live-oauth"),
    `oauth-${provider}-persistent-browser-e2e.png`
  );
}
