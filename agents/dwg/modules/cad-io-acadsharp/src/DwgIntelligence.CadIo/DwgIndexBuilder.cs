using System.Security.Cryptography;
using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.IO;
using ACadSharp.Tables;
using CSMath;

namespace DwgIntelligence.CadIo;

public static class DwgIndexBuilder
{
    public static CadIndex Build(string path)
    {
        string fullPath = Path.GetFullPath(path);
        // The save coordinator pins the written copy with its own open handle
        // while it verifies the output, so indexing must tolerate other holders
        // instead of demanding exclusive write access.
        using FileStream stream = new(
            fullPath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete);
        return Path.GetExtension(fullPath).Equals(".dxf", StringComparison.OrdinalIgnoreCase)
            ? BuildDxf(stream, fullPath)
            : Build(stream, fullPath);
    }

    internal static CadIndex Build(Stream stream, string sourceName)
    {
        stream.Position = 0;
        string drawingId = CreateDrawingId(stream);
        stream.Position = 0;
        return BuildFromDocument(DwgReader.Read(stream), drawingId, "dwg", sourceName);
    }

    // Save verification reopens a written DXF copy through the same ACadSharp
    // layout enumeration the DWG path uses. Reading it with a different parser
    // produces a different entity model, which verification can never match.
    internal static CadIndex BuildDxf(Stream stream, string sourceName)
    {
        stream.Position = 0;
        string drawingId = CreateDrawingId(stream);
        stream.Position = 0;
        return BuildFromDocument(DxfReader.Read(stream), drawingId, "dxf", sourceName);
    }

    private static CadIndex BuildFromDocument(
        CadDocument document,
        string drawingId,
        string sourceKind,
        string sourceName)
    {
        var unsupported = new Dictionary<(string Type, string Reason), int>();
        var entities = new List<CadEntityItem>();

        LayoutEnumerationResult located =
            LayoutEntityEnumerator.Enumerate(document);
        foreach (LocatedCadEntity item in located.Entities)
        {
            entities.Add(ConvertEntity(item, unsupported));
        }
        foreach (
            KeyValuePair<string, int> duplicate
            in located.DuplicateHandles)
        {
            AddUnsupported(
                unsupported,
                "ENTITY",
                $"duplicate-handle:{duplicate.Key}",
                duplicate.Value);
        }

        IReadOnlyList<CadLayerItem> layers = document.Layers
            .Select(layer => CreateLayerItem(layer, entities, unsupported))
            .OrderBy(layer => layer.Name, StringComparer.Ordinal)
            .ToArray();

        IReadOnlyList<UnsupportedCadEntity> unsupportedItems = unsupported
            .OrderBy(item => item.Key.Type, StringComparer.Ordinal)
            .ThenBy(item => item.Key.Reason, StringComparer.Ordinal)
            .Select(item => new UnsupportedCadEntity(
                item.Key.Type,
                item.Value,
                item.Key.Reason))
            .ToArray();

        return new CadIndex(
            "cad-index/v0.2",
            drawingId,
            new CadIndexSource(
                sourceKind,
                Path.GetFileName(sourceName),
                "acadsharp@3.6.35"),
            new CadDrawingMetadata(
                document.Header.VersionString,
                document.Header.InsUnits.ToString()),
            new CadIndexSummary(
                entities.Count,
                layers.Count,
                unsupportedItems.Sum(item => item.Count),
                entities.Count(entity => entity.Space == "model"),
                entities.Count(entity => entity.Space == "paper")),
            layers,
            entities,
            unsupportedItems);
    }

    internal static CadLayerItem CreateLayerItem(
        Layer layer,
        IReadOnlyCollection<CadEntityItem> entities,
        IDictionary<(string Type, string Reason), int> unsupported)
    {
        int? color = layer.Color.IsTrueColor
            ? null
            : layer.Color.Index;
        if (color is null)
        {
            AddUnsupported(
                unsupported,
                "LAYER",
                $"true-color-unsupported:{layer.Name}");
        }

        return new CadLayerItem(
            layer.Name,
            entities.Count(entity => entity.Layer == layer.Name),
            layer.IsOn,
            layer.Flags.HasFlag(LayerFlags.Frozen),
            color,
            layer.Flags.HasFlag(LayerFlags.Locked));
    }

    private static CadEntityItem ConvertEntity(
        LocatedCadEntity located,
        IDictionary<(string Type, string Reason), int> unsupported)
    {
        Entity entity = located.Entity;
        string type = string.IsNullOrWhiteSpace(entity.ObjectName)
            ? entity.GetType().Name.ToUpperInvariant()
            : entity.ObjectName;
        string? handle = entity.Handle == 0
            ? null
            : entity.Handle.ToString("X");
        string id = handle is null
            ? $"generated:{located.Layout}:{type}:{located.EncounterIndex}"
            : $"h:{handle}";
        var warnings = new List<string>();
        CadBoundingBox? bbox = GetBoundingBox(entity, type, warnings, unsupported);
        GeometryExtraction geometry =
            EntityGeometryExtractor.Extract(entity, bbox);
        AddWarnings(
            warnings,
            geometry.Warnings,
            unsupported,
            type);

        InsertAttributeResult attributes = entity is Insert insertEntity
            ? InsertAttributeExtractor.Extract(insertEntity)
            : new InsertAttributeResult(
                new Dictionary<string, string>(),
                []);
        AddWarnings(
            warnings,
            attributes.Warnings,
            unsupported,
            type);

        if (handle is null)
        {
            warnings.Add("missing-handle");
            AddUnsupported(unsupported, type, "missing-handle");
        }

        return new CadEntityItem(
            id,
            handle,
            type,
            entity.Layer?.Name ?? "0",
            located.Space,
            located.Layout,
            bbox,
            GetText(entity),
            entity is Insert insert ? insert.Block?.Name : null,
            attributes.Attributes,
            geometry.Geometry,
            warnings);
    }

    private static string? GetText(Entity entity)
    {
        return entity switch
        {
            MText text => text.PlainText,
            IText text => text.Value,
            _ => null
        };
    }

    private static void AddWarnings(
        ICollection<string> warnings,
        IEnumerable<string> additions,
        IDictionary<(string Type, string Reason), int> unsupported,
        string type)
    {
        foreach (string warning in additions)
        {
            if (warnings.Contains(warning))
            {
                continue;
            }
            warnings.Add(warning);
            AddUnsupported(unsupported, type, warning);
        }
    }

    internal static CadBoundingBox? GetBoundingBox(
        Entity entity,
        string type,
        ICollection<string> warnings,
        IDictionary<(string Type, string Reason), int> unsupported)
    {
        try
        {
            BoundingBox box = entity.GetBoundingBox();
            double[] min = [box.Min.X, box.Min.Y, box.Min.Z];
            double[] max = [box.Max.X, box.Max.Y, box.Max.Z];
            if (min.Concat(max).Any(value => !double.IsFinite(value)))
            {
                warnings.Add("bbox-unavailable");
                AddUnsupported(unsupported, type, "bbox-unavailable");
                return null;
            }
            // ACadSharp derives an XY-plane hatch's Z extent differently
            // depending on whether it read DWG or DXF. Its elevation is an
            // OCS coordinate along the unit normal, so project that plane to
            // world Z instead of choosing either edge of the format-specific
            // box. A hatch with another normal can legitimately span world Z
            // and must retain that extent.
            if (
                entity is Hatch hatch
                && double.IsFinite(hatch.Elevation)
                && double.IsFinite(hatch.Normal.X)
                && double.IsFinite(hatch.Normal.Y)
                && double.IsFinite(hatch.Normal.Z)
                && Math.Abs(hatch.Normal.X) <= 1e-12
                && Math.Abs(hatch.Normal.Y) <= 1e-12
                && Math.Abs(hatch.Normal.Z) > 1e-12)
            {
                double planeZ = hatch.Elevation * Math.Sign(hatch.Normal.Z);
                min[2] = planeZ;
                max[2] = planeZ;
            }
            return new CadBoundingBox(min, max);
        }
        catch (NotImplementedException)
        {
            warnings.Add("bbox-not-implemented");
            AddUnsupported(unsupported, type, "bbox-not-implemented");
            return null;
        }
        catch (Exception exception)
        {
            string reason = $"bbox-error:{exception.GetType().Name}";
            warnings.Add(reason);
            AddUnsupported(unsupported, type, reason);
            return null;
        }
    }

    private static void AddUnsupported(
        IDictionary<(string Type, string Reason), int> unsupported,
        string type,
        string reason,
        int increment = 1)
    {
        var key = (type, reason);
        unsupported[key] = unsupported.TryGetValue(key, out int count)
            ? count + increment
            : increment;
    }

    private static string CreateDrawingId(Stream stream)
    {
        string hash = Convert.ToHexString(SHA256.HashData(stream));
        return $"dwg:{hash[..24].ToLowerInvariant()}";
    }
}
