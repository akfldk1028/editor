import { mkdir, readdir, rm } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";

import { docsExportRoot, e2eExportRoot } from "./repositoryOutputPaths.js";

export default async function exportRootGlobalSetup() {
  const root = process.env.DWG_EXPORT_MODE === "docs" ? docsExportRoot : e2eExportRoot;
  const ownedParent = resolve(root, "../../");
  const ownedRelative = relative(ownedParent, root);
  if (
    !ownedRelative ||
    ownedRelative === ".." ||
    ownedRelative.startsWith(`..${sep}`) ||
    isAbsolute(ownedRelative)
  ) {
    throw new Error("Export root must be an exact child of tests/visual/test-results");
  }
  await rm(root, { recursive: true, force: true });
  await mkdir(root, { recursive: true });
  if ((await readdir(root)).length !== 0) {
    throw new Error("Export root preflight must be empty");
  }
  process.env.DWG_EXPORT_ROOT = root;
  return async () => {
    await rm(root, { recursive: true, force: true });
  };
}
