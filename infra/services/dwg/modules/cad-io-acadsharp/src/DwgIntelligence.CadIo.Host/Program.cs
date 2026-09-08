using System.Text;
using System.Text.Json;
using DwgIntelligence.CadIo;

const string genericDiagnostic = "CAD I/O request failed.";
var jsonOptions = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase
};

try
{
    if (IsProbeMode(args))
    {
        DwgVersionProbe.Run(args[1], args[2]);
        return 0;
    }
    string? manifest = ParseManifestArgument(args);
    DwgVersionPolicy? dwgVersionPolicy = manifest is null
        ? null
        : DwgVersionPolicy.Load(manifest);
    string requestJson = ReadSingleRequest();
    CadIoRequest request = CadIoRequest.Parse(requestJson);
    CadIoSuccessResponse response = CadFileWriter.Write(
        request,
        dwgVersionPolicy);
    WriteBoundedJson(response);
    return 0;
}
catch (CadIoException exception)
{
    WriteBoundedJson(CadIoErrorResponse.Create(exception.Code));
    Console.Error.WriteLine(genericDiagnostic);
    return 1;
}
catch
{
    WriteBoundedJson(CadIoErrorResponse.Create("CAD_IO_FAILED"));
    Console.Error.WriteLine(genericDiagnostic);
    return 1;
}

string ReadSingleRequest()
{
    Stream input = Console.OpenStandardInput();
    using var buffer = new MemoryStream();
    byte[] chunk = new byte[16_384];
    while (true)
    {
        int read = input.Read(chunk, 0, chunk.Length);
        if (read == 0)
        {
            break;
        }
        if (buffer.Length + read > CadIoRequest.MaxJsonBytes)
        {
            throw new CadIoException("CAD_REQUEST_LIMIT");
        }
        buffer.Write(chunk, 0, read);
    }
    try
    {
        return new UTF8Encoding(false, true).GetString(buffer.ToArray());
    }
    catch (DecoderFallbackException exception)
    {
        throw new CadIoException("CAD_REQUEST_INVALID", exception);
    }
}

string? ParseManifestArgument(string[] arguments)
{
    if (arguments.Length == 0)
    {
        return null;
    }
    if (
        arguments.Length != 2
        || arguments[0] != "--dwg-policy-manifest"
        || !Path.IsPathFullyQualified(arguments[1]))
    {
        throw new CadIoException("CAD_REQUEST_INVALID");
    }
    return arguments[1];
}

bool IsProbeMode(string[] arguments)
{
    if (
        arguments.Length > 0
        && arguments[0] == "--probe-versions")
    {
        if (arguments.Length != 3)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return true;
    }
    return false;
}

void WriteBoundedJson<T>(T response)
{
    string json = JsonSerializer.Serialize(response, jsonOptions);
    if (Encoding.UTF8.GetByteCount(json) > CadIoRequest.MaxJsonBytes)
    {
        throw new CadIoException("CAD_RESPONSE_LIMIT");
    }
    Console.Out.WriteLine(json);
}
