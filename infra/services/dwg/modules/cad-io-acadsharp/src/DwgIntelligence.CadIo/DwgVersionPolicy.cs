using System.Collections.ObjectModel;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace DwgIntelligence.CadIo;

public sealed record DwgVersionEvidence(
    string Version,
    string ProbeFixtureSha256,
    bool Verified,
    string InvariantSha256);

public sealed class DwgVersionPolicy
{
    private const int MaxManifestBytes = 1_048_576;
    private const string SchemaVersion = "dwg-roundtrip-policy/v1";
    private static readonly Regex Sha256Pattern = new(
        "^[0-9A-F]{64}$",
        RegexOptions.CultureInvariant);
    private static readonly ReadOnlyCollection<string> Candidates =
        Array.AsReadOnly(
            new[]
            {
                "AC1014",
                "AC1015",
                "AC1018",
                "AC1024",
                "AC1027",
                "AC1032"
            });
    private readonly HashSet<string> allowed;

    private DwgVersionPolicy(IReadOnlyList<DwgVersionEvidence> entries)
    {
        Entries = entries;
        allowed = entries
            .Where(entry => entry.Verified)
            .Select(entry => entry.Version)
            .ToHashSet(StringComparer.Ordinal);
    }

    public static IReadOnlyList<string> CandidateVersions => Candidates;

    public IReadOnlyList<DwgVersionEvidence> Entries { get; }

    public bool IsAllowed(string version)
    {
        return allowed.Contains(version);
    }

    public static DwgVersionPolicy Load(string path)
    {
        try
        {
            if (!Path.IsPathFullyQualified(path))
            {
                throw Invalid();
            }
            byte[] bytes = File.ReadAllBytes(path);
            if (
                bytes.Length == 0
                || bytes.Length > MaxManifestBytes
                || bytes.AsSpan().StartsWith(
                    new byte[] { 0xEF, 0xBB, 0xBF }))
            {
                throw Invalid();
            }
            string json = new UTF8Encoding(false, true).GetString(bytes);
            using JsonDocument document = JsonDocument.Parse(
                json,
                new JsonDocumentOptions
                {
                    AllowTrailingCommas = false,
                    CommentHandling = JsonCommentHandling.Disallow,
                    MaxDepth = 16
                });
            JsonElement root = document.RootElement;
            RequireObjectKeys(
                root,
                ["schemaVersion", "candidates"]);
            if (
                root.GetProperty("schemaVersion").ValueKind
                    != JsonValueKind.String
                || root.GetProperty("schemaVersion").GetString()
                    != SchemaVersion)
            {
                throw Invalid();
            }
            JsonElement candidates = root.GetProperty("candidates");
            if (
                candidates.ValueKind != JsonValueKind.Array
                || candidates.GetArrayLength() != Candidates.Count)
            {
                throw Invalid();
            }

            var entries = new List<DwgVersionEvidence>(
                Candidates.Count);
            int index = 0;
            foreach (JsonElement candidate in candidates.EnumerateArray())
            {
                RequireObjectKeys(
                    candidate,
                    [
                        "version",
                        "probeFixtureSha256",
                        "verified",
                        "invariantSha256"
                    ]);
                string version = RequireString(
                    candidate,
                    "version");
                string probeHash = RequireString(
                    candidate,
                    "probeFixtureSha256");
                string invariantHash = RequireString(
                    candidate,
                    "invariantSha256");
                JsonElement verifiedElement =
                    candidate.GetProperty("verified");
                if (
                    verifiedElement.ValueKind != JsonValueKind.True
                    && verifiedElement.ValueKind != JsonValueKind.False)
                {
                    throw Invalid();
                }
                bool verified = verifiedElement.GetBoolean();
                if (
                    version != Candidates[index]
                    || (verified
                        && (!Sha256Pattern.IsMatch(probeHash)
                            || !Sha256Pattern.IsMatch(invariantHash)))
                    || (!verified
                        && (probeHash.Length != 0
                            || invariantHash.Length != 0)))
                {
                    throw Invalid();
                }
                entries.Add(new DwgVersionEvidence(
                    version,
                    probeHash,
                    verified,
                    invariantHash));
                index += 1;
            }
            if (!entries.Any(entry => entry.Verified))
            {
                throw Invalid();
            }
            return new DwgVersionPolicy(
                Array.AsReadOnly(entries.ToArray()));
        }
        catch (CadIoException)
        {
            throw;
        }
        catch (Exception exception)
        {
            throw Invalid(exception);
        }
    }

    private static string RequireString(
        JsonElement element,
        string property)
    {
        JsonElement value = element.GetProperty(property);
        if (value.ValueKind != JsonValueKind.String)
        {
            throw Invalid();
        }
        return value.GetString() ?? throw Invalid();
    }

    private static void RequireObjectKeys(
        JsonElement element,
        IReadOnlyCollection<string> expected)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            throw Invalid();
        }
        string[] actual = element
            .EnumerateObject()
            .Select(property => property.Name)
            .ToArray();
        if (
            actual.Length != expected.Count
            || actual.Distinct(StringComparer.Ordinal).Count()
                != actual.Length
            || actual.Any(name => !expected.Contains(name)))
        {
            throw Invalid();
        }
    }

    private static CadIoException Invalid(Exception? inner = null)
    {
        return inner is null
            ? new CadIoException("DWG_POLICY_INVALID")
            : new CadIoException("DWG_POLICY_INVALID", inner);
    }
}

public static class DwgRoundTripInvariant
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    public static string ComputeSha256(CadIndex index)
    {
        var invariant = new
        {
            index.SchemaVersion,
            Drawing = new
            {
                index.Drawing.Units
            },
            index.Summary,
            Layers = index.Layers
                .OrderBy(layer => layer.Name, StringComparer.Ordinal)
                .ToArray(),
            Entities = index.Entities
                .OrderBy(entity => entity.Id, StringComparer.Ordinal)
                .Select(entity => new
                {
                    entity.Id,
                    entity.Handle,
                    entity.Type,
                    entity.Layer,
                    entity.Space,
                    entity.Layout,
                    entity.Bbox,
                    entity.Text,
                    entity.BlockName,
                    Attributes = entity.Attributes
                        .OrderBy(
                            item => item.Key,
                            StringComparer.Ordinal)
                        .ToArray(),
                    entity.Geometry,
                    Warnings = entity.Warnings
                        .OrderBy(
                            warning => warning,
                            StringComparer.Ordinal)
                        .ToArray()
                })
                .ToArray(),
            Unsupported = index.Unsupported
                .OrderBy(item => item.Type, StringComparer.Ordinal)
                .ThenBy(item => item.Reason, StringComparer.Ordinal)
                .ToArray()
        };
        byte[] json = JsonSerializer.SerializeToUtf8Bytes(
            invariant,
            JsonOptions);
        return Convert.ToHexString(SHA256.HashData(json));
    }
}
