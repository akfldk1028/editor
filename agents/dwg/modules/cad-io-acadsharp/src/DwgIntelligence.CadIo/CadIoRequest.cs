using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace DwgIntelligence.CadIo;

public sealed record CadIoRequest(
    string SchemaVersion,
    string Operation,
    string SourcePath,
    string TemporaryOutputPath,
    string Format,
    string Version,
    IReadOnlyList<CadIoWriteTransaction> Lineage)
{
    public const int MaxJsonBytes = 1_048_576;
    public const int MaxCommands = 10_000;
    public const long MaxSafeRevision = 9_007_199_254_740_991;

    private const string UuidPatternText =
        "[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
    private static readonly Regex UuidPattern = new(
        $"^{UuidPatternText}$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex HandlePattern = new(
        "^[1-9A-F][0-9A-F]{0,15}$",
        RegexOptions.CultureInvariant);
    private static readonly Regex TemporaryIdPattern = new(
        $"^copy:(?<transaction>{UuidPatternText}):(?<command>{UuidPatternText}):(?<index>0|[1-9][0-9]*)$",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex VersionPattern = new(
        "^AC[0-9]{4}$",
        RegexOptions.CultureInvariant);
    private static readonly Regex LayerIdPattern = new(
        "^layer:(?:imported|created):[A-Za-z0-9_-]+$",
        RegexOptions.CultureInvariant);

    public static CadIoRequest Parse(string json)
    {
        int byteCount;
        try
        {
            byteCount = new UTF8Encoding(false, true).GetByteCount(json);
        }
        catch (EncoderFallbackException exception)
        {
            throw new CadIoException("CAD_REQUEST_INVALID", exception);
        }
        if (byteCount > MaxJsonBytes)
        {
            throw new CadIoException("CAD_REQUEST_LIMIT");
        }

        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(
                json,
                new JsonDocumentOptions
                {
                    AllowTrailingCommas = false,
                    CommentHandling = JsonCommentHandling.Disallow,
                    MaxDepth = 64
                });
        }
        catch (JsonException exception)
        {
            throw new CadIoException("CAD_REQUEST_INVALID", exception);
        }

        using (document)
        {
            try
            {
                RejectDuplicateProperties(document.RootElement);
                return ParseRoot(document.RootElement);
            }
            catch (CadIoException)
            {
                throw;
            }
            catch (Exception exception) when (
                exception is InvalidOperationException
                or FormatException
                or OverflowException
                or ArgumentException)
            {
                throw new CadIoException(
                    "CAD_REQUEST_INVALID",
                    exception);
            }
        }
    }

    private static CadIoRequest ParseRoot(JsonElement root)
    {
        RequireObject(
            root,
            "schemaVersion",
            "operation",
            "sourcePath",
            "temporaryOutputPath",
            "format",
            "version",
            "lineage");
        string schemaVersion = RequiredString(root, "schemaVersion", 64);
        string operation = RequiredString(root, "operation", 64);
        string sourcePath = RequiredString(root, "sourcePath", 32_767);
        string outputPath = RequiredString(
            root,
            "temporaryOutputPath",
            32_767);
        string format = RequiredString(root, "format", 16);
        string version = RequiredString(root, "version", 16);
        if (
            schemaVersion != "cad-io/v1"
            || operation != "write-copy"
            || (format != "dxf" && format != "dwg")
            || !VersionPattern.IsMatch(version)
            || !Path.IsPathFullyQualified(sourcePath)
            || !Path.IsPathFullyQualified(outputPath)
            || StringComparer.OrdinalIgnoreCase.Equals(
                Path.GetFullPath(sourcePath),
                Path.GetFullPath(outputPath)))
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return new CadIoRequest(
            schemaVersion,
            operation,
            sourcePath,
            outputPath,
            format,
            version,
            ParseLineage(root.GetProperty("lineage")));
    }

    private static IReadOnlyList<CadIoWriteTransaction> ParseLineage(
        JsonElement element)
    {
        if (element.ValueKind != JsonValueKind.Array)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        var transactions = new List<CadIoWriteTransaction>();
        var transactionIds = new HashSet<string>(
            StringComparer.OrdinalIgnoreCase);
        var temporaryIds = new HashSet<string>(StringComparer.Ordinal);
        long expectedRevision = 0;
        int commandCount = 0;
        foreach (JsonElement item in element.EnumerateArray())
        {
            RequireObject(
                item,
                "transactionId",
                "beforeRevision",
                "afterRevision",
                "commands");
            string transactionId = RequiredString(
                item,
                "transactionId",
                64);
            long beforeRevision = RequiredRevision(
                item,
                "beforeRevision");
            long afterRevision = RequiredRevision(item, "afterRevision");
            if (
                !UuidPattern.IsMatch(transactionId)
                || !transactionIds.Add(transactionId)
                || beforeRevision != expectedRevision
                || afterRevision != beforeRevision + 1)
            {
                throw new CadIoException("CAD_LINEAGE_INVALID");
            }
            expectedRevision = afterRevision;
            JsonElement commandsElement = item.GetProperty("commands");
            if (commandsElement.ValueKind != JsonValueKind.Array)
            {
                throw new CadIoException("CAD_REQUEST_INVALID");
            }
            var commands = new List<CadIoWriteCommand>();
            foreach (
                JsonElement commandElement
                in commandsElement.EnumerateArray())
            {
                commandCount++;
                if (commandCount > MaxCommands)
                {
                    throw new CadIoException("CAD_REQUEST_LIMIT");
                }
                commands.Add(ParseCommand(
                    commandElement,
                    transactionId,
                    temporaryIds));
            }
            transactions.Add(new CadIoWriteTransaction(
                transactionId,
                beforeRevision,
                afterRevision,
                commands));
        }
        return transactions;
    }

    private static CadIoWriteCommand ParseCommand(
        JsonElement element,
        string transactionId,
        ISet<string> temporaryIds)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        string kind = RequiredString(element, "kind", 64);
        switch (kind)
        {
            case "layer.create":
                RequireObject(
                    element,
                    "kind",
                    "layerId",
                    "name",
                    "color");
                return new LayerCreateCommand(
                    RequireLayerId(element),
                    RequiredString(element, "name", 255),
                    RequiredColor(element, "color"));
            case "layer.update":
                RequireObject(
                    element,
                    ["kind", "layerId"],
                    ["name", "color", "visible", "frozen", "locked"]);
                string? name = OptionalString(element, "name", 255);
                int? color = OptionalColor(element, "color");
                bool? visible = OptionalBoolean(element, "visible");
                bool? frozen = OptionalBoolean(element, "frozen");
                bool? locked = OptionalBoolean(element, "locked");
                if (
                    name is null
                    && color is null
                    && visible is null
                    && frozen is null
                    && locked is null)
                {
                    throw new CadIoException("CAD_REQUEST_INVALID");
                }
                return new LayerUpdateCommand(
                    RequireLayerId(element),
                    name,
                    color,
                    visible,
                    frozen,
                    locked);
            case "text.replace":
                RequireObject(
                    element,
                    "kind",
                    "handle",
                    "value");
                return new TextReplaceCommand(
                    RequireHandle(element.GetProperty("handle")),
                    RequiredString(
                        element,
                        "value",
                        16_384,
                        allowEmpty: true));
            case "entity.move":
                RequireObject(
                    element,
                    "kind",
                    "handles",
                    "delta");
                return new EntityMoveCommand(
                    RequireHandles(element.GetProperty("handles")),
                    RequirePoint(element.GetProperty("delta")));
            case "entity.copy":
                RequireObject(
                    element,
                    "kind",
                    "sourceHandles",
                    "temporaryIds",
                    "delta");
                IReadOnlyList<string> sourceHandles = RequireHandles(
                    element.GetProperty("sourceHandles"));
                IReadOnlyList<string> copies = RequireTemporaryIds(
                    element.GetProperty("temporaryIds"),
                    transactionId,
                    temporaryIds);
                if (sourceHandles.Count != copies.Count)
                {
                    throw new CadIoException("CAD_REQUEST_INVALID");
                }
                return new EntityCopyCommand(
                    sourceHandles,
                    copies,
                    RequirePoint(element.GetProperty("delta")));
            case "entity.delete":
                RequireObject(element, "kind", "handles");
                return new EntityDeleteCommand(
                    RequireHandles(element.GetProperty("handles")));
            default:
                throw new CadIoException("CAD_REQUEST_INVALID");
        }
    }

    private static IReadOnlyList<string> RequireHandles(
        JsonElement element)
    {
        if (
            element.ValueKind != JsonValueKind.Array
            || element.GetArrayLength() is < 1 or > 200)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        var handles = new List<string>();
        var unique = new HashSet<string>(StringComparer.Ordinal);
        foreach (JsonElement item in element.EnumerateArray())
        {
            string handle = RequireHandle(item);
            if (!unique.Add(handle))
            {
                throw new CadIoException("CAD_REQUEST_INVALID");
            }
            handles.Add(handle);
        }
        return handles;
    }

    private static IReadOnlyList<string> RequireTemporaryIds(
        JsonElement element,
        string transactionId,
        ISet<string> allIds)
    {
        if (
            element.ValueKind != JsonValueKind.Array
            || element.GetArrayLength() is < 1 or > 200)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        var ids = new List<string>();
        foreach (JsonElement item in element.EnumerateArray())
        {
            string id = ElementString(item, 256);
            Match match = TemporaryIdPattern.Match(id);
            if (
                !match.Success
                || !StringComparer.OrdinalIgnoreCase.Equals(
                    match.Groups["transaction"].Value,
                    transactionId)
                || !int.TryParse(
                    match.Groups["index"].Value,
                    NumberStyles.None,
                    CultureInfo.InvariantCulture,
                    out int entityIndex)
                || !allIds.Add(id))
            {
                throw new CadIoException("CAD_REQUEST_INVALID");
            }
            ids.Add(id);
        }
        return ids;
    }

    private static CadPoint3 RequirePoint(JsonElement element)
    {
        if (
            element.ValueKind != JsonValueKind.Array
            || element.GetArrayLength() != 3)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        double[] coordinates = element
            .EnumerateArray()
            .Select(item => item.GetDouble())
            .ToArray();
        if (coordinates.Any(value => !double.IsFinite(value)))
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return new CadPoint3(
            coordinates[0],
            coordinates[1],
            coordinates[2]);
    }

    private static string RequireLayerId(JsonElement element)
    {
        string layerId = RequiredString(element, "layerId", 512);
        if (!LayerIdPattern.IsMatch(layerId))
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return layerId;
    }

    private static string RequireHandle(JsonElement element)
    {
        string handle = ElementString(element, 32);
        if (
            !HandlePattern.IsMatch(handle)
            || !ulong.TryParse(
                handle,
                NumberStyles.HexNumber,
                CultureInfo.InvariantCulture,
                out ulong parsed)
            || parsed == 0)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return handle;
    }

    private static int RequiredColor(
        JsonElement element,
        string name)
    {
        int color = element.GetProperty(name).GetInt32();
        if (color is < 1 or > 255)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return color;
    }

    private static int? OptionalColor(
        JsonElement element,
        string name)
    {
        return element.TryGetProperty(name, out _)
            ? RequiredColor(element, name)
            : null;
    }

    private static bool? OptionalBoolean(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(name, out JsonElement value))
        {
            return null;
        }
        if (
            value.ValueKind != JsonValueKind.True
            && value.ValueKind != JsonValueKind.False)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return value.GetBoolean();
    }

    private static long RequiredRevision(
        JsonElement element,
        string name)
    {
        long value = element.GetProperty(name).GetInt64();
        if (value is < 0 or > MaxSafeRevision)
        {
            throw new CadIoException("CAD_LINEAGE_INVALID");
        }
        return value;
    }

    private static string RequiredString(
        JsonElement element,
        string name,
        int maxLength,
        bool allowEmpty = false)
    {
        if (!element.TryGetProperty(name, out JsonElement value))
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return ElementString(value, maxLength, allowEmpty);
    }

    private static string? OptionalString(
        JsonElement element,
        string name,
        int maxLength)
    {
        return element.TryGetProperty(name, out JsonElement value)
            ? ElementString(value, maxLength)
            : null;
    }

    private static string ElementString(
        JsonElement element,
        int maxLength,
        bool allowEmpty = false)
    {
        if (element.ValueKind != JsonValueKind.String)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        string value = element.GetString()!;
        if (
            (!allowEmpty && value.Length == 0)
            || value.Length > maxLength
            || value.Contains('\0'))
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        return value;
    }

    private static void RequireObject(
        JsonElement element,
        params string[] required)
    {
        RequireObject(element, required, []);
    }

    private static void RequireObject(
        JsonElement element,
        IReadOnlyCollection<string> required,
        IReadOnlyCollection<string> optional)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
        var allowed = new HashSet<string>(
            required.Concat(optional),
            StringComparer.Ordinal);
        var present = element
            .EnumerateObject()
            .Select(property => property.Name)
            .ToHashSet(StringComparer.Ordinal);
        if (
            present.Any(property => !allowed.Contains(property))
            || required.Any(property => !present.Contains(property)))
        {
            throw new CadIoException("CAD_REQUEST_INVALID");
        }
    }

    private static void RejectDuplicateProperties(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (JsonProperty property in element.EnumerateObject())
            {
                if (!names.Add(property.Name))
                {
                    throw new CadIoException("CAD_REQUEST_INVALID");
                }
                RejectDuplicateProperties(property.Value);
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement item in element.EnumerateArray())
            {
                RejectDuplicateProperties(item);
            }
        }
    }
}

public sealed record CadIoWriteTransaction(
    string TransactionId,
    long BeforeRevision,
    long AfterRevision,
    IReadOnlyList<CadIoWriteCommand> Commands);

public abstract record CadIoWriteCommand(string Kind);

public sealed record LayerCreateCommand(
    string LayerId,
    string Name,
    int Color)
    : CadIoWriteCommand("layer.create");

public sealed record LayerUpdateCommand(
    string LayerId,
    string? Name,
    int? Color,
    bool? Visible,
    bool? Frozen,
    bool? Locked)
    : CadIoWriteCommand("layer.update");

public sealed record TextReplaceCommand(string Handle, string Value)
    : CadIoWriteCommand("text.replace");

public sealed record EntityMoveCommand(
    IReadOnlyList<string> Handles,
    CadPoint3 Delta)
    : CadIoWriteCommand("entity.move");

public sealed record EntityCopyCommand(
    IReadOnlyList<string> SourceHandles,
    IReadOnlyList<string> TemporaryIds,
    CadPoint3 Delta)
    : CadIoWriteCommand("entity.copy");

public sealed record EntityDeleteCommand(
    IReadOnlyList<string> Handles)
    : CadIoWriteCommand("entity.delete");

public sealed record CadPoint3(double X, double Y, double Z);
