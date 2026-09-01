# ACadSharp CAD I/O adapter

This private adapter is the sole repository owner of ACadSharp document
mapping and writer invocation. The parser host consumes its read-side index
builder. `DwgIntelligence.CadIo.Host` reads one strict `cad-io/v1` request from
stdin and writes one bounded JSON response to stdout. `DxfWriter` and
`DwgWriter` are confined to `CadFileWriter`.

The TypeScript package root exports the process client and committed-lineage
mapper. It sends command DTOs only: snapshots, resolved before-state, raw CAD
bytes, provider data, and unknown fields never cross the process boundary.
Combined stdout/stderr and every JSON request are limited to 1 MiB.

Source drawings are read-only. Writers target a distinct temporary path and a
failed mapping or write does not produce a committed output. DXF is available
directly. DWG is denied unless a version-policy manifest path is supplied;
the later allowlist task verifies manifest content and tested DWG versions.

Focused verification:

```powershell
dotnet test modules/cad-io-acadsharp/tests/DwgIntelligence.CadIo.Tests/DwgIntelligence.CadIo.Tests.csproj --nologo
node --import tsx --test modules/cad-io-acadsharp/tests/process-client.test.ts
```
