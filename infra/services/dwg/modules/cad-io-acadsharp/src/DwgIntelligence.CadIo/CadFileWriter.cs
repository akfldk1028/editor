using ACadSharp;
using ACadSharp.IO;

namespace DwgIntelligence.CadIo;

public static class CadFileWriter
{
    public static CadIoSuccessResponse Write(
        CadIoRequest request,
        DwgVersionPolicy? dwgVersionPolicy = null)
    {
        if (request.Format == "dwg" && dwgVersionPolicy is null)
        {
            throw new CadIoException("DWG_POLICY_NOT_CONFIGURED");
        }
        if (
            request.Format == "dwg"
            && !dwgVersionPolicy!.IsAllowed(request.Version))
        {
            throw new CadIoException("DWG_VERSION_NOT_ALLOWLISTED");
        }
        if (!File.Exists(request.SourcePath))
        {
            throw new CadIoException("CAD_SOURCE_NOT_FOUND");
        }
        if (File.Exists(request.TemporaryOutputPath))
        {
            throw new CadIoException("CAD_OUTPUT_EXISTS");
        }
        string? outputDirectory = Path.GetDirectoryName(
            request.TemporaryOutputPath);
        if (
            string.IsNullOrEmpty(outputDirectory)
            || !Directory.Exists(outputDirectory))
        {
            throw new CadIoException("CAD_OUTPUT_DIRECTORY_INVALID");
        }

        CadDocument document = ReadSource(request.SourcePath);
        if (!Enum.TryParse(request.Version, out ACadVersion version))
        {
            throw new CadIoException("CAD_VERSION_UNSUPPORTED");
        }
        document.Header.Version = version;
        CommandMappingResult mapping = CommandMapper.Apply(
            document,
            request.Lineage);
        document.UpdateDxfClasses(reset: false);

        try
        {
            if (request.Format == "dxf")
            {
                DxfWriter.Write(
                    request.TemporaryOutputPath,
                    document);
            }
            else
            {
                DwgWriter.Write(
                    request.TemporaryOutputPath,
                    document);
            }
        }
        catch (Exception exception)
        {
            TryDelete(request.TemporaryOutputPath);
            throw new CadIoException("CAD_WRITE_FAILED", exception);
        }

        // Count what the CAD index counts: entities reachable through layouts,
        // deduplicated by handle. Summing every block record also counts block
        // definition contents, which the index never reports, so verification
        // could never match a real drawing.
        int entityCount = LayoutEntityEnumerator
            .Enumerate(document)
            .Entities
            .Count;
        return CadIoSuccessResponse.Create(
            request.Format,
            document.Header.VersionString,
            entityCount,
            mapping.CopiedHandleMap,
            mapping.Warnings);
    }

    private static CadDocument ReadSource(string path)
    {
        try
        {
            return Path.GetExtension(path).ToLowerInvariant() switch
            {
                ".dxf" => DxfReader.Read(path),
                ".dwg" => DwgReader.Read(path),
                _ => throw new CadIoException(
                    "CAD_SOURCE_FORMAT_UNSUPPORTED")
            };
        }
        catch (CadIoException)
        {
            throw;
        }
        catch (Exception exception)
        {
            throw new CadIoException("CAD_SOURCE_READ_FAILED", exception);
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch
        {
            // The later save coordinator owns quarantine.
        }
    }
}
