using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.Objects;
using ACadSharp.Tables;

namespace DwgIntelligence.CadIo;

public sealed record LocatedCadEntity(
    Entity Entity,
    string Space,
    string Layout,
    int EncounterIndex);

public sealed record LayoutEnumerationResult(
    IReadOnlyList<LocatedCadEntity> Entities,
    IReadOnlyDictionary<string, int> DuplicateHandles);

public static class LayoutEntityEnumerator
{
    public static LayoutEnumerationResult Enumerate(CadDocument document)
    {
        var located = new List<LocatedCadEntity>();
        var visitedBlocks = new HashSet<ulong>();
        int encounterIndex = 0;

        IEnumerable<Layout> layouts = document.Layouts
            .OrderBy(layout => layout.IsPaperSpace ? 1 : 0)
            .ThenBy(layout => layout.TabOrder)
            .ThenBy(layout => layout.Name, StringComparer.Ordinal);

        foreach (Layout layout in layouts)
        {
            string space = layout.IsPaperSpace ? "paper" : "model";
            visitedBlocks.Add(layout.AssociatedBlock.Handle);
            foreach (Entity entity in layout.AssociatedBlock.Entities)
            {
                located.Add(new LocatedCadEntity(
                    entity,
                    space,
                    layout.Name,
                    encounterIndex));
                encounterIndex += 1;
            }
        }

        // A DXF without LAYOUT objects still carries its entities in the model
        // and paper space block records. Walking layouts alone reports zero
        // entities for those documents, so any space record no layout already
        // covered is swept as well. Records reached through a layout are
        // skipped outright: re-walking them would report every entity as a
        // duplicate handle rather than deduplicating silently.
        foreach (BlockRecord record in document.BlockRecords)
        {
            if (visitedBlocks.Contains(record.Handle))
            {
                continue;
            }
            bool isModelSpace = record.Name.Equals(
                "*Model_Space",
                StringComparison.OrdinalIgnoreCase);
            bool isPaperSpace = record.Name.StartsWith(
                "*Paper_Space",
                StringComparison.OrdinalIgnoreCase);
            if (!isModelSpace && !isPaperSpace)
            {
                continue;
            }
            foreach (Entity entity in record.Entities)
            {
                located.Add(new LocatedCadEntity(
                    entity,
                    isModelSpace ? "model" : "paper",
                    isModelSpace ? "Model" : record.Name,
                    encounterIndex));
                encounterIndex += 1;
            }
        }

        return Deduplicate(located, StableIdentity);
    }

    public static LayoutEnumerationResult Deduplicate(
        IEnumerable<LocatedCadEntity> entities,
        Func<Entity, string?> identity)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var unique = new List<LocatedCadEntity>();
        var duplicates = new Dictionary<string, int>(StringComparer.Ordinal);

        foreach (LocatedCadEntity item in entities)
        {
            string? stableIdentity = identity(item.Entity);
            if (stableIdentity is null || seen.Add(stableIdentity))
            {
                unique.Add(item);
                continue;
            }

            duplicates[stableIdentity] =
                duplicates.TryGetValue(stableIdentity, out int count)
                    ? count + 1
                    : 1;
        }

        return new LayoutEnumerationResult(unique, duplicates);
    }

    private static string? StableIdentity(Entity entity)
    {
        return entity.Handle == 0
            ? null
            : $"h:{entity.Handle:X}";
    }
}
