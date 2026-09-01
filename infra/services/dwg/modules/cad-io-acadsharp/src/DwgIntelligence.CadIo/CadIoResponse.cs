namespace DwgIntelligence.CadIo;

public sealed record CadIoSuccessResponse(
    string Status,
    string Format,
    string Version,
    int EntityCount,
    IReadOnlyDictionary<string, string> CopiedHandleMap,
    IReadOnlyList<string> Warnings)
{
    public static CadIoSuccessResponse Create(
        string format,
        string version,
        int entityCount,
        IReadOnlyDictionary<string, string> copiedHandleMap,
        IReadOnlyList<string> warnings)
    {
        return new CadIoSuccessResponse(
            "ok",
            format,
            version,
            entityCount,
            copiedHandleMap,
            warnings);
    }
}

public sealed record CadIoErrorDetail(string Code, string Message);

public sealed record CadIoErrorResponse(
    string Status,
    CadIoErrorDetail Error)
{
    public static CadIoErrorResponse Create(string code)
    {
        return new CadIoErrorResponse(
            "error",
            new CadIoErrorDetail(code, "CAD I/O request failed."));
    }
}

public sealed class CadIoException : Exception
{
    public string Code { get; }

    public CadIoException(string code)
        : base("CAD I/O request failed.")
    {
        Code = code;
    }

    public CadIoException(string code, Exception innerException)
        : base("CAD I/O request failed.", innerException)
    {
        Code = code;
    }
}
