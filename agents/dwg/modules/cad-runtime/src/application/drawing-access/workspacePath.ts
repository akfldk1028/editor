import { existsSync, realpathSync } from "node:fs";
import { extname, isAbsolute, relative, resolve } from "node:path";

export function resolveWorkspaceCadPath(
  workspaceRoot: string,
  configuredPath: string
) {
  const root = realpathSync(resolve(workspaceRoot));
  const lexicalPath = resolve(root, configuredPath);
  assertContained(root, lexicalPath);

  const extension = extname(lexicalPath).toLowerCase();
  if (extension !== ".dwg" && extension !== ".dxf") {
    throw new Error(`Unsupported drawing format: ${extension || "(none)"}`);
  }
  if (!existsSync(lexicalPath)) {
    throw new Error(`Drawing not found: ${configuredPath}`);
  }

  const drawingPath = realpathSync(lexicalPath);
  assertContained(root, drawingPath);
  return drawingPath;
}

function assertContained(root: string, drawingPath: string) {
  const relativePath = relative(root, drawingPath);
  if (
    relativePath === ".." ||
    relativePath.startsWith(`..\\`) ||
    relativePath.startsWith("../") ||
    isAbsolute(relativePath)
  ) {
    throw new Error("Drawing path is outside workspace");
  }
}
