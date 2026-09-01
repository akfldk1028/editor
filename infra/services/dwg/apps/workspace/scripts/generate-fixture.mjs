import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const workspaceRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(workspaceRoot, "../..");
const parserProject = resolve(
  repositoryRoot,
  "modules/dwg-parser/src/DwgIntelligence.DwgParser"
);
const source = resolve(
  repositoryRoot,
  "tests/fixtures/dwg/export_sample.dwg"
);
const destination = resolve(workspaceRoot, "public/data/export_sample.index.json");

const output = execFileSync(
  "dotnet",
  ["run", "--project", parserProject, "--no-launch-profile", "--", "index", source],
  { encoding: "utf8", maxBuffer: 20 * 1024 * 1024 }
);
const index = JSON.parse(output);

if (
  index.schemaVersion !== "cad-index/v0.2" ||
  index.source?.kind !== "dwg" ||
  index.entities?.length !== index.summary?.entityCount
) {
  throw new Error("Generated fixture does not match the verified DWG index contract");
}

mkdirSync(dirname(destination), { recursive: true });
writeFileSync(destination, `${JSON.stringify(index, null, 2)}\n`, "utf8");
console.log(`Generated ${destination} from unchanged DWG source (${index.entities.length} entities).`);
