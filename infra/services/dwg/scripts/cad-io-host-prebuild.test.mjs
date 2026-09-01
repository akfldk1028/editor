import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("official Save As entrypoints prebuild the shared CAD I/O host once", async () => {
  const manifest = JSON.parse(await readFile("package.json", "utf8"));
  const scripts = manifest.scripts;

  assert.equal(
    scripts["build:cad-io-host"],
    "dotnet build modules/cad-io-acadsharp/src/DwgIntelligence.CadIo.Host/DwgIntelligence.CadIo.Host.csproj --nologo"
  );
  for (const hook of ["pretest", "premcp", "pregateway"]) {
    assert.match(scripts[hook], /npm run build:cad-io-host/u, hook);
  }
  assert.match(
    scripts.preskill,
    /DwgIntelligence\.CadIo\.Host\.csproj --nologo --verbosity quiet/u
  );
});
